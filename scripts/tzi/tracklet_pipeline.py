#!/usr/bin/env python3
"""
TZI Tracklet Pipeline — 5分検証版

ステップ:
  1. YOLO+ByteTrack で全フレーム連続追跡 → trackletの断片リストを抽出
  2. tracklet連結: 時間・距離が近い断片を同一人物として繋ぐ
  3. アンカー紐付け: jersey6_trajectory.json の座標に最も近いチェーンを #6 と確定
  4. オーバーレイ動画生成 + ワープ計測 (毎フレームID切替なし → ワープ構造的ゼロ)

実行:
  python tracklet_pipeline.py
"""
import cv2, json, time, subprocess, numpy as np
from pathlib import Path
from collections import defaultdict
from ultralytics import YOLO
from config import VIDEO_H1, TRAJ_JSON, OUTPUT_DIR, p2f, FW, FH

# ── 設定 ─────────────────────────────────────────────────────
DURATION_MIN   = 5.0      # 処理する時間 (分)
IMGSZ          = 640      # YOLO推論解像度 (640=高速, 1280=高精度)
CONF           = 0.20     # 検出信頼度下限
EVERY_N        = 6        # Nフレームに1回処理 (1=全フレーム, 6=5fps相当)
FPS_OUT        = 5        # 出力動画fps
W_OUT, H_OUT   = 1280, 720

# tracklet連結パラメータ
LINK_GAP_SEC   = 2.0      # 連結する最大時間ギャップ (秒)
LINK_DIST_M    = 4.0      # 連結する最大フィールド距離 (m)

# ワープ判定
WARP_THRESH_M  = 4.0      # 5fps換算でこれ以上動いたらワープ

OUT_JSON = OUTPUT_DIR / "tracklets_5min.json"
OUT_VID  = OUTPUT_DIR / "tracklet_overlay_5min.mp4"
FONT     = cv2.FONT_HERSHEY_SIMPLEX

# ─────────────────────────────────────────────────────────────
# STEP 1: YOLO+ByteTrack で tracklet 抽出
# ─────────────────────────────────────────────────────────────
def extract_tracklets(video_path, duration_min, fps_video):
    model  = YOLO(str(Path(__file__).parent / "yolov8n.pt"))
    cap    = cv2.VideoCapture(str(video_path))
    end_f  = int(fps_video * duration_min * 60)

    # raw_tracklets[track_id] = list of {frame, t_sec, px, py, fx, fy, bbox}
    raw = defaultdict(list)
    fn  = 0
    t0  = time.time()
    print(f"STEP1: tracklet抽出 (最初{duration_min}分, imgsz={IMGSZ}, N={EVERY_N})...")

    while fn < end_f:
        ret, frame = cap.read()
        if not ret:
            break
        if fn % EVERY_N == 0:
            results = model.track(frame, persist=True, classes=[0],
                                  imgsz=IMGSZ, conf=CONF,
                                  verbose=False, tracker="bytetrack_hi.yaml")
            if results[0].boxes is not None and results[0].boxes.id is not None:
                ids   = results[0].boxes.id.cpu().numpy().astype(int)
                boxes = results[0].boxes.xyxy.cpu().numpy()
                for tid, box in zip(ids, boxes):
                    x1, y1, x2, y2 = map(int, box)
                    cx = (x1 + x2) // 2
                    cy = y2           # 足元
                    fx, fy = p2f(cx, cy)
                    raw[int(tid)].append({
                        "frame": fn,
                        "t_sec": fn / fps_video,
                        "px": cx, "py": (y1 + y2) // 2,
                        "fx": round(fx, 2), "fy": round(fy, 2),
                        "bbox": [x1, y1, x2, y2],
                    })
        fn += 1
        if fn % int(fps_video * 30) == 0:
            pct = fn / end_f * 100
            print(f"  {pct:.0f}% ({fn/fps_video:.0f}s)  IDs={len(raw)}  {time.time()-t0:.0f}s経過")

    cap.release()
    # 各trackletを時刻順にソート + 短すぎる断片を除去(0.3秒未満)
    tracklets = {}
    for tid, entries in raw.items():
        entries.sort(key=lambda e: e["frame"])
        span = entries[-1]["t_sec"] - entries[0]["t_sec"]
        if span >= 0.3 and len(entries) >= 3:
            tracklets[tid] = entries

    print(f"STEP1完了: {len(tracklets)}トラックレット (うち0.3秒以上)")
    return tracklets


