# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## 🏛️ 財団設立ビジョン（Foundation Vision）

**INDICA LABS Foundation** — テクノロジーと人間のクリエイティビティが共存する社会基盤の構築

### 代表プロフィール（牧野氏）
- **所属**: INDICA LABS（インディカラボ）
- **ルーツ**: Aperio Technologies（デジタルパソロジー領域）のCTO・Ole氏の下で働いた創業者Stevenと牧野氏の関係から生まれた会社
- **DNA**: PayPal Mafia的な「実行速度・グローバル視点・スケールへの執念」
- **使命**: 財団設立を通じた社会的レガシーの構築 + AI-Native組織の実証

### 財団設立の3つの柱
1. **テクノロジー民主化**: AIツールを誰もが使えるインフラ整備
2. **クリエイター支援**: 創造的な仕事に集中できる環境の提供
3. **グローバルコミュニティ**: Coworkのような知識共有エコシステムの拡大

### 牧野氏の「クリエイティブ時間」を守る原則
> 低抽象度の案件処理は全てCXOエージェントに委譲。牧野氏に来るのは「判断と指示」だけ。

### ✅ クローズ済み案件（CXOエージェントは再度フラグを立てないこと）

| 日付 | 案件 | 理由 | 指示者 |
|---|---|---|---|
| 2026-05-28 | Indica Labs Japan の**合同会社化** | 不要。G-P EOR継続。バロンデオロは既に株式会社化済み。 | Sevak（Indica Labs CFO） |

---

## 🤖 CXO Sub-Agent System（AI-Native Executive Team）

### 概念
1つのチャットで `COO` に指示を出すと、関連するCXOエージェントが並列稼働し、統合レポートを返す。

### CXOチーム構成（Archetype C: AI-Native Chief of Staff）

| エージェント | 役割 | 担当領域 |
|---|---|---|
| **COO/EA** | 指示受付・ルーティング・統合 | 全領域の調整・代表フィルタリング |
| **CFO** 💰 | 財務・投資・財団拠出 | 予算・キャッシュ・投資リターン |
| **CMO** 📡 | ビジョン・コミュニケーション | PR・ブランド・ステークホルダー |
| **CTO** ⚙️ | 技術・自動化・AI基盤 | Claude API・GitHub Actions・MCP |
| **CLO** ⚖️ | 法務・財団設立・コンプライアンス | 定款・評議員会・主務官庁認定 |
| **CPO** 🎯 | 人材・組織・採用 | COO/EAスカウト・AI-Nativeチーム |

### 使い方（Claude Code チャット内）

```bash
# CXOに一括指示
python scripts/cxo/dispatch.py "財団設立の現状確認と今週の優先アクションを教えてください"

# 特定ドメインに絞る場合
python -c "
from scripts.cxo.dispatch import dispatch, print_report
report = dispatch('COO/EAの採用基準を設計してください', target_agents=['CPO','CMO'])
print_report(report)
"
```

### COO採用基準スコアカード（Archetype C）
**必須**:
- AI tooling自主活用（Claude Code使いこなし）
- 英日バイリンガル（ビジネスレベル以上）
- 財団/NPO設立の法務理解またはネットワーク
- PayPal Mafia的「speed & scale」への共感

**加点**:
- Aperio / 医療AI / ライフサイエンス業界知識
- 日本の公益財団法人設立経験
- VC/エコシステムへの既存アクセス

---

## 🔄 自動化スケジュール（完全版）

| 時刻 | ワークフロー | 内容 |
|---|---|---|
| 毎日 7:00 JST | `daily-brief.yml` | Notion優先事項→HTML→メール送信 |
| 毎日 3:03 JST | `daily-loop-stock.yml` | 株価予想→Notion保存 |
| 毎週水 8:36 JST | `nakajima.yml` | メルマガ要約→PDF→Notion |

## ♻️ 推奨 /loop スキル（Claude Code セッション内）

セッション中に使えるループコマンド:

```
/loop 30m  → 30分ごとに「今日の残りタスク確認」を実行
/loop 1h   → 1時間ごとにCXO統合ブリーフ生成
```

**注意**: `/loop` はセッション中のみ有効。定期自動化はGitHub Actionsを使う。

---

## 💼 本業コンテキスト（Indica Labs Japan）

> ChatGPT / Gemini からの移行コンテキスト統合済み（2026-05-29）

### 役職・ミッション
- **Hideya Makino** | Director, Japan | Indica Labs
- **署名**: Hideya Makino, MS | Director, Japan | Indica Labs | makino@indicalab.com | +81-(0)3-4400-0466
- **ミッション**: HALO / HALO AI / HALO Link / HALO AP を日本の病理・医療画像解析領域の標準へ

### アクティブプロジェクト

| プロジェクト | 現状 | 次のアクション |
|---|---|---|
| **Japan市場拡大 / HALO suite** | 病院・研究機関・代理店向け説明継続中 | 経営層向け: TAT短縮・標準化・労働時間削減・診断ばらつき抑制で訴求 |
| **HALO Link / HALO AP ポジショニング** | HALO AP=臨床グレード/HL7/LIS、HALO Link=RUO/研究/GraphQL で整理済み | 顧客要件ごとにLink/APの線引きを明確化 |
| **Brain Atlas / AI画像解析** | sagittal対応・bounding box・複数動物処理の課題あり | 学術ニーズ×AI活用を5点に絞り商談資料化 |
| **Ogura-san採用** | ex-Hamamatsu Photonics、20年超のKOLネットワーク保有。Day-one title・Steven可視化・Adam承認が未決 | Adamへ: Senior IC役割・事業的必然性・Japan信用獲得効果を明確化して承認取得 |
| **Minori/Ando 人事再編** | MinoriはAPAC reseller支援20%振り分け案。AndoはApps Group配置方針 | EOR移管後にタイトル・職務定義整理。Adam/Haiying/Wangへの開示範囲を慎重に管理 |
| **Visualix/LBS/Roche チャネル戦略** | Visualix=LBS補完の戦略的パートナー候補。Leica代理店整理中 | LBSへ: Visualixの定量的メリット・販売コミット・既存代理店差別化を提案 |
| **録音→まとめ→資料化ワークフロー** | 出力形式固定済み | 録音来たら: ①文字起こし②200文字要約③スライド+3行コツ で一貫処理 |

### 未決事項（Pending Decisions）
1. Ogura-san を Day 1 から Senior title にするか
2. Ogura-san採用を Steven Hashagen へいつ可視化するか
3. Minori の APAC reseller支援への正式移管範囲
4. Minori課題を Wang へどこまで開示するか
5. Ando の Apps Group への正式移管範囲
6. HALO Link / HALO AP の RUO vs 臨床用途の顧客別表現方法
7. Visualix を LBS チャネルに追加するための定量メリット設計
8. Roche スキャナー前提案件での Leica/Hamamatsu/科研費活用の現実性
9. HALO Link perpetual/annual 混在のCRM運用方針
10. 長期データベース化の中心ツール選定（Gemini/NotebookLM/ChatGPT/Claude）

### 重要関係者

| 名前 | 役割 | 重要事項 |
|---|---|---|
| **Adam** | 上司・承認者 | Ogura-san採用・Japan strategy・人事タイトル・代理店戦略の最終承認者 |
| **Steven Hashagen** | Indica Labs CEO | Ogura-san採用・Japan market strategyの上位承認対象 |
| **Ogura-san** | 採用候補 / ex-Hamamatsu | KOLネットワーク×病理IT理解。once-in-a-career talent |
| **Minori** | Japan team | コミュニケーション・役割逸脱に課題。APAC reseller支援検討中 |
| **Ando** | 顧客対応 / Apps Group候補 | 顧客エンゲージメント・リカバリー力が高い。一次情報アクセス位置への配置推奨 |
| **Wang** | 関係者 | Minori関連。情報開示範囲を慎重に管理 |
| **Haiying** | APAC reseller支援 | Minori 20%稼働の受け皿候補 |
| **Visualix** | 戦略的パートナー候補 | HALO Link+HALO APパイプライン創出・LBS補完 |
| **Leica Biosystems / LBS** | 主要パートナー | HALO suite×スキャナー組み合わせ・代理店整理・annual推進 |
| **Roche** | 連携/競合 | uPath・navify・DP200/600・胃HER2・ADCモジュール文脈 |
| **藤井様** | 病院企画課 | 院長カンファレンスでHALO Link/AIの病院内メリット説明が必要 |

