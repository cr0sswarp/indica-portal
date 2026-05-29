#!/usr/bin/env python3
"""
TZI Pipeline GPU版 — YOLOv8m + BoT-SORT (Re-ID) + RTMPose

GPU環境 (Vast.ai RTX4090 / A100) での本番パイプライン。
CPU版 tzi_pipeline_v2.py との違い:
  - YOLOv8m (高精度モデル)
  - imgsz=1280 (広角カメラでの小物体検出向上)
  - EVERY_N=1 (全フレーム処理)
  - BoT-SORT with Re-ID (osnet_x0_25 軽量モデル)
  - RTMPose-m による体の向き推定

使い方:
  python tzi_pipeline_gpu.py --combined          # H1 0-5 + H2 10-15 結合
  python tzi_pipeline_gpu.py --half 1 --dur 45   # 前半全体 (45分)
  python tzi_pipeline_gpu.py --half 2 --dur 45   # 後半全体
"""
import os
# "cuda" は CUDA_VISIBLE_DEVICES の正しい値ではない (GPU番号のみ有効)。
# select_device が誤って書き込んだ場合に GPU を見失うので除去する。
if os.environ.get("CUDA_VISIBLE_DEVICES") == "cuda":
    del os.environ["CUDA_VISIBLE_DEVICES"]

import cv2, json, time, argparse, subprocess, re, numpy as np
from pathlib import Path
from collections import defaultdict
from ultralytics import YOLO
try:
    # boxmot v18+ (Python 3.9+)
    from boxmot.trackers.botsort.botsort import BotSort
except ImportError:
    # boxmot v10.x (Python 3.8) — クラス名/モジュール名が異なる
    from boxmot.trackers.botsort.bot_sort import BoTSORT as BotSort
from config import VIDEO_H1, VIDEO_H2, TRAJ_JSON, OUTPUT_DIR, p2f, FW, FH

# ── 設定 ──────────────────────────────────────────────────────
# GPU番号で指定する ("cuda" 文字列は ultralytics/boxmot の select_device で
# CUDA_VISIBLE_DEVICES="cuda" に化けてGPUを見失うため "0" を使う)
DEVICE     = "0"       # GPU使用 (1枚目のGPU)
IMGSZ      = 1280      # 高解像度 (GPU必須)
CONF       = 0.20
EVERY_N    = 1         # 全フレーム処理 (GPU必須)
FPS_OUT    = 10        # 出力動画fps (GPU版は10fps)
W_OUT      = 1920
H_OUT      = 1080
MODEL_NAME = "yolov8m.pt"
WARP_THRESH_M = 4.0
FONT = cv2.FONT_HERSHEY_SIMPLEX

ANCHOR_TOL_MIN = 1.5
LOST_THRESH    = 3.0   # 3秒ロストで再バインド許可 (GPU: 全フレームなので短くできる)
REBIND_DIST_M  = 6.0   # 位置ベース再バインド距離

USE_POSE  = True       # RTMPose による向き推定
USE_REID  = True       # Re-ID モデル使用

# ──────────────────────────────────────────────────────────────
def make_botsort(fps, use_reid=True):
    """boxmot のバージョン差を吸収して BoT-SORT トラッカーを生成する。

    v10.x (Python3.8): BoTSORT(model_weights, device, fp16, ..., with_reid=)
    v18+ (Python3.9+): BotSort(reid_model=, with_reid=, ...)
    """
    import inspect
    params = inspect.signature(BotSort.__init__).parameters
    common = dict(
        track_high_thresh=0.25,
        track_low_thresh=0.10,
        new_track_thresh=0.40,
        track_buffer=90,          # 3秒 (全フレーム処理なので短くてOK)
        match_thresh=0.85,
        frame_rate=int(fps),
    )
    if "cmc_method" in params:
        common["cmc_method"] = "ecc"   # カメラ動き補正 (パン/ズーム対応)

    if "model_weights" in params:
        # ── boxmot v10.x API ──────────────────────────────
        reid_w = Path("osnet_x0_25_msmt17.pt")
        try:
            t = BotSort(model_weights=reid_w, device=DEVICE, fp16=True,
                        with_reid=use_reid, **common)
            print(f"BoT-SORT (v10 API) Re-ID={use_reid} loaded")
            return t
        except Exception as e:
            print(f"Re-ID付き生成失敗 ({e}) → Re-IDなしで再試行")
            return BotSort(model_weights=reid_w, device=DEVICE, fp16=True,
                           with_reid=False, **common)

    # ── boxmot v18+ API ───────────────────────────────────
    reid_model = None
    if use_reid:
        try:
            from boxmot.reid.auto_backend import ReidAutoBackend
            reid_model = ReidAutoBackend(
                weights=Path("osnet_x0_25_msmt17.pt"),
                device=DEVICE, half=True).model
            print("Re-ID model (osnet_x0_25) loaded")
        except Exception as e:
            print(f"Re-ID skip: {e}")
    return BotSort(reid_model=reid_model,
                   with_reid=(reid_model is not None), **common)


