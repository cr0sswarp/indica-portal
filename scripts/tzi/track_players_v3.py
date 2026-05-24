#!/usr/bin/env python3
"""
TZI: Player Tracking v3 — Dual-Team Augmentation + Direction Normalization

Key improvements over v2:
1. Dual-team detection: Waseda (maroon) + opponent team (auto-detected dominant color)
   → Opponent positions used as spatial anchors for better field coverage
2. Half-time direction normalization: auto-detect which side Waseda attacks each half
   → Flip coordinates so Waseda ALWAYS attacks toward x=105 (right)
   → Right-back (#6) consistently appears at high Y, low X in normalized frame
3. Y-axis fix: remove incorrect m[680:]=0 cutoff — near touchline is at pixel Y=705,
   not 680, so previously all touchline players were cut off
4. Normalized heatmap: generates heatmap where right-back should ALWAYS appear
   on right side regardless of which half they played

Usage:
    python track_players_v3.py --match 20260325
    python track_players_v3.py --match 20260325 --interval 2
    python track_players_v3.py --match all  # process all available matches

Output:
    data/tzi/match_YYYYMMDD/players_v3.json
    data/tzi/match_YYYYMMDD/heatmap_v3_jersey6.png
    data/tzi/match_YYYYMMDD/heatmap_v3_team.png
    data/tzi/match_YYYYMMDD/direction_debug.jpg  (per-half centroid visualization)
    data/tzi/match_YYYYMMDD/tracking_report_v3.html
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
DATA_TZI     = PROJECT_ROOT / "data" / "tzi"
FW, FH       = 105.0, 68.0

# ── Homography (same calibration points) ─────────────────────────
# SRC: pixel coords of known field points in video frame
# DST: corresponding field coords in meters
# Point 1: top-left corner of visible field (far touchline, goal line)  → (0,0)
# Point 2: top-right corner                                              → (105,0)
# Point 3: center circle at pixel ~y=298 (center field, far half)       → (52.5,34)
# Point 4: center of near touchline at pixel ~y=705                     → (52.5,68)
SRC = np.float32([[20, 90], [1255, 88], [635, 298], [635, 705]])
DST = np.float32([[0, 0],   [105, 0],  [52.5, 34], [52.5, 68]])
H_MAT, _ = cv2.findHomography(SRC, DST, cv2.RANSAC, 3.0)

# ── HSV ranges ───────────────────────────────────────────────────
# Waseda maroon (dark red)
W_LO1, W_HI1 = np.array([0,   50, 40]),  np.array([12,  255, 220])
W_LO2, W_HI2 = np.array([165, 50, 40]),  np.array([180, 255, 220])
# Field green (excluded from opponent detection)
G_LO,  G_HI  = np.array([35,  40, 40]),  np.array([85,  255, 200])
# White/light players
WH_LO, WH_HI = np.array([0,   0,  160]), np.array([180, 60,  255])
# Blue players (Japan national)
BL_LO, BL_HI = np.array([100, 60, 40]),  np.array([130, 255, 220])

KNL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

# ── Tracking parameters ───────────────────────────────────────────
MAX_DIST_PIXELS   = 100
MAX_DISAPPEAR     = 6
RE_ID_DIST        = 180
HIST_SIMILARITY   = 0.35
MAX_PLAYERS_FIELD = 11
MERGE_GAP_MIN     = 15.0
MERGE_DIST_M      = 22.0
MIN_SIGHTINGS     = 3
FONT = cv2.FONT_HERSHEY_SIMPLEX

# ── Match configuration ───────────────────────────────────────────
MATCH_CONFIGS = {
    "20260314":        {"h1": "26_03_14_I_TRM vs埼玉大.mp4",         "h2": None},
    "20260316":        {"h1": "26_03_16_I_vs 岐阜協立.mp4",          "h2": None},
    "20260317mid":     {"h1": "26_03_17_I_ vs中京U-19 前半.mp4",     "h2": "26_03_17_I_ vs中京U-19 後半.mp4"},
    "20260317osaka":   {"h1": "26_03_17_I_ vs大阪学院 前半.mp4",     "h2": "26_03_17_I_ vs大阪学院 後半.mp4"},
    "20260318":        {"h1": "26_03_18_I_ vs作新学院 前半.mp4",     "h2": "26_03_18_I_ vs作新学院 後半.mp4"},
    "20260325":        {"h1": "26_03_25_I_TRM vs立教大 前半.mp4",    "h2": "26_03_25_I_TRM vs立教大 後半.mp4"},
    "20260329":        {"h1": "26_03_29_I_TRM vs川崎U-18 前半.mp4", "h2": "26_03_29_I_TRM vs 川崎U-18 後半.mp4"},
    "20260405":        {"h1": "26_04_05_I_TRM vs獨協大前半.mp4",     "h2": "26_04_05_I_TRM vs獨協大後半.mp4"},
}
MATCH_LABELS = {
    "20260314":      "vs埼玉大 (03/14)",
    "20260316":      "vs岐阜協立 (03/16)",
    "20260317mid":   "vs中京U-19 (03/17)",
    "20260317osaka": "vs大阪学院 (03/17)",
    "20260318":      "vs作新学院 (03/18)",
    "20260325":      "vs立教大 (03/25)",
    "20260329":      "vs川崎U-18 (03/29)",
    "20260405":      "vs獨協大 (04/05)",
}


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


def normalize_pos(fx, fy, flip):
    """Normalize field coordinates so Waseda always attacks right (x→105).
    Only X is flipped — 'right touchline' stays the same side all game.
    Teams swap ENDS (goals) at HT, not their wing assignments.
    """
    if flip:
        return round(FW - fx, 2), round(fy, 2)
    return round(fx, 2), round(fy, 2)


# ── Detection functions ───────────────────────────────────────────

def _build_base_mask(frame_h):
    """Returns slice params for valid detection region.
    Near touchline is at pixel Y≈705, so don't cut before 715."""
    return 60, min(frame_h, 720)   # (top_cutoff, bottom_cutoff)


