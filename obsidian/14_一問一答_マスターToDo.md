---
tags: [一問一答, マスターToDo, 進行表, COO, アクティブ]
updated: 2026-05-31
status: 進行中
active: "#1 Vast.ai 停止＋環境保存"
note: 牧野英哉の全To-Doを統合した一問一答の進行表。1問ずつ解決→次へ。
---

# 🎯 一問一答 マスターToDo 進行表

> **運用ルール（かれん原理）**: 1問ずつ。答え（決定/完了）を記録 → 次へ。
> 低抽象度の処理はCOOが代行、牧野さんには「判断と指示」だけを残す。
> **今のアクティブ → 🟢 #1 Vast.ai 停止＋環境保存**

---

## 🟢 #1【アクティブ・実行中】Vast.ai 停止＋環境保存 ⏳

> **問い**: 課金を止めたい。でも作り込んだ作業環境は残したい。どうする？
> **答え（決定済み）**: Vast.ai上に環境をタダで残すことは不可（Stopでもストレージ課金、マイナス放置で破棄）。
> → **環境をVast.ai外に退避してからDestroy**（＝重い実体は持たず「設計図＋データ」だけ残す）。

### 実行チェックリスト（牧野さん側・60秒×3）
- [ ] **Step 0**: Vast.ai → Billing → Add Credit で **$5** 入金（退避の猶予を確保）
- [ ] **Step 1**: 環境をDockerイメージ化して退避
      `docker commit <container_id> <dockerhub_user>/valiente-env:latest`
      `docker push <dockerhub_user>/valiente-env:latest`
- [ ] **Step 2**: データ/成果物をGoogle Driveへ退避
      `rclone copy /workspace/<結果> gdrive:VastBackup/ -P`
- [ ] **Step 3**: 該当インスタンスを **DESTROY**（課金完全停止）
- [ ] **完了報告** → COOが #1 をクローズし #2 へ進める

> 📌 後日復元: 新インスタンス作成時に `valiente-env:latest` をテンプレ指定 → 環境復活。データはDriveから戻す。
> 出典: Vast.ai Instances FAQ / Billing（docs.vast.ai）

---

## 🔴 #2【次】月曜6/2 PIP準備（最も不可逆）

> 月曜10:00 PIP通知面談（Minori・G-P同席）。週末に仕込む。

- [ ] みさきさん(G-P)へ PIP最終版確認メール（英→日 両方）
- [ ] Teams会議招待送信（Minori・G-P／ニュートラル件名）
- [ ] 最終版ドキュメント最終確認（Drive保存済み）
- [ ] 月曜10:00 面談実施

---

## 🟡 #3 Adamへ状況報告（Ogura-san件）
- [ ] Ogura-san採用の現況をAdamへメール（6/10回答期限の前提共有）

## 🟡 #4 JSDP理事会 日程返信（押尾氏・要返信）
- [ ] 出欠返信: 6/15(月)15:30 / 8/3(月)16:00 / 12/7(月)14:30 / 3/15(月)14:30

## 🔴 #5 GitHub CI 2件修正（COO=私が実行可）
- [ ] daily-brief.yml 失敗（main 109bd06）の原因調査・修正
- [ ] notion-obsidian-sync.yml 失敗の原因調査・修正

## 🟡 #6 らくらくモード（6/6）
- [ ] 日野さんと完成・レビュー

## 🟡 #7 Ogura-san 返答待ち（~6/10）
- [ ] 受諾確認後 → Adamへ報告

## 🟢 #8 新潟県央基幹病院 訪問調整
- [ ] 福岡先生ライン/直接コンタクトで訪問日程調整

## 🟢 #9 東北大HALO作業（日野マター・把握のみ）
- [ ] 月曜作業（PC旧型/新型注意）。牧野は把握のみ（japan@ CC）

---

## ✅ クローズ済み
（まだなし — #1完了でここに移動）

---

## 📌 関連
- [[03_直近アクション]] / [[04_Minori_PIP]] / [[02_本業_IndicaLabs]]
- [[00_HUB_牧野の外部脳]]
