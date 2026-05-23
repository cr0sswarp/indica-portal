#!/usr/bin/env python3
"""
TZI: Player Tracking v2 — Constrained Re-ID with Jersey Number Recognition

Key improvements over v1:
1. Appearance-based Re-ID: color histogram of each player crop stored per track
2. Global track merging: post-process merges fragmented tracks belonging to same player
3. Max-on-field constraint: at most 11 Waseda players visible simultaneously
4. Substitution detection: flags when one track ends and a new one starts at same position/zone
5. Jersey OCR: EasyOCR attempts to read jersey number from player crop
6. Iterative refinement: multiple passes to converge player count toward 11-40

Target output:
- ≤40 unique player IDs per match (22 starters + ~18 max substitutes)
- Each player: jersey_number (if readable), all sightings, substitution events
- Substitution log: time, player_out_id, player_in_id, approximate position

Usage:
    python track_players_v2.py --match 20260325
    python track_players_v2.py --match 20260329 --interval 2
    python track_players_v2.py --match 20260325 --no-ocr   # skip OCR (faster)

Output:
    data/tzi/match_YYYYMMDD/players_v2.json
    data/tzi/match_YYYYMMDD/substitutions.json
    data/tzi/match_YYYYMMDD/frames_v2/   (annotated with merged IDs + jersey numbers)
    data/tzi/match_YYYYMMDD/tracking_report_v2.html
"""

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent.parent
FW, FH = 105.0, 68.0

# ── Homography ────────────────────────────────────────────────────
SRC = np.float32([[20, 90], [1255, 88], [635, 298], [635, 705]])
DST = np.float32([[0, 0], [105, 0], [52.5, 34], [52.5, 68]])
H_MAT, _ = cv2.findHomography(SRC, DST, cv2.RANSAC, 3.0)

# ── HSV ranges (Waseda maroon) ────────────────────────────────────
W_LO1, W_HI1 = np.array([0,   50, 40]), np.array([12,  255, 220])
W_LO2, W_HI2 = np.array([165, 50, 40]), np.array([180, 255, 220])
KNL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

# ── Tracking parameters ───────────────────────────────────────────
MAX_DIST_PIXELS   = 100    # max centroid distance for same-frame match
MAX_DISAPPEAR     = 6      # frames before track is "suspended" (not deleted)
RE_ID_DIST        = 180    # pixels: max dist for Re-ID (suspended → active)
HIST_SIMILARITY   = 0.35   # cosine similarity threshold (lower = more merges)
MAX_PLAYERS_FIELD = 11     # max Waseda players on field at once
MERGE_GAP_MIN     = 15.0   # minutes: max gap to merge two tracks (covers half-time)
MERGE_DIST_M      = 22.0   # meters: max field distance for post-process merge
MIN_SIGHTINGS     = 3      # tracks with fewer sightings are noise-filtered

FONT = cv2.FONT_HERSHEY_SIMPLEX
ALL_ZONES = ["D1", "D2", "D3", "A1", "A2", "A3"]


# ── Field coordinate helpers ──────────────────────────────────────

def p2f(px, py):
    pt = np.array([[[float(px), float(py)]]], dtype=np.float32)
    r  = cv2.perspectiveTransform(pt, H_MAT)
    return float(np.clip(r[0][0][0], 0, FW)), float(np.clip(r[0][0][1], 0, FH))


def fx_to_zone(fx):
    if fx < 21:    return "D1"
    if fx < 42:    return "D2"
    if fx < 52.5:  return "D3"
    if fx < 63:    return "A1"
    if fx < 84:    return "A2"
    return "A3"


# ── Detection ────────────────────────────────────────────────────

def detect_waseda(frame):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    m   = cv2.bitwise_or(cv2.inRange(hsv, W_LO1, W_HI1),
                          cv2.inRange(hsv, W_LO2, W_HI2))
    m[:60, :] = 0; m[680:, :] = 0
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN,  KNL)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, KNL, iterations=2)
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cnts:
        a = cv2.contourArea(c)
        if not (60 < a < 3000): continue
        x, y, w, h = cv2.boundingRect(c)
        if h / (w + 1e-5) < 0.4 or h / (w + 1e-5) > 9: continue
        cx, cy = x + w // 2, y + h
        fx, fy = p2f(cx, cy)
        crop = frame[max(0,y):y+h, max(0,x):x+w]
        hist = _color_hist(crop)
        out.append({
            "px": cx, "py": cy - h // 2,
            "fx": round(fx, 2), "fy": round(fy, 2),
            "bbox": (x, y, x+w, y+h),
            "area": round(a, 1), "zone": fx_to_zone(fx),
            "hist": hist, "crop": crop,
        })
    return out