def detect_waseda(frame):
    """Detect Waseda (maroon) players. Returns list of detection dicts."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    m   = cv2.bitwise_or(cv2.inRange(hsv, W_LO1, W_HI1),
                          cv2.inRange(hsv, W_LO2, W_HI2))
    top, bot = _build_base_mask(frame.shape[0])
    m[:top, :] = 0
    m[bot:, :] = 0
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN,  KNL)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, KNL, iterations=2)
    return _extract_dets(m, frame)


def detect_opponents(frame, opp_hsv_ranges):
    """Detect opponent players using pre-determined HSV ranges."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    # Start with all non-green, non-maroon blobs
    field_mask = cv2.inRange(hsv, G_LO, G_HI)
    waseda_m   = cv2.bitwise_or(cv2.inRange(hsv, W_LO1, W_HI1),
                                 cv2.inRange(hsv, W_LO2, W_HI2))

    opp_m = np.zeros(field_mask.shape, dtype=np.uint8)
    for (lo, hi) in opp_hsv_ranges:
        opp_m = cv2.bitwise_or(opp_m, cv2.inRange(hsv, lo, hi))

    # Exclude field and Waseda
    opp_m = cv2.bitwise_and(opp_m, cv2.bitwise_not(field_mask))
    opp_m = cv2.bitwise_and(opp_m, cv2.bitwise_not(waseda_m))

    top, bot = _build_base_mask(frame.shape[0])
    opp_m[:top, :] = 0
    opp_m[bot:, :]  = 0
    opp_m = cv2.morphologyEx(opp_m, cv2.MORPH_OPEN,  KNL)
    opp_m = cv2.morphologyEx(opp_m, cv2.MORPH_CLOSE, KNL, iterations=2)
    return _extract_dets(opp_m, frame)


def _extract_dets(mask, frame):
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cnts:
        a = cv2.contourArea(c)
        # Raise min area to 150 to filter small noise/shadow blobs
        if not (150 < a < 3500): continue
        x, y, w, h = cv2.boundingRect(c)
        # Require taller-than-wide blobs (players are vertical); reject wide bench artifacts
        if h / (w + 1e-5) < 0.65 or h / (w + 1e-5) > 9: continue
        cx, cy = x + w // 2, y + h
        fx, fy = p2f(cx, cy)
        crop = frame[max(0, y):y+h, max(0, x):x+w]
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
    return h / n if n > 0 else h


def hist_sim(a, b):
    return float(np.dot(a, b))


# ── Auto-detect opponent color from first 10 frames of a video ───

def auto_detect_opponent_color(video_path, n_sample=10):
    """
    Sample first n_sample frames and use K-means on non-field, non-Waseda HSV
    pixels to find dominant opponent jersey color range.
    Returns list of (lo, hi) HSV range tuples.
    """
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    # Sample at 2min, 5min, 8min, ... intervals
    sample_frames = [int(fps * 60 * t) for t in range(2, 2 + n_sample * 3, 3)]

    all_px = []
    for target_f in sample_frames:
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_f)
        ret, frame = cap.read()
        if not ret:
            break
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        # Mask out field (green) and Waseda (maroon) and background (top/bottom)
        field_mask  = cv2.inRange(hsv, G_LO, G_HI)
        waseda_mask = cv2.bitwise_or(cv2.inRange(hsv, W_LO1, W_HI1),
                                      cv2.inRange(hsv, W_LO2, W_HI2))
        combined = cv2.bitwise_or(field_mask, waseda_mask)
        valid    = cv2.bitwise_not(combined)

        # Only look in the player region (Y: 60–720)
        h = frame.shape[0]
        roi_mask = np.zeros(h, dtype=np.uint8)
        roi_mask[60:min(h, 720)] = 255
        roi_2d = np.zeros_like(valid)
        roi_2d[60:min(h, 720), :] = valid[60:min(h, 720), :]

        px = hsv[roi_2d > 0]
        if len(px) > 100:
            # Subsample to keep computation fast
            idx = np.random.choice(len(px), min(500, len(px)), replace=False)
            all_px.append(px[idx])

    cap.release()

    if not all_px:
        print("  [auto_color] No pixels found, using white/light as default opponent")
        return [(WH_LO, WH_HI)]

    all_px = np.vstack(all_px).astype(np.float32)

    # K-means to find 3 dominant non-field, non-Waseda colors
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 0.5)
    k = min(4, len(all_px))
    _, labels, centers = cv2.kmeans(all_px, k, None, criteria, 5, cv2.KMEANS_PP_CENTERS)

    # Each center is (H, S, V); build ranges with ±15H, ±50S, ±60V
    ranges = []
    for c in centers:
        h_c, s_c, v_c = int(c[0]), int(c[1]), int(c[2])
        # Skip dark/unsaturated clusters (likely shadows/lines)
        if v_c < 60 or s_c < 20:
            continue
        lo = np.array([max(0, h_c - 15), max(0, s_c - 50), max(30, v_c - 60)])
        hi = np.array([min(180, h_c + 15), min(255, s_c + 50), min(255, v_c + 60)])
        ranges.append((lo, hi))

    if not ranges:
        print("  [auto_color] K-means gave no valid clusters, using white default")
        return [(WH_LO, WH_HI)]

    print(f"  [auto_color] Detected {len(ranges)} opponent color clusters:")
    for lo, hi in ranges:
        print(f"    H={lo[0]}-{hi[0]}, S={lo[1]}-{hi[1]}, V={lo[2]}-{hi[2]}")

    return ranges


# ── Direction detection (per-half) ───────────────────────────────

def detect_attack_direction(sightings_1h, sightings_2h):
    """
    Determine if Waseda attacks right (x→105) or left (x→0) in each half.
    Returns (flip_1h: bool, flip_2h: bool) — True means flip that half's coords.

    Logic:
    - Compute mean X position of Waseda in each half
    - If 1H mean X < 52.5 (left half), Waseda defends left, attacks right → no flip
    - If 1H mean X > 52.5 (right half), Waseda defends right, attacks left → flip 1H
    - Teams swap ends at HT, so 2H is always opposite of 1H
    """
    def mean_x(sightings):
        if not sightings:
            return 52.5
        xs = [s["fx"] for s in sightings]
        return float(np.mean(xs))

    cx_1h = mean_x(sightings_1h)
    cx_2h = mean_x(sightings_2h)

    print(f"  [direction] 1H centroid_x={cx_1h:.1f}m, 2H centroid_x={cx_2h:.1f}m")

    # A right-back (defending team's right) typically stays in one side
    # If both halves have similar centroid, it's ambiguous (both teams detected)
    # Use absolute comparison against center line
    flip_1h = cx_1h > 52.5   # Waseda is in right half in 1H → they attack LEFT → flip
    flip_2h = cx_2h > 52.5   # Same logic for 2H

    # Sanity: teams should swap at HT, so flip_1h != flip_2h ideally
    if flip_1h == flip_2h and sightings_1h and sightings_2h:
        # Ambiguous - both halves same side. Compare magnitudes.
        dev_1h = abs(cx_1h - 52.5)
        dev_2h = abs(cx_2h - 52.5)
        # Use the half with clearer signal to infer the other
        if dev_1h > dev_2h:
            flip_2h = not flip_1h
            print(f"  [direction] Ambiguous: using 1H ({cx_1h:.1f}m) as primary, flip_2h={flip_2h}")
        else:
            flip_1h = not flip_2h
            print(f"  [direction] Ambiguous: using 2H ({cx_2h:.1f}m) as primary, flip_1h={flip_1h}")

    dir_1h = "attacks_LEFT (flip)" if flip_1h else "attacks_RIGHT (keep)"
    dir_2h = "attacks_LEFT (flip)" if flip_2h else "attacks_RIGHT (keep)"
    print(f"  [direction] 1H: {dir_1h}")
    print(f"  [direction] 2H: {dir_2h}")

    return flip_1h, flip_2h


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
    if not use_ocr or crop is None or crop.size == 0:
        return None
    reader = _get_ocr()
    if not reader:
        return None
    h, w = crop.shape[:2]
    roi = crop[:int(h * 0.6), :]
    if roi.size == 0:
        return None
    roi  = cv2.resize(roi, (roi.shape[1] * 3, roi.shape[0] * 3))
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


