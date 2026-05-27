#!/usr/bin/env python3
"""
診断2: YOLOv8n を imgsz=1280 (高解像度) + 調整済みByteTrack で連続追跡。
小物体検出の改善でtracklet持続が伸びるかを検証。30秒分。
"""
import cv2
import numpy as np
from collections import defaultdict
from ultralytics import YOLO
from config import VIDEO_H1

model = YOLO("yolov8n.pt")
cap = cv2.VideoCapture(str(VIDEO_H1))
fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

DURATION_SEC = 30
end_f = int(fps * DURATION_SEC)
IMGSZ = 1280

track_frames = defaultdict(list)
f = 0
print(f"診断2: imgsz={IMGSZ} + bytetrack_hi.yaml ({DURATION_SEC}秒連続)...")
while f < end_f:
    ret, frame = cap.read()
    if not ret:
        break
    results = model.track(frame, persist=True, classes=[0], imgsz=IMGSZ,
                          conf=0.20, verbose=False, tracker="bytetrack_hi.yaml")
    if results[0].boxes is not None and results[0].boxes.id is not None:
        ids = results[0].boxes.id.cpu().numpy().astype(int)
        for tid in ids:
            track_frames[int(tid)].append(f)
    f += 1
    if f % 150 == 0:
        ndet = len(results[0].boxes) if results[0].boxes is not None else 0
        print(f"  {f/fps:.0f}s, {len(track_frames)} IDs, {ndet} det/frame")

cap.release()

durations = []
for tid, frames in track_frames.items():
    span = (max(frames) - min(frames)) / fps
    cov = len(frames) / max(max(frames) - min(frames) + 1, 1)
    durations.append((tid, span, len(frames), cov))
durations.sort(key=lambda x: -x[1])

print(f"\n=== 結果 (imgsz={IMGSZ}, {DURATION_SEC}秒) ===")
print(f"総ユニークID数: {len(track_frames)}")
print(f"全期間({DURATION_SEC}s)持続: {len([d for d in durations if d[1] >= DURATION_SEC*0.9])}")
print(f"20秒以上持続: {len([d for d in durations if d[1] >= 20])}")
print(f"10秒以上持続: {len([d for d in durations if d[1] >= 10])}")
print(f"\n上位15トラック:")
for tid, span, nf, cov in durations[:15]:
    print(f"  ID={tid:4d}  span={span:5.1f}s  frames={nf:4d}  cov={cov:.2f}")
