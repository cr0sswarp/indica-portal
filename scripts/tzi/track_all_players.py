#!/usr/bin/env python3
"""
TZI: Full-match tracking for ALL detected players across a match.

For each sampled frame, detect all Waseda-color player blobs and assign
consistent player IDs using IoU/distance-based tracking across frames.

Usage:
    # Both halves (default videos from config)
    python track_all_players.py --match 20260325

    # Specify video paths explicitly
    python track_all_players.py --match 20260329 \
        --h1 "26_03_29_I_TRM vs川崎U-18 前半.mp4" \
        --h2 "26_03_29_I_TRM vs川崎U-18 後半.mp4"

    # Single-video match (no --h2)
    python track_all_players.py --match 20260329 --single \
        --h1 "26_03_29_I_TRM vs川崎U-18 前半.mp4"

    # Custom sample interval (default: 3 minutes)
    python track_all_players.py --match 20260325 --interval 5

Output:
    data/tzi/match_YYYYMMDD/all_players_trajectory.json
    data/tzi/match_YYYYMMDD/frames_annotated/  (annotated frame images)
"""

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

# ── Constants ────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent.parent

FW, FH = 105.0, 68.0
SRC = np.float32([[20, 90], [1255, 88], [635, 298], [635, 705]])
DST = np.float32([[0, 0], [105, 0], [52.5, 34], [52.5, 68]])
H_MAT, _ = cv2.findHomography(SRC, DST, cv2.RANSAC, 3.0)

W_LO1, W_HI1 = np.array([0, 50, 40]),   np.array([12, 255, 220])
W_LO2, W_HI2 = np.array([165, 50, 40]), np.array([180, 255, 220])
KNL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

# Tracking parameters
MAX_TRACK_DIST = 80   # pixels: max distance for IoU/centroid match
MAX_DISAPPEAR  = 3    # frames: drop track after this many misses

ZONE_COLS = {"D1": 0, "D2": 1, "D3": 2, "A1": 3, "A2": 4, "A3": 5}
ALL_ZONES = ["D1", "D2", "D3", "A1", "A2", "A3"]


# ── Helpers ───────────────────────────────────────────────────────

def p2f(px: float, py: float):
    """Pixel coordinate -> field coordinate (m)."""
    pt = np.array([[[float(px), float(py)]]], dtype=np.float32)
    r  = cv2.perspectiveTransform(pt, H_MAT)
    return float(np.clip(r[0][0][0], 0, FW)), float(np.clip(r[0][0][1], 0, FH))


def fx_to_zone(fx: float) -> str:
    if fx < 21:    return "D1"
    elif fx < 42:  return "D2"
    elif fx < 52.5: return "D3"
    elif fx < 63:  return "A1"
    elif fx < 84:  return "A2"
    else:          return "A3"