def _color_hist(crop):
    if crop.size == 0:
        return np.zeros(48)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h = cv2.calcHist([hsv], [0, 1], None, [16, 3], [0, 180, 0, 256])
    h = h.flatten().astype(np.float32)
    n = np.linalg.norm(h)
    return (h / n if n > 0 else h)


def hist_sim(a, b):
    return float(np.dot(a, b))  # both normalized → cosine similarity


# ── OCR helper ───────────────────────────────────────────────────

_ocr_reader = None

def _get_ocr():
    global _ocr_reader
    if _ocr_reader is None:
        try:
            import easyocr
            _ocr_reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        except Exception:
            _ocr_reader = False
    return _ocr_reader


def read_jersey_number(crop, use_ocr=True):
    """Try to read a jersey number from a player crop. Returns int or None."""
    if not use_ocr or crop is None or crop.size == 0:
        return None
    reader = _get_ocr()
    if not reader:
        return None
    h, w = crop.shape[:2]
    # Focus on upper-back region (jersey number is on upper back)
    roi = crop[:int(h * 0.6), :]
    if roi.size == 0:
        return None
    # Enlarge + grayscale + threshold for better OCR
    roi = cv2.resize(roi, (roi.shape[1] * 3, roi.shape[0] * 3))
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    try:
        results = reader.readtext(thresh, allowlist="0123456789", detail=0, paragraph=False)
        for r in results:
            r = r.strip()
            if r.isdigit() and 1 <= int(r) <= 99:
                return int(r)
    except Exception:
        pass
    return None


# ── Per-track data structure ─────────────────────────────────────

class PlayerTrack:
    __slots__ = ("tid", "sightings", "hist_samples", "disappeared",
                 "active", "jersey_number", "jersey_votes", "last_px", "last_py")

    def __init__(self, tid, det):
        self.tid           = tid
        self.sightings     = []
        self.hist_samples  = []
        self.disappeared   = 0
        self.active        = True
        self.jersey_number = None
        self.jersey_votes  = defaultdict(int)
        self.last_px       = det["px"]
        self.last_py       = det["py"]

    def update(self, det, t_min, half):
        self.sightings.append({
            "time_min": round(t_min, 2),
            "half": half,
            "fx": det["fx"], "fy": det["fy"],
            "px": det["px"], "py": det["py"],
            "zone": det["zone"],
        })
        self.hist_samples.append(det["hist"])
        if len(self.hist_samples) > 20:
            self.hist_samples = self.hist_samples[-20:]
        self.last_px = det["px"]
        self.last_py = det["py"]
        self.disappeared = 0

    def mean_hist(self):
        if not self.hist_samples:
            return np.zeros(48)
        return np.mean(self.hist_samples, axis=0)

    def vote_jersey(self, num):
        if num is not None:
            self.jersey_votes[num] += 1
            top = max(self.jersey_votes, key=self.jersey_votes.get)
            if self.jersey_votes[top] >= 2:
                self.jersey_number = top


# ── Tracker ───────────────────────────────────────────────────────

