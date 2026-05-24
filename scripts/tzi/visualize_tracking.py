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

# ════════════════════════════════════════════════════════════════
#  描画スタイル設定 — ここだけ変えれば見た目を調整できる (色はBGR)
# ════════════════════════════════════════════════════════════════
STYLE = {
    # ── 羽瑠の強調マーカー: 頭上から頭へ向かう下向き矢印 ──
    "haru_color":        (120, 255, 120),  # 緑
    "head_offset":       26,    # py(胴中心)から頭頂までの推定上方オフセット(px)
    "arrow_len":         48,    # 矢印の長さ(px) — 大きいほど目立つ
    "arrow_thickness":   4,
    "arrow_tip_ratio":   0.35,  # 矢じりの大きさ(線長に対する比)
    "haru_label":        True,  # "#6 P05 RB" ラベルを出すか
    "haru_label_scale":  0.6,
    "haru_label_thick":  2,

    # ── 軌跡トレイル ──
    "show_trail":        True,
    "trail_color":       (90, 220, 90),
    "trail_len":         10,    # 何サンプル分残すか
    "trail_thickness":   2,

    # ── その他Waseda選手マーカー ──
    "other_color":       (150, 150, 150),
    "other_radius":      6,
    "other_label":       True,  # トラックID(P12等)を出すか
    "other_label_scale": 0.34,

    # ── ヘッダー ──
    "header_color":      (120, 255, 120),
    "header_scale":      0.55,
}

FONT = cv2.FONT_HERSHEY_SIMPLEX


def draw_haru_marker(frame, x, y, label, st=STYLE):
    """頭上から頭へ向かう下向き矢印で羽瑠を強調."""
    head_y = y - st["head_offset"]              # 頭頂の推定位置
    tail = (x, head_y - st["arrow_len"])         # 矢印の根元(上)
    tip = (x, head_y)                            # 矢印の先端(頭を指す)
    cv2.arrowedLine(frame, tail, tip, st["haru_color"], st["arrow_thickness"],
                    line_type=cv2.LINE_AA, tipLength=st["arrow_tip_ratio"])
    if st["haru_label"] and label:
        cv2.putText(frame, label, (x + 8, tail[1] - 6), FONT,
                    st["haru_label_scale"], st["haru_color"],
                    st["haru_label_thick"], cv2.LINE_AA)


def draw_other_marker(frame, x, y, pid, st=STYLE):
    """その他選手は小さな点で表示."""
    cv2.circle(frame, (x, y), st["other_radius"], st["other_color"], 1)
    if st["other_label"]:
        cv2.putText(frame, pid, (x + 7, y - 5), FONT,
                    st["other_label_scale"], st["other_color"], 1, cv2.LINE_AA)


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
        if STYLE["show_trail"]:
            for pts in haru_trails.values():
                for i in range(1, len(pts)):
                    cv2.line(frame, pts[i - 1], pts[i],
                             STYLE["trail_color"], STYLE["trail_thickness"])

        for pid, s in sample:
            px, py = s.get("px"), s.get("py")
            if px is None:
                continue
            x, y = int(px * scale), int(py * scale)
            if pid in haru_ids:
                role = seg_label.get(pid, "")
                draw_haru_marker(frame, x, y, f"#6 {pid} {role}".strip())
                haru_trails[pid].append((x, y))
                haru_trails[pid] = haru_trails[pid][-STYLE["trail_len"]:]
            else:
                draw_other_marker(frame, x, y, pid)

        # ヘッダー
        half = sample[0][1]["half"]
        cv2.rectangle(frame, (0, 0), (out_w, 34), (0, 0, 0), -1)
        cv2.putText(frame,
                    f"{label}  {half} {t:.0f}min  | arrow=#6 Haru ({primary})",
                    (8, 23), FONT, STYLE["header_scale"],
                    STYLE["header_color"], 2, cv2.LINE_AA)
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