# ─────────────────────────────────────────────────────────────
# STEP 2: tracklet 連結 (短い断片を同一人物チェーンに繋ぐ)
# ─────────────────────────────────────────────────────────────
def link_tracklets(tracklets, gap_sec, dist_m):
    """
    tracklet A の末尾と tracklet B の先頭が
    gap_sec秒以内 かつ dist_m m以内 → 同一人物として連結。
    最終的に「チェーン」のリストを返す (各チェーン = 時系列のsightingリスト)
    """
    print(f"STEP2: tracklet連結 (gap<{gap_sec}s, dist<{dist_m}m)...")
    tids = sorted(tracklets.keys(),
                  key=lambda t: tracklets[t][0]["t_sec"])

    # 各trackletの要約 (先頭・末尾の時刻と座標)
    summaries = {}
    for tid in tids:
        e = tracklets[tid]
        summaries[tid] = {
            "t_start": e[0]["t_sec"], "fx_start": e[0]["fx"], "fy_start": e[0]["fy"],
            "t_end":   e[-1]["t_sec"], "fx_end":   e[-1]["fx"], "fy_end":   e[-1]["fy"],
        }

    # Union-Find で同一チェーンを管理
    parent = {tid: tid for tid in tids}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def union(a, b):
        pa, pb = find(a), find(b)
        if pa != pb:
            parent[pb] = pa

    # 各trackletの末尾から「次に来そうなtracklet」を探して連結
    linked = 0
    for i, ta in enumerate(tids):
        sa = summaries[ta]
        for tb in tids[i+1:]:
            sb = summaries[tb]
            gap  = sb["t_start"] - sa["t_end"]
            if gap < 0 or gap > gap_sec:
                continue
            dist = ((sb["fx_start"] - sa["fx_end"])**2 +
                    (sb["fy_start"] - sa["fy_end"])**2) ** 0.5
            if dist <= dist_m:
                union(ta, tb)
                linked += 1

    # チェーンを構築
    chains = defaultdict(list)
    for tid in tids:
        chains[find(tid)].append(tid)

    # チェーンごとに全sightingsを時系列で結合
    chain_sightings = []
    for root, members in chains.items():
        sightings = []
        for tid in members:
            sightings.extend(tracklets[tid])
        sightings.sort(key=lambda e: e["frame"])
        chain_sightings.append(sightings)

    chain_sightings.sort(key=lambda c: c[0]["t_sec"])
    print(f"STEP2完了: {len(tids)}トラックレット → {len(chain_sightings)}チェーン "
          f"({linked}件連結)")
    return chain_sightings


# ─────────────────────────────────────────────────────────────
# STEP 3: アンカーで #6 チェーンを確定
# ─────────────────────────────────────────────────────────────
def bind_anchor_to_chain(chain_sightings, anchor_t, anchor_fx, anchor_fy):
    """
    指定時刻・フィールド座標に最も近いsightingを持つチェーンを #6 と確定。
    チェーンをそのまま返す (以後そのチェーンが #6 として扱われる)。
    """
    print(f"STEP3: アンカー紐付け (t={anchor_t:.2f}min, fx={anchor_fx}, fy={anchor_fy})...")
    best_chain, best_d = None, 1e9
    for chain in chain_sightings:
        for s in chain:
            t_min = s["t_sec"] / 60
            if abs(t_min - anchor_t) > 1.0:  # ±1分以内のsightingだけ評価
                continue
            d = ((s["fx"] - anchor_fx)**2 + (s["fy"] - anchor_fy)**2) ** 0.5
            if d < best_d:
                best_d, best_chain = d, chain

    if best_chain is None:
        print("  WARNING: アンカーに合うチェーンが見つかりませんでした")
        return None

    span = best_chain[-1]["t_sec"] - best_chain[0]["t_sec"]
    print(f"STEP3完了: #6チェーン確定 (アンカーから{best_d:.1f}m, "
          f"sightings={len(best_chain)}, span={span:.1f}s)")
    return best_chain