class PlayerTrackerV2:
    def __init__(self):
        self.nid      = 0
        self.active: dict[int, PlayerTrack]    = {}
        self.suspended: dict[int, PlayerTrack] = {}  # lost but Re-ID eligible
        self.done: list[PlayerTrack]           = []  # permanently retired

    def _new_track(self, det) -> PlayerTrack:
        t = PlayerTrack(f"P{self.nid:03d}", det)
        self.nid += 1
        return t

    def _match(self, dets, tracks: dict[int, PlayerTrack]):
        """Greedy matching: distance + appearance."""
        if not tracks or not dets:
            return {}, set(range(len(dets)))
        tids = list(tracks.keys())
        n, m = len(tids), len(dets)
        cost = np.full((n, m), 9999.0)
        for i, tid in enumerate(tids):
            tr = tracks[tid]
            mh = tr.mean_hist()
            for j, d in enumerate(dets):
                dist = np.sqrt((tr.last_px - d["px"])**2 + (tr.last_py - d["py"])**2)
                if dist > MAX_DIST_PIXELS:
                    continue
                sim  = hist_sim(mh, d["hist"])
                cost[i, j] = dist * (1.0 - 0.3 * sim)
        # Greedy assignment
        matched = {}
        used_j  = set()
        order   = np.dstack(np.unravel_index(np.argsort(cost.ravel()), cost.shape))[0]
        for i, j in order:
            if cost[i, j] >= 9999: break
            tid = tids[i]
            if tid in matched or j in used_j: continue
            matched[tid] = j
            used_j.add(j)
        unmatched = {j for j in range(m) if j not in used_j}
        return matched, unmatched

    def update(self, dets, t_min, half, use_ocr=True):
        # 1. Match dets → active tracks
        matched, unmatched = self._match(dets, self.active)

        # 2. Update matched active tracks
        for tid, j in matched.items():
            d = dets[j]
            self.active[tid].update(d, t_min, half)
            num = read_jersey_number(d["crop"], use_ocr)
            self.active[tid].vote_jersey(num)

        # 3. Increment disappeared for unmatched active
        for tid in list(self.active.keys()):
            if tid not in matched:
                self.active[tid].disappeared += 1
                if self.active[tid].disappeared > MAX_DISAPPEAR:
                    tr = self.active.pop(tid)
                    self.suspended[tid] = tr

        # 4. Try Re-ID for remaining unmatched dets against suspended tracks
        still_unmatched = set()
        for j in unmatched:
            d = dets[j]
            best_tid, best_cost = None, 9999.0
            for tid, tr in self.suspended.items():
                dist = np.sqrt((tr.last_px - d["px"])**2 + (tr.last_py - d["py"])**2)
                if dist > RE_ID_DIST: continue
                sim  = hist_sim(tr.mean_hist(), d["hist"])
                c    = dist * (1.0 - 0.4 * sim)
                if c < best_cost:
                    best_cost = c
                    best_tid  = tid
            if best_tid is not None and best_cost < RE_ID_DIST * 0.8:
                tr = self.suspended.pop(best_tid)
                tr.disappeared = 0
                tr.update(d, t_min, half)
                tr.vote_jersey(read_jersey_number(d["crop"], use_ocr))
                self.active[best_tid] = tr
            else:
                still_unmatched.add(j)

        # 5. Enforce max-on-field: if >MAX_PLAYERS_FIELD active, suspend the
        #    most recently created (fewest sightings) extras
        if len(self.active) > MAX_PLAYERS_FIELD:
            by_sightings = sorted(self.active.keys(),
                                  key=lambda k: len(self.active[k].sightings))
            extras = by_sightings[:len(self.active) - MAX_PLAYERS_FIELD]
            for tid in extras:
                self.suspended[tid] = self.active.pop(tid)
            still_unmatched = still_unmatched.union(set())

        # 6. Create new tracks for remaining unmatched dets
        for j in still_unmatched:
            d = dets[j]
            tr = self._new_track(d)
            tr.update(d, t_min, half)
            tr.vote_jersey(read_jersey_number(d["crop"], use_ocr))
            self.active[self.nid - 1] = tr  # use the last-assigned nid as key
        return list(self.active.values())

    def flush_all(self):
        for tr in self.active.values():
            self.done.append(tr)
        for tr in self.suspended.values():
            self.done.append(tr)
        self.active.clear()
        self.suspended.clear()

    def all_tracks(self):
        return self.done


# ── Track merging (post-process) ─────────────────────────────────

