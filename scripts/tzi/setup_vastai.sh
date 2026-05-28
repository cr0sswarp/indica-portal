#!/bin/bash
# =============================================================
# TZI Vast.ai セットアップスクリプト
# Vast.ai の PyTorch テンプレートインスタンスで実行
# 使い方: bash setup_vastai.sh
# =============================================================
set -e

echo "=== TZI GPU セットアップ開始 ==="

# ── 1. システム依存 ──────────────────────────────────────────
apt-get update -q && apt-get install -y -q \
    rclone git curl wget unzip ffmpeg \
    python3-pip python3-dev build-essential \
    libgl1-mesa-glx libglib2.0-0

# ── 2. Python パッケージ ─────────────────────────────────────
pip install -q --upgrade pip

pip install -q \
    ultralytics \
    boxmot \
    rtmlib \
    onnxruntime-gpu \
    opencv-python \
    numpy scipy matplotlib \
    rich lap

# filterpy (boxmot依存 / wheel問題回避)
cd /tmp && git clone --depth 1 https://github.com/rlabbe/filterpy.git 2>/dev/null || true
SITE=$(python3 -c "import site; print(site.getsitepackages()[0])")
[ -d /tmp/filterpy/filterpy ] && cp -r /tmp/filterpy/filterpy $SITE/
python3 -c "import filterpy" 2>/dev/null && echo "filterpy OK" || echo "filterpy skip"

# ── 3. リポジトリ取得 ────────────────────────────────────────
cd /workspace
if [ ! -d "indica-portal" ]; then
    git clone https://github.com/cr0sswarp/indica-portal.git
fi
cd indica-portal
git pull origin claude/sleepy-albattani-nCXmu || git pull origin main

# ── 4. rclone 設定 ───────────────────────────────────────────
echo ""
echo "=== rclone Google Drive 設定 ==="
echo "次のステップで Google Drive を設定します:"
echo "  rclone config"
echo "  → n (新規) → gdrive → drive → [ブラウザ認証]"
echo ""
echo "設定済みの場合は以下で確認:"
echo "  rclone listremotes"
echo ""

# ── 5. モデル事前ダウンロード ────────────────────────────────
cd /workspace/indica-portal/scripts/tzi
python3 -c "
from ultralytics import YOLO
YOLO('yolov8m.pt')
print('yolov8m.pt OK')
YOLO('yolov8n.pt')
print('yolov8n.pt OK')
"

# ── 6. 動画ダウンロード ──────────────────────────────────────
echo ""
echo "=== 動画ファイルのダウンロード ==="
echo "rclone が設定済みなら以下を実行:"
echo "  cd /workspace/indica-portal"
echo "  bash scripts/download_videos.sh"
echo ""

echo "=== セットアップ完了 ==="
echo ""
echo "実行コマンド:"
echo "  cd /workspace/indica-portal/scripts/tzi"
echo "  python3 tzi_pipeline_gpu.py --combined"
echo "  python3 tzi_pipeline_gpu.py --half 1 --start 0 --dur 45  # 前半全体"
