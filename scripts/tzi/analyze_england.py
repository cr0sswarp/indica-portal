#!/usr/bin/env python3
"""
TZI: Japan vs England (2026.03.31) 試合分析

Japan (青/ブルー) と England (白) の選手をHSV検出し、
全選手の位置情報・ゾーン分布・タクティカルパターンを分析する。

Usage:
    python analyze_england.py
    python analyze_england.py --interval 5 --sample_frames

Output:
    data/tzi/match_20260331_england/
      all_players_japan.json      - Japan players trajectory
      all_players_england.json    - England players trajectory
      tactical_report.html        - Full tactical analysis HTML
      frames/                     - Annotated frame images
"""

import argparse
import base64
import json
import time
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent.parent
VIDEO_PATH = PROJECT_ROOT / "videos" / "2026.03.31 Englan vs Japan.mp4"
MATCH_DIR  = PROJECT_ROOT / "data" / "tzi" / "match_20260331_england"

FW, FH = 105.0, 68.0

# Japan national team: blue jersey
# Deep blue around hue 200-220 in HSV
JAPAN_LO = np.array([100, 60, 40])
JAPAN_HI = np.array([130, 255, 220])

# England: white jersey
ENGLAND_LO = np.array([0, 0, 180])
ENGLAND_HI = np.array([180, 40, 255])

KNL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

# Field homography — use same calibration as Waseda matches as starting point
# Note: different camera, so this may need adjustment. We use it for rough coords.
SRC = np.float32([[20, 90], [1255, 88], [635, 298], [635, 705]])
DST = np.float32([[0, 0], [105, 0], [52.5, 34], [52.5, 68]])
H_MAT, _ = cv2.findHomography(SRC, DST, cv2.RANSAC, 3.0)

ZONES = ["D1", "D2", "D3", "A1", "A2", "A3"]
ZONE_COLORS_BGR = {
    "D1": (219, 152, 52), "D2": (185, 128, 41), "D3": (156, 188, 26),
    "A1": (60, 76, 231),  "A2": (33, 126, 230), "A3": (21, 193, 241),
}


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


def detect_team(frame, lo, hi, lo2=None, hi2=None):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, lo, hi)
    if lo2 is not None:
        m = cv2.bitwise_or(m, cv2.inRange(hsv, lo2, hi2))
    m[:60, :] = 0
    m[680:, :] = 0
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, KNL)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, KNL, iterations=2)
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cnts:
        a = cv2.contourArea(c)
        if not (60 < a < 3000):
            continue
        x, y, w, h = cv2.boundingRect(c)
        ratio = h / (w + 1e-5)
        if ratio < 0.4 or ratio > 9:
            continue
        cx, cy = x + w // 2, y + h
        fx, fy = p2f(cx, cy)
        out.append({
            "px": cx, "py": cy - h // 2,
            "fx": round(fx, 2), "fy": round(fy, 2),
            "bbox": (x, y, x + w, y + h),
            "area": round(a, 1), "zone": fx_to_zone(fx),
        })
    return out