def merge_tracks(tracks: list[PlayerTrack]) -> list[PlayerTrack]:
    """
    Merge fragmented tracks that likely belong to the same player.
    Criteria: temporal gap < MERGE_GAP_MIN AND field distance < MERGE_DIST_M
    AND appearance similarity > HIST_SIMILARITY
    """
    # Sort each track's sightings by time
    for t in tracks:
        t.sightings.sort(key=lambda s: s["time_min"])

    # Build list of (last_time, first_time, last_pos, first_pos, hist)
    def info(t: PlayerTrack):
        s = t.sightings
        if not s: return None
        return {
            "t_end":  s[-1]["time_min"],
            "t_start": s[0]["time_min"],
            "end_fx": s[-1]["fx"], "end_fy": s[-1]["fy"],
            "start_fx": s[0]["fx"], "start_fy": s[0]["fy"],
        }

    merged = True
    while merged:
        merged = False
        n = len(tracks)
        used = [False] * n
        result = []
        for i in range(n):
            if used[i]: continue
            ti = tracks[i]
            ii = info(ti)
            if ii is None: used[i] = True; continue
            best_j, best_score = -1, 9999.0
            for j in range(i+1, n):
                if used[j]: continue
                tj = tracks[j]
                ij = info(tj)
                if ij is None: continue
                # ti ends before tj starts (or vice versa)
                if ii["t_end"] < ij["t_start"]:
                    gap  = ij["t_start"] - ii["t_end"]
                    dist = np.sqrt((ii["end_fx"]-ij["start_fx"])**2 + (ii["end_fy"]-ij["start_fy"])**2)
                elif ij["t_end"] < ii["t_start"]:
                    gap  = ii["t_start"] - ij["t_end"]
                    dist = np.sqrt((ij["end_fx"]-ii["start_fx"])**2 + (ij["end_fy"]-ii["start_fy"])**2)
                else:
                    continue  # overlapping — different players
                if gap > MERGE_GAP_MIN or dist > MERGE_DIST_M: continue
                sim = hist_sim(ti.mean_hist(), tj.mean_hist())
                if sim < HIST_SIMILARITY: continue
                score = gap * dist / (sim + 0.01)
                if score < best_score:
                    best_score = score; best_j = j
            if best_j >= 0:
                tj = tracks[best_j]
                ti.sightings.extend(tj.sightings)
                ti.sightings.sort(key=lambda s: s["time_min"])
                ti.hist_samples.extend(tj.hist_samples)
                ti.hist_samples = ti.hist_samples[-20:]
                for num, cnt in tj.jersey_votes.items():
                    ti.jersey_votes[num] += cnt
                if ti.jersey_votes:
                    ti.jersey_number = max(ti.jersey_votes, key=ti.jersey_votes.get)
                used[best_j] = True
                merged = True
            if not used[i]:
                result.append(ti)
                used[i] = True
        tracks = result

    # Remove noise tracks (too few sightings → shadows/advertising boards)
    tracks = [t for t in tracks if len(t.sightings) >= MIN_SIGHTINGS]
    return tracks


# ── Substitution detection ────────────────────────────────────────

def detect_substitutions(tracks: list[PlayerTrack]) -> list[dict]:
    """
    Detect probable substitution events:
    A player track ends and a new one begins nearby in time and space.
    """
    subs = []
    # Sort tracks by their last sighting time
    by_end = sorted(tracks, key=lambda t: t.sightings[-1]["time_min"] if t.sightings else 0)

    for i, t_out in enumerate(by_end):
        if not t_out.sightings: continue
        t_end   = t_out.sightings[-1]["time_min"]
        fx_out  = t_out.sightings[-1]["fx"]
        fy_out  = t_out.sightings[-1]["fy"]
        half_out = t_out.sightings[-1]["half"]

        # Don't flag tracks that end at the very end of a half
        if t_end > 43 and half_out == "1H": continue  # end of half
        if t_end > 88 and half_out == "2H": continue

        # Look for a track that starts within 5 min and within 25m
        for t_in in tracks:
            if not t_in.sightings: continue
            if t_in.tid == t_out.tid: continue
            t_start = t_in.sightings[0]["time_min"]
            if not (0 < t_start - t_end < 5.0): continue
            fx_in = t_in.sightings[0]["fx"]
            fy_in = t_in.sightings[0]["fy"]
            dist  = np.sqrt((fx_out - fx_in)**2 + (fy_out - fy_in)**2)
            if dist > 25: continue
            subs.append({
                "time_min": round((t_end + t_start) / 2, 1),
                "player_out": t_out.tid,
                "player_out_jersey": t_out.jersey_number,
                "player_in": t_in.tid,
                "player_in_jersey": t_in.jersey_number,
                "zone": fx_to_zone(fx_out),
                "confidence": round(1 - dist / 25, 2),
            })
            break  # one substitution partner per track
    subs.sort(key=lambda s: s["time_min"])
    return subs


# ── Annotated frame drawing ───────────────────────────────────────

COLORS = [
    (255, 80,  80),  (80,  255, 80),  (80,  80,  255),
    (255, 255, 80),  (255, 80,  255), (80,  255, 255),
    (200, 140, 80),  (140, 200, 80),  (80,  140, 200),
    (200, 80,  140), (140, 80,  200), (80,  200, 140),
]