def load_anchor():
    with open(TRAJ_JSON) as f:
        traj = json.load(f)
    return [a for a in traj["confirmed_positions"]
            if "不明" not in a.get("note", "")]


def upload_gdrive(out_path):
    """Google Drive にアップロードして公開リンクを返す"""
    print(f"Google Drive アップロード中: {out_path.name}...")
    subprocess.run(["rclone", "copy", str(out_path), "gdrive:TZI/outputs/"],
                   check=False)
    result = subprocess.run(
        ["rclone", "link", f"gdrive:TZI/outputs/{out_path.name}"],
        capture_output=True, text=True)
    link = result.stdout.strip()
    m = re.search(r'id=([\w-]+)', link)
    if m:
        fid = m.group(1)
        token_raw = subprocess.run(
            ["rclone", "config", "dump"], capture_output=True, text=True).stdout
        import json as _j
        cfg = _j.loads(token_raw)
        tok = _j.loads(cfg.get("gdrive", {}).get("token", "{}"))
        access_token = tok.get("access_token", "")
        if access_token:
            subprocess.run([
                "curl", "-s", "-X", "POST",
                f"https://www.googleapis.com/drive/v3/files/{fid}/permissions",
                "-H", f"Authorization: Bearer {access_token}",
                "-H", "Content-Type: application/json",
                "-d", '{"role":"reader","type":"anyone"}'
            ], capture_output=True)
            return f"https://drive.google.com/file/d/{fid}/view?usp=sharing"
    return link


