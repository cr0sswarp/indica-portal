#!/bin/bash
#
# setup_gdrive.sh
# リモート環境（Claude Code Web / サーバー）向け Google Drive rclone 認証セットアップ
#
# ブラウザが開けない環境向けに、手動コード貼り付けフローを使う。
#
# 使用方法:
#   bash scripts/setup_gdrive.sh
#

set -e

REMOTE_NAME="gdrive"

log_info()    { echo "ℹ️  $1"; }
log_success() { echo "✅ $1"; }
log_error()   { echo "❌ $1" >&2; }
log_step()    { echo ""; echo "━━━ $1 ━━━"; }

# ────────────────────────────────────────────────────────
# Step 1: rclone インストール確認
# ────────────────────────────────────────────────────────
log_step "Step 1: rclone インストール確認"

if ! command -v rclone &> /dev/null; then
    log_info "rclone が見つかりません。インストールします..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        brew install rclone
    elif [[ -f /etc/debian_version ]]; then
        curl -s https://rclone.org/install.sh | sudo bash
    else
        log_error "自動インストールに対応していません。手動でインストールしてください:"
        log_error "  https://rclone.org/install/"
        exit 1
    fi
fi

log_success "rclone $(rclone version | head -1)"

# ────────────────────────────────────────────────────────
# Step 2: 既存設定の確認
# ────────────────────────────────────────────────────────
log_step "Step 2: 既存設定の確認"

if rclone listremotes 2>/dev/null | grep -q "^${REMOTE_NAME}:$"; then
    log_success "リモート '${REMOTE_NAME}' は既に設定されています"
    log_info "接続テスト中..."
    if rclone lsd "${REMOTE_NAME}:" --max-depth 1 2>/dev/null; then
        log_success "Google Drive への接続成功！"
        log_info "以下を実行して動画をダウンロードできます:"
        log_info "  bash scripts/download_videos.sh"
        exit 0
    else
        log_error "接続テスト失敗。再認証します..."
        rclone config delete "${REMOTE_NAME}" 2>/dev/null || true
    fi
fi

# ────────────────────────────────────────────────────────
# Step 3: ヘッドレス認証（ブラウザ不要フロー）
# ────────────────────────────────────────────────────────
log_step "Step 3: Google Drive 認証（ヘッドレスモード）"

cat << 'INSTRUCTIONS'

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  リモート環境での Google Drive 認証手順
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  この環境ではブラウザが開けないため、「手動コードフロー」を使います。

  以下の rclone config コマンドを実行し、質問には次のように答えてください:

  1. "n" → 新規リモート作成
  2. Name: gdrive
  3. Storage: "drive" と入力（または番号を選択）
  4. client_id: [Enter でスキップ]
  5. client_secret: [Enter でスキップ]
  6. scope: "1" (Full access)
  7. root_folder_id: [Enter でスキップ]
  8. service_account_file: [Enter でスキップ]
  9. Edit advanced config? "n"
  10. ★★★ Use web browser to authenticate? → "n" ← ここが重要！★★★
      → rclone が URL を表示します
  11. その URL をローカルの PC/スマホのブラウザで開く
  12. Google アカウントでログインして「許可」をクリック
  13. 画面に表示されるコード（verification code）をターミナルに貼り付ける
  14. Configure this as a Shared Drive? "n"
  15. "y" で保存

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

INSTRUCTIONS

log_info "準備ができたら Enter を押して rclone config を起動します..."
read -r

rclone config

# ────────────────────────────────────────────────────────
# Step 4: 設定確認
# ────────────────────────────────────────────────────────
log_step "Step 4: 設定確認"

if rclone listremotes 2>/dev/null | grep -q "^${REMOTE_NAME}:$"; then
    log_info "接続テスト中..."
    if rclone lsd "${REMOTE_NAME}:" --max-depth 1 2>/dev/null; then
        log_success "Google Drive 認証成功！"
        echo ""
        log_info "次のコマンドで動画をダウンロードできます:"
        echo "  bash scripts/download_videos.sh"
    else
        log_error "認証は完了しましたが接続テストに失敗しました"
        log_info "手動で確認してください: rclone lsd gdrive:"
    fi
else
    log_error "認証が完了しませんでした。もう一度試してください:"
    log_error "  bash scripts/setup_gdrive.sh"
fi
