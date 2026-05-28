#!/usr/bin/env python3
"""
TZI Pipeline v2 — YOLOv8m + BoT-SORT + RTMPose

改善点:
  - YOLOv8n → YOLOv8m (検出精度向上)
  - ByteTrack → BoT-SORT (CMC + Re-ID対応, 追跡持続向上)
  - RTMPose で体の向き・重心を全フレーム推定
  - アンカー紐付けは1回のみ → 以後はBoT-SORTのtrack_idに追従

使い方:
  python tzi_pipeline_v2.py                  # H1前半5分 (デフォルト)
  python tzi_pipeline_v2.py --half 2 --start 10 --dur 5  # H2 10-15分
  python tzi_pipeline_v2.py --combined       # H1 0-5 + H2 10-15 を1本に結合
"""
import cv2, json, time, argparse, subprocess, numpy as np
from pathlib import Path
from collections import defaultdict
from ultralytics import YOLO
from boxmot.trackers.botsort.botsort import BotSort
from config import VIDEO_H1, VIDEO_H2, TRAJ_JSON, OUTPUT_DIR, p2f, FW, FH

# ── 設定 ──────────────────────────────────────────────────────
IMGSZ      = 640       # CPU環境: 640固定。GPU移行後は1280に変更
CONF       = 0.20
EVERY_N    = 3         # 10fps相当 (CPU限定。GPU環境では1に変更)
FPS_OUT    = 5         # 出力動画fps
MODEL_NAME = "yolov8n.pt"  # CPU: yolov8n。GPU移行後は yolov8m.pt に変更
W_OUT      = 1280
H_OUT      = 720
WARP_THRESH_M = 4.0
FONT = cv2.FONT_HERSHEY_SIMPLEX

# アンカー検索許容範囲
ANCHOR_TOL_MIN = 1.5

# RTMPose 使用フラグ (初回はモデルダウンロードが必要)
USE_POSE = True

# ──────────────────────────────────────────────────────────────
def make_botsort(fps):
    """BoT-SORT インスタンスを生成 (Re-IDなし軽量版)"""
    return BotSort(
        with_reid=False,          # CPU環境ではRe-IDは重すぎる → GPU移行後に True に
        track_high_thresh=0.25,   # 低信頼検出も拾う
        track_low_thresh=0.10,
        new_track_thresh=0.40,
        track_buffer=120,         # 4秒間ID保持 (30fps基準)
        match_thresh=0.85,
        cmc_method="ecc",         # カメラ動き補正 (pan/tilt対応)
        frame_rate=int(fps),
    )


def load_anchor():
    with open(TRAJ_JSON) as f:
        traj = json.load(f)
    valid = [a for a in traj["confirmed_positions"]
             if "不明" not in a.get("note", "")]
    return valid  # [{time_min, fx, fy, ...}, ...]