# ──────────────────────────────────────────────────────────────
def process_segment(video_path, start_min, dur_min, fps,
                    anchors, label, out_path,
                    pose_estimator=None, tracker=None, model=None):

    if model is None:
        model = YOLO(str(Path(__file__).parent / MODEL_NAME))
    if tracker is None:
        tracker = make_botsort(fps, use_reid=USE_REID)

    start_f = int(fps * start_min * 60)
    end_f   = start_f + int(fps * dur_min * 60)
    sample  = max(1, int(fps / FPS_OUT))

    cap = cv2.VideoCapture(str(video_path))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_f)

    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-f", "rawvideo", "-vcodec", "rawvideo",
         "-s", f"{W_OUT}x{H_OUT}", "-pix_fmt", "bgr24",
         "-r", str(FPS_OUT), "-i", "pipe:0",
         "-c:v", "libx264", "-preset", "fast", "-crf", "20",
         "-pix_fmt", "yuv420p", str(out_path)],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    seg_end_min = start_min + dur_min
    seg_anchors = sorted(
        [a for a in anchors
         if start_min - ANCHOR_TOL_MIN <= a["time_min"] <= seg_end_min + ANCHOR_TOL_MIN],
        key=lambda a: a["time_min"]
    )

    haru_id     = None
    haru_pos    = None
    haru_lost_t = None
    trail       = []
    warps       = 0
    tracked_f   = 0
    total_out_f = 0
    prev_t      = None
    used_anchors = set()
    tracks      = []
    pose_data   = {}  # frame → {angle, conf}

    t0 = time.time()
    print(f"  [{label}] 開始 {start_min:.0f}-{start_min+dur_min:.0f}min "
          f"imgsz={IMGSZ} N={EVERY_N} Re-ID={USE_REID} Pose={USE_POSE and pose_estimator is not None}")

    fn = start_f
    while fn < end_f:
        ret, frame = cap.read()
        if not ret:
            break

        t_sec = fn / fps
        t_min = t_sec / 60

        # ── YOLO + BoT-SORT ──────────────────────────────────
        if (fn - start_f) % EVERY_N == 0:
            results = model(frame, classes=[0], imgsz=IMGSZ,
                            conf=CONF, verbose=False, device=DEVICE)
            boxes = results[0].boxes
            if boxes is not None and len(boxes) > 0:
                dets = np.hstack([
                    boxes.xyxy.cpu().numpy(),
                    boxes.conf.cpu().numpy().reshape(-1,1),
                    boxes.cls.cpu().numpy().reshape(-1,1),
                ])
                tracks = tracker.update(dets, frame)
            else:
                tracks = tracker.update(np.empty((0,6)), frame)

            # ── アンカー確認 (ロスト時のみ) ──────────────────
            is_lost = (haru_id is None or
                       (haru_lost_t is not None and
                        t_sec - haru_lost_t > LOST_THRESH))
            if is_lost:
                for ai, anc in enumerate(seg_anchors):
                    if ai in used_anchors:
                        continue
                    if abs(anc["time_min"] - t_min) < ANCHOR_TOL_MIN / 4:
                        best_tid, best_d = None, 1e9
                        for tr in tracks:
                            fx, fy = p2f((tr[0]+tr[2])/2, tr[3])
                            d = ((fx-anc["fx"])**2+(fy-anc["fy"])**2)**0.5
                            if d < best_d:
                                best_d, best_tid = d, int(tr[4])
                        if best_tid is not None and best_d < 8.0:
                            haru_id = best_tid
                            haru_pos = (anc["fx"], anc["fy"])
                            haru_lost_t = t_sec
                            used_anchors.add(ai)

            # ── #6 特定 ──────────────────────────────────────
            haru_det = next((tr for tr in tracks if int(tr[4]) == haru_id), None)

            # 位置ベース再バインド (ロスト + アンカーなし)
            if haru_det is None and haru_pos is not None and is_lost and len(tracks) > 0:
                best_tid, best_d = None, 1e9
                for tr in tracks:
                    fx, fy = p2f((tr[0]+tr[2])/2, tr[3])
                    d = ((fx-haru_pos[0])**2+(fy-haru_pos[1])**2)**0.5
                    if d < best_d:
                        best_d, best_tid = d, int(tr[4])
                if best_tid is not None and best_d < REBIND_DIST_M:
                    haru_id  = best_tid
                    haru_det = next((tr for tr in tracks if int(tr[4]) == haru_id), None)

            if haru_det is not None:
                x1,y1,x2,y2 = map(int, haru_det[:4])
                fx, fy = p2f((x1+x2)/2, y2)
                if haru_pos is not None and prev_t is not None:
                    d = ((fx-haru_pos[0])**2+(fy-haru_pos[1])**2)**0.5
                    if d > WARP_THRESH_M:
                        warps += 1
                haru_pos    = (fx, fy)
                haru_lost_t = t_sec
                prev_t      = t_sec

                # ── RTMPose 体の向き推定 ──────────────────────
                if pose_estimator is not None and fn % 3 == 0:
                    try:
                        crop = frame[max(0,y1):y2+10, max(0,x1-5):x2+5]
                        if crop.shape[0] > 20 and crop.shape[1] > 10:
                            kps, scores = pose_estimator(crop)
                            if kps is not None and len(kps) > 0:
                                kp = kps[0]
                                # 左肩(5), 右肩(6), 左腰(11), 右腰(12)
                                if len(kp) >= 13:
                                    # 肩ベクトルから胴体向きを推定
                                    ls, rs = kp[5][:2], kp[6][:2]
                                    lh, rh = kp[11][:2], kp[12][:2]
                                    shoulder_vec = rs - ls
                                    hip_vec = rh - lh
                                    # 胴体の正面向き = 肩ベクトルの法線
                                    body_angle = np.degrees(
                                        np.arctan2(
                                            (shoulder_vec[1]+hip_vec[1])/2,
                                            (shoulder_vec[0]+hip_vec[0])/2
                                        )
                                    ) + 90
                                    pose_data[fn] = {
                                        "angle": float(body_angle % 360),
                                        "cx": (x1+x2)//2,
                                        "cy": (y1+y2)//2,
                                        "x1":x1,"y1":y1,"x2":x2,"y2":y2
                                    }
                    except Exception:
                        pass

        # ── 出力フレーム生成 ─────────────────────────────────
        if (fn - start_f) % sample == 0:
            vis = cv2.resize(frame, (W_OUT, H_OUT))
            sx  = W_OUT / frame.shape[1]
            sy  = H_OUT / frame.shape[0]
            total_out_f += 1

            # 全選手 (灰点)
            for tr in tracks:
                if int(tr[4]) != haru_id:
                    cv2.circle(vis,
                               (int(((tr[0]+tr[2])/2)*sx), int(((tr[1]+tr[3])/2)*sy)),
                               5, (80,80,80), 1)

            haru_det_vis = next((tr for tr in tracks if int(tr[4]) == haru_id), None)

            if haru_det_vis is not None:
                tracked_f += 1
                x1,y1,x2,y2 = [int(v*(sx if i%2==0 else sy))
                                for i,v in enumerate(haru_det_vis[:4])]
                px,py = (x1+x2)//2, (y1+y2)//2

                trail.append((px,py))
                if len(trail) > 30: trail.pop(0)
                for i in range(1, len(trail)):
                    a = i/len(trail)
                    cv2.line(vis, trail[i-1], trail[i],
                             (int(40*a), int(220*a), int(100*a)), 2)

                cv2.rectangle(vis, (x1,y1), (x2,y2), (0,255,120), 2)
                cv2.arrowedLine(vis, (px, y1-55), (px, y1-12),
                                (0,255,120), 3, tipLength=0.35)

                info = f"#6  ({haru_pos[0]:.0f},{haru_pos[1]:.0f})m"

                # 体の向き矢印
                if fn in pose_data:
                    pd = pose_data[fn]
                    angle_rad = np.radians(pd["angle"])
                    ex = int(px + 45*np.cos(angle_rad))
                    ey = int(py + 45*np.sin(angle_rad))
                    cv2.arrowedLine(vis, (px,py), (ex,ey),
                                    (255,210,0), 3, tipLength=0.3)
                    info += f"  ⬆{pd['angle']:.0f}°"

                cv2.putText(vis, info, (x1, y1-14), FONT, 0.65, (0,255,120), 2)

            elif haru_pos is not None and trail:
                lx, ly = trail[-1]
                for ag in range(0,360,25):
                    a = np.radians(ag)
                    cv2.circle(vis, (int(lx+22*np.cos(a)), int(ly+22*np.sin(a))),
                               2, (0,160,70), -1)
                cv2.arrowedLine(vis, (lx,ly-58), (lx,ly-26),
                                (0,160,70), 2, tipLength=0.4)
                cv2.putText(vis,
                            f"#6 LOST ({haru_pos[0]:.0f},{haru_pos[1]:.0f})m",
                            (lx-50, ly-60), FONT, 0.52, (0,160,70), 1)

            cov = tracked_f / max(total_out_f,1) * 100
            cv2.rectangle(vis, (0,0), (W_OUT,44), (0,0,0), -1)
            cv2.putText(vis,
                        f"[{label}]  t={t_sec/60:.2f}min  "
                        f"#6={'OK' if haru_det_vis is not None else 'LOST'}  "
                        f"cov={cov:.0f}%  warps={warps}",
                        (8,30), FONT, 0.62, (0,255,120), 2)

            proc.stdin.write(vis.tobytes())

        fn += 1
        elapsed = fn - start_f
        total   = end_f - start_f
        if elapsed % int(fps*60) == 0 and elapsed > 0:
            cov = tracked_f / max(total_out_f,1) * 100
            print(f"    {elapsed/total*100:.0f}% ({elapsed/fps:.0f}s)"
                  f"  cov={cov:.0f}%  warps={warps}  {time.time()-t0:.0f}s経過")

    cap.release()
    proc.stdin.close()
    proc.wait()

    cov = tracked_f / max(total_out_f,1) * 100
    print(f"  [{label}] 完了: cov={cov:.0f}%  warps={warps}")
    return warps, cov