# ── Kalman filter: 2D constant-velocity model ─────────────────────
# State: [px, py, vx, vy].  Observation: [px, py].
# Used to predict player position during detection gaps (ByteTrack / OC-SORT).

class KF2D:
    """Lightweight 2D Kalman filter for pixel-space player tracking."""

    def __init__(self, px: float, py: float):
        dt = 1.0
        self.x = np.array([px, py, 0.0, 0.0], dtype=float)
        self.F = np.array([[1, 0, dt, 0],
                           [0, 1, 0, dt],
                           [0, 0, 1,  0],
                           [0, 0, 0,  1]], dtype=float)
        self.H = np.array([[1, 0, 0, 0],
                           [0, 1, 0, 0]], dtype=float)
        # Process noise: higher on velocity components
        self.Q = np.diag([10.0, 10.0, 40.0, 40.0])
        # Measurement noise (pixels²)
        self.R = np.diag([30.0, 30.0])
        self.P = np.eye(4) * 100.0

    def predict(self):
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q
        return float(self.x[0]), float(self.x[1])

    def update(self, px: float, py: float):
        z = np.array([px, py])
        y = z - self.H @ self.x
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.x = self.x + K @ y
        self.P = (np.eye(4) - K @ self.H) @ self.P
        return float(self.x[0]), float(self.x[1])

    def predicted_pos(self):
        """Return next-step predicted position without mutating state."""
        x_next = self.F @ self.x
        return float(x_next[0]), float(x_next[1])

    def velocity(self):
        return float(self.x[2]), float(self.x[3])

    def oc_sort_reinit(self, px_new: float, py_new: float, px_last: float, py_last: float, dt: float):
        """OC-SORT observation-centric re-update: when a track reappears after
        a gap, recalibrate velocity from the last confirmed obs → new obs rather
        than trusting the drifted Kalman velocity."""
        if dt > 0:
            self.x[2] = (px_new - px_last) / dt
            self.x[3] = (py_new - py_last) / dt
        self.x[0], self.x[1] = px_new, py_new
        self.P = np.eye(4) * 100.0  # reset covariance


# ── Expansion IoU helper ──────────────────────────────────────────

def expansion_iou(b1, b2, expand: float = 1.5) -> float:
    """Compute IoU after expanding both bounding boxes by 'expand' factor.
    Expansion compensates for slight misalignment of player detections
    (Deep HM-SORT / EIoU technique, CVPR 2023)."""
    def expand_box(b, f):
        x1, y1, x2, y2 = b
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        hw, hh = (x2 - x1) * f / 2, (y2 - y1) * f / 2
        return cx - hw, cy - hh, cx + hw, cy + hh

    a, b = expand_box(b1, expand), expand_box(b2, expand)
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter + 1e-6)


# ── Player track ─────────────────────────────────────────────────

class PlayerTrack:
    __slots__ = ("tid", "sightings", "hist_samples", "disappeared",
                 "active", "jersey_number", "jersey_votes",
                 "last_px", "last_py", "last_bbox", "kf")

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
        self.last_bbox     = det.get("bbox")
        self.kf            = KF2D(float(det["px"]), float(det["py"]))

    def predicted_px_py(self):
        """Kalman-predicted pixel position for next frame."""
        return self.kf.predicted_pos()

    def update(self, det, t_min, half):
        self.sightings.append({
            "time_min": round(t_min, 2),
            "half":     half,
            "fx":       det["fx"],
            "fy":       det["fy"],
            "px":       det["px"],
            "py":       det["py"],
            "zone":     det["zone"],
        })
        self.hist_samples.append(det["hist"])
        if len(self.hist_samples) > 20:
            self.hist_samples = self.hist_samples[-20:]
        self.kf.predict()
        self.kf.update(float(det["px"]), float(det["py"]))
        self.last_px  = det["px"]
        self.last_py  = det["py"]
        self.last_bbox = det.get("bbox")
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

