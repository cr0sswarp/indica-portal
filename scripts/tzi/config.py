"""
TZI プロジェクト共通設定
すべてのスクリプトはここからパスをインポートする
"""
from pathlib import Path
import numpy as np
import cv2

# プロジェクトルート（このファイルの2つ上 = 優先順位付けのための/）
PROJECT_ROOT = Path(__file__).parent.parent.parent

# 動画パス
VIDEO_H1 = PROJECT_ROOT / "videos" / "26_03_25_前半.mp4"
VIDEO_H2 = PROJECT_ROOT / "videos" / "26_03_25_後半.mp4"

# データパス
MATCH_DIR   = PROJECT_ROOT / "TZI_prototype" / "match_20260325"
TRAJ_JSON   = MATCH_DIR / "jersey6_trajectory.json"
ANCHOR_DIR  = MATCH_DIR / "anchor_checks"
OUTPUT_DIR  = MATCH_DIR

# フィールドサイズ
FW, FH = 105.0, 68.0

# ホモグラフィー（このカメラアングルで固定）
SRC = np.float32([[20,90],[1255,88],[635,298],[635,705]])
DST = np.float32([[0,0],[105,0],[52.5,34],[52.5,68]])
H_MAT, _ = cv2.findHomography(SRC, DST, cv2.RANSAC, 3.0)

# 早稲田HSV色範囲（濃いマルーン）
W_LO1, W_HI1 = np.array([0,50,40]),   np.array([12,255,220])
W_LO2, W_HI2 = np.array([165,50,40]), np.array([180,255,220])
KNL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(5,5))

def p2f(px, py):
    """ピクセル座標 → フィールド座標（m）"""
    pt = np.array([[[float(px), float(py)]]], dtype=np.float32)
    r  = cv2.perspectiveTransform(pt, H_MAT)
    return float(np.clip(r[0][0][0],0,FW)), float(np.clip(r[0][0][1],0,FH))