# ──────────────────────────────────────────────────────────────
def concat_videos(paths, out_path):
    lst = OUTPUT_DIR / "_concat.txt"
    with open(lst,"w") as f:
        for p in paths: f.write(f"file '{p.resolve()}'\n")
    subprocess.run(
        ["ffmpeg","-y","-f","concat","-safe","0",
         "-i",str(lst),"-c","copy",str(out_path)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    lst.unlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--half",     type=int,   default=1, choices=[1,2])
    parser.add_argument("--start",    type=float, default=0.0)
    parser.add_argument("--dur",      type=float, default=5.0)
    parser.add_argument("--combined", action="store_true",
                        help="H1 0-5min + H2 10-15min を1本に結合")
    parser.add_argument("--full",     action="store_true",
                        help="前半+後半 各45分フル処理")
    parser.add_argument("--no-pose",  action="store_true")
    parser.add_argument("--no-reid",  action="store_true")
    args = parser.parse_args()

    global USE_POSE, USE_REID
    if args.no_pose: USE_POSE = False
    if args.no_reid: USE_REID = False

    cap_tmp = cv2.VideoCapture(str(VIDEO_H1))
    fps = cap_tmp.get(cv2.CAP_PROP_FPS) or 30.0
    cap_tmp.release()

    anchors = load_anchor()

    # RTMPose 初期化
    pose_estimator = None
    if USE_POSE:
        try:
            from rtmlib import Body
            pose_estimator = Body(
                pose='rtmpose-m',
                to_openpose=False,
                backend='onnxruntime',
                device='cuda'
            )
            print("RTMPose-m (CUDA) loaded")
        except Exception as e:
            print(f"RTMPose skip: {e}")

    # YOLO + トラッカー (セグメント間でリセット)
    t_total = time.time()

    if args.full:
        segs = [
            (VIDEO_H1, 0.0,  45.0, "H1 前半全体",
             OUTPUT_DIR / "gpu_h1_full.mp4"),
            (VIDEO_H2, 0.0,  45.0, "H2 後半全体",
             OUTPUT_DIR / "gpu_h2_full.mp4"),
        ]
        out_path = OUTPUT_DIR / "gpu_full_match.mp4"
    elif args.combined:
        segs = [
            (VIDEO_H1, 0.0,  5.0, "H1 00:00-05:00",
             OUTPUT_DIR / "gpu_seg_h1.mp4"),
            (VIDEO_H2, 10.0, 5.0, "H2 10:00-15:00",
             OUTPUT_DIR / "gpu_seg_h2.mp4"),
        ]
        out_path = OUTPUT_DIR / "gpu_combined_overlay.mp4"
    else:
        video = VIDEO_H1 if args.half == 1 else VIDEO_H2
        out_path = OUTPUT_DIR / f"gpu_h{args.half}_{int(args.start)}to{int(args.start+args.dur)}.mp4"
        segs = [(video, args.start, args.dur,
                 f"H{args.half} {args.start:.0f}-{args.start+args.dur:.0f}min",
                 out_path)]

    seg_paths = []
    for vid, st, dur, lbl, seg_out in segs:
        w, c = process_segment(vid, st, dur, fps, anchors,
                               lbl, seg_out, pose_estimator)
        seg_paths.append(seg_out)

    if len(seg_paths) > 1:
        print("ffmpeg concat 中...")
        concat_videos(seg_paths, out_path)

    size_mb = out_path.stat().st_size / 1e6
    elapsed_min = (time.time()-t_total)/60
    print(f"\n{'='*55}")
    print(f"完成: {out_path.name}  ({size_mb:.1f} MB)")
    print(f"総処理時間: {elapsed_min:.1f}分")

    link = upload_gdrive(out_path)
    if link:
        print(f"\nGoogle Drive リンク:\n  {link}")


if __name__ == "__main__":
    main()
