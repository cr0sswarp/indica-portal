#!/usr/bin/env python3
"""
前半0-5分 + 後半10-15分 を結合したオーバーレイ動画を生成する。
各セグメントで tracklet抽出→連結→アンカー紐付け→オーバーレイを実行し
最後に ffmpeg concat で1本にまとめる。
"""
import cv2, json, time, subprocess, numpy as np
from pathlib import Path
from collections import defaultdict
from ultralytics import YOLO
from config import VIDEO_H1, VIDEO_H2, TRAJ_JSON, OUTPUT_DIR, p2f, FW, FH

# ── 設定 ──────────────────────────────────────────────────────
IMGSZ        = 640
CONF         = 0.20
EVERY_N      = 6          # 5fps相当
FPS_OUT      = 5
W_OUT, H_OUT = 1280, 720
LINK_GAP_SEC = 2.0
LINK_DIST_M  = 4.0
WARP_THRESH  = 4.0
FONT         = cv2.FONT_HERSHEY_SIMPLEX

# セグメント定義: (動画ファイル, 開始分, 長さ分, アンカーのin-video時間min, fx, fy, ラベル)
# 後半アンカーは絶対52.8min → VIDEO_H2相対 = 52.8-45 = 7.8min だが
# 処理範囲(10-15min)の直前なので ±3分まで緩めて検索する
SEGMENTS = [
    {
        "video":      VIDEO_H1,
        "start_min":  0.0,
        "dur_min":    5.0,
        "anchor_t":   0.75,    # in-video min
        "anchor_fx":  29.8,
        "anchor_fy":  36.6,
        "anchor_tol": 1.0,     # ±minutes
        "label":      "H1 00:00-05:00",
        "out_raw":    OUTPUT_DIR / "seg_h1_0to5.mp4",
    },
    {
        "video":      VIDEO_H2,
        "start_min":  10.0,
        "dur_min":    5.0,
        "anchor_t":   7.8,     # 52.8-45 = 7.8 in-video min (before clip start)
        "anchor_fx":  30.0,    # 後半は大まかな位置推定 (first-half average)
        "anchor_fy":  42.0,
        "anchor_tol": 5.0,     # ±5分まで緩める
        "label":      "H2 10:00-15:00",
        "out_raw":    OUTPUT_DIR / "seg_h2_10to15.mp4",
    },
]

OUT_FINAL = OUTPUT_DIR / "combined_overlay.mp4"


# ──────────────────────────────────────────────────────────────
def extract_tracklets(video_path, start_min, dur_min, fps_video):
    model = YOLO(str(Path(__file__).parent / "yolov8n.pt"))
    cap   = cv2.VideoCapture(str(video_path))
    start_f = int(fps_video * start_min * 60)
    end_f   = start_f + int(fps_video * dur_min * 60)

    # skip to start frame
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_f)

    raw = defaultdict(list)
    fn  = start_f
    t0  = time.time()
    print(f"  STEP1: tracklet抽出 ({start_min:.0f}-{start_min+dur_min:.0f}min, N={EVERY_N})...")

    while fn < end_f:
        ret, frame = cap.read()
        if not ret:
            break
        if (fn - start_f) % EVERY_N == 0:
            results = model.track(frame, persist=True, classes=[0],
                                  imgsz=IMGSZ, conf=CONF, verbose=False,
                                  tracker="bytetrack_hi.yaml")
            if results[0].boxes is not None and results[0].boxes.id is not None:
                ids   = results[0].boxes.id.cpu().numpy().astype(int)
                boxes = results[0].boxes.xyxy.cpu().numpy()
                for tid, box in zip(ids, boxes):
                    x1, y1, x2, y2 = map(int, box)
                    cx = (x1 + x2) // 2
                    cy = y2
                    fx, fy = p2f(cx, cy)
                    raw[int(tid)].append({
                        "frame":  fn,
                        "t_sec":  fn / fps_video,
                        "px": cx, "py": (y1 + y2) // 2,
                        "fx": round(fx, 2), "fy": round(fy, 2),
                        "bbox": [x1, y1, x2, y2],
                    })
        fn += 1
        elapsed_pct = (fn - start_f) / (end_f - start_f) * 100
        if (fn - start_f) % int(fps_video * 60) == 0 and fn > start_f:
            print(f"    {elapsed_pct:.0f}% ({(fn-start_f)/fps_video:.0f}s)  IDs={len(raw)}  "
                  f"{time.time()-t0:.0f}s経過")

    cap.release()
    tracklets = {}
    for tid, entries in raw.items():
        entries.sort(key=lambda e: e["frame"])
        span = entries[-1]["t_sec"] - entries[0]["t_sec"]
        if span >= 0.3 and len(entries) >= 3:
            tracklets[tid] = entries
    print(f"  STEP1完了: {len(tracklets)}トラックレット")
    return tracklets


