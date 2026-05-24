#!/usr/bin/env python3
"""
TZI Tracking Visualizer — 追跡オーバーレイ動画生成

実際の試合映像に追跡マーカーを重ね、羽瑠(背番号6)の特定トラックを
強調表示したタイムラプスmp4を生成する。識別が正しいか目視検証できる。

  python visualize_tracking.py --match 20260316
  python visualize_tracking.py --match 20260316 --fps 3 --width 960

出力: data/tzi/match_<id>/tracking_overlay.mp4
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

from track_players_v3 import MATCH_CONFIGS, MATCH_LABELS
from tactical_intelligence import analyze_match

# OpenCV putText は日本語非対応のためASCIIラベルを用意
ASCII_LABELS = {
    "20260314": "vs Saitama-u (03/14)",
    "20260316": "vs Gifu-kyoritsu (03/16)",
    "20260317mid": "vs Chukyo U-19 (03/17)",
    "20260317osaka": "vs Osaka-gakuin (03/17)",
    "20260318": "vs Sakushin (03/18)",
    "20260325": "vs Rikkyo-u (03/25)",
    "20260329": "vs Kawasaki U-18 (03/29)",
    "20260405": "vs Dokkyo-u (04/05)",
}

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_TZI = PROJECT_ROOT / "data" / "tzi"
VIDEOS = PROJECT_ROOT / "videos"

GREEN = (120, 255, 120)   # 羽瑠 (BGR)
DIM   = (150, 150, 150)   # その他Waseda
TRAIL = (90, 220, 90)


def _video_geometry(match_id):
    """(combined, h1_path, h2_path, fps, h1_dur_min) を返す."""
    cfg = MATCH_CONFIGS[match_id]
    h1 = VIDEOS / cfg["h1"]
    cap = cv2.VideoCapture(str(h1))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    nf = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    combined = bool(cfg.get("combined"))
    if combined:
        h1_dur = (nf // 2) / fps / 60.0
        return True, h1, None, fps, h1_dur
    h2 = VIDEOS / cfg["h2"] if cfg.get("h2") else None
    return False, h1, h2, fps, nf / fps / 60.0


def _frame_for(sighting, combined, fps, h1_dur):
    """sighting の (動画ファイル選択キー, フレーム番号) を返す."""
    t = sighting["time_min"]
    half = sighting["half"]
    if combined:
        return "h1", int(t * fps * 60)
    if half == "1H":
        return "h1", int(t * fps * 60)
    return "h2", int((t - h1_dur) * fps * 60)


def build_overlay(match_id, out_fps=3, width=960):
    path = DATA_TZI / f"match_{match_id}" / "players_v3.json"
    data = json.load(open(path))
    tracks = data["players"]

    # 羽瑠の特定トラックID(セグメント別)を取得
    role_roman = {"右SB": "RB", "ボランチ": "Volante", "右ボランチ": "R-Volante",
                  "セントラル": "CM", "アンカー": "Anchor"}
    res = analyze_match(match_id)
    haru_ids, seg_label = set(), {}
    for s in res.get("haru_id", {}).get("segments", []):
        if s.get("player_id"):
            haru_ids.add(s["player_id"])
            seg_label[s["player_id"]] = role_roman.get(s["label"], "")
    primary = res.get("haru_track", {}).get("player_id")

    combined, h1p, h2p, fps, h1_dur = _video_geometry(match_id)
    caps = {"h1": cv2.VideoCapture(str(h1p))}
    if h2p:
        caps["h2"] = cv2.VideoCapture(str(h2p))

    # 時刻ごとに (track_id, px, py) を集約
    by_time = defaultdict(list)
    for p in tracks:
        pid = p["player_id"]
        for s in p["sightings"]:
            by_time[round(s["time_min"], 2)].append((pid, s))
    times = sorted(by_time.keys())

    # 羽瑠の軌跡(トレイル)をトラックID別に保持 (segment間の混線を防ぐ)
    haru_trails = defaultdict(list)

    # 出力サイズ決定
    c0 = caps["h1"]
    w0 = int(c0.get(cv2.CAP_PROP_FRAME_WIDTH))
    h0 = int(c0.get(cv2.CAP_PROP_FRAME_HEIGHT))
    scale = width / w0
    out_w, out_h = width, int(h0 * scale)

    out_path = DATA_TZI / f"match_{match_id}" / "tracking_overlay.mp4"
    vw = cv2.VideoWriter(str(out_path),
                         cv2.VideoWriter_fourcc(*"mp4v"),
                         out_fps, (out_w, out_h))

    label = ASCII_LABELS.get(match_id, match_id)
    print(f"  {MATCH_LABELS.get(match_id, match_id)}: {len(times)} samples → {out_path.name}")

    for t in times:
        sample = by_time[t]
        key, fn = _frame_for(sample[0][1], combined, fps, h1_dur)
        cap = caps.get(key)
        if cap is None:
            continue
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, fn - 1))
        ret, frame = cap.read()
        if not ret:
            continue
        frame = cv2.resize(frame, (out_w, out_h))

        # 羽瑠トレイル描画 (トラックID別)
        for pts in haru_trails.values():
            for i in range(1, len(pts)):
                cv2.line(frame, pts[i - 1], pts[i], TRAIL, 2)

        for pid, s in sample:
            px, py = s.get("px"), s.get("py")
            if px is None:
                continue
            x, y = int(px * scale), int(py * scale)
            is_haru = pid in haru_ids
            if is_haru:
                cv2.circle(frame, (x, y), 13, GREEN, 3)
                role = seg_label.get(pid, "")
                cv2.putText(frame, f"#6 {pid} {role}", (x + 16, y - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, GREEN, 2, cv2.LINE_AA)
                haru_trails[pid].append((x, y))
                haru_trails[pid] = haru_trails[pid][-10:]
            else:
                cv2.circle(frame, (x, y), 6, DIM, 1)
                cv2.putText(frame, pid, (x + 7, y - 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.34, DIM, 1, cv2.LINE_AA)

        # ヘッダー
        half = sample[0][1]["half"]
        cv2.rectangle(frame, (0, 0), (out_w, 34), (0, 0, 0), -1)
        cv2.putText(frame,
                    f"{label}  {half} {t:.0f}min  | green=#6 Haru ({primary})",
                    (8, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (120, 255, 120), 2, cv2.LINE_AA)
        vw.write(frame)

    vw.release()
    for c in caps.values():
        c.release()
    print(f"  ✓ {out_path}  ({out_w}x{out_h} @ {out_fps}fps)")
    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", required=True)
    ap.add_argument("--fps", type=float, default=3)
    ap.add_argument("--width", type=int, default=960)
    args = ap.parse_args()
    build_overlay(args.match, args.fps, args.width)
