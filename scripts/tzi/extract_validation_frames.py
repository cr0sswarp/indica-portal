#!/usr/bin/env python3
"""
TZI ground-truth validation: extract real video frames at the timestamps where
a given tracked player was sighted, draw a marker on the tracked pixel position,
and annotate the field coordinates. Lets a human (or multimodal model) visually
confirm:
  - whether the tracked blob is actually a Waseda (maroon) player
  - where on the field they really are
  - which direction Waseda is attacking (visible from goal / formation)

Usage:
    python extract_validation_frames.py --match 20260325 --jersey 6
    python extract_validation_frames.py --match 20260325 --player P11
    python extract_validation_frames.py --match 20260325 --overview   # team-shape frames
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_TZI     = PROJECT_ROOT / "data" / "tzi"
VIDEOS       = PROJECT_ROOT / "videos"

# Match -> (h1 video, h2 video)
MATCH_VIDEOS = {
    "20260314":      ("26_03_14_I_TRM vs埼玉大.mp4", None),
    "20260316":      ("26_03_16_I_vs 岐阜協立.mp4", None),
    "20260317mid":   ("26_03_17_I_ vs中京U-19 後半.mp4", None),
    "20260317osaka": ("26_03_17_I_ vs大阪学院 前半.mp4", "26_03_17_I_ vs大阪学院 後半.mp4"),
    "20260318":      ("26_03_18_I_ vs作新学院 前半.mp4", None),
    "20260325":      ("26_03_25_I_TRM vs立教大 前半.mp4", "26_03_25_I_TRM vs立教大 後半.mp4"),
    "20260329":      ("26_03_29_I_TRM vs川崎U-18 前半.mp4", "26_03_29_I_TRM vs 川崎U-18 後半.mp4"),
    "20260405":      ("26_04_05_I_TRM vs獨協大前半.mp4", "26_04_05_I_TRM vs獨協大後半.mp4"),
}


def draw_field_legend(img):
    """Draw a small orientation legend on the frame."""
    h, w = img.shape[:2]
    cv2.rectangle(img, (0, h - 70), (w, h), (0, 0, 0), -1)
    cv2.putText(img, "Screen LEFT = field X=0 goal | Screen RIGHT = field X=105 goal",
                (8, h - 46), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(img, "TOP of pitch = field Y=0 (far touchline) | BOTTOM = Y=68 (near touchline)",
                (8, h - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2, cv2.LINE_AA)


def extract_for_player(match_id, jersey=None, player_id=None):
    d = json.load(open(DATA_TZI / f"match_{match_id}" / "players_v3.json"))
    players = d["players"]
    if jersey is not None:
        tr = next((p for p in players if p.get("jersey_number") == jersey), None)
        tag = f"j{jersey}"
    else:
        tr = next((p for p in players if p["player_id"] == player_id), None)
        tag = player_id
    if not tr:
        print(f"Player not found (jersey={jersey} id={player_id})")
        return

    print(f"Player {tr['player_id']} jersey={tr.get('jersey_number')} "
          f"n={len(tr['sightings'])}  direction={d['direction']}")

    out_dir = DATA_TZI / f"match_{match_id}" / "validation"
    out_dir.mkdir(exist_ok=True)

    h1v, h2v = MATCH_VIDEOS[match_id]
    caps = {}
    caps["1H"] = cv2.VideoCapture(str(VIDEOS / h1v))
    if h2v:
        caps["2H"] = cv2.VideoCapture(str(VIDEOS / h2v))
    else:
        caps["2H"] = caps["1H"]   # single-video matches: 2H offset handled below

    # local time within each half = sighting time_min - half offset.
    # 1H offset is 0; 2H offset is h1 duration (we recompute local from fps).
    fps1 = caps["1H"].get(cv2.CAP_PROP_FPS) or 30.0
    nf1  = int(caps["1H"].get(cv2.CAP_PROP_FRAME_COUNT))
    h1_dur = nf1 / fps1 / 60.0

    for i, s in enumerate(tr["sightings"]):
        half = s["half"]
        cap  = caps[half]
        fps  = cap.get(cv2.CAP_PROP_FPS) or 30.0
        local_min = s["time_min"] if half == "1H" else s["time_min"] - h1_dur
        frame_no  = int(local_min * 60 * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame_no))
        ret, frame = cap.read()
        if not ret:
            print(f"  [{half} {local_min:.1f}min] read failed")
            continue

        px, py = int(s["px"]), int(s["py"])
        flipped = s.get("direction_flipped", False)
        fxn = s.get("fx_norm", s["fx"]); fyn = s.get("fy_norm", s["fy"])

        # Big crosshair on tracked player
        cv2.drawMarker(frame, (px, py), (0, 255, 0), cv2.MARKER_CROSS, 60, 4)
        cv2.circle(frame, (px, py), 34, (0, 255, 0), 3)
        label = (f"{tr['player_id']} #{tr.get('jersey_number')}  {half} {local_min:.1f}min  "
                 f"raw=({s['fx']:.0f},{s['fy']:.0f})  norm=({fxn:.0f},{fyn:.0f}) flip={flipped}")
        cv2.rectangle(frame, (0, 0), (frame.shape[1], 38), (0, 0, 0), -1)
        cv2.putText(frame, label, (8, 26), cv2.FONT_HERSHEY_SIMPLEX,
                    0.62, (0, 255, 0), 2, cv2.LINE_AA)
        draw_field_legend(frame)

        fname = out_dir / f"{tag}_{half}_{local_min:.1f}min.jpg"
        cv2.imwrite(str(fname), frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
        print(f"  saved {fname.name}")

    for c in set(caps.values()):
        c.release()


def extract_overview(match_id, n_per_half=4):
    """Extract evenly-spaced full frames to read team shape / attack direction."""
    out_dir = DATA_TZI / f"match_{match_id}" / "validation"
    out_dir.mkdir(exist_ok=True)
    h1v, h2v = MATCH_VIDEOS[match_id]
    vids = [("1H", h1v)]
    if h2v:
        vids.append(("2H", h2v))
    for half, vid in vids:
        cap = cv2.VideoCapture(str(VIDEOS / vid))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        nf  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        for k in range(1, n_per_half + 1):
            frame_no = int(nf * k / (n_per_half + 1))
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
            ret, frame = cap.read()
            if not ret:
                continue
            tmin = frame_no / fps / 60.0
            cv2.rectangle(frame, (0, 0), (frame.shape[1], 38), (0, 0, 0), -1)
            cv2.putText(frame, f"{match_id} {half} overview {tmin:.1f}min",
                        (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2, cv2.LINE_AA)
            draw_field_legend(frame)
            fname = out_dir / f"overview_{half}_{tmin:.0f}min.jpg"
            cv2.imwrite(str(fname), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            print(f"  saved {fname.name}")
        cap.release()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", required=True)
    ap.add_argument("--jersey", type=int, default=None)
    ap.add_argument("--player", default=None)
    ap.add_argument("--overview", action="store_true")
    args = ap.parse_args()

    if args.overview:
        extract_overview(args.match)
    else:
        extract_for_player(args.match, jersey=args.jersey, player_id=args.player)


if __name__ == "__main__":
    main()