def link_tracklets(tracklets):
    print(f"  STEP2: tracklet連結 (gap<{LINK_GAP_SEC}s, dist<{LINK_DIST_M}m)...")
    tids = sorted(tracklets, key=lambda t: tracklets[t][0]["t_sec"])
    summaries = {
        tid: {
            "t_start": tracklets[tid][0]["t_sec"],
            "fx_start": tracklets[tid][0]["fx"],
            "fy_start": tracklets[tid][0]["fy"],
            "t_end":   tracklets[tid][-1]["t_sec"],
            "fx_end":  tracklets[tid][-1]["fx"],
            "fy_end":  tracklets[tid][-1]["fy"],
        } for tid in tids
    }
    parent = {t: t for t in tids}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def union(a, b):
        pa, pb = find(a), find(b)
        if pa != pb: parent[pb] = pa

    linked = 0
    for i, ta in enumerate(tids):
        sa = summaries[ta]
        for tb in tids[i+1:]:
            sb = summaries[tb]
            gap = sb["t_start"] - sa["t_end"]
            if gap < 0 or gap > LINK_GAP_SEC:
                continue
            dist = ((sb["fx_start"]-sa["fx_end"])**2 +
                    (sb["fy_start"]-sa["fy_end"])**2) ** 0.5
            if dist <= LINK_DIST_M:
                union(ta, tb); linked += 1

    chains_map = defaultdict(list)
    for tid in tids:
        chains_map[find(tid)].append(tid)
    chains = []
    for members in chains_map.values():
        s = []
        for tid in members: s.extend(tracklets[tid])
        s.sort(key=lambda e: e["frame"])
        chains.append(s)
    chains.sort(key=lambda c: c[0]["t_sec"])
    print(f"  STEP2完了: {len(tids)}→{len(chains)}チェーン ({linked}件連結)")
    return chains


def bind_anchor(chains, anchor_t, anchor_fx, anchor_fy, tol_min):
    print(f"  STEP3: アンカー紐付け (t={anchor_t:.2f}min ±{tol_min}min, "
          f"fx={anchor_fx}, fy={anchor_fy})...")
    best_chain, best_d = None, 1e9
    for chain in chains:
        for s in chain:
            t_min = s["t_sec"] / 60
            if abs(t_min - anchor_t) > tol_min:
                continue
            d = ((s["fx"]-anchor_fx)**2 + (s["fy"]-anchor_fy)**2) ** 0.5
            if d < best_d:
                best_d, best_chain = d, chain
    if best_chain is None:
        best_chain = max(chains, key=lambda c: c[-1]["t_sec"] - c[0]["t_sec"])
        print(f"  STEP3 fallback: 最長チェーンを使用 ({len(best_chain)} sightings)")
    else:
        span = best_chain[-1]["t_sec"] - best_chain[0]["t_sec"]
        print(f"  STEP3完了: アンカー{best_d:.1f}m, span={span:.1f}s, "
              f"sightings={len(best_chain)}")
    return best_chain