# ─────────────────────────────────────────────────────────────
# STEP 4: ワープ計測 + オーバーレイ動画生成
# ─────────────────────────────────────────────────────────────
def generate_overlay(video_path, haru_chain, chain_sightings,
                     fps_video, duration_min):
    print("STEP4: オーバーレイ動画生成 + ワープ計測...")

    # #6チェーンのframe→sightingマップ
    haru_by_frame = {s["frame"]: s for s in haru_chain}

    # 全選手のframe→sightingsマップ
    all_by_frame = defaultdict(list)
    for chain in chain_sightings:
        for s in chain:
            all_by_frame[s["frame"]].append(s)

    end_f  = int(fps_video * duration_min * 60)
    sample = max(1, int(fps_video / FPS_OUT))  # 出力fps
    cap    = cv2.VideoCapture(str(video_path))

    ffmpeg_cmd = [
        "ffmpeg", "-y", "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", f"{W_OUT}x{H_OUT}", "-pix_fmt", "bgr24",
        "-r", str(FPS_OUT), "-i", "pipe:0",
        "-c:v", "libx264", "-preset", "fast", "-crf", "24",
        "-pix_fmt", "yuv420p", str(OUT_VID)
    ]
    proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # ワープ計測
    warps = 0
    prev_haru_pos = None
    trail = []

    fn = 0
    while fn < end_f:
        ret, frame = cap.read()
        if not ret:
            break
        if fn % sample == 0:
            vis = cv2.resize(frame, (W_OUT, H_OUT))
            sx  = W_OUT / frame.shape[1]
            sy  = H_OUT / frame.shape[0]
            t_sec = fn / fps_video

            # 全選手 (灰色点)
            for s in all_by_frame.get(fn, []):
                px, py = int(s["px"] * sx), int(s["py"] * sy)
                cv2.circle(vis, (px, py), 5, (100, 100, 100), 1)

            # #6 (このフレームに検出があれば)
            haru_s = haru_by_frame.get(fn)
            if haru_s:
                px, py = int(haru_s["px"] * sx), int(haru_s["py"] * sy)
                # トレイル
                trail.append((px, py))
                if len(trail) > 15:
                    trail.pop(0)
                for i in range(1, len(trail)):
                    cv2.line(vis, trail[i-1], trail[i], (0, 220, 100), 2)
                # マーカー
                x1,y1,x2,y2 = [int(v * sx if i%2==0 else v * sy)
                                for i,v in enumerate(haru_s["bbox"])]
                cv2.rectangle(vis, (x1,y1), (x2,y2), (0,255,120), 2)
                cv2.arrowedLine(vis, (px, y1-50), (px, y1-10),
                                (0,255,120), 3, tipLength=0.4)
                cv2.putText(vis, f"#6  ({haru_s['fx']:.0f},{haru_s['fy']:.0f})m",
                            (x1, y1-14), FONT, 0.65, (0,255,120), 2)
                # ワープ計測
                if prev_haru_pos is not None:
                    d = ((haru_s["fx"]-prev_haru_pos[0])**2 +
                         (haru_s["fy"]-prev_haru_pos[1])**2) ** 0.5
                    dt = t_sec - prev_haru_pos[2]
                    if d > WARP_THRESH_M:
                        warps += 1
                        cv2.putText(vis, f"WARP! {d:.1f}m",
                                    (px+10, py), FONT, 0.7, (0,0,255), 2)
                prev_haru_pos = (haru_s["fx"], haru_s["fy"], t_sec)
            else:
                # #6が検出されていないフレーム → 前回位置を薄く表示
                if trail:
                    cv2.circle(vis, trail[-1], 12, (0, 150, 80), 1)

            # ヘッダー
            cv2.rectangle(vis, (0,0), (W_OUT, 40), (0,0,0), -1)
            cv2.putText(vis, f"t={t_sec/60:.2f}min  Warps={warps}  "
                             f"#6={'TRACKED' if haru_s else 'interpolating'}",
                        (8, 28), FONT, 0.6, (0,255,120), 2)

            proc.stdin.write(vis.tobytes())
        fn += 1

    cap.release()
    proc.stdin.close()
    proc.wait()
    return warps


# ─────────────────────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────────────────────
def main():
    cap_tmp = cv2.VideoCapture(str(VIDEO_H1))
    fps     = cap_tmp.get(cv2.CAP_PROP_FPS) or 30.0
    cap_tmp.release()

    t_total = time.time()

    # アンカー読み込み
    with open(TRAJ_JSON) as f:
        traj = json.load(f)
    valid_anchors = [a for a in traj["confirmed_positions"]
                     if "不明" not in a.get("note", "")]
    # 最初の有効アンカー
    anchor = valid_anchors[0]
    anchor_t  = anchor["time_min"]
    anchor_fx = anchor["fx"]
    anchor_fy = anchor["fy"]
    print(f"アンカー: t={anchor_t:.2f}min  fx={anchor_fx}  fy={anchor_fy}")

    # STEP 1
    tracklets = extract_tracklets(VIDEO_H1, DURATION_MIN, fps)

    # STEP 2
    chains = link_tracklets(tracklets, LINK_GAP_SEC, LINK_DIST_M)

    # STEP 3
    haru_chain = bind_anchor_to_chain(chains, anchor_t, anchor_fx, anchor_fy)
    if haru_chain is None:
        print("失敗: #6チェーンが見つかりませんでした")
        return

    # チェーン統計
    haru_span = haru_chain[-1]["t_sec"] - haru_chain[0]["t_sec"]
    haru_coverage = len(haru_chain) / max(
        int((haru_chain[-1]["frame"] - haru_chain[0]["frame"]) / EVERY_N + 1), 1)

    # STEP 4
    warps = generate_overlay(VIDEO_H1, haru_chain, chains, fps, DURATION_MIN)

    print(f"\n{'='*50}")
    print(f"=== 結果サマリー ({DURATION_MIN}分) ===")
    print(f"{'='*50}")
    print(f"#6チェーン: {len(haru_chain)} sightings, span={haru_span:.1f}s, cov={haru_coverage:.2f}")
    print(f"ワープ数 (>{WARP_THRESH_M}m/frame): {warps}")
    print(f"出力動画: {OUT_VID}")
    print(f"総処理時間: {(time.time()-t_total)/60:.1f}分")


if __name__ == "__main__":
    main()
