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


TAGS_JSON = Path(__file__).parent / "tags.json"


def load_tags():
    """tags.json から {jersey_str: {bbox, frame_idx}} を返す。なければ空辞書。"""
    if TAGS_JSON.exists():
        return json.loads(TAGS_JSON.read_text())
    return {}


def init_tag_map(tracker, model, video_path, tags: dict,
                 start_sec: float = 0.0) -> tuple:
    """
    セグメント開始フレームでYOLO検出し、タグbboxに最近傍のtrack_idを紐付ける。
    H2など途中開始セグメントはstart_secで実際の開始位置を指定する。
    戻り値: (tag_map {track_id: jersey}, init_pos {jersey: (fx,fy)})
    """
    if not tags:
        return {}, {}

    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    # タグ初期化はセグメント開始フレームで行う
    frame_idx = max(0, int(fps * start_sec))
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        return {}, {}

    results = model(frame, classes=[0], imgsz=IMGSZ, conf=CONF,
                    verbose=False, device=DEVICE)
    boxes = results[0].boxes
    if boxes is None or len(boxes) == 0:
        return {}, {}
    dets = np.hstack([
        boxes.xyxy.cpu().numpy(),
        boxes.conf.cpu().numpy().reshape(-1, 1),
        boxes.cls.cpu().numpy().reshape(-1, 1),
    ])
    tracks = tracker.update(dets, frame)

    tag_map  = {}
    init_pos = {}
    for jersey, info in tags.items():
        tx1, ty1, tx2, ty2 = info["bbox"]
        tcx, tcy = (tx1+tx2)/2, (ty1+ty2)/2
        best_tid, best_d = None, 1e9
        for tr in tracks:
            cx, cy = (tr[0]+tr[2])/2, (tr[1]+tr[3])/2
            d = ((cx-tcx)**2+(cy-tcy)**2)**0.5
            if d < best_d:
                best_d, best_tid = d, int(tr[4])
        if best_tid is not None and best_d < 300:
            tag_map[best_tid] = jersey
            tr = next(t for t in tracks if int(t[4]) == best_tid)
            init_pos[jersey] = p2f((tr[0]+tr[2])/2, tr[3])
            print(f"  タグ初期化: #{jersey} → track_id={best_tid} (dist={best_d:.0f}px)")
    return tag_map, init_pos


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
                    tag_map, label, out_path,
                    init_pos=None,
                    pose_estimator=None, tracker=None, model=None):
    """
    tag_map:  {track_id(int): jersey_str} — 手動タグ初期化後のマッピング
    init_pos: {jersey_str: (fx,fy)} — セグメント開始時の選手フィールド座標
    タグの付いた全選手を追跡。track_idが消えた場合は近傍trackに再バインド。
    """
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

    # tag_map は {track_id: jersey_str}。セグメント中に更新される。
    live_map  = dict(tag_map)           # {track_id: jersey}
    last_pos  = dict(init_pos or {})    # {jersey: (fx,fy)} フィールド座標
    last_seen = {j: start_min*60 for j in (init_pos or {})}  # {jersey: t_sec}
    trails    = defaultdict(list)       # {jersey: [(px,py),...]}
    warps     = 0
    tracked_f = 0     # メインタグ選手(全員)で1フレームでも追跡できた数
    total_out_f = 0
    tracks    = []
    pose_data = {}    # frame → {jersey: {angle,...}}

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

            current_tids = {int(tr[4]) for tr in tracks}

            # ── 全タグ選手の位置更新 + 再バインド ────────────
            for tid, jersey in list(live_map.items()):
                tr = next((t for t in tracks if int(t[4]) == tid), None)
                if tr is not None:
                    x1,y1,x2,y2 = map(int, tr[:4])
                    fx, fy = p2f((x1+x2)/2, y2)
                    if jersey in last_pos:
                        d = ((fx-last_pos[jersey][0])**2+(fy-last_pos[jersey][1])**2)**0.5
                        if d > WARP_THRESH_M:
                            warps += 1
                    last_pos[jersey]  = (fx, fy)
                    last_seen[jersey] = t_sec

                    # RTMPose 体の向き推定
                    if pose_estimator is not None and fn % 3 == 0:
                        try:
                            crop = frame[max(0,y1):y2+10, max(0,x1-5):x2+5]
                            if crop.shape[0] > 20 and crop.shape[1] > 10:
                                kps, _ = pose_estimator(crop)
                                if kps is not None and len(kps) > 0:
                                    kp = kps[0]
                                    if len(kp) >= 13:
                                        ls, rs = kp[5][:2], kp[6][:2]
                                        lh, rh = kp[11][:2], kp[12][:2]
                                        sv = rs - ls; hv = rh - lh
                                        angle = np.degrees(np.arctan2(
                                            (sv[1]+hv[1])/2, (sv[0]+hv[0])/2)) + 90
                                        if fn not in pose_data:
                                            pose_data[fn] = {}
                                        pose_data[fn][jersey] = {
                                            "angle": float(angle % 360),
                                            "x1":x1,"y1":y1,"x2":x2,"y2":y2
                                        }
                        except Exception:
                            pass
                else:
                    # track_id 消失 → 位置ベース再バインド
                    lost_sec = t_sec - last_seen.get(jersey, 0)
                    if lost_sec > LOST_THRESH and jersey in last_pos:
                        lx, ly = last_pos[jersey]
                        untagged = [t for t in tracks
                                    if int(t[4]) not in live_map]
                        best_tid2, best_d2 = None, 1e9
                        for t in untagged:
                            fx, fy = p2f((t[0]+t[2])/2, t[3])
                            d = ((fx-lx)**2+(fy-ly)**2)**0.5
                            if d < best_d2:
                                best_d2, best_tid2 = d, int(t[4])
                        if best_tid2 is not None and best_d2 < REBIND_DIST_M:
                            del live_map[tid]
                            live_map[best_tid2] = jersey
                            print(f"  再バインド: #{jersey} tid={tid}→{best_tid2} "
                                  f"({best_d2:.1f}m)")

        # ── 出力フレーム生成 ─────────────────────────────────
        if (fn - start_f) % sample == 0:
            vis = cv2.resize(frame, (W_OUT, H_OUT))
            sx  = W_OUT / frame.shape[1]
            sy  = H_OUT / frame.shape[0]
            total_out_f += 1

            # タグなし選手 (灰点)
            tagged_tids = set(live_map.keys())
            for tr in tracks:
                if int(tr[4]) not in tagged_tids:
                    cv2.circle(vis,
                               (int(((tr[0]+tr[2])/2)*sx),
                                int(((tr[1]+tr[3])/2)*sy)),
                               4, (70,70,70), 1)

            # タグ付き選手を描画
            any_tracked = False
            COLORS = {"6":(0,255,120),"11":(0,180,255),"9":(255,160,0),
                      "7":(200,0,255),"3":(255,50,50),"5":(0,220,220)}
            for tid, jersey in live_map.items():
                col = COLORS.get(jersey, (200,200,200))
                tr = next((t for t in tracks if int(t[4]) == tid), None)
                if tr is not None:
                    any_tracked = True
                    x1,y1,x2,y2 = [int(v*(sx if i%2==0 else sy))
                                    for i,v in enumerate(tr[:4])]
                    px,py = (x1+x2)//2, (y1+y2)//2
                    trails[jersey].append((px,py))
                    if len(trails[jersey]) > 40:
                        trails[jersey].pop(0)
                    trail = trails[jersey]
                    for i in range(1, len(trail)):
                        a = i/len(trail)
                        cv2.line(vis, trail[i-1], trail[i],
                                 tuple(int(c*a) for c in col), 2)
                    cv2.rectangle(vis, (x1,y1), (x2,y2), col, 2)
                    pos = last_pos.get(jersey, (0,0))
                    info = f"#{jersey}  ({pos[0]:.0f},{pos[1]:.0f})m"
                    if fn in pose_data and jersey in pose_data[fn]:
                        pd = pose_data[fn][jersey]
                        ar = np.radians(pd["angle"])
                        ex = int(px + 45*np.cos(ar))
                        ey = int(py + 45*np.sin(ar))
                        cv2.arrowedLine(vis, (px,py), (ex,ey),
                                        (255,210,0), 2, tipLength=0.3)
                        info += f" {pd['angle']:.0f}°"
                    cv2.putText(vis, info, (x1, max(y1-6,14)),
                                FONT, 0.60, col, 2)
                else:
                    # LOST表示
                    trail = trails[jersey]
                    if trail:
                        lx,ly = trail[-1]
                        cv2.putText(vis, f"#{jersey} LOST",
                                    (lx-20, ly-28), FONT, 0.48, col, 1)

            if any_tracked:
                tracked_f += 1

            cov = tracked_f / max(total_out_f,1) * 100
            cv2.rectangle(vis, (0,0), (W_OUT,44), (0,0,0), -1)
            cv2.putText(vis,
                        f"[{label}]  t={t_sec/60:.2f}min  "
                        f"players={len(live_map)}  cov={cov:.0f}%  warps={warps}",
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
    parser.add_argument("--tags",     type=str, default=None,
                        help="tags.jsonのパス (tag_ui.pyで生成)")
    args = parser.parse_args()

    global USE_POSE, USE_REID
    if args.no_pose: USE_POSE = False
    if args.no_reid: USE_REID = False

    cap_tmp = cv2.VideoCapture(str(VIDEO_H1))
    fps = cap_tmp.get(cv2.CAP_PROP_FPS) or 30.0
    cap_tmp.release()

    # タグ読み込み (手動初期化)
    tags_path = Path(args.tags) if args.tags else TAGS_JSON
    tags = load_tags() if not args.tags else json.loads(tags_path.read_text())
    if tags:
        print(f"タグ読み込み: {list(tags.keys())} 選手")
    else:
        print("⚠️  tags.jsonなし — タグなしで実行 (アノテーションなし)")

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

    # YOLO モデル (タグ初期化に再使用)
    yolo_model = YOLO(str(Path(__file__).parent / MODEL_NAME))

    seg_paths = []
    for vid, st, dur, lbl, seg_out in segs:
        # セグメントごとに新規トラッカー + タグ初期化
        tracker = make_botsort(fps, use_reid=USE_REID)
        tag_map, init_pos = (
            init_tag_map(tracker, yolo_model, vid, tags, start_sec=st*60)
            if tags else ({}, {})
        )
        w, c = process_segment(vid, st, dur, fps, tag_map,
                               lbl, seg_out, init_pos=init_pos,
                               pose_estimator=pose_estimator,
                               tracker=tracker, model=yolo_model)
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