def follow_chains(chains, seed_chain, dur_sec,
                  rebind_gap_sec=5.0, rebind_dist_m=6.0):
    """
    seed_chainが途切れた後、最寄りチェーンに繰り返し再バインドして
    dur_sec 全体を通じた #6 sightings リストを返す。
    各チェーンを時系列ソート済みの sightings リストとして扱う。
    """
    # チェーンの先頭・末尾インデックスを構築
    chain_map = {id(c): c for c in chains}

    used = set()
    used.add(id(seed_chain))
    full_sightings = list(seed_chain)  # コピー

    rebinds = 0
    while True:
        last = full_sightings[-1]
        last_t  = last["t_sec"]
        last_fx = last["fx"]
        last_fy = last["fy"]

        if last_t >= dur_sec:
            break

        # last_t の直後に始まる最寄りチェーンを探す
        best_next, best_score = None, 1e9
        for cid, chain in chain_map.items():
            if cid in used:
                continue
            t_start = chain[0]["t_sec"]
            gap = t_start - last_t
            if gap < 0 or gap > rebind_gap_sec:
                continue
            dist = ((chain[0]["fx"]-last_fx)**2 +
                    (chain[0]["fy"]-last_fy)**2) ** 0.5
            if dist > rebind_dist_m:
                continue
            # スコア: 距離優先
            score = dist + gap * 0.5
            if score < best_score:
                best_score, best_next = score, cid

        if best_next is None:
            break  # 近いチェーンなし → 終了

        next_chain = chain_map[best_next]
        full_sightings.extend(next_chain)
        used.add(best_next)
        rebinds += 1

    full_sightings.sort(key=lambda s: s["frame"])
    span = full_sightings[-1]["t_sec"] - full_sightings[0]["t_sec"]
    print(f"  STEP3b: チェーン追跡 {rebinds}回再バインド → "
          f"合計{len(full_sightings)} sightings, span={span:.1f}s")
    return full_sightings


def generate_segment_overlay(video_path, start_min, dur_min, fps_video,
                              haru_chain, chains, label, out_path):
    print(f"  STEP4: オーバーレイ動画生成 → {out_path.name}...")
    start_f = int(fps_video * start_min * 60)
    end_f   = start_f + int(fps_video * dur_min * 60)
    sample  = max(1, int(fps_video / FPS_OUT))

    haru_by_frame = {s["frame"]: s for s in haru_chain}
    all_by_frame  = defaultdict(list)
    for chain in chains:
        for s in chain:
            all_by_frame[s["frame"]].append(s)

    cap = cv2.VideoCapture(str(video_path))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_f)

    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-f", "rawvideo", "-vcodec", "rawvideo",
         "-s", f"{W_OUT}x{H_OUT}", "-pix_fmt", "bgr24",
         "-r", str(FPS_OUT), "-i", "pipe:0",
         "-c:v", "libx264", "-preset", "fast", "-crf", "24",
         "-pix_fmt", "yuv420p", str(out_path)],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    warps = 0; prev_pos = None; trail = []; last_px = last_py = None
    last_fx = last_fy = None
    fn = start_f
    while fn < end_f:
        ret, frame = cap.read()
        if not ret: break
        if (fn - start_f) % sample == 0:
            vis = cv2.resize(frame, (W_OUT, H_OUT))
            sx, sy = W_OUT / frame.shape[1], H_OUT / frame.shape[0]
            t_sec = fn / fps_video

            for s in all_by_frame.get(fn, []):
                cv2.circle(vis, (int(s["px"]*sx), int(s["py"]*sy)), 5, (100,100,100), 1)

            hs = haru_by_frame.get(fn)
            if hs:
                px, py = int(hs["px"]*sx), int(hs["py"]*sy)
                trail.append((px, py))
                if len(trail) > 15: trail.pop(0)
                for i in range(1, len(trail)):
                    cv2.line(vis, trail[i-1], trail[i], (0,220,100), 2)
                x1,y1,x2,y2 = [int(v*(sx if i%2==0 else sy))
                                for i,v in enumerate(hs["bbox"])]
                cv2.rectangle(vis, (x1,y1), (x2,y2), (0,255,120), 2)
                cv2.arrowedLine(vis, (px, y1-50), (px, y1-10), (0,255,120), 3, tipLength=0.4)
                cv2.putText(vis, f"#6  ({hs['fx']:.0f},{hs['fy']:.0f})m",
                            (x1, y1-14), FONT, 0.65, (0,255,120), 2)
                if prev_pos is not None:
                    d = ((hs["fx"]-prev_pos[0])**2+(hs["fy"]-prev_pos[1])**2)**0.5
                    if d > WARP_THRESH:
                        warps += 1
                        cv2.putText(vis, f"WARP! {d:.1f}m",
                                    (px+10, py), FONT, 0.7, (0,0,255), 2)
                prev_pos = (hs["fx"], hs["fy"])
                last_px, last_py = px, py
                last_fx, last_fy = hs["fx"], hs["fy"]
            else:
                # 検出なし → 最後の既知位置に "LOST" マーカーを表示
                if last_px is not None:
                    # 破線丸＋矢印
                    for angle in range(0, 360, 20):
                        a = np.radians(angle)
                        pt = (int(last_px + 22*np.cos(a)),
                              int(last_py + 22*np.sin(a)))
                        cv2.circle(vis, pt, 2, (0,180,80), -1)
                    cv2.arrowedLine(vis, (last_px, last_py-60),
                                    (last_px, last_py-26),
                                    (0,180,80), 2, tipLength=0.4)
                    cv2.putText(vis, f"#6 LOST ({last_fx:.0f},{last_fy:.0f})m",
                                (last_px-40, last_py-64),
                                FONT, 0.55, (0,180,80), 1)

            # ヘッダー (ラベル付き)
            cv2.rectangle(vis, (0,0), (W_OUT,40), (0,0,0), -1)
            cv2.putText(vis,
                        f"[{label}]  t={t_sec/60:.2f}min  Warps={warps}  "
                        f"#6={'TRACKED' if hs else 'LOST (last pos shown)'}",
                        (8,28), FONT, 0.55, (0,255,120), 2)
            proc.stdin.write(vis.tobytes())
        fn += 1

    cap.release()
    proc.stdin.close(); proc.wait()
    print(f"  STEP4完了: warps={warps}")
    return warps