class PlayerTrackerV3:
    def __init__(self):
        self.nid       = 0
        self.active:    dict[int, PlayerTrack] = {}
        self.suspended: dict[int, PlayerTrack] = {}
        self.done:      list[PlayerTrack]      = []

    def _new_track(self, det):
        t = PlayerTrack(f"P{self.nid:03d}", det)
        self.nid += 1
        return t

    def _match(self, dets, tracks):
        """Two-stage ByteTrack-style matching with Kalman prediction + EIoU.

        Stage 1: Match dets to active tracks using Kalman-predicted positions
                 and Expansion IoU (handles slight bbox misalignment).
        Stage 2: Remaining dets matched to recently-suspended tracks via
                 appearance (histogram) + spatial proximity (Re-ID).
        """
        if not tracks or not dets:
            return {}, set(range(len(dets)))

        tids = list(tracks.keys())
        n, m = len(tids), len(dets)
        cost = np.full((n, m), 9999.0)

        for i, tid in enumerate(tids):
            tr = tracks[tid]
            mh = tr.mean_hist()
            # Use Kalman-predicted position for matching (not last observed)
            pred_px, pred_py = tr.kf.predicted_pos()
            for j, d in enumerate(dets):
                dist = np.sqrt((pred_px - d["px"])**2 + (pred_py - d["py"])**2)
                if dist > MAX_DIST_PIXELS:
                    continue
                sim = hist_sim(mh, d["hist"])
                # EIoU bonus: reward spatial overlap with expanded bboxes
                eiou = 0.0
                if tr.last_bbox and d.get("bbox"):
                    eiou = expansion_iou(tr.last_bbox, d["bbox"], expand=1.5)
                # Combined cost: distance penalized by appearance + EIoU
                cost[i, j] = dist * (1.0 - 0.3 * sim - 0.2 * eiou)

        matched, used_j = {}, set()
        order = np.dstack(np.unravel_index(np.argsort(cost.ravel()), cost.shape))[0]
        for i, j in order:
            if cost[i, j] >= 9999: break
            tid = tids[i]
            if tid in matched or j in used_j: continue
            matched[tid] = j
            used_j.add(j)
        unmatched = {j for j in range(m) if j not in used_j}
        return matched, unmatched

    def update(self, dets, t_min, half, use_ocr=True):
        matched, unmatched = self._match(dets, self.active)

        for tid, j in matched.items():
            d = dets[j]
            self.active[tid].update(d, t_min, half)
            self.active[tid].vote_jersey(read_jersey_number(d["crop"], use_ocr))

        for tid in list(self.active.keys()):
            if tid not in matched:
                # Advance Kalman prediction even when no detection (predict-only step)
                self.active[tid].kf.predict()
                self.active[tid].disappeared += 1
                if self.active[tid].disappeared > MAX_DISAPPEAR:
                    tr = self.active.pop(tid)
                    self.suspended[tid] = tr

        still_unmatched = set()
        for j in unmatched:
            d = dets[j]
            best_tid, best_cost = None, 9999.0
            for tid, tr in self.suspended.items():
                # Use Kalman-predicted position for Re-ID distance
                pred_px, pred_py = tr.kf.predicted_pos()
                dist = np.sqrt((pred_px - d["px"])**2 + (pred_py - d["py"])**2)
                if dist > RE_ID_DIST: continue
                sim  = hist_sim(tr.mean_hist(), d["hist"])
                eiou = expansion_iou(tr.last_bbox, d["bbox"], 1.5) if tr.last_bbox and d.get("bbox") else 0.0
                c    = dist * (1.0 - 0.4 * sim - 0.15 * eiou)
                if c < best_cost:
                    best_cost = c; best_tid = tid
            if best_tid is not None and best_cost < RE_ID_DIST * 0.8:
                tr = self.suspended.pop(best_tid)
                # OC-SORT: recalibrate velocity from last observed → new observed
                # rather than trusting drifted Kalman velocity during the gap
                gap_frames = tr.disappeared + 1
                tr.kf.oc_sort_reinit(float(d["px"]), float(d["py"]),
                                     float(tr.last_px), float(tr.last_py),
                                     float(gap_frames))
                tr.disappeared = 0
                tr.update(d, t_min, half)
                tr.vote_jersey(read_jersey_number(d["crop"], use_ocr))
                self.active[best_tid] = tr
            else:
                still_unmatched.add(j)

        if len(self.active) > MAX_PLAYERS_FIELD:
            by_s = sorted(self.active.keys(), key=lambda k: len(self.active[k].sightings))
            for tid in by_s[:len(self.active) - MAX_PLAYERS_FIELD]:
                self.suspended[tid] = self.active.pop(tid)

        for j in still_unmatched:
            d  = dets[j]
            tr = self._new_track(d)
            tr.update(d, t_min, half)
            tr.vote_jersey(read_jersey_number(d["crop"], use_ocr))
            self.active[self.nid - 1] = tr

        return list(self.active.values())

    def flush_all(self):
        for tr in self.active.values():   self.done.append(tr)
        for tr in self.suspended.values(): self.done.append(tr)
        self.active.clear(); self.suspended.clear()

    def all_tracks(self): return self.done


# ── Track merging ─────────────────────────────────────────────────

def merge_tracks(tracks):
    """Merge tracklet fragments that likely belong to the same player.

    Improvements over v3:
    - Velocity consistency check: if gap is short and trajectory direction
      matches expected movement, boost the merge score (AFLink-inspired).
    - Symmetric gap handling: either tracklet can be 'earlier'.
    """
    for t in tracks:
        t.sightings.sort(key=lambda s: s["time_min"])

    def info(t):
        s = t.sightings
        if not s: return None
        return {"t_end":    s[-1]["time_min"],  "t_start": s[0]["time_min"],
                "end_fx":   s[-1]["fx"],         "end_fy":  s[-1]["fy"],
                "start_fx": s[0]["fx"],          "start_fy": s[0]["fy"]}

    def _velocity_penalty(ii, ij, gap):
        """Penalize merges where implied velocity is physically impossible.
        A player cannot cross >8m/s (sprint ≈7m/s), but interval is minutes.
        For multi-minute gaps any position is plausible → no penalty."""
        if gap < 1.0:  # within 1 min: check implied speed
            dist = np.sqrt((ii["end_fx"] - ij["start_fx"])**2 +
                           (ii["end_fy"] - ij["start_fy"])**2)
            speed = dist / (gap * 60)  # m/s
            if speed > 8.0:
                return 5.0   # heavy penalty — physically implausible
        return 1.0            # no penalty

    merged = True
    while merged:
        merged = False
        n = len(tracks)
        used = [False] * n
        result = []
        for i in range(n):
            if used[i]: continue
            ti = tracks[i]; ii = info(ti)
            if ii is None: used[i] = True; continue
            best_j, best_score = -1, 9999.0
            for j in range(i + 1, n):
                if used[j]: continue
                tj = tracks[j]; ij = info(tj)
                if ij is None: continue
                if ii["t_end"] < ij["t_start"]:
                    earlier, later = ii, ij
                    gap  = later["t_start"] - earlier["t_end"]
                    dist = np.sqrt((earlier["end_fx"] - later["start_fx"])**2 +
                                   (earlier["end_fy"] - later["start_fy"])**2)
                elif ij["t_end"] < ii["t_start"]:
                    earlier, later = ij, ii
                    gap  = later["t_start"] - earlier["t_end"]
                    dist = np.sqrt((earlier["end_fx"] - later["start_fx"])**2 +
                                   (earlier["end_fy"] - later["start_fy"])**2)
                else:
                    continue
                if gap > MERGE_GAP_MIN or dist > MERGE_DIST_M: continue
                sim = hist_sim(ti.mean_hist(), tj.mean_hist())
                if sim < HIST_SIMILARITY: continue
                v_pen = _velocity_penalty(earlier, later, gap)
                score = (gap * dist / (sim + 0.01)) * v_pen
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

    return [t for t in tracks if len(t.sightings) >= MIN_SIGHTINGS]


