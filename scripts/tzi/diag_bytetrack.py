#!/usr/bin/env python3
"""
診断: ByteTrackを「連続フレーム」で正しく走らせ、tracklet持続を計測。
前回は6フレーム飛ばしで断片化した。今回は全フレーム連続で投入する。
60秒分のみ。track_idが何秒持続するかを測る。
"""
import cv2
import numpy as np
from collections import defaultdict
from ultralytics import YOLO
from config import VIDEO_H1

model = YOLO("yolov8n.pt")
cap = cv2.VideoCapture(str(VIDEO_H1))
fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

DURATION_SEC = 60
end_f = int(fps * DURATION_SEC)

track_frames = defaultdict(list)   # track_id → [frame_idx,...]
track_positions = defaultdict(list)  # track_id → [(px,py),...]

f = 0
print(f"ByteTrack連続フレーム診断 ({DURATION_SEC}秒, 全フレーム連続投入)...")
while f < end_f:
    ret, frame = cap.read()
    if not ret:
        break
    # 全フレーム連続でByteTrackに投入 (これが正しい使い方)
    results = model.track(frame, persist=True, classes=[0],
                          verbose=False, tracker="bytetrack.yaml")
    if results[0].boxes is not None and results[0].boxes.id is not None:
        ids = results[0].boxes.id.cpu().numpy().astype(int)
        boxes = results[0].boxes.xywh.cpu().numpy()
        for tid, box in zip(ids, boxes):
            track_frames[int(tid)].append(f)
            track_positions[int(tid)].append((float(box[0]), float(box[1])))
    f += 1
    if f % 300 == 0:
        print(f"  {f/fps:.0f}s processed, {len(track_frames)} unique IDs so far")

cap.release()

# 持続時間を計算 (最初の出現〜最後の出現)
durations = []
for tid, frames in track_frames.items():
    span = (max(frames) - min(frames)) / fps
    coverage = len(frames) / max(max(frames) - min(frames) + 1, 1)
    durations.append((tid, span, len(frames), coverage))

durations.sort(key=lambda x: -x[1])

print(f"\n=== 結果 ({DURATION_SEC}秒間) ===")
print(f"総ユニークID数: {len(track_frames)}")
long_tracks = [d for d in durations if d[1] >= 30]
print(f"30秒以上持続したtrack: {len(long_tracks)}")
print(f"10秒以上持続したtrack: {len([d for d in durations if d[1] >= 10])}")
print(f"\n上位15トラック (span=最初〜最後の秒数, frames=検出回数, cov=被覆率):")
for tid, span, nframes, cov in durations[:15]:
    print(f"  ID={tid:4d}  span={span:5.1f}s  frames={nframes:4d}  cov={cov:.2f}")
