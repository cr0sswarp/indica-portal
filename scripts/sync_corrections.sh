#!/bin/bash
# sync_corrections.sh
# Google Drive の TZI/corrections/ を data/tzi/corrections/ に同期する
#
# 使い方:
#   bash scripts/sync_corrections.sh          # 同期のみ
#   bash scripts/sync_corrections.sh --apply  # 同期後に apply_corrections.py も実行

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
CORR_DIR="$PROJECT_ROOT/data/tzi/corrections"
RCLONE_REMOTE="gdrive"
RCLONE_PATH="TZI/corrections"

echo "=== TZI 修正ファイル同期 ==="

if ! command -v rclone &> /dev/null; then
    echo "❌ rclone がインストールされていません"
    exit 1
fi

if ! rclone listremotes | grep -q "^${RCLONE_REMOTE}:$"; then
    echo "❌ rclone リモート '${RCLONE_REMOTE}' が設定されていません"
    exit 1
fi

mkdir -p "$CORR_DIR"

echo "📥 Drive (${RCLONE_REMOTE}:${RCLONE_PATH}) → ${CORR_DIR}"
rclone sync "${RCLONE_REMOTE}:${RCLONE_PATH}" "$CORR_DIR" \
    --include="corrections_*.json" \
    --verbose

echo ""
echo "同期済みファイル:"
ls -lh "$CORR_DIR"/corrections_*.json 2>/dev/null || echo "  (まだ修正ファイルなし)"

if [[ "$1" == "--apply" ]]; then
    echo ""
    echo "=== 修正を適用中 ==="
    python3 "$SCRIPT_DIR/tzi/apply_corrections.py"
fi

echo ""
echo "✅ 完了"