def smooth_trajectories(tracks):
    """Apply Savitzky-Golay filter to smooth normalized trajectory positions.

    Ref: StrongSORT++ GSI (Gaussian-Smoothed Interpolation) concept.
    We use Savitzky-Golay which preserves peaks (sudden direction changes)
    better than Gaussian — important for realistic soccer movements.

    Adds 'fx_smooth' and 'fy_smooth' fields to each sighting.
    Tracks with < 5 sightings are left unsmoothed.
    """
    try:
        from scipy.signal import savgol_filter
    except ImportError:
        return tracks  # scipy not available

    for tr in tracks:
        sigs = sorted(tr.sightings, key=lambda s: s["time_min"])
        n = len(sigs)
        if n < 5:
            for s in sigs:
                s["fx_smooth"] = s.get("fx_norm", s["fx"])
                s["fy_smooth"] = s.get("fy_norm", s["fy"])
            continue

        fxs = np.array([s.get("fx_norm", s["fx"]) for s in sigs])
        fys = np.array([s.get("fy_norm", s["fy"]) for s in sigs])

        # Window must be odd and <= n; polynomial order < window
        window = min(n, 7) if n >= 7 else (n if n % 2 == 1 else n - 1)
        if window < 3:
            for s in sigs:
                s["fx_smooth"] = s.get("fx_norm", s["fx"])
                s["fy_smooth"] = s.get("fy_norm", s["fy"])
            continue

        poly = min(2, window - 1)
        fxs_s = savgol_filter(fxs, window, poly)
        fys_s = savgol_filter(fys, window, poly)

        for i, s in enumerate(sigs):
            s["fx_smooth"] = round(float(np.clip(fxs_s[i], 0, FW)), 2)
            s["fy_smooth"] = round(float(np.clip(fys_s[i], 0, FH)), 2)
            s["zone_smooth"] = fx_to_zone(s["fx_smooth"])

    return tracks


# ── Substitution detection ────────────────────────────────────────

def detect_substitutions(tracks):
    subs = []
    by_end = sorted(tracks, key=lambda t: t.sightings[-1]["time_min"] if t.sightings else 0)
    for t_out in by_end:
        if not t_out.sightings: continue
        t_end   = t_out.sightings[-1]["time_min"]
        fx_out  = t_out.sightings[-1]["fx"]
        fy_out  = t_out.sightings[-1]["fy"]
        half_out = t_out.sightings[-1]["half"]
        if t_end > 43 and half_out == "1H": continue
        if t_end > 88 and half_out == "2H": continue
        for t_in in tracks:
            if not t_in.sightings or t_in.tid == t_out.tid: continue
            t_start = t_in.sightings[0]["time_min"]
            if not (0 < t_start - t_end < 5.0): continue
            dist = np.sqrt((fx_out - t_in.sightings[0]["fx"])**2 +
                           (fy_out - t_in.sightings[0]["fy"])**2)
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
            break
    subs.sort(key=lambda s: s["time_min"])
    return subs


# ── Heatmap generation ────────────────────────────────────────────