# ──────────────────────────────────────────────────────────────
def process_segment(video_path, start_min, dur_min, fps,
                    anchors, label, out_path, pose_estimator=None):
    """
    1セグメントを処理してオーバーレイ動画を生成。
    戻り値: (warp_count, coverage_pct)
    """
    model   = YOLO(str(Path(__file__).parent / MODEL_NAME))
    tracker = make_botsort(fps)

    start_f = int(fps * start_min * 60)
    end_f   = start_f + int(fps * dur_min * 60)
    total_frames_out = int(dur_min * 60 * FPS_OUT)
    sample  = max(1, int(fps / FPS_OUT))

    cap = cv2.VideoCapture(str(video_path))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_f)

    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-f", "rawvideo", "-vcodec", "rawvideo",
         "-s", f"{W_OUT}x{H_OUT}", "-pix_fmt", "bgr24",
         "-r", str(FPS_OUT), "-i", "pipe:0",
         "-c:v", "libx264", "-preset", "fast", "-crf", "22",
         "-pix_fmt", "yuv420p", str(out_path)],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    # アンカーをin-video時間でフィルタ
    seg_end_min = start_min + dur_min
    seg_anchors = [a for a in anchors
                   if start_min - ANCHOR_TOL_MIN <= a["time_min"] <= seg_end_min + ANCHOR_TOL_MIN]
    # 時系列ソート
    seg_anchors.sort(key=lambda a: a["time_min"])

    haru_id      = None   # BoT-SORT track_id
    haru_pos     = None   # (fx, fy) 最後の確認位置
    haru_lost_t  = None   # #6 が最後に見えたt_sec (長期ロスト検出用)
    LOST_THRESH  = 5.0    # 5秒間見えなければ再バインド許可
    trail        = []
    warps        = 0
    tracked_frames   = 0
    total_out_frames = 0
    prev_t       = None
    used_anchors = set()  # 一度使ったアンカーを再使用しない

    # 姿勢キャッシュ (frame → {track_id: (angle_deg, cx, cy)})
    pose_cache = {}

    print(f"  [{label}] 処理開始: {start_min:.0f}-{start_min+dur_min:.0f}min, "
          f"imgsz={IMGSZ}, N={EVERY_N}")
    t0 = time.time()

    fn = start_f
    while fn < end_f:
        ret, frame = cap.read()
        if not ret:
            break

        t_sec = fn / fps
        t_min = t_sec / 60

        # ── YOLO + BoT-SORT (EVERY_N フレームに1回) ──
        if (fn - start_f) % EVERY_N == 0:
            results = model(frame, classes=[0], imgsz=IMGSZ,
                            conf=CONF, verbose=False)
            boxes = results[0].boxes
            if boxes is not None and len(boxes) > 0:
                dets = np.hstack([
                    boxes.xyxy.cpu().numpy(),
                    boxes.conf.cpu().numpy().reshape(-1, 1),
                    boxes.cls.cpu().numpy().reshape(-1, 1),
                ])
                tracks = tracker.update(dets, frame)  # [x1,y1,x2,y2,id,conf,cls,idx]
            else:
                tracks = tracker.update(
                    np.empty((0, 6)), frame)

            # ── アンカー確認 ──
            # 条件: haru_idが未設定 OR 長期ロスト(5秒以上見えない) のときのみ適用
            is_lost = (haru_id is None or
                       (haru_lost_t is not None and
                        t_sec - haru_lost_t > LOST_THRESH))
            if is_lost:
                for anc_idx, anc in enumerate(seg_anchors):
                    if anc_idx in used_anchors:
                        continue
                    if abs(anc["time_min"] - t_min) < ANCHOR_TOL_MIN / 4:
                        best_tid, best_d = None, 1e9
                        for tr in tracks:
                            x1,y1,x2,y2,tid = tr[0],tr[1],tr[2],tr[3],int(tr[4])
                            cx_px = (x1+x2)/2; cy_px = y2
                            fx, fy = p2f(cx_px, cy_px)
                            d = ((fx - anc["fx"])**2 + (fy - anc["fy"])**2)**0.5
                            if d < best_d:
                                best_d, best_tid = d, tid
                        if best_tid is not None and best_d < 8.0:
                            haru_id      = best_tid
                            haru_pos     = (anc["fx"], anc["fy"])
                            haru_lost_t  = None
                            used_anchors.add(anc_idx)

            # ── #6 の現在位置を特定 ──
            haru_det = None
            for tr in tracks:
                if int(tr[4]) == haru_id:
                    haru_det = tr
                    break

            # ── 位置ベース再バインド (ロスト後 + アンカーなしの場合) ──
            # haru_id が消えたとき、最後の既知位置から近い track に再割り当て
            if haru_det is None and haru_pos is not None and is_lost:
                best_tid, best_d = None, 1e9
                for tr in tracks:
                    tid = int(tr[4])
                    cx_px = (tr[0]+tr[2])/2; cy_px = tr[3]  # 足元
                    fx, fy = p2f(cx_px, cy_px)
                    d = ((fx-haru_pos[0])**2+(fy-haru_pos[1])**2)**0.5
                    if d < best_d:
                        best_d, best_tid = d, tid
                if best_tid is not None and best_d < 6.0:  # 6m以内なら再バインド
                    haru_id     = best_tid
                    haru_lost_t = t_sec
                    # 再検索
                    for tr in tracks:
                        if int(tr[4]) == haru_id:
                            haru_det = tr
                            break

            if haru_det is not None:
                x1,y1,x2,y2 = map(int, haru_det[:4])
                cx_px = (x1+x2)//2; cy_px = y2
                fx, fy = p2f(cx_px, cy_px)

                # ワープチェック
                if haru_pos is not None and prev_t is not None:
                    d = ((fx-haru_pos[0])**2+(fy-haru_pos[1])**2)**0.5
                    speed = d / max(t_sec - prev_t, 0.01)
                    if d > WARP_THRESH_M:
                        warps += 1

                haru_pos    = (fx, fy)
                haru_lost_t = t_sec
                prev_t      = t_sec

                # ── 姿勢推定 ──
                if pose_estimator is not None and (fn - start_f) % (EVERY_N * 2) == 0:
                    try:
                        crop = frame[max(0,y1):y2, max(0,x1):x2]
                        if crop.size > 0:
                            keypoints = pose_estimator(crop)
                            if keypoints is not None and len(keypoints) > 0:
                                kp = keypoints[0]  # 最初の人物
                                # 肩(5,6)と腰(11,12)から体の向きを推定
                                if len(kp) >= 12:
                                    ls, rs = kp[5][:2], kp[6][:2]
                                    angle = np.degrees(np.arctan2(rs[1]-ls[1], rs[0]-ls[0]))
                                    pose_cache[fn] = {"angle": float(angle),
                                                      "cx": cx_px, "cy": (y1+y2)//2}
                    except Exception:
                        pass

        # ── 出力フレーム生成 ──
        if (fn - start_f) % sample == 0:
            vis = cv2.resize(frame, (W_OUT, H_OUT))
            sx  = W_OUT / frame.shape[1]
            sy  = H_OUT / frame.shape[0]
            total_out_frames += 1

            # 全検出選手 (灰点)
            if (fn - start_f) % EVERY_N == 0 and len(tracks) > 0:
                for tr in tracks:
                    if int(tr[4]) != haru_id:
                        px = int(((tr[0]+tr[2])/2) * sx)
                        py = int(((tr[1]+tr[3])/2) * sy)
                        cv2.circle(vis, (px, py), 5, (80, 80, 80), 1)

            if haru_pos is not None and haru_det is not None:
                tracked_frames += 1
                x1,y1,x2,y2 = [int(v*(sx if i%2==0 else sy))
                                for i,v in enumerate(haru_det[:4])]
                px = (x1+x2)//2; py = (y1+y2)//2

                trail.append((px, py))
                if len(trail) > 20: trail.pop(0)
                for i in range(1, len(trail)):
                    alpha = i / len(trail)
                    cv2.line(vis, trail[i-1], trail[i],
                             (int(50*alpha), int(220*alpha), int(100*alpha)), 2)

                cv2.rectangle(vis, (x1,y1), (x2,y2), (0,255,120), 2)
                cv2.arrowedLine(vis, (px, y1-50), (px, y1-12),
                                (0,255,120), 3, tipLength=0.4)

                label_txt = f"#6  ({haru_pos[0]:.0f},{haru_pos[1]:.0f})m"

                # 向き情報があれば追加
                if fn in pose_cache:
                    ang = pose_cache[fn]["angle"]
                    label_txt += f"  dir={ang:.0f}°"
                    # 向き矢印
                    rad = np.radians(ang)
                    ex = int(px + 30*np.cos(rad))
                    ey = int(py + 30*np.sin(rad))
                    cv2.arrowedLine(vis, (px, py), (ex, ey),
                                    (255, 200, 0), 2, tipLength=0.3)

                cv2.putText(vis, label_txt, (x1, y1-14),
                            FONT, 0.60, (0,255,120), 2)

            elif haru_pos is not None:
                # LOST: 最後の既知位置にマーカー
                # (pixel座標が古いので使わず、フィールド座標のみ表示)
                if trail:
                    lx, ly = trail[-1]
                    for angle in range(0, 360, 25):
                        a = np.radians(angle)
                        pt = (int(lx+20*np.cos(a)), int(ly+20*np.sin(a)))
                        cv2.circle(vis, pt, 2, (0,160,70), -1)
                    cv2.arrowedLine(vis, (lx, ly-55), (lx, ly-24),
                                    (0,160,70), 2, tipLength=0.4)
                    cv2.putText(vis, f"#6 LOST ({haru_pos[0]:.0f},{haru_pos[1]:.0f})m",
                                (lx-40, ly-58), FONT, 0.50, (0,160,70), 1)

            # ヘッダー
            cov_pct = tracked_frames / max(total_out_frames, 1) * 100
            cv2.rectangle(vis, (0,0), (W_OUT, 42), (0,0,0), -1)
            cv2.putText(vis,
                        f"[{label}]  t={t_sec/60:.2f}min  "
                        f"#6={'OK' if (haru_pos and haru_det is not None) else 'LOST'}  "
                        f"cov={cov_pct:.0f}%  warps={warps}",
                        (8, 28), FONT, 0.58, (0,255,120), 2)

            proc.stdin.write(vis.tobytes())

        fn += 1

        # 進捗
        elapsed_f = fn - start_f
        total_f   = end_f - start_f
        if elapsed_f % int(fps * 60) == 0 and elapsed_f > 0:
            pct = elapsed_f / total_f * 100
            cov = tracked_frames / max(total_out_frames, 1) * 100
            print(f"    {pct:.0f}% ({elapsed_f/fps:.0f}s)  "
                  f"cov={cov:.0f}%  warps={warps}  "
                  f"{time.time()-t0:.0f}s経過")

    cap.release()
    proc.stdin.close()
    proc.wait()

    cov_pct = tracked_frames / max(total_out_frames, 1) * 100
    print(f"  [{label}] 完了: cov={cov_pct:.0f}%  warps={warps}")
    return warps, cov_pct


# ──────────────────────────────────────────────────────────────
def concat_videos(paths, out_path):
    list_file = OUTPUT_DIR / "_concat_list.txt"
    with open(list_file, "w") as f:
        for p in paths:
            f.write(f"file '{p.resolve()}'\n")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
         "-i", str(list_file), "-c", "copy", str(out_path)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    list_file.unlink()


# ──────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--half",     type=int, default=1, choices=[1,2])
    parser.add_argument("--start",    type=float, default=0.0)
    parser.add_argument("--dur",      type=float, default=5.0)
    parser.add_argument("--combined", action="store_true",
                        help="H1 0-5min + H2 10-15min を1本に結合")
    parser.add_argument("--no-pose",  action="store_true",
                        help="RTMPose をスキップ (高速化)")
    args = parser.parse_args()

    cap_tmp = cv2.VideoCapture(str(VIDEO_H1))
    fps = cap_tmp.get(cv2.CAP_PROP_FPS) or 30.0
    cap_tmp.release()

    anchors = load_anchor()

    # 姿勢推定器
    pose_estimator = None
    if USE_POSE and not args.no_pose:
        try:
            from rtmlib import Body
            pose_estimator = Body(
                pose='rtmpose-m',
                to_openpose=False,
                backend='onnxruntime',
                device='cpu'
            )
            print("RTMPose-m loaded (CPU)")
        except Exception as e:
            print(f"RTMPose skip: {e}")

    t_total = time.time()

    if args.combined:
        # H1 0-5分 + H2 10-15分 の結合
        segs = [
            (VIDEO_H1, 0.0,  5.0, "H1 00:00-05:00",
             OUTPUT_DIR / "v2_seg_h1_0to5.mp4"),
            (VIDEO_H2, 10.0, 5.0, "H2 10:00-15:00",
             OUTPUT_DIR / "v2_seg_h2_10to15.mp4"),
        ]
        out_path = OUTPUT_DIR / "v2_combined_overlay.mp4"
        seg_paths = []
        for vid, st, dur, lbl, seg_out in segs:
            w, c = process_segment(vid, st, dur, fps,
                                   anchors, lbl, seg_out, pose_estimator)
            seg_paths.append(seg_out)
        print("ffmpeg concat で結合中...")
        concat_videos(seg_paths, out_path)

    else:
        video = VIDEO_H1 if args.half == 1 else VIDEO_H2
        out_path = OUTPUT_DIR / f"v2_h{args.half}_{int(args.start)}to{int(args.start+args.dur)}.mp4"
        process_segment(video, args.start, args.dur, fps,
                        anchors, f"H{args.half} {args.start:.0f}-{args.start+args.dur:.0f}min",
                        out_path, pose_estimator)

    size_mb = out_path.stat().st_size / 1e6
    print(f"\n完成: {out_path}  ({size_mb:.1f} MB)")
    print(f"総処理時間: {(time.time()-t_total)/60:.1f}分")

    # Google Drive アップロード
    print("Google Drive にアップロード中...")
    subprocess.run(["rclone", "copy", str(out_path), "gdrive:TZI/outputs/"],
                   check=False)
    result = subprocess.run(
        ["rclone", "link", f"gdrive:TZI/outputs/{out_path.name}"],
        capture_output=True, text=True)
    link = result.stdout.strip()
    if link:
        # 公開設定
        import re
        m = re.search(r'id=([\w-]+)', link)
        if m:
            fid = m.group(1)
            token_raw = subprocess.run(
                ["rclone", "config", "dump"], capture_output=True, text=True
            ).stdout
            import json as _json
            cfg = _json.loads(token_raw)
            tok = _json.loads(cfg.get("gdrive", {}).get("token", "{}"))
            access_token = tok.get("access_token", "")
            if access_token:
                subprocess.run([
                    "curl", "-s", "-X", "POST",
                    f"https://www.googleapis.com/drive/v3/files/{fid}/permissions",
                    "-H", f"Authorization: Bearer {access_token}",
                    "-H", "Content-Type: application/json",
                    "-d", '{"role":"reader","type":"anyone"}'
                ], capture_output=True)
                print(f"\nGoogle Drive リンク:")
                print(f"  https://drive.google.com/file/d/{fid}/view?usp=sharing")


if __name__ == "__main__":
    main()
