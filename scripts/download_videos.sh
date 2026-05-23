#!/bin/bash
#
# download_videos.sh
# TZI Google Drive から動画をダウンロード
#
# 使用方法:
#   bash scripts/download_videos.sh
#
# 要件:
#   - rclone がインストール済み
#   - rclone config で "gdrive" リモートが設定済み
#

set -e

# ────────────────────────────────────────────────────────
# 定数
# ────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
VIDEOS_DIR="$PROJECT_ROOT/videos"
RCLONE_REMOTE="gdrive"
RCLONE_PATH="TZI/videos"

# ────────────────────────────────────────────────────────
# функции
# ────────────────────────────────────────────────────────

log_info() {
    echo "ℹ️  $1"
}

log_success() {
    echo "✅ $1"
}

log_error() {
    echo "❌ $1" >&2
}

# ────────────────────────────────────────────────────────
# メイン処理
# ────────────────────────────────────────────────────────

main() {
    log_info "TZI 動画ダウンロード開始"

    # 1. rclone がインストール済みか確認
    if ! command -v rclone &> /dev/null; then
        log_error "rclone がインストールされていません"
        log_info "インストール方法:"
        log_info "  macOS:  brew install rclone"
        log_info "  Linux:  sudo apt-get install rclone"
        log_info "  その他: https://rclone.org/install/"
        exit 1
    fi

    # 2. rclone リモート設定が存在するか確認
    if ! rclone listremotes | grep -q "^${RCLONE_REMOTE}:$"; then
        log_error "rclone リモート '${RCLONE_REMOTE}' が設定されていません"
        log_info "セットアップ手順（ブラウザ不要・ヘッドレス認証）:"
        log_info "  bash scripts/setup_gdrive.sh"
        log_info ""
        log_info "  ※ rclone config 実行中に"
        log_info "     'Use web browser to authenticate? (Y/n)' は 'n' と答えること"
        log_info "     → URLが表示されるのでローカルのブラウザで開き、コードを貼り付ける"
        exit 1
    fi

    # 3. videos ディレクトリを作成
    mkdir -p "$VIDEOS_DIR"
    log_info "出力先: $VIDEOS_DIR"

    # 4. Google Drive から動画をダウンロード
    log_info "Google Drive (${RCLONE_REMOTE}:${RCLONE_PATH}) から動画をダウンロード中..."

    if rclone sync "${RCLONE_REMOTE}:${RCLONE_PATH}" "$VIDEOS_DIR" \
        --progress \
        --transfers=4 \
        --exclude=".*" \
        --exclude="*.tmp" \
        --verbose; then
        log_success "ダウンロード完了"
    else
        log_error "ダウンロードに失敗しました"
        exit 1
    fi

    # 5. ダウンロード結果を表示
    log_info "ダウンロード済みファイル:"
    if [ -d "$VIDEOS_DIR" ] && [ "$(ls -A "$VIDEOS_DIR")" ]; then
        ls -lh "$VIDEOS_DIR"
        log_success "すべての動画がダウンロードされました"
    else
        log_error "動画ファイルが見つかりません"
        exit 1
    fi
}

main "$@"