def generate_heatmap(tracks, match_dir, match_id, jersey6_id=None):
    """Generate normalized heatmap — Waseda always attacks right."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.font_manager as fm
        from scipy.ndimage import gaussian_filter
        from matplotlib.patches import FancyArrowPatch
        _jp_font = "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf"
        if Path(_jp_font).exists():
            fm.fontManager.addfont(_jp_font)
            matplotlib.rcParams["font.family"] = "IPAGothic"
    except ImportError:
        print("  [heatmap] matplotlib/scipy not available, skipping")
        return

    all_fx, all_fy = [], []
    j6_fx, j6_fy   = [], []

    for tr in tracks:
        for s in tr.sightings:
            fx_n, fy_n = s.get("fx_norm", s["fx"]), s.get("fy_norm", s["fy"])
            all_fx.append(fx_n); all_fy.append(fy_n)
            if tr.jersey_number == 6 or tr.tid == jersey6_id:
                j6_fx.append(fx_n); j6_fy.append(fy_n)

    if not all_fx:
        print("  [heatmap] No positions to plot")
        return

    fig, axes = plt.subplots(1, 2, figsize=(18, 6.5))
    fig.patch.set_facecolor("#0d1117")

    titles = [
        f"Team Heatmap — {MATCH_LABELS.get(match_id, match_id)} (n={len(all_fx)})",
        f"#6 牧野羽瑠 — {MATCH_LABELS.get(match_id, match_id)} (n={len(j6_fx)})",
    ]
    data_pairs = [(all_fx, all_fy), (j6_fx, j6_fy)]

    for ax, (fxs, fys), title in zip(axes, data_pairs, titles):
        ax.set_facecolor("#161b22")
        ax.set_xlim(0, FW); ax.set_ylim(0, FH)
        ax.set_aspect("equal")
        ax.set_title(title, color="#e6edf3", fontsize=10, pad=6)

        # Draw field lines
        _draw_field(ax)

        if fxs:
            H, xe, ye = np.histogram2d(fxs, fys, bins=[35, 23],
                                        range=[[0, FW], [0, FH]])
            H = gaussian_filter(H.T, sigma=1.8)
            ax.contourf(np.linspace(0, FW, 35), np.linspace(0, FH, 23),
                        H, levels=12, cmap="hot", alpha=0.7)

        # Mark #6 sightings explicitly
        if fxs and (fxs is j6_fx):
            ax.scatter(fxs, fys, c="cyan", s=20, alpha=0.7, zorder=5, marker="*")
            if fxs:
                ax.scatter([np.mean(fxs)], [np.mean(fys)], c="white", s=80,
                           marker="X", zorder=6, label=f"centroid ({np.mean(fxs):.1f},{np.mean(fys):.1f})")
                ax.legend(fontsize=7, labelcolor="white",
                          facecolor="#21262d", edgecolor="#30363d")

        # Arrow showing attack direction (always right in normalized view)
        ax.annotate("", xy=(FW * 0.9, FH / 2), xytext=(FW * 0.75, FH / 2),
                    arrowprops=dict(arrowstyle="->", color="#3fb950", lw=2))
        ax.text(FW * 0.92, FH / 2, "ATTACK", color="#3fb950",
                fontsize=7, va="center")

        ax.tick_params(colors="#8b949e")
        for sp in ax.spines.values():
            sp.set_edgecolor("#30363d")

    plt.tight_layout(pad=1.5)
    out_path = match_dir / "heatmap_v3.png"
    plt.savefig(str(out_path), dpi=130, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  [heatmap] Saved → {out_path}")
    return out_path


def _draw_field(ax):
    """Draw basic soccer field markings."""
    import matplotlib.patches as mpatches
    col = "#30363d"
    # Outline
    ax.add_patch(mpatches.Rectangle((0, 0), FW, FH, fill=False, edgecolor=col, lw=1.5))
    # Center line
    ax.axvline(FW / 2, color=col, lw=1)
    # Center circle
    ax.add_patch(mpatches.Circle((FW / 2, FH / 2), 9.15, fill=False, edgecolor=col, lw=1))
    # Penalty areas
    for x_start in [0, FW - 16.5]:
        ax.add_patch(mpatches.Rectangle((x_start, (FH - 40.32) / 2),
                                         16.5, 40.32, fill=False, edgecolor=col, lw=1))
    # Goals
    for x_start in [0, FW - 2.44]:
        ax.add_patch(mpatches.Rectangle((x_start, (FH - 7.32) / 2),
                                         2.44, 7.32, fill=False, edgecolor="#8b949e", lw=1.5))


# ── Direction debug visualization ────────────────────────────────

def save_direction_debug(tracks, match_dir, flip_1h, flip_2h):
    """Save a small diagram showing raw vs normalized centroids per half."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.font_manager as fm
        _jp = "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf"
        if Path(_jp).exists():
            fm.fontManager.addfont(_jp)
            matplotlib.rcParams["font.family"] = "IPAGothic"
    except ImportError:
        return

    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    fig.patch.set_facecolor("#0d1117")
    fig.suptitle("Direction Normalization Debug", color="#e6edf3", fontsize=12)

    raw_1h_x, raw_1h_y = [], []
    raw_2h_x, raw_2h_y = [], []
    norm_1h_x, norm_1h_y = [], []
    norm_2h_x, norm_2h_y = [], []

    for tr in tracks:
        for s in tr.sightings:
            fx, fy = s["fx"], s["fy"]
            if s["half"] == "1H":
                raw_1h_x.append(fx); raw_1h_y.append(fy)
                nx, ny = normalize_pos(fx, fy, flip_1h)
                norm_1h_x.append(nx); norm_1h_y.append(ny)
            else:
                raw_2h_x.append(fx); raw_2h_y.append(fy)
                nx, ny = normalize_pos(fx, fy, flip_2h)
                norm_2h_x.append(nx); norm_2h_y.append(ny)

    pairs = [
        (axes[0][0], raw_1h_x,  raw_1h_y,  f"1H RAW  (flip={flip_1h})",  "#f85149"),
        (axes[0][1], raw_2h_x,  raw_2h_y,  f"2H RAW  (flip={flip_2h})",  "#f85149"),
        (axes[1][0], norm_1h_x, norm_1h_y, "1H NORMALIZED",               "#3fb950"),
        (axes[1][1], norm_2h_x, norm_2h_y, "2H NORMALIZED",               "#3fb950"),
    ]

    for ax, fxs, fys, title, col in pairs:
        ax.set_facecolor("#161b22")
        ax.set_xlim(0, FW); ax.set_ylim(0, FH)
        ax.set_title(title, color=col, fontsize=9, pad=4)
        _draw_field(ax)
        if fxs:
            ax.scatter(fxs, fys, c=col, s=4, alpha=0.5, zorder=5)
            ax.axvline(np.mean(fxs), color="white", lw=1.5, linestyle="--",
                       label=f"μX={np.mean(fxs):.1f}m")
            ax.axhline(np.mean(fys), color="yellow", lw=1, linestyle=":")
            ax.legend(fontsize=7, labelcolor="white",
                      facecolor="#21262d", edgecolor="#30363d")
        ax.tick_params(colors="#8b949e")
        for sp in ax.spines.values():
            sp.set_edgecolor("#30363d")

    plt.tight_layout(pad=1.5)
    out = match_dir / "direction_debug.png"
    plt.savefig(str(out), dpi=100, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  [debug] Direction debug → {out}")


# ── HTML report ───────────────────────────────────────────────────

def build_report(match_id, tracks, subs, stats, flip_1h, flip_2h, opp_ranges):
    rows = ""
    for tr in sorted(tracks, key=lambda t: t.jersey_number or 99):
        n  = len(tr.sightings)
        j  = tr.jersey_number or "?"
        zones = defaultdict(int)
        for s in tr.sightings: zones[s["zone"]] += 1
        dominant = max(zones, key=zones.get) if zones else "?"
        t_start  = tr.sightings[0]["time_min"] if tr.sightings else 0
        t_end    = tr.sightings[-1]["time_min"] if tr.sightings else 0
        zc = {"D1":"#3498db","D2":"#2980b9","D3":"#1abc9c",
              "A1":"#e74c3c","A2":"#e67e22","A3":"#f1c40f"}.get(dominant,"#888")
        rows += f"""<tr>
          <td style="font-weight:700;color:#58a6ff">{tr.tid}</td>
          <td style="font-size:1.2rem;font-weight:700;color:#f0883e">#{j}</td>
          <td>{n}</td>
          <td>{t_start:.0f}–{t_end:.0f} min</td>
          <td><span style="background:{zc};color:#fff;padding:2px 8px;border-radius:4px;font-size:11px">{dominant}</span></td>
        </tr>"""

    sub_rows = "".join(f"""<tr>
      <td>{s['time_min']}min</td>
      <td style="color:#f85149">OUT: {s['player_out']} #{s['player_out_jersey'] or '?'}</td>
      <td style="color:#3fb950">IN: {s['player_in']} #{s['player_in_jersey'] or '?'}</td>
      <td>{s['zone']}</td><td>{int(s['confidence']*100)}%</td>
    </tr>""" for s in subs)

    opp_color_html = "".join(
        f"<span style='background:hsl({int(lo[0])+int(hi[0])}deg,60%,40%);color:white;padding:2px 8px;border-radius:4px;font-size:11px;margin:2px'>H:{lo[0]}-{hi[0]} S:{lo[1]}-{hi[1]}</span> "
        for lo, hi in opp_ranges[:3]
    ) if opp_ranges else "auto-detected"

    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8">
<title>TZI v3 — match_{match_id}</title>
<style>
* {{box-sizing:border-box;margin:0;padding:0}}
body {{background:#0d1117;color:#e6edf3;font-family:'Segoe UI',Arial,sans-serif}}
.hero {{background:linear-gradient(135deg,#0f2027,#1a3a4a,#2c5364);padding:24px 32px;border-bottom:1px solid #30363d}}
.hero h1 {{font-size:1.4rem;color:#58a6ff}} .hero p {{font-size:.82rem;color:#8b949e;margin-top:4px}}
.stats {{display:flex;gap:16px;padding:16px 32px;background:#161b22;border-bottom:1px solid #30363d;flex-wrap:wrap}}
.stat {{background:#21262d;border:1px solid #30363d;border-radius:8px;padding:10px 18px}}
.stat .v {{font-size:1.8rem;font-weight:700}} .stat .l {{font-size:.75rem;color:#8b949e}}
.content {{max-width:1100px;margin:0 auto;padding:24px 20px}}
h2 {{font-size:1rem;padding-bottom:8px;border-bottom:1px solid #30363d;margin:24px 0 14px}}
table {{width:100%;border-collapse:collapse;font-size:12px}}
th {{background:#21262d;padding:8px 10px;text-align:left;color:#8b949e}}
td {{padding:7px 10px;border-bottom:1px solid #21262d}}
tr:hover td {{background:#161b22}}
.badge {{display:inline-block;padding:2px 10px;border-radius:12px;font-size:11px;font-weight:600}}
</style></head><body>
<div class="hero">
  <h1>TZI Player Tracking v3 — match_{match_id}</h1>
  <p>Dual-Team Detection · Direction Normalization · Kalman+EIoU · OC-SORT Re-ID · Savitzky-Golay Smoothing</p>
</div>
<div class="stats">
  <div class="stat"><div class="v" style="color:#3fb950">{stats['n_players']}</div><div class="l">Unique Players</div></div>
  <div class="stat"><div class="v" style="color:#58a6ff">{stats['n_frames']}</div><div class="l">Frames Sampled</div></div>
  <div class="stat"><div class="v" style="color:#f0883e">{stats['n_with_jersey']}</div><div class="l">Jersey # Found</div></div>
  <div class="stat"><div class="v" style="color:#d2a8ff">{len(subs)}</div><div class="l">Substitutions</div></div>
  <div class="stat"><div class="v" style="color:#79c0ff">{stats['avg_per_frame']:.1f}</div><div class="l">Avg/Frame</div></div>
  <div class="stat">
    <div class="l" style="margin-bottom:4px">Direction Normalization</div>
    <span class="badge" style="background:{'#f85149' if flip_1h else '#3fb950'};color:#fff">1H: {'FLIP' if flip_1h else 'KEEP'}</span>
    <span class="badge" style="background:{'#f85149' if flip_2h else '#3fb950'};color:#fff;margin-left:4px">2H: {'FLIP' if flip_2h else 'KEEP'}</span>
  </div>
</div>
<div class="content">
  <h2>Opponent Color Detection</h2>
  <p style="font-size:12px;color:#8b949e;margin-bottom:8px">Auto-detected opponent jersey HSV clusters used as spatial augmentation:</p>
  <div style="margin-bottom:16px">{opp_color_html}</div>

  <h2>Player List ({stats['n_players']}名 · Normalized Coordinates)</h2>
  <table><thead><tr><th>Track ID</th><th>Jersey #</th><th>Sightings</th><th>Active Period</th><th>Primary Zone</th></tr></thead>
  <tbody>{rows}</tbody></table>

  <h2>Substitutions ({len(subs)}件)</h2>
  {'<table><thead><tr><th>Time</th><th>Player Out</th><th>Player In</th><th>Zone</th><th>Confidence</th></tr></thead><tbody>' + sub_rows + '</tbody></table>' if subs else '<p style="color:#8b949e;font-size:12px">None detected</p>'}
</div>
<div style="text-align:center;padding:20px;color:#8b949e;font-size:11px">
TZI v3 — Tactical Zone Intelligence · Indica Labs · 2026</div>
</body></html>"""


# ── Half processing ───────────────────────────────────────────────

def process_half(video_path, half_label, t_offset, match_dir, interval_min,
                  use_ocr, opp_ranges):
    cap     = cv2.VideoCapture(str(video_path))
    fps     = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_f = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    sample  = max(1, int(fps * 60 * interval_min))
    duration_min = total_f / fps / 60

    frames_dir = match_dir / "frames_v3"
    frames_dir.mkdir(exist_ok=True)

    tracker    = PlayerTrackerV3()
    frame_log  = []
    opp_log    = []

    # Build list of target frame positions (fast-seek mode)
    target_frames = []
    fn_cursor = sample
    while fn_cursor <= total_f:
        target_frames.append(fn_cursor)
        fn_cursor += sample

    print(f"\n{half_label}: {total_f}f, {fps:.0f}fps, ~{duration_min:.0f}min  ({len(target_frames)} samples)")

    for fn in target_frames:
        cap.set(cv2.CAP_PROP_POS_FRAMES, fn - 1)
        ret, frame = cap.read()
        if not ret:
            continue

        local_t = fn / fps / 60
        t_min   = local_t + t_offset
        dets_w  = detect_waseda(frame)
        dets_o  = detect_opponents(frame, opp_ranges)

        active = tracker.update(dets_w, t_min, half_label, use_ocr)

        # Record opponent centroid for direction inference
        if dets_o:
            opp_log.append({
                "time_min": round(t_min, 2),
                "centroid_x": float(np.mean([d["fx"] for d in dets_o])),
                "centroid_y": float(np.mean([d["fy"] for d in dets_o])),
                "n": len(dets_o),
            })

        # Annotated frame
        out_f = frame.copy()
        for d in dets_w:
            x1, y1, x2, y2 = d["bbox"]
            cv2.rectangle(out_f, (x1, y1), (x2, y2), (80, 80, 255), 2)
        for d in dets_o:
            x1, y1, x2, y2 = d["bbox"]
            cv2.rectangle(out_f, (x1, y1), (x2, y2), (255, 180, 80), 1)

        n_j = sum(1 for tr in active if tr.jersey_number)
        cv2.rectangle(out_f, (0, 0), (out_f.shape[1], 40), (0, 0, 0), -1)
        cv2.putText(out_f,
                    f"v3 {half_label} {local_t:.1f}min | W={len(dets_w)} O={len(dets_o)} active={len(active)} j={n_j}",
                    (8, 26), FONT, 0.55, (255, 255, 255), 2, cv2.LINE_AA)

        fname = frames_dir / f"v3_{half_label}_{local_t:.1f}min.jpg"
        cv2.imwrite(str(fname), out_f, [cv2.IMWRITE_JPEG_QUALITY, 80])
        frame_log.append({"time_min": round(t_min, 2), "n_waseda": len(dets_w),
                           "n_opp": len(dets_o), "n_active": len(active)})

        if target_frames.index(fn) % 10 == 0 and target_frames.index(fn) > 0:
            print(f"  {local_t:.0f}min  W={len(dets_w)} O={len(dets_o)} "
                  f"active={len(active)} susp={len(tracker.suspended)}")

    cap.release()
    tracker.flush_all()
    return tracker.all_tracks(), frame_log, opp_log


# ── Main ──────────────────────────────────────────────────────────

def process_match(match_id, interval_min, use_ocr, videos_dir):
    match_dir = DATA_TZI / f"match_{match_id}"
    match_dir.mkdir(parents=True, exist_ok=True)

    cfg = MATCH_CONFIGS.get(match_id)
    if not cfg:
        print(f"  [{match_id}] No config found — skip")
        return False

    h1_path = videos_dir / cfg["h1"]
    if not h1_path.exists():
        print(f"  [{match_id}] Video not found: {h1_path} — skip")
        return False

    print(f"\n{'='*60}")
    print(f"  match_{match_id}  {MATCH_LABELS.get(match_id, match_id)}")
    print(f"{'='*60}")

    t0 = time.time()

    # Auto-detect opponent color from first half
    print("  Auto-detecting opponent jersey colors...")
    opp_ranges = auto_detect_opponent_color(h1_path)

    all_tracks, all_frames = [], []
    opp_log_1h, opp_log_2h = [], []

    h1_tracks, h1_frames, opp1 = process_half(
        h1_path, "1H", 0.0, match_dir, interval_min, use_ocr, opp_ranges)
    all_tracks.extend(h1_tracks)
    all_frames.extend(h1_frames)
    opp_log_1h = opp1

    h2_path = videos_dir / cfg["h2"] if cfg.get("h2") else None
    if h2_path and h2_path.exists():
        cap_tmp = cv2.VideoCapture(str(h1_path))
        fps_tmp = cap_tmp.get(cv2.CAP_PROP_FPS) or 30.0
        nf_tmp  = int(cap_tmp.get(cv2.CAP_PROP_FRAME_COUNT))
        cap_tmp.release()
        h1_dur = nf_tmp / fps_tmp / 60.0

        h2_tracks, h2_frames, opp2 = process_half(
            h2_path, "2H", h1_dur, match_dir, interval_min, use_ocr, opp_ranges)
        all_tracks.extend(h2_tracks)
        all_frames.extend(h2_frames)
        opp_log_2h = opp2

    print(f"\nBefore merge: {len(all_tracks)} tracks")
    all_tracks = merge_tracks(all_tracks)
    print(f"After  merge: {len(all_tracks)} tracks")

    subs = detect_substitutions(all_tracks)
    print(f"Substitutions: {len(subs)}")

    # Renumber
    for i, tr in enumerate(sorted(all_tracks, key=lambda t: t.sightings[0]["time_min"] if t.sightings else 0)):
        tr.tid = f"P{i+1:02d}"

    # ── Direction detection ───────────────────────────────────────
    sightings_1h = [s for tr in all_tracks for s in tr.sightings if s["half"] == "1H"]
    sightings_2h = [s for tr in all_tracks for s in tr.sightings if s["half"] == "2H"]

    print("\n  Detecting attack direction...")
    flip_1h, flip_2h = detect_attack_direction(sightings_1h, sightings_2h)

    # Save direction debug diagram before normalizing
    save_direction_debug(all_tracks, match_dir, flip_1h, flip_2h)

    # ── Apply normalization to all sightings ──────────────────────
    for tr in all_tracks:
        for s in tr.sightings:
            flip = flip_1h if s["half"] == "1H" else flip_2h
            fx_n, fy_n = normalize_pos(s["fx"], s["fy"], flip)
            s["fx_norm"] = fx_n
            s["fy_norm"] = fy_n
            s["zone_norm"] = fx_to_zone(fx_n)
            s["direction_flipped"] = flip

    # Savitzky-Golay trajectory smoothing (post-normalization)
    print("  Smoothing trajectories (Savitzky-Golay)...")
    all_tracks = smooth_trajectories(all_tracks)

    # Find jersey #6
    j6 = next((tr for tr in all_tracks if tr.jersey_number == 6), None)
    if j6:
        print(f"\n  #6 found: {j6.tid} ({j6.n_sightings if hasattr(j6,'n_sightings') else len(j6.sightings)} sightings)")
        j6_fx = [s["fx_norm"] for s in j6.sightings]
        j6_fy = [s["fy_norm"] for s in j6.sightings]
        print(f"  #6 normalized centroid: X={np.mean(j6_fx):.1f}m  Y={np.mean(j6_fy):.1f}m")
        print(f"  Expected right-back: X=15-35m, Y=45-68m")

    # ── Generate heatmap ─────────────────────────────────────────
    generate_heatmap(all_tracks, match_dir, match_id, j6.tid if j6 else None)

    # ── Stats ────────────────────────────────────────────────────
    n_with_jersey = sum(1 for t in all_tracks if t.jersey_number)
    total_sights  = sum(len(t.sightings) for t in all_tracks)
    stats = {
        "n_players":     len(all_tracks),
        "n_frames":      len(all_frames),
        "n_with_jersey": n_with_jersey,
        "avg_per_frame": total_sights / max(len(all_frames), 1),
        "elapsed_sec":   round(time.time() - t0, 1),
        "flip_1h":       flip_1h,
        "flip_2h":       flip_2h,
    }

    # ── Save JSON ────────────────────────────────────────────────
    out_players = []
    for tr in all_tracks:
        zones = defaultdict(int)
        zones_n = defaultdict(int)
        for s in tr.sightings:
            zones[s["zone"]] += 1
            zones_n[s.get("zone_norm", s["zone"])] += 1
        out_players.append({
            "player_id":     tr.tid,
            "jersey_number": tr.jersey_number,
            "n_sightings":   len(tr.sightings),
            "zone_dist":     dict(zones),
            "zone_dist_norm": dict(zones_n),
            "sightings":     tr.sightings,
        })

    out_json = match_dir / "players_v3.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({
            "match":           match_id,
            "label":           MATCH_LABELS.get(match_id, match_id),
            "stats":           stats,
            "direction":       {"flip_1h": flip_1h, "flip_2h": flip_2h},
            "opponent_colors": [[lo.tolist(), hi.tolist()] for lo, hi in opp_ranges],
            "players":         out_players,
        }, f, ensure_ascii=False, indent=2)

    with open(match_dir / "substitutions_v3.json", "w", encoding="utf-8") as f:
        json.dump(subs, f, ensure_ascii=False, indent=2)

    # ── HTML report ──────────────────────────────────────────────
    opp_np = [(np.array(lo), np.array(hi)) for lo, hi in opp_ranges] if opp_ranges else []
    report = build_report(match_id, all_tracks, subs, stats, flip_1h, flip_2h, opp_np)
    (match_dir / "tracking_report_v3.html").write_text(report, encoding="utf-8")

    print(f"\n  Players: {len(all_tracks)}  Jersey#: {n_with_jersey}  Subs: {len(subs)}")
    print(f"  flip_1h={flip_1h}  flip_2h={flip_2h}")
    print(f"  Elapsed: {time.time()-t0:.0f}s")
    print(f"  JSON  → {out_json}")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--match",    default="20260325",
                    help="Match ID or 'all'")
    ap.add_argument("--interval", type=float, default=3.0,
                    help="Sample interval in minutes")
    ap.add_argument("--no-ocr",   action="store_true")
    args = ap.parse_args()

    videos_dir = PROJECT_ROOT / "videos"
    use_ocr    = not args.no_ocr

    if args.match == "all":
        matches = sorted(MATCH_CONFIGS.keys())
    else:
        matches = [args.match]

    print(f"=== TZI Track v3  ({len(matches)} matches)  interval={args.interval}min  ocr={use_ocr} ===")

    ok = 0
    for m in matches:
        if process_match(m, args.interval, use_ocr, videos_dir):
            ok += 1

    print(f"\n{'='*60}")
    print(f"  Completed: {ok}/{len(matches)} matches")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
