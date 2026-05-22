# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 📍 Project Overview

**VALIENTE Portal** - INDICA LABSのマルチ機能ポータルプロジェクト。HTML ポータルサイト + Claude APIを活用した自動化スクリプトで構成。

- **メインサイト**: `index.html` - スキル、リンク、クラウド自動化、Claude ワークスペースへのアクセス
- **自動化ワークフロー**: GitHub Actions で定期実行される Notion × Claude 統合スクリプト
- **スキルセット**: Cowork コミュニティ向けの `.skill` ファイル

## 🏗️ Architecture

### ファイル構成

```
.
├── index.html              # メインポータルページ（HTML/CSS）
├── scripts/                # Python自動化スクリプト
│   ├── daily_loop_stock.py  # 株価予想ループ（毎日 3:03 JST）
│   └── nakajima.py         # メルマガ要約・PDF生成（毎週水曜 8:36 JST）
├── .github/workflows/      # GitHub Actions ワークフロー
│   ├── daily-loop-stock.yml
│   └── nakajima.yml
├── skills/                 # Cowork スキルファイル (.skill)
├── schedules/              # スケジュール定義
└── images/                 # ポータル用画像（背景など）
```

### データフロー

**daily_loop_stock.py:**
- Notion → 株価コンテキスト読み込み
- Claude Sonnet → 自己学習型分析実行
- Notion ← 分析結果保存（追記）

**nakajima.py:**
- Gmail (IMAP) → 最新メルマガ取得
- Claude Sonnet → 要約生成
- ReportLab → PDF生成
- Notion ← 結果保存（オプション）
- GitHub Artifacts ← PDF アップロード

## ⚙️ セットアップ

### 1. ローカル環境変数設定

```bash
# .env または .env.local を作成（git管理外）
export ANTHROPIC_API_KEY="sk-..."
export NOTION_TOKEN="secret_..."
export NOTION_PAGE_ID="35680324ec93812ab3c1fe4eb4eac3f5"
export GMAIL_ADDRESS="makino@indicalab.jp"
export GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"  # Google アプリパスワード
export NOTION_NAKAJIMA_PAGE_ID="..."
```

### 2. GitHub Secrets 設定

リポジトリの **Settings → Secrets and variables → Actions** に登録:
- `ANTHROPIC_API_KEY`
- `NOTION_TOKEN`
- `NOTION_PAGE_ID`
- `GMAIL_ADDRESS`
- `GMAIL_APP_PASSWORD`
- `NOTION_NAKAJIMA_PAGE_ID`

### 3. Python依存関係

```bash
pip install anthropic notion-client requests reportlab
# 日本語フォント（Linuxの場合）
sudo apt-get install -y fonts-noto-cjk
```

### 4. Gmail アプリパスワード生成

1. https://myaccount.google.com/apppasswords にアクセス
2. 2段階認証が有効なGoogleアカウントでサインイン
3. アプリを選択 → 「その他（カスタム名）」で「GitHub Actions」など入力
4. 生成されたパスワード（16文字）をコピー

## 📝 よく使うコマンド

### ローカルで daily_loop_stock を実行（テスト）

```bash
# 環境変数を読み込んで実行
source .env && python scripts/daily_loop_stock.py
```

### ローカルで nakajima を実行（テスト）

```bash
source .env && python scripts/nakajima.py
# → output/nakajima_YYYY-MM-DD_HH-MM-SS.pdf が生成される
```

### 手動でワークフローをトリガー

GitHub の **Actions** タブで各ワークフローを選択 → **Run workflow** → 実行

### リポジトリ内でコマンド実行テスト

```bash
# 環境変数を .env に記述してから以下で確認
python -c "import os; print(os.environ.get('ANTHROPIC_API_KEY', 'NOT SET'))"
```

## 🔧 開発ワークフロー

### スクリプト追加時の手順

1. **scripts/に新規スクリプト作成**
   - 先頭にDocstring: 目的・入出力
   - 環境変数は `os.environ["KEY"]` で取得
   - 例外処理を含める（外部API呼び出し時）

2. **ワークフロー作成 (.github/workflows/xxx.yml)**
   - 環境変数を `env:` セクションに指定
   - Secrets参照: `${{ secrets.SECRET_NAME }}`
   - 実行時刻を `on.schedule.cron` で定義（UTC）

