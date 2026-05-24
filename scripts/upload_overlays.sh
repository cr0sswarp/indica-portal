#!/bin/bash
# upload_overlays.sh
# トラッキングオーバーレイ動画を Google Drive の TZI/overlays/ にアップロード
#
# 使い方:
#   bash scripts/upload_overlays.sh             # 全試合
#   bash scripts/upload_overlays.sh 20260325    # 特定試合のみ

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DATA_TZI="$PROJECT_ROOT/data/tzi"
RCLONE_REMOTE="gdrive"
DRIVE_OVERLAYS="TZI/overlays"

MATCH_LABELS=(
    "20260314:vs埼玉大_03-14"
    "20260316:vs岐阜協立_03-16"
    "20260317mid:vs中京U19_03-17"
    "20260317osaka:vs大阪学院_03-17"
    "20260318:vs作新学院_03-18"
    "20260325:vs立教大_03-25"
    "20260329:vs川崎U18_03-29"
    "20260405:vs獨協大_04-05"
)

echo "=== オーバーレイ動画を Drive にアップロード ==="

if ! command -v rclone &> /dev/null; then
    echo "❌ rclone がインストールされていません"
    exit 1
fi

if ! rclone listremotes | grep -q "^${RCLONE_REMOTE}:$"; then
    echo "❌ rclone リモート '${RCLONE_REMOTE}' が設定されていません"
    exit 1
fi

FILTER="$1"  # 引数で試合IDを絞り込み可能

for entry in "${MATCH_LABELS[@]}"; do
    match_id="${entry%%:*}"
    label="${entry##*:}"

    # 引数指定があれば絞り込み
    if [[ -n "$FILTER" && "$match_id" != "$FILTER" ]]; then
        continue
    fi

    src="$DATA_TZI/match_${match_id}/tracking_overlay.mp4"
    dst_name="overlay_${match_id}_${label}.mp4"
    dst="${RCLONE_REMOTE}:${DRIVE_OVERLAYS}/${dst_name}"

    if [[ ! -f "$src" ]]; then
        echo "  ⚠️  スキップ (動画なし): match_${match_id}"
        continue
    fi

    echo "  📤 $dst_name をアップロード中..."
    rclone copyto "$src" "$dst" --progress
    echo "  ✅ 完了: $dst_name"
done

echo ""
echo "=== Drive 上のオーバーレイ一覧 ==="
rclone ls "${RCLONE_REMOTE}:${DRIVE_OVERLAYS}" 2>/dev/null || echo "  (まだ空)"

echo ""
echo "✅ アップロード完了"
echo ""
echo "次のステップ:"
echo "  牧野羽瑠に以下を伝える:"
echo "  Drive > TZI > overlays > 各動画を確認"
echo "  Drive > TZI > corrections > 試合名フォルダ > corrections.txt に記入"