def _track_color(tid_str):
    idx = int(tid_str[1:]) % len(COLORS)
    return COLORS[idx]


def draw_frame(frame, frame_dets, active_tracks):
    """Draw bounding boxes + track IDs on frame."""
    out = frame.copy()
    # Build px,py → track mapping from active tracks' last position
    pos_to_track = {}
    for tr in active_tracks:
        pos_to_track[(tr.last_px, tr.last_py)] = tr

    for d in frame_dets:
        x1, y1, x2, y2 = d["bbox"]
        cx, cy = (x1+x2)//2, (y1+y2)//2

        # Find matching track
        tr = None
        best = 999
        for (px, py), t in pos_to_track.items():
            dist = abs(px - cx) + abs(py - cy)
            if dist < best:
                best = dist; tr = t

        if tr and best < 30:
            col = _track_color(tr.tid)
            label = tr.tid
            if tr.jersey_number:
                label = f"#{tr.jersey_number}"
        else:
            col   = (200, 200, 200)
            label = "?"

        cv2.rectangle(out, (x1, y1), (x2, y2), col, 2)
        cv2.putText(out, label, (x1, y1 - 6), FONT, 0.55, col, 2, cv2.LINE_AA)
        cv2.putText(out, f"Z:{d['zone']}", (x1, y2 + 14),
                    FONT, 0.38, col, 1, cv2.LINE_AA)
    return out


# ── HTML report ───────────────────────────────────────────────────

def build_report(match_id, tracks, subs, stats):
    rows = ""
    for tr in sorted(tracks, key=lambda t: t.jersey_number or 99):
        n = len(tr.sightings)
        j = tr.jersey_number or "?"
        zones = defaultdict(int)
        for s in tr.sightings: zones[s["zone"]] += 1
        dominant = max(zones, key=zones.get) if zones else "?"
        t_start = tr.sightings[0]["time_min"] if tr.sightings else 0
        t_end   = tr.sightings[-1]["time_min"] if tr.sightings else 0
        zc = {"D1":"#3498db","D2":"#2980b9","D3":"#1abc9c",
              "A1":"#e74c3c","A2":"#e67e22","A3":"#f1c40f"}.get(dominant,"#888")
        rows += f"""<tr>
          <td style="font-weight:700;color:#58a6ff">{tr.tid}</td>
          <td style="font-size:1.2rem;font-weight:700;color:#f0883e">#{j}</td>
          <td>{n}</td>
          <td>{t_start:.0f}–{t_end:.0f} min</td>
          <td><span style="background:{zc};color:#fff;padding:2px 8px;border-radius:4px;font-size:11px">{dominant}</span></td>
        </tr>"""

    sub_rows = ""
    for s in subs:
        sub_rows += f"""<tr>
          <td>{s['time_min']}min</td>
          <td style="color:#f85149">OUT: {s['player_out']} #{s['player_out_jersey'] or '?'}</td>
          <td style="color:#3fb950">IN:  {s['player_in']} #{s['player_in_jersey'] or '?'}</td>
          <td>{s['zone']}</td>
          <td>{int(s['confidence']*100)}%</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8">
<title>TZI Tracking v2 — match_{match_id}</title>
<style>
* {{box-sizing:border-box;margin:0;padding:0}}
body {{background:#0d1117;color:#e6edf3;font-family:'Segoe UI',Arial,sans-serif}}
.hero {{background:linear-gradient(135deg,#0f2027,#203a43,#2c5364);padding:24px 32px;border-bottom:1px solid #30363d}}
.hero h1 {{font-size:1.4rem;color:#58a6ff}}
.hero p  {{font-size:.82rem;color:#8b949e;margin-top:4px}}
.stats {{display:flex;gap:20px;padding:16px 32px;background:#161b22;border-bottom:1px solid #30363d;flex-wrap:wrap}}
.stat {{background:#21262d;border:1px solid #30363d;border-radius:8px;padding:10px 18px}}
.stat .v {{font-size:1.8rem;font-weight:700}}
.stat .l {{font-size:.75rem;color:#8b949e}}
.content {{max-width:1100px;margin:0 auto;padding:24px 20px}}
h2 {{font-size:1rem;padding-bottom:8px;border-bottom:1px solid #30363d;margin:24px 0 14px}}
table {{width:100%;border-collapse:collapse;font-size:12px}}
th {{background:#21262d;padding:8px 10px;text-align:left;color:#8b949e}}
td {{padding:7px 10px;border-bottom:1px solid #21262d}}
tr:hover td {{background:#161b22}}
</style></head><body>
<div class="hero">
  <h1>TZI Player Tracking v2 — match_{match_id}</h1>
  <p>Re-ID + Track Merging + Jersey OCR + Substitution Detection</p>
</div>
<div class="stats">
  <div class="stat"><div class="v" style="color:#3fb950">{stats['n_players']}</div><div class="l">Unique Players</div></div>
  <div class="stat"><div class="v" style="color:#58a6ff">{stats['n_frames']}</div><div class="l">Frames Sampled</div></div>
  <div class="stat"><div class="v" style="color:#f0883e">{stats['n_with_jersey']}</div><div class="l">Jersey # Identified</div></div>
  <div class="stat"><div class="v" style="color:#d2a8ff">{len(subs)}</div><div class="l">Substitutions Detected</div></div>
  <div class="stat"><div class="v" style="color:#79c0ff">{stats['avg_per_frame']:.1f}</div><div class="l">Avg Players/Frame</div></div>
</div>
<div class="content">
  <h2>Player List (全{stats['n_players']}名)</h2>
  <table><thead><tr><th>Track ID</th><th>Jersey #</th><th>Sightings</th><th>Active Period</th><th>Primary Zone</th></tr></thead>
  <tbody>{rows}</tbody></table>

  <h2>Substitutions Detected ({len(subs)}件)</h2>
  {'<table><thead><tr><th>Time</th><th>Player Out</th><th>Player In</th><th>Zone</th><th>Confidence</th></tr></thead><tbody>' + sub_rows + '</tbody></table>' if subs else '<p style="color:#8b949e;font-size:12px">No substitutions detected</p>'}
</div>
<div style="text-align:center;padding:20px;color:#8b949e;font-size:11px">
  TZI v2 — Tactical Zone Intelligence · Indica Labs · 2026
</div></body></html>"""