def draw_minimap(frame, japan_dets, england_dets, t_min):
    MW, MH = 168, 112
    mp = np.zeros((MH, MW, 3), dtype=np.uint8)
    mp[:, :, 1] = 40
    cv2.rectangle(mp, (0, 0), (MW - 1, MH - 1), (180, 180, 180), 1)
    cv2.line(mp, (MW // 2, 0), (MW // 2, MH), (180, 180, 180), 1)
    for d in england_dets:
        cv2.circle(mp, (int(d["fx"] / FW * MW), int(d["fy"] / FH * MH)), 3, (200, 200, 200), -1)
    for d in japan_dets:
        cv2.circle(mp, (int(d["fx"] / FW * MW), int(d["fy"] / FH * MH)), 4, (200, 100, 0), -1)
    cv2.putText(mp, "MAP", (2, 9), cv2.FONT_HERSHEY_SIMPLEX, 0.28, (255, 255, 255), 1)
    x1m, y1m = frame.shape[1] - MW - 8, frame.shape[0] - MH - 8
    frame[y1m:y1m + MH, x1m:x1m + MW] = mp
    cv2.rectangle(frame, (x1m, y1m), (x1m + MW, y1m + MH), (160, 160, 160), 1)


def process_video(video_path, interval_min=3.0, save_frames=True):
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_f = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    sample = max(1, int(fps * 60 * interval_min))

    MATCH_DIR.mkdir(parents=True, exist_ok=True)
    frames_dir = MATCH_DIR / "frames"
    if save_frames:
        frames_dir.mkdir(exist_ok=True)

    japan_by_time = []
    england_by_time = []

    fn = 0
    t_start = time.time()
    print(f"Video: {total_f} frames, {fps:.0f}fps, ~{total_f/fps/60:.0f}min")

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        fn += 1
        if fn % sample != 0:
            continue

        t_min = fn / fps / 60
        japan = detect_team(frame, JAPAN_LO, JAPAN_HI)
        england = detect_team(frame, ENGLAND_LO, ENGLAND_HI)

        for d in japan:
            japan_by_time.append({"time_min": round(t_min, 2), **d})
        for d in england:
            england_by_time.append({"time_min": round(t_min, 2), **d})

        if save_frames:
            out = frame.copy()
            for d in japan:
                x1, y1, x2, y2 = d["bbox"]
                cv2.rectangle(out, (x1, y1), (x2, y2), (200, 100, 0), 2)
                cv2.putText(out, f"JPN {d['zone']}", (x1, y1 - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 100, 0), 1)
            for d in england:
                x1, y1, x2, y2 = d["bbox"]
                cv2.rectangle(out, (x1, y1), (x2, y2), (200, 200, 200), 2)
                cv2.putText(out, f"ENG {d['zone']}", (x1, y1 - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
            draw_minimap(out, japan, england, t_min)
            cv2.putText(out, f"{t_min:.1f}min  JPN:{len(japan)}  ENG:{len(england)}",
                        (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
            cv2.imwrite(str(frames_dir / f"frame_{t_min:.1f}min.jpg"), out,
                        [cv2.IMWRITE_JPEG_QUALITY, 80])

        if fn % 1800 == 0:
            elapsed = time.time() - t_start
            print(f"  [{fn/total_f*100:.0f}%] {t_min:.0f}min  "
                  f"JPN:{len(japan)}  ENG:{len(england)}  {elapsed:.0f}s")

    cap.release()
    return japan_by_time, england_by_time


def zone_distribution(detections):
    dist = {z: 0 for z in ZONES}
    for d in detections:
        z = d.get("zone", fx_to_zone(d.get("fx", 0)))
        if z in dist:
            dist[z] += 1
    return dist


def build_tactical_report(japan_all, england_all, match_label="Japan vs England"):
    j_dist = zone_distribution(japan_all)
    e_dist = zone_distribution(england_all)
    j_total = max(sum(j_dist.values()), 1)
    e_total = max(sum(e_dist.values()), 1)

    def bar(pct, color):
        return (f'<div style="background:#21262d;border-radius:3px;height:6px;width:100%;margin-top:3px">'
                f'<div style="background:{color};width:{min(pct,100)}%;height:6px;border-radius:3px"></div></div>')

    zone_rows = ""
    for z in ZONES:
        zc = {"D1":"#3498db","D2":"#2980b9","D3":"#1abc9c",
              "A1":"#e74c3c","A2":"#e67e22","A3":"#f1c40f"}[z]
        j_p = int(j_dist[z] / j_total * 100)
        e_p = int(e_dist[z] / e_total * 100)
        zone_rows += f"""
        <tr>
          <td style="padding:6px 10px">
            <span style="background:{zc};color:#fff;padding:2px 8px;border-radius:3px;font-weight:700;font-size:11px">{z}</span>
          </td>
          <td style="padding:6px 10px;width:30%">
            {j_p}% {bar(j_p,'#c8640a')}
          </td>
          <td style="padding:6px 10px;width:30%">
            {e_p}% {bar(e_p,'#aaaaaa')}
          </td>
        </tr>"""

    # Compute dominant zones
    j_top = max(j_dist, key=lambda z: j_dist[z])
    e_top = max(e_dist, key=lambda z: e_dist[z])
    j_attack = int((j_dist["A1"] + j_dist["A2"] + j_dist["A3"]) / j_total * 100)
    e_attack = int((e_dist["A1"] + e_dist["A2"] + e_dist["A3"]) / e_total * 100)

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TZI Tactical Report — {match_label}</title>
<style>
  * {{ box-sizing:border-box;margin:0;padding:0 }}
  body {{ background:#0d1117;color:#e6edf3;font-family:'Segoe UI',Arial,sans-serif }}
  .hero {{ background:linear-gradient(135deg,#0f1a2e,#1a2a4e,#0f2550);
           padding:28px 36px;border-bottom:1px solid #30363d }}
  .hero h1 {{ font-size:1.5rem;color:#58a6ff }}
  .hero p  {{ color:#8b949e;font-size:0.82rem;margin-top:4px }}
  .content {{ max-width:1200px;margin:0 auto;padding:28px 24px }}
  .section  {{ margin-bottom:32px }}
  .section h2 {{ font-size:1rem;color:#e6edf3;padding-bottom:10px;
                 border-bottom:1px solid #30363d;margin-bottom:16px }}
  .cards {{ display:flex;gap:16px;flex-wrap:wrap }}
  .card  {{ flex:1 1 220px;background:#161b22;border:1px solid #30363d;
             border-radius:8px;padding:18px }}
  .card .val {{ font-size:2rem;font-weight:700 }}
  .card .lbl {{ font-size:0.75rem;color:#8b949e;margin-top:2px }}
  table {{ width:100%;border-collapse:collapse;font-size:12px }}
  th {{ background:#21262d;padding:8px 10px;text-align:left;color:#8b949e }}
  td {{ border-bottom:1px solid #21262d }}
</style>
</head>
<body>
<div class="hero">
  <h1>TZI Tactical Report — {match_label}</h1>
  <p>日本代表 vs イングランド | 2026.03.31 | HSV Color Detection Analysis</p>
</div>
<div class="content">

  <div class="section">
    <h2>ゾーン占有率サマリー</h2>
    <div class="cards">
      <div class="card">
        <div class="val" style="color:#c8640a">{j_attack}%</div>
        <div class="lbl">Japan Attack Zone Time</div>
      </div>
      <div class="card">
        <div class="val" style="color:#aaa">{e_attack}%</div>
        <div class="lbl">England Attack Zone Time</div>
      </div>
      <div class="card">
        <div class="val" style="color:#58a6ff">{j_top}</div>
        <div class="lbl">Japan Dominant Zone</div>
      </div>
      <div class="card">
        <div class="val" style="color:#8b949e">{e_top}</div>
        <div class="lbl">England Dominant Zone</div>
      </div>
    </div>
  </div>

  <div class="section">
    <h2>ゾーン別分布</h2>
    <table>
      <thead><tr><th>Zone</th><th>Japan 🇯🇵</th><th>England 🏴󠁧󠁢󠁥󠁮󠁧󠁿</th></tr></thead>
      <tbody>{zone_rows}</tbody>
    </table>
  </div>

  <div class="section">
    <h2>検出統計</h2>
    <table>
      <thead><tr><th>Metric</th><th>Japan</th><th>England</th></tr></thead>
      <tbody>
        <tr><td style="padding:6px 10px">Total detections</td>
            <td style="padding:6px 10px">{len(japan_all)}</td>
            <td style="padding:6px 10px">{len(england_all)}</td></tr>
        <tr><td style="padding:6px 10px">Avg per frame</td>
            <td style="padding:6px 10px">{len(japan_all)/max(1,len(set(d['time_min'] for d in japan_all))):.1f}</td>
            <td style="padding:6px 10px">{len(england_all)/max(1,len(set(d['time_min'] for d in england_all))):.1f}</td></tr>
      </tbody>
    </table>
  </div>

</div>
<div style="text-align:center;padding:20px;color:#8b949e;font-size:11px">
  TZI — Tactical Zone Intelligence · Indica Labs · 2026
</div>
</body>
</html>"""
    return html


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=float, default=3.0,
                        help="Sample interval in minutes (default: 3)")
    parser.add_argument("--no-frames", action="store_true",
                        help="Skip saving annotated frames")
    args = parser.parse_args()

    if not VIDEO_PATH.exists():
        print(f"ERROR: Video not found: {VIDEO_PATH}")
        print("Expected: videos/2026.03.31 Englan vs Japan.mp4")
        return

    print(f"=== TZI: analyze_england ===")
    print(f"Video   : {VIDEO_PATH}")
    print(f"Interval: {args.interval}min")
    print(f"Output  : {MATCH_DIR}")

    MATCH_DIR.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    japan_all, england_all = process_video(
        VIDEO_PATH,
        interval_min=args.interval,
        save_frames=not args.no_frames,
    )

    # Save JSONs
    j_path = MATCH_DIR / "all_players_japan.json"
    e_path = MATCH_DIR / "all_players_england.json"
    with open(j_path, "w") as f:
        json.dump({"match": "20260331_england", "team": "Japan",
                   "detections": japan_all}, f, ensure_ascii=False, indent=2)
    with open(e_path, "w") as f:
        json.dump({"match": "20260331_england", "team": "England",
                   "detections": england_all}, f, ensure_ascii=False, indent=2)

    # Generate tactical report
    report_html = build_tactical_report(japan_all, england_all)
    report_path = MATCH_DIR / "tactical_report.html"
    report_path.write_text(report_html, encoding="utf-8")

    elapsed = time.time() - t0
    print(f"\n=== DONE ===")
    print(f"Japan detections  : {len(japan_all)}")
    print(f"England detections: {len(england_all)}")
    print(f"Time              : {elapsed:.0f}s ({elapsed/60:.1f}min)")
    print(f"Report            : {report_path}")


if __name__ == "__main__":
    main()
