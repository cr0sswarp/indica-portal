# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## ⚠️ 事実確認・反ハルシネーション原則（最重要・全タスク共通）

> このルールは他のすべてに優先する。牧野氏の信頼の基盤であり、セカンドブレイン（Notion/Obsidian）の価値を守る前提。

- **検証可能な事実（固有名詞・人物の経歴・所属・出身校・統計・日付・数値・製品仕様など）を述べる前に、必ず調査して裏を取る。記憶や推測だけで断定しない。**
- 特に誤りやすく必ず確認すべき対象:
  - サッカー選手の出身校・経歴・所属クラブ・代表選出（例: クラブと学校、現所属と過去所属の混同に注意）
  - 人物の役職・会社・連絡先
  - 製品仕様・日付・数値・市場データ
- **不確実な場合は「未確認」と明示する。** 確信が持てないまま事実として書かない。
- 外部事実は WebSearch 等で一次情報に近いソースを確認してから記載する。
- 一度誤った事実を出したら、**訂正を最優先し、何と混同したか原因を明示する。**
- セカンドブレインに保存する情報は牧野氏の長期的な判断材料になるため、誤情報の混入は重大な損害とみなす。

> **教訓ログ**:
> - 佐野海舟の出身校を「鹿島学園」と誤記（過去所属の鹿島アントラーズと混同）→ 正しくは**米子北高校**。固有名詞は必ず検索で裏取りすること。
> - 「T-MASC」と表記し定義を Technical/Mental/Athletic/Strategic/Creative と**捏造**→ 正しくは **T+MASC**（Ekkono＝エコノメソッドの実在スカウティング公式）で **Talent / Motor skills / Availability / Smartness / Commitment**。**もっともらしい略語の展開を勝手に埋めない**こと。
> - **英語ソースのみで結論を出す誤り**: エコノメソッド創始者を「Romagosa・Hernández の2名」と断じ「ジョアン・ヴィラは創始者でない」と書いたが、**日本語一次ソース（奈良クラブ／浜田満）では創始者は3名で Joan Vila を含む**と判明（現英語版公式が2名なのはVila離脱後のため）。→ **日本関連・人物史は日本語の一次ソースも必ず当たる**こと。英語圏で情報が削除/更新されていても、立ち上げ期の現地ソースに残っていることがある。ユーザー提供のソースは必ず精査する。

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
| 毎週月 02:00 JST | `tmasc-research.yml` | T+MASC/TIPS/JoanVila史実をWeb調査→Obsidian保存 |

## ♻️ 推奨 /loop スキル（Claude Code セッション内）

セッション中に使えるループコマンド:

```
/loop 30m  → 30分ごとに「今日の残りタスク確認」を実行
/loop 1h   → 1時間ごとにCXO統合ブリーフ生成
```

**注意**: `/loop` はセッション中のみ有効。定期自動化はGitHub Actionsを使う。

---

## 💼 本業コンテキスト（Indica Labs Japan）

> **機密情報取扱注意**: 顧客名・売上・PL・契約内容は外部サービスに送信しない。PE（恒久的施設）リスク回避のため対外資料の住所はAlbuquerque HQ。
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
| **Ogura-san採用** | Adam・Steven承認済み。年俸¥10M上限OK。要望への対応力確認済み | **6/10回答期限** → 受諾確認後Adamへ状況報告 |
| **Minori PIP** | 6/2 10:00 PIP通知面談（G-P同席）。最終版ドキュメント作成済み（Drive保存） | 月曜朝: みさきさんへ確認メール + Teams招待送信 |
| **Ando Apps Group移行** | 現時点未着手。来年確定予定 | 来年に向けてタイトル・職務定義整理 |
| **Visualix パートナーシップ** | 実質的営業パートナーとして既に稼働中。東大・阪大との共同研究提案中。福岡先生と協議詰め中 | 新潟県央基幹病院への直接訪問・ヒアリング実施 |
| **AetherAI競合対策（らくらくモード）** | 日野さんと共同開発中。ボタン1つで操作性大幅向上 | **6/6（来週中）完成・レビュー** |
| **モデル病院（新潟県央基幹病院）** | 400床。福岡先生指名。代理店経由では返事なし | 牧野さんが直接現場の先生にコンタクト・ヒアリング |
| **LBS/Danaherリスク管理** | ⚠️機密：Danaher傘下LBSへの吸収リスクあり | 今年いっぱいVisualix連携で独立維持。浜松ホトニクス軸にエコシステム強化 |
| **録音→まとめ→資料化ワークフロー** | 出力形式固定済み | 録音来たら: ①文字起こし②200文字要約③スライド+3行コツ で一貫処理 |

### 未決事項（Pending Decisions）
1. ~~Ogura-san Day 1 Senior title~~ → ✅ Adam・Steven承認済み（6/10回答待ち）
2. ~~Ogura-san Steven可視化~~ → ✅ Adam経由で共有済み
3. ~~Minori APAC 20%振り分け~~ → ✅ 削除。PIPに移行（6/2通知）
4. Minori課題を Wang へどこまで開示するか（CLO管轄）
5. Ando の Apps Group への正式移管範囲（来年）
6. HALO Link / HALO AP の RUO vs 臨床用途の顧客別表現方法
7. Visualix との正式契約形態の確定（現在は実質稼働中）
8. Roche スキャナー前提案件での Leica/Hamamatsu/科研費活用の現実性
9. HALO Link perpetual/annual 混在のCRM運用方針
10. 新潟県央基幹病院への直接訪問タイミング確定