### 繰り返しルール（必ず守ること）
- **録音後の出力形式**: ①文字起こし → ②約200文字の一文要約 → ③スライドファイル形式 → 最後に3行でコツに気づける要点
- **病院経営層向け**: 専門用語を抑え、ROI・標準化・時間短縮・診断品質・人員不足対策で説明
- **HALO製品の整理**: HALO Link=研究/RUO/GraphQL/Study権限、HALO AP=臨床診断/HL7/FHIR/LIS/EMR
- **スキャナー予算の説得**: WSIスキャナーはコモディティ化→HALO suiteを同じ予算に入れるアービトラージ論法
- **メール文面**: 英日ともに丁寧・相手尊重・事業上の主張を明確に
- **採用・人事・代理店**: 感情論でなく事業価値・市場浸透・信頼獲得・売上貢献の論理で説明
- **AIツール役割分担**: Claude Code=戦略・自動化・永続コンテキスト管理（本リポジトリ）

---

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
│   ├── nakajima.py         # メルマガ要約・PDF生成（毎週水曜 8:36 JST）
│   ├── download_videos.sh  # Google Driveから動画をダウンロード
│   └── tzi/                # TZI動画分析スクリプト
│       ├── config.py       # 設定・定数
│       ├── extract_frame.py # フレーム確認
│       ├── check_all_anchors.py # アンカー確認
│       ├── generate_video.py # マークアップ動画生成
│       └── generate_heatmap.py # ヒートマップ生成
├── data/tzi/               # TZI分析結果
│   └── match_20260325/     # 2026-03-25 早稲田vs立教
│       ├── jersey6_trajectory.json  # #6選手の軌跡データ
│       ├── heatmap_jersey6_latest.png # ヒートマップ
│       ├── anchor_checks/ # アンカーポイント確認画像
│       └── ※動画は.gitignoreで除外
├── .claude/                # Claude Code 設定
│   └── settings.json       # セッションフック・パーミッション定義
├── .github/workflows/      # GitHub Actions ワークフロー
│   ├── daily-brief.yml     # 毎朝 7:00 JST 統合ブリーフメール ★NEW
│   ├── daily-loop-stock.yml
│   ├── nakajima.yml
│   └── foundation-weekly.yml # 毎週月曜 財団進捗レポート ★NEW
├── scripts/cxo/            # CXO Sub-Agent システム ★NEW
│   ├── __init__.py
│   └── dispatch.py         # COO→CXO並列ディスパッチ
├── skills/                 # Cowork スキルファイル (.skill)
├── videos/                 # rcloneでダウンロード済み動画
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

**TZI (Tactical Zone Intelligence) - 動画分析:**
- Google Drive → 試合映像ダウンロード（rclone経由）
- OpenCV → フレーム抽出・選手検出
- Homography → ピクセル座標 → フィールド座標に変換
- JSON → アンカーポイントによる位置確認
- ffmpeg → マークアップ動画生成
- matplotlib → ヒートマップ生成

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

### TZI動画分析（ローカルテスト）

```bash
# venvが未作成の場合（初回のみ）
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# scripts/tzi/ で実行
cd scripts/tzi

# 特定時刻のフレーム確認
python extract_frame.py 300 1H 30.9 52.1

# 全アンカー一括確認
python check_all_anchors.py

# ヒートマップ再生成（約30秒）
python generate_heatmap.py

# 90分マークアップ動画再生成（約7分）
python generate_video.py
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