def detect_waseda(frame):
    """Detect Waseda-color (maroon) player blobs. Returns list of dicts."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    m   = cv2.bitwise_or(
        cv2.inRange(hsv, W_LO1, W_HI1),
        cv2.inRange(hsv, W_LO2, W_HI2),
    )
    # Ignore scoreboard region (top) and below pitch
    m[:60, :] = 0
    m[680:, :] = 0
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, KNL)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, KNL, iterations=2)

    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cnts:
        area = cv2.contourArea(c)
        if not (60 < area < 2800):
            continue
        x, y, w, h = cv2.boundingRect(c)
        ratio = h / (w + 1e-5)
        if ratio < 0.5 or ratio > 9:
            continue
        cx, cy = x + w // 2, y + h
        fx, fy = p2f(cx, cy)
        out.append({
            "px": cx,
            "py": cy - h // 2,   # mid-body y
            "fx": round(fx, 2),
            "fy": round(fy, 2),
            "bbox": (x, y, x + w, y + h),
            "area": round(area, 1),
        })
    return out


def iou(b1, b2):
    """Intersection over union between two bboxes (x1,y1,x2,y2)."""
    xa = max(b1[0], b2[0]); ya = max(b1[1], b2[1])
    xb = min(b1[2], b2[2]); yb = min(b1[3], b2[3])
    inter = max(0, xb - xa) * max(0, yb - ya)
    a1 = (b1[2] - b1[0]) * (b1[3] - b1[1])
    a2 = (b2[2] - b2[0]) * (b2[3] - b2[1])
    union = a1 + a2 - inter
    return inter / union if union > 0 else 0.0


# ── Tracker ───────────────────────────────────────────────────────

class PlayerTracker:
    """
    Simple IoU + centroid distance tracker.
    Assigns a persistent integer ID (0-based) to each detected blob.
    """

    def __init__(self):
        self._next_id   = 0
        self._tracks    = {}   # id -> latest detection dict
        self._disappear = {}   # id -> consecutive-miss count

    def update(self, detections):
        """
        Update tracker with new detections.
        Returns list of (player_id, detection_dict).
        """
        # --- No detections: age all tracks ---
        if not detections:
            for tid in list(self._disappear):
                self._disappear[tid] += 1
                if self._disappear[tid] > MAX_DISAPPEAR:
                    del self._tracks[tid]
                    del self._disappear[tid]
            return []

        # --- First frame: register everything ---
        if not self._tracks:
            for det in detections:
                tid = self._next_id
                self._next_id += 1
                self._tracks[tid]    = det
                self._disappear[tid] = 0
            return [(tid, self._tracks[tid]) for tid in self._tracks]

        # --- Match existing tracks to new detections ---
        tids  = list(self._tracks.keys())
        t_pts = np.array([(self._tracks[t]["px"], self._tracks[t]["py"]) for t in tids], dtype=float)
        d_pts = np.array([(d["px"],              d["py"])               for d in detections], dtype=float)

        # Cost matrix: Euclidean centroid distance
        cost = np.linalg.norm(t_pts[:, None, :] - d_pts[None, :, :], axis=2)  # (T, D)

        matched_t = set()
        matched_d = set()

        # Greedy matching: pick smallest-cost pairs first
        order = np.dstack(np.unravel_index(np.argsort(cost.ravel()), cost.shape))[0]
        for ti, di in order:
            if ti in matched_t or di in matched_d:
                continue
            if cost[ti, di] > MAX_TRACK_DIST:
                break
            tid = tids[ti]
            self._tracks[tid]    = detections[di]
            self._disappear[tid] = 0
            matched_t.add(ti)
            matched_d.add(di)

        # Age unmatched tracks
        for ti, tid in enumerate(tids):
            if ti not in matched_t:
                self._disappear[tid] += 1
                if self._disappear[tid] > MAX_DISAPPEAR:
                    del self._tracks[tid]
                    del self._disappear[tid]

        # Register new unmatched detections
        for di, det in enumerate(detections):
            if di not in matched_d:
                tid = self._next_id
                self._next_id += 1
                self._tracks[tid]    = det
                self._disappear[tid] = 0

        return [(tid, self._tracks[tid]) for tid in self._tracks]


# ── Palette for player ID colours ─────────────────────────────────

_COLOURS = [
    (255, 80,  80),  (80, 200, 80),   (80, 80, 255),   (255, 200, 0),
    (0,  200, 255),  (255, 100, 200), (160, 255, 80),   (255, 160, 40),
    (100, 200, 255), (200, 100, 255), (255, 255, 100),  (100, 255, 200),
]

def _colour(tid: int):
    return _COLOURS[tid % len(_COLOURS)]


# ── Per-half processing ───────────────────────────────────────────

def process_half(
    video_path: Path,
    half_label: str,
    t_offset: float,
    match_dir: Path,
    sample_every_min: float,
) -> tuple[dict, list]:
    """
    Process one half of the match.

    Returns:
        tracks_data: dict  pid -> list of sighting dicts
        frame_paths: list  paths of annotated frame images
    """
    frames_dir = match_dir / "frames_annotated"
    frames_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"  ERROR: cannot open {video_path}", file=sys.stderr)
        return {}, []

    fps        = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_f    = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step_f     = int(sample_every_min * 60 * fps)
    total_min  = total_f / fps / 60
    print(f"\n{half_label}: {total_f} frames, {fps:.1f} fps, ~{total_min:.1f} min")
    print(f"  Sampling every {sample_every_min} min ({step_f} frames)")

    tracker     = PlayerTracker()
    tracks_data = {}   # pid (str "P###") -> list of sightings

    fn          = 0
    frame_paths = []

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        fn += 1
        if fn % step_f != 0:
            continue

        local_min = fn / fps / 60
        t_min     = round(local_min + t_offset, 2)

        detections = detect_waseda(frame)
        tracked    = tracker.update(detections)

        # Annotate frame
        vis = frame.copy()
        for tid, det in tracked:
            col  = _colour(tid)
            x1, y1, x2, y2 = det["bbox"]
            pid_str = f"P{tid:03d}"
            zone    = fx_to_zone(det["fx"])

            cv2.rectangle(vis, (x1, y1), (x2, y2), col, 2)
            cv2.putText(vis,
                        f"{pid_str} ({det['fx']:.0f},{det['fy']:.0f}) {zone}",
                        (x1, max(0, y1 - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, col, 1, cv2.LINE_AA)

            # Record sighting
            if pid_str not in tracks_data:
                tracks_data[pid_str] = []
            tracks_data[pid_str].append({
                "time_min": t_min,
                "half":     half_label,
                "fx":       det["fx"],
                "fy":       det["fy"],
                "zone":     zone,
                "px":       det["px"],
                "py":       det["py"],
            })

        # Timestamp overlay
        cv2.putText(vis,
                    f"{half_label} {local_min:.1f}min  |  {len(tracked)} players",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (255, 255, 255), 2)

        fname = f"annotated_{half_label}_{local_min:.1f}min.jpg"
        out_p = frames_dir / fname
        cv2.imwrite(str(out_p), vis, [cv2.IMWRITE_JPEG_QUALITY, 85])
        frame_paths.append(out_p)

        det_count = len(detections)
        trk_count = len(tracked)
        print(f"  {half_label} {local_min:.1f}min: {det_count} detections, "
              f"{trk_count} active tracks -> {fname}")

    cap.release()
    return tracks_data, frame_paths


# ── Post-processing: build output structure ───────────────────────

def build_output(all_tracks: dict) -> list:
    """Convert raw track dict to sorted output list with zone distributions."""
    result = []
    for pid, sightings in sorted(all_tracks.items()):
        sightings.sort(key=lambda s: s["time_min"])

        zone_dist = {z: 0 for z in ALL_ZONES}
        for s in sightings:
            zone_dist[s["zone"]] = zone_dist.get(s["zone"], 0) + 1

        avg_fx = round(sum(s["fx"] for s in sightings) / len(sightings), 2) if sightings else 0.0
        avg_fy = round(sum(s["fy"] for s in sightings) / len(sightings), 2) if sightings else 0.0

        result.append({
            "player_id":       pid,
            "sightings":       sightings,
            "zone_distribution": zone_dist,
            "avg_fx":          avg_fx,
            "avg_fy":          avg_fy,
            "total_sightings": len(sightings),
        })

    # Sort by total sightings descending (most-seen player first)
    result.sort(key=lambda p: p["total_sightings"], reverse=True)
    return result


# ── Main ──────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="TZI full-match tracking for ALL detected players."
    )
    parser.add_argument("--match",    required=True,
                        help="Match date string, e.g. 20260325")
    parser.add_argument("--h1",       default=None,
                        help="Filename of first-half video under videos/. "
                             "Defaults to config.py VIDEO_H1.")
    parser.add_argument("--h2",       default=None,
                        help="Filename of second-half video under videos/. "
                             "Defaults to config.py VIDEO_H2.")
    parser.add_argument("--single",   action="store_true",
                        help="Single-video match (no second half).")
    parser.add_argument("--interval", type=float, default=3.0,
                        help="Sample every N minutes (default: 3.0).")
    return parser.parse_args()


def main():
    args       = parse_args()
    videos_dir = PROJECT_ROOT / "videos"
    match_dir  = PROJECT_ROOT / "data" / "tzi" / f"match_{args.match}"
    match_dir.mkdir(parents=True, exist_ok=True)

    # Resolve video paths
    if args.h1:
        video_h1 = videos_dir / args.h1
    else:
        # Fall back to config defaults if match is 20260325
        try:
            from config import VIDEO_H1
            video_h1 = VIDEO_H1
        except ImportError:
            print("ERROR: --h1 required (config.py VIDEO_H1 not available)", file=sys.stderr)
            sys.exit(1)

    if not args.single:
        if args.h2:
            video_h2 = videos_dir / args.h2
        else:
            try:
                from config import VIDEO_H2
                video_h2 = VIDEO_H2
            except ImportError:
                print("ERROR: --h2 required or use --single", file=sys.stderr)
                sys.exit(1)

    print(f"=== TZI: track_all_players  match={args.match} ===")
    print(f"Sample interval : {args.interval} min")
    print(f"H1 video        : {video_h1}")
    if not args.single:
        print(f"H2 video        : {video_h2}")
    print(f"Output dir      : {match_dir}")

    # Validate video files exist
    if not video_h1.exists():
        print(f"ERROR: H1 video not found: {video_h1}", file=sys.stderr)
        sys.exit(1)
    if not args.single and not video_h2.exists():
        print(f"ERROR: H2 video not found: {video_h2}", file=sys.stderr)
        sys.exit(1)

    all_tracks = {}

    # --- Process first half ---
    h1_tracks, h1_frames = process_half(
        video_h1, "1H", t_offset=0.0,
        match_dir=match_dir,
        sample_every_min=args.interval,
    )
    for pid, sightings in h1_tracks.items():
        all_tracks.setdefault(pid, []).extend(sightings)

    # --- Process second half ---
    if not args.single:
        # Determine first-half duration for time offset
        cap_tmp = cv2.VideoCapture(str(video_h1))
        fps_tmp = cap_tmp.get(cv2.CAP_PROP_FPS) or 30.0
        nf_tmp  = int(cap_tmp.get(cv2.CAP_PROP_FRAME_COUNT))
        cap_tmp.release()
        h1_duration = nf_tmp / fps_tmp / 60.0
        print(f"\n1H duration: {h1_duration:.1f} min  (used as 2H time offset)")

        h2_tracks, h2_frames = process_half(
            video_h2, "2H", t_offset=h1_duration,
            match_dir=match_dir,
            sample_every_min=args.interval,
        )
        for pid, sightings in h2_tracks.items():
            # 2H tracker starts fresh -> shift IDs to avoid collisions
            shifted_pid = f"P{int(pid[1:]) + 500:03d}"
            all_tracks.setdefault(shifted_pid, []).extend(sightings)

    # --- Build and save output ---
    output_list = build_output(all_tracks)

    out_json = match_dir / "all_players_trajectory.json"
    payload  = {
        "match":          args.match,
        "sample_interval_min": args.interval,
        "total_players":  len(output_list),
        "players":        output_list,
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"\n=== DONE ===")
    print(f"Players tracked : {len(output_list)}")
    print(f"JSON saved      : {out_json}")
    print(f"Annotated frames: {match_dir / 'frames_annotated'}")


if __name__ == "__main__":
    main()