### 直近To Do（2026-05-30 セッション記録）

| 期限 | アクション |
|---|---|
| **月曜朝（6/2）** | みさきさんへメール送信（PIP最終版確認依頼） |
| **月曜朝（6/2）** | Teams会議招待送信（Minori・G-P宛、ニュートラルタイトル） |
| **月曜（6/2）10:00** | PIP通知面談（Minori・G-P同席） |
| **月曜（6/2）** | Adamへ状況報告メール送信（Ogura-san件） |
| **6/6（来週中）** | 日野さんとらくらくモード完成・レビュー |
| **6/10まで** | Ogura-sanからの返答待ち → 受諾確認後Adam報告 |
| **要調整** | 新潟県央基幹病院への直接訪問・ヒアリング実施 |

### 重要関係者

| 名前 | 役割 | 重要事項 |
|---|---|---|
| **Adam** | 上司・承認者 | Ogura-san採用・Japan strategy・人事タイトル・代理店戦略の最終承認者 |
| **Steven Hashagen** | Indica Labs CEO | Ogura-san採用・Japan market strategyの上位承認対象 |
| **Jonathon Bartlett** | Indica Labs CHRO | PIP承認・人事プロセスの上位承認者 |
| **Ogura-san** | 採用候補 / ex-Hamamatsu | KOLネットワーク×病理IT理解×要望対応力。once-in-a-career talent。6/10回答期限 |
| **Minori（田渕未里）** | Japan team / PIP対象 | 6/2 PIP通知。機密扱い。WangへのMinori情報開示は慎重に |
| **Ando** | 顧客対応 / Apps Group候補 | 顧客エンゲージメント・リカバリー力が高い。来年Apps Group移行予定 |
| **日野さん** | Indica Labs テクニカルエンジニア | らくらくモード開発担当。6/6完成目標 |
| **Wang** | APAC商業統括（中国カントリーマネージャー） | Minori関連情報の開示範囲を慎重に管理 |
| **Haiying** | APAC reseller支援 | 情報開示注意 |
| **Misaki Yamane** | G-P HRスペシャリスト | PIP担当。ymisaki@g-p.com / nsuzuki@g-p.com |
| **福岡先生** | 病理KOL / モデル病院キーパーソン | 新潟県央基幹病院への派遣オプション保持。東大・阪大共同研究提案中 |
| **Visualix** | 実質的営業パートナー（稼働中） | AetherAI対抗・二次店展開・LBS傘下回避の中核 |
| **Leica Biosystems / LBS** | ⚠️機密：Danaher傘下・吸収リスクあり | 日本では機能しない。独立維持戦略の観点から距離を保つ |
| **AetherAI** | 主要競合 | 弱点：性能。武器：シンプルなUI。対抗：らくらくモード |
| **Roche** | 連携/競合 | uPath・navify・DP200/600・胃HER2・ADCモジュール文脈 |
| **藤井様** | 病院企画課 | 院長カンファレンスでHALO Link/AIの病院内メリット説明が必要 |

### 日本市場エコシステム（モデル病院向け）

| カテゴリ | 会社 |
|---|---|
| **スキャナーベンダー** | 浜松ホトニクス（中心軸）・フィリップス・ライカ |
| **LISベンダー** | インテック・正晃テック・フィンガルリンク・ひろぎん |
| **AIプラットフォーム** | HALO AP（Indica Labs） |
| **戦略パートナー** | Visualix（営業・二次店展開） |
| **ターゲット病院** | 新潟県央基幹病院（400床・福岡先生指名） |

### 繰り返しルール（必ず守ること）
- **録音後の出力形式**: ①文字起こし → ②約200文字の一文要約 → ③スライドファイル形式 → 最後に3行でコツに気づける要点
- **病院経営層向け**: 専門用語を抑え、ROI・標準化・時間短縮・診断品質・人員不足対策で説明
- **HALO製品の整理**: HALO Link=研究/RUO/GraphQL/Study権限、HALO AP=臨床診断/HL7/FHIR/LIS/EMR
- **スキャナー予算の説得**: WSIスキャナーはコモディティ化→HALO suiteを同じ予算に入れるアービトラージ論法
- **メール文面**: 英日ともに丁寧・相手尊重・事業上の主張を明確に（英文→日本語の順で必ず両方作成）
- **採用・人事・代理店**: 感情論でなく事業価値・市場浸透・信頼獲得・売上貢献の論理で説明
- **AIツール役割分担**: Claude Code=戦略・自動化・永続コンテキスト管理（本リポジトリ）
- **LBS/Danaher情報**: 機密。社外・Wang/Haiyingへ開示不可
- **AetherAI対抗軸**: 性能訴求 + らくらくモード（操作性）の2軸で差別化

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
