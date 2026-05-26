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
from tactical_intelligence import (
    analyze_match, signature_distance, get_coords,
    HARU_GROUND_TRUTH, ROLE_SIGNATURE,
)

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


# ASCII役割ラベル (OpenCV日本語非対応)
ROLE_ROMAN = {"右SB": "RB", "サイドバック": "RB", "ボランチ": "Volante",
              "右ボランチ": "R-Volante", "セントラル": "CM",
              "アンカー": "Anchor", "トップ下": "AM"}

# このゾーン距離(m)を超えるトラックは「羽瑠の役割位置」に該当しない
# とみなし矢印を描かない (全く別位置の選手を誤って指さないため)
HARU_FIT_MAX = 26.0


def _active_role(match_id, half, rel_t):
    """指定ハーフ・ハーフ内相対時刻における羽瑠の確定ロールを返す.
    ground truth が無い試合 (ホールドアウト) は None。"""
    gt = HARU_GROUND_TRUTH.get(match_id)
    if not gt:
        return None, None
    for seg in gt["segments"]:
        if seg["half"] != half:
            continue
        if "t_rel" in seg:
            lo, hi = seg["t_rel"]
            if not (lo <= rel_t < hi):
                continue
        return seg["role"], seg.get("label", seg["role"])
    return None, None


def _build_assignment_map(tracks):
    """jersey_number が確定している全トラックの pid→jersey と
    jersey→pid の辞書を返す。#6 以外の番号が消去法のキー。"""
    pid_to_jersey = {}
    jersey_to_pid = {}
    for p in tracks:
        j = p.get("jersey_number")
        if j is not None:
            pid_to_jersey[p["player_id"]] = j
            jersey_to_pid[j] = p["player_id"]
    return pid_to_jersey, jersey_to_pid


def _find_jersey6_track(tracks):
    """players_v3.json の tracks から jersey_number=6 の player_id を返す。
    なければ None。"""
    for p in tracks:
        if p.get("jersey_number") == 6:
            return p["player_id"]
    return None


def _pick_haru(sample, role, h1_dur, combined,
               confirmed_pid=None, pid_to_jersey=None,
               haru_last_pos=None):
    """このフレームで羽瑠(#6)を特定する。

    優先順位:
    1. confirmed_pid (#6確定トラック) がサンプルにいれば即返す
    2. 消去法: 他の確定番号(#3,#4,#5,#7…)をすべて除外し、
               残り1つなら即返す / 複数なら軌跡予測で絞り込む
    3. ロールシグネチャーで最近接 (フォールバック)
    """
    # 優先①: 確定トラックIDがこのフレームにいる
    if confirmed_pid:
        for pid, s in sample:
            if pid == confirmed_pid:
                return (pid, s)

    # 優先②: 消去法
    if pid_to_jersey:
        # 確定番号が付いた他選手を除外（#6は除外しない）
        candidates = [(pid, s) for pid, s in sample
                      if pid_to_jersey.get(pid, 6) == 6  # 未割り当て or #6
                      or pid_to_jersey.get(pid) is None]
        # さらに絞り込み: jersey_number=0以外の既知番号を全て除外
        candidates = [(pid, s) for pid, s in sample
                      if pid_to_jersey.get(pid) in (None, 6)]

        if len(candidates) == 1:
            return candidates[0]

        if len(candidates) > 1 and haru_last_pos is not None:
            # 軌跡予測: 直前位置に最も近い候補を選ぶ
            lx, ly = haru_last_pos
            best, best_d = None, 1e9
            for pid, s in candidates:
                x, y = get_coords(s)
                d = ((x - lx) ** 2 + (y - ly) ** 2) ** 0.5
                if d < best_d:
                    best_d, best = d, (pid, s)
            if best and best_d < 30.0:   # 30m以内なら信頼
                return best

    # 優先③: ロールシグネチャーで最近接 (フォールバック)
    if role is None or role not in ROLE_SIGNATURE:
        return None
    best, best_d = None, 1e9
    for pid, s in sample:
        x, y = get_coords(s)
        d = signature_distance(np.array([x]), np.array([y]), role)
        if d < best_d:
            best_d, best = d, (pid, s)
    if best is None or best_d > HARU_FIT_MAX:
        return None
    return best