3. **CLAUDE.md を更新**
   - 新しい Secrets を記載
   - スケジュール情報を追加

### ポータル更新時

- `index.html` を編集
- スキルカードやセクションを追加可能（セマンティックHTML + インラインCSS）
- Base64 埋め込み版スキルは `skills/valiente-portal-v3.skill` 参照

## 📌 Notion連携について

- **Notion Integration**: 
  - https://www.notion.so/my-integrations で作成
  - トークンを `NOTION_TOKEN` に設定
  - ページIDは URL末尾の32文字（ダッシュ除去）
  
- **ページの権限設定**:
  - Notion ページで **共有** → Integration を追加して **編集権限** 付与
  - 権限がないと append に失敗

## 🚀 本番デプロイ

このプロジェクトはGitHub Actions で完全自動実行。以下の場合に自動トリガー:
- `daily-loop-stock.yml`: 毎日 3:03 JST
- `nakajima.yml`: 毎週水曜 8:36 JST

### ワークフロー無効化

`.github/workflows/xxx.yml` の `on:` を削除またはコメントアウト → コミット

### スケジュール変更

cron 式を編集（[crontab.guru](https://crontab.guru/) で検証）
- 形式: `"分 時 日 月 曜"`
- タイムゾーン: UTC（JST = UTC + 9）

## ⚡ 新しい端末でのセットアップ手順

### 基本セットアップ

新しい環境で開発を開始する場合:

```bash
# 1. リポジトリをクローン
git clone https://github.com/cr0sswarp/indica-portal
cd indica-portal

# 2. Python依存関係をインストール
pip install anthropic notion-client requests reportlab

# 3. 環境変数を設定（セキュアに）
# .env ファイルを作成して必要な環境変数を設定
# または GitHub Secrets から環境変数をエクスポート

# 4. ローカルテスト実行
source .env && python scripts/daily_loop_stock.py

# 5. Claude Code で開発開始
claude
```

### TZI 動画分析ツールのセットアップ

動画ファイルが必要な場合:

#### Step 1: rclone のインストール

```bash
# macOS
brew install rclone

# Linux
sudo apt-get install -y rclone

# その他
# https://rclone.org/install/ を参照
```

#### Step 2: Google Drive 認証設定

```bash
rclone config
# 対話的に以下を設定:
# - n (新規リモートを作成)
# - Name: gdrive
# - Storage: drive (Google Drive)
# - 画面の指示に従ってブラウザで認証を完了
```

#### Step 3: TZI フォルダ構成を Google Drive に作成

このリポジトリオーナー（makino@indicalab.jp）が以下の構成を準備:

```
TZI/
└── videos/
    ├── 26_03_25_前半.mp4
    └── 26_03_25_後半.mp4
```

（または以下でローカルから手動アップロード:）

```bash
# ~/Library/Mobile Documents/com~apple~CloudDocs/Documents/Claude/Projects/優先順位付けのための/videos/
# のファイルを Google Drive の TZI/videos/ にアップロード
```

#### Step 4: 動画ダウンロード

すべてのセットアップ後、以下の 1 コマンドで動画をダウンロード:

```bash
bash scripts/download_videos.sh
# → videos/ フォルダに自動ダウンロードされます
```

**検証:**

```bash
ls -la videos/
# 26_03_25_前半.mp4
# 26_03_25_後半.mp4
# などが表示されれば成功
```

#### トラブルシューティング

**rclone: command not found**
```bash
# インストール再確認
brew install rclone  # macOS
sudo apt-get install rclone  # Linux
```

**リモート 'gdrive' が見つからない**
```bash
# rclone config で gdrive リモートを設定
rclone config
# または既存設定を確認:
rclone listremotes
```

**権限エラー (403 Forbidden)**
```bash
# Google Drive 上のファイルにアクセス権があるか確認
# TZI フォルダの共有設定を確認
# rclone の認証をリセット:
rclone config delete gdrive
rclone config  # 再設定
```

## 📚 関連リソース

- [Anthropic API Documentation](https://docs.anthropic.com)
- [Notion API Reference](https://developers.notion.com)
- [GitHub Actions Documentation](https://docs.github.com/actions)
- [ReportLab Documentation](https://www.reportlab.com/docs/reportlab-userguide.pdf)