# ── Main processing ───────────────────────────────────────────────

def process_half(video_path, half_label, t_offset, match_dir, interval_min, use_ocr):
    cap     = cv2.VideoCapture(str(video_path))
    fps     = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_f = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    sample  = max(1, int(fps * 60 * interval_min))

    frames_dir = match_dir / "frames_v2"
    frames_dir.mkdir(exist_ok=True)

    tracker    = PlayerTrackerV2()
    frame_dets = []
    fn = 0

    print(f"\n{half_label}: {total_f}f, {fps:.0f}fps, ~{total_f/fps/60:.0f}min")

    while True:
        ret, frame = cap.read()
        if not ret: break
        fn += 1
        if fn % sample != 0: continue

        local_t = fn / fps / 60
        t_min   = local_t + t_offset
        dets    = detect_waseda(frame)

        active  = tracker.update(dets, t_min, half_label, use_ocr)

        # Annotate and save frame
        out_frame = draw_frame(frame, dets, active)
        # HUD
        cv2.rectangle(out_frame, (0, 0), (out_frame.shape[1], 44), (0, 0, 0), -1)
        cv2.addWeighted(out_frame[:44], 0.6, frame[:44], 0.4, 0, out_frame[:44])
        n_jersey = sum(1 for tr in active if tr.jersey_number)
        cv2.putText(out_frame, f"{half_label} {local_t:.1f}min | active={len(active)} jersey_id={n_jersey}/{len(active)}",
                    (8, 18), FONT, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
        fname = frames_dir / f"v2_{half_label}_{local_t:.1f}min.jpg"
        cv2.imwrite(str(fname), out_frame, [cv2.IMWRITE_JPEG_QUALITY, 82])

        frame_dets.append({"time_min": round(t_min, 2), "n_dets": len(dets), "n_active": len(active)})

        if fn % (sample * 10) == 0:
            print(f"  {local_t:.0f}min active={len(active)} "
                  f"suspended={len(tracker.suspended)} total_created={tracker.nid}")

    cap.release()
    tracker.flush_all()
    return tracker.all_tracks(), frame_dets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--match",    required=True, help="e.g. 20260325")
    ap.add_argument("--interval", type=float, default=3.0)
    ap.add_argument("--h1",       default=None)
    ap.add_argument("--h2",       default=None)
    ap.add_argument("--single",   action="store_true")
    ap.add_argument("--no-ocr",   action="store_true")
    args = ap.parse_args()

    use_ocr   = not args.no_ocr
    match_dir = PROJECT_ROOT / "data" / "tzi" / f"match_{args.match}"
    match_dir.mkdir(parents=True, exist_ok=True)
    videos    = PROJECT_ROOT / "videos"

    print(f"=== TZI Track v2  match={args.match}  interval={args.interval}min  ocr={use_ocr} ===")

    # Resolve video paths
    if args.h1:
        h1 = videos / args.h1
    else:
        try:
            from config import VIDEO_H1; h1 = VIDEO_H1
        except Exception:
            print("ERROR: --h1 required"); sys.exit(1)

    if not h1.exists():
        print(f"ERROR: {h1}"); sys.exit(1)

    t0 = time.time()
    all_tracks, all_frames = [], []

    # First half
    h1_tracks, h1_frames = process_half(h1, "1H", 0.0, match_dir, args.interval, use_ocr)
    all_tracks.extend(h1_tracks)
    all_frames.extend(h1_frames)

    # Second half
    if not args.single:
        if args.h2:
            h2 = videos / args.h2
        else:
            try:
                from config import VIDEO_H2; h2 = VIDEO_H2
            except Exception:
                print("WARNING: no H2 video, treating as single"); h2 = None

        if h2 and h2.exists():
            cap_tmp = cv2.VideoCapture(str(h1))
            fps_tmp = cap_tmp.get(cv2.CAP_PROP_FPS) or 30.0
            nf_tmp  = int(cap_tmp.get(cv2.CAP_PROP_FRAME_COUNT))
            cap_tmp.release()
            h1_dur = nf_tmp / fps_tmp / 60.0
            h2_tracks, h2_frames = process_half(h2, "2H", h1_dur, match_dir, args.interval, use_ocr)
            all_tracks.extend(h2_tracks)
            all_frames.extend(h2_frames)

    print(f"\nBefore merge: {len(all_tracks)} tracks")
    all_tracks = merge_tracks(all_tracks)
    print(f"After  merge: {len(all_tracks)} tracks")

    subs = detect_substitutions(all_tracks)
    print(f"Substitutions detected: {len(subs)}")

    # Renumber tracks cleanly
    for i, tr in enumerate(sorted(all_tracks, key=lambda t: t.sightings[0]["time_min"] if t.sightings else 0)):
        tr.tid = f"P{i+1:02d}"

    # Stats
    n_with_jersey = sum(1 for t in all_tracks if t.jersey_number)
    total_sights  = sum(len(t.sightings) for t in all_tracks)
    avg_pf        = total_sights / max(len(all_frames), 1)

    stats = {
        "n_players":    len(all_tracks),
        "n_frames":     len(all_frames),
        "n_with_jersey": n_with_jersey,
        "avg_per_frame": avg_pf,
        "elapsed_sec":  round(time.time() - t0, 1),
    }

    # Build output JSON
    out_players = []
    for tr in all_tracks:
        zones = defaultdict(int)
        for s in tr.sightings: zones[s["zone"]] += 1
        out_players.append({
            "player_id":     tr.tid,
            "jersey_number": tr.jersey_number,
            "sightings":     tr.sightings,
            "zone_dist":     dict(zones),
            "n_sightings":   len(tr.sightings),
        })

    out_json = match_dir / "players_v2.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({"match": args.match, "stats": stats,
                   "players": out_players}, f, ensure_ascii=False, indent=2)

    sub_json = match_dir / "substitutions.json"
    with open(sub_json, "w", encoding="utf-8") as f:
        json.dump(subs, f, ensure_ascii=False, indent=2)

    report_html = build_report(args.match, all_tracks, subs, stats)
    report_path = match_dir / "tracking_report_v2.html"
    report_path.write_text(report_html, encoding="utf-8")

    elapsed = time.time() - t0
    print(f"\n=== DONE ===")
    print(f"Players (merged)  : {len(all_tracks)}")
    print(f"Jersey # found    : {n_with_jersey}/{len(all_tracks)}")
    print(f"Substitutions     : {len(subs)}")
    print(f"Time              : {elapsed:.0f}s ({elapsed/60:.1f}min)")
    print(f"JSON  → {out_json}")
    print(f"Report→ {report_path}")


if __name__ == "__main__":
    main()