def build_overlay(match_id, out_fps=3, width=960):
    path = DATA_TZI / f"match_{match_id}" / "players_v3.json"
    data = json.load(open(path))
    tracks = data["players"]

    # ホールドアウト試合用フォールバック: 自動推定の主トラックID
    res = analyze_match(match_id)
    fallback_id = res.get("haru_track", {}).get("player_id")

    combined, h1p, h2p, fps, h1_dur = _video_geometry(match_id)
    caps = {"h1": cv2.VideoCapture(str(h1p))}
    if h2p:
        caps["h2"] = cv2.VideoCapture(str(h2p))

    # 時刻ごとに (track_id, sighting) を集約
    by_time = defaultdict(list)
    for p in tracks:
        pid = p["player_id"]
        for s in p["sightings"]:
            by_time[round(s["time_min"], 2)].append((pid, s))
    times = sorted(by_time.keys())

    # 全トラックの番号割り当てマップを構築（消去法用）
    pid_to_jersey, jersey_to_pid = _build_assignment_map(tracks)
    confirmed_pid = jersey_to_pid.get(6)
    if confirmed_pid:
        print(f"  [haru] confirmed track: {confirmed_pid} (jersey #6)")
    others = {j: p for j, p in jersey_to_pid.items() if j != 6}
    print(f"  [elimination] confirmed non-#6: {sorted(others.keys())}")

    # 羽瑠の軌跡トレイル (フレーム横断で1本)
    haru_trail  = []
    haru_last_pos = None   # 直前フレームのフィールド座標 (消去法軌跡補完用)

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

    n_arrow = 0
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

        # ── このフレームでの羽瑠ロールを決定 → 最適トラックを選択 ──
        half = sample[0][1]["half"]
        rel_t = t if half == "1H" else (t - h1_dur)
        role, role_label = _active_role(match_id, half, rel_t)
        haru_pick = _pick_haru(sample, role, h1_dur, combined,
                               confirmed_pid=confirmed_pid,
                               pid_to_jersey=pid_to_jersey,
                               haru_last_pos=haru_last_pos)
        # フォールバック (ground truth 無し・confirmed_pid 無し):
        # 自動推定トラックがこの時刻にいれば指す
        if haru_pick is None and role is None and fallback_id and not confirmed_pid:
            for pid, s in sample:
                if pid == fallback_id:
                    haru_pick = (pid, s)
                    break
        haru_pid = haru_pick[0] if haru_pick else None

        # 羽瑠トレイル描画
        if STYLE["show_trail"]:
            for i in range(1, len(haru_trail)):
                cv2.line(frame, haru_trail[i - 1], haru_trail[i],
                         STYLE["trail_color"], STYLE["trail_thickness"])

        # その他選手 → 羽瑠 の順に描画 (矢印を最前面に)
        for pid, s in sample:
            px, py = s.get("px"), s.get("py")
            if px is None or pid == haru_pid:
                continue
            x, y = int(px * scale), int(py * scale)
            draw_other_marker(frame, x, y, pid)

        if haru_pick:
            _, s = haru_pick
            x, y = int(s["px"] * scale), int(s["py"] * scale)
            rl = ROLE_ROMAN.get(role_label, ROLE_ROMAN.get(role, ""))
            draw_haru_marker(frame, x, y, f"#6 Haru {rl}".strip())
            haru_trail.append((x, y))
            haru_trail = haru_trail[-STYLE["trail_len"]:]
            # 直前位置を更新（軌跡補完用）
            haru_last_pos = (get_coords(s)[0], get_coords(s)[1])
            n_arrow += 1

        # ヘッダー
        rl_disp = ROLE_ROMAN.get(role_label, "?") if role else "auto"
        cv2.rectangle(frame, (0, 0), (out_w, 34), (0, 0, 0), -1)
        cv2.putText(frame,
                    f"{label}  {half} {t:.0f}min  | arrow=#6 Haru ({rl_disp})",
                    (8, 23), FONT, STYLE["header_scale"],
                    STYLE["header_color"], 2, cv2.LINE_AA)
        vw.write(frame)

    vw.release()
    for c in caps.values():
        c.release()
    print(f"  ✓ {out_path}  ({out_w}x{out_h} @ {out_fps}fps)  arrow in {n_arrow}/{len(times)} frames")
    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", required=True)
    ap.add_argument("--fps", type=float, default=3)
    ap.add_argument("--width", type=int, default=960)
    args = ap.parse_args()
    build_overlay(args.match, args.fps, args.width)