def concat_segments(seg_paths, out_path):
    list_file = OUTPUT_DIR / "_concat_list.txt"
    with open(list_file, "w") as f:
        for p in seg_paths:
            f.write(f"file '{p.resolve()}'\n")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
         "-i", str(list_file), "-c", "copy", str(out_path)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    list_file.unlink()
    print(f"結合完了: {out_path}")


def main():
    t_total = time.time()
    cap_tmp = cv2.VideoCapture(str(VIDEO_H1))
    fps = cap_tmp.get(cv2.CAP_PROP_FPS) or 30.0
    cap_tmp.release()

    seg_paths = []
    for seg in SEGMENTS:
        print(f"\n{'='*55}")
        print(f"  セグメント: {seg['label']}")
        print(f"{'='*55}")
        # 各セグメントで独立したモデルインスタンス (ByteTrack状態リセット)
        tracklets = extract_tracklets(
            seg["video"], seg["start_min"], seg["dur_min"], fps)
        chains    = link_tracklets(tracklets)
        haru_seed = bind_anchor(
            chains, seg["anchor_t"], seg["anchor_fx"], seg["anchor_fy"],
            seg["anchor_tol"])
        dur_sec = seg["dur_min"] * 60 + seg["start_min"] * 60
        haru    = follow_chains(chains, haru_seed, dur_sec,
                               rebind_gap_sec=15.0, rebind_dist_m=8.0)
        generate_segment_overlay(
            seg["video"], seg["start_min"], seg["dur_min"], fps,
            haru, chains, seg["label"], seg["out_raw"])
        seg_paths.append(seg["out_raw"])

    print(f"\n{'='*55}")
    print("  ffmpeg concat で結合中...")
    concat_segments(seg_paths, OUT_FINAL)

    size_mb = OUT_FINAL.stat().st_size / 1e6
    print(f"\n{'='*55}")
    print(f"完成: {OUT_FINAL}")
    print(f"サイズ: {size_mb:.1f} MB")
    print(f"総処理時間: {(time.time()-t_total)/60:.1f}分")


if __name__ == "__main__":
    main()
