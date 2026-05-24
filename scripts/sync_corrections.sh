#!/bin/bash
# sync_corrections.sh
# Google Drive の TZI/corrections/ を同期し、テキストを JSON 化して適用
#
# 使い方:
#   bash scripts/sync_corrections.sh           # 同期のみ
#   bash scripts/sync_corrections.sh --apply   # 同期 + JSON化 + ground_truth 更新

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
CORR_DIR="$PROJECT_ROOT/data/tzi/corrections"
RCLONE_REMOTE="gdrive"
DRIVE_CORRECTIONS="TZI/corrections"

echo "=== 修正ファイル同期 ==="

if ! command -v rclone &> /dev/null; then
    echo "❌ rclone がインストールされていません"; exit 1
fi
if ! rclone listremotes | grep -q "^${RCLONE_REMOTE}:$"; then
    echo "❌ rclone リモート '${RCLONE_REMOTE}' が設定されていません"; exit 1
fi

mkdir -p "$CORR_DIR"

echo "📥 Drive (${RCLONE_REMOTE}:${DRIVE_CORRECTIONS}) → $CORR_DIR"
rclone sync "${RCLONE_REMOTE}:${DRIVE_CORRECTIONS}" "$CORR_DIR" \
    --include="*/corrections.txt" \
    --verbose

echo ""
echo "同期済み corrections.txt:"
find "$CORR_DIR" -name "corrections.txt" | sort | while read f; do
    lines=$(wc -l < "$f")
    echo "  ${f#$CORR_DIR/}  (${lines}行)"
done

if [[ "$1" == "--apply" ]]; then
    echo ""
    echo "=== テキスト → JSON 化 + 適用 ==="
    python3 "$SCRIPT_DIR/tzi/parse_corrections.py"
fi

echo ""
echo "✅ 完了"
