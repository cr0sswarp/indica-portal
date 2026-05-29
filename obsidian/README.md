---
title: VALIENTE Vault Index
updated: 2026-05-28
---

# 🧠 VALIENTE Vault — 牧野の外部脳

> Notionから自動同期 | 最終更新: 2026-05-28
> Source of Truth: [Notion 外部脳ハブ](https://www.notion.so/34080324ec9381a5a658ed4b34123f8d)

## 📂 ページ一覧

- [[外部脳ハブ]]
- [[株価/株価予測AIシステム]]
- [[AI_COMPANY/AI_COMPANY実装マスタープラン]]

---

## ⚙️ このVaultについて
- **同期元**: Notion ワークスペース（indica labs / 牧野英哉）
- **同期方法**: GitHub Actions → `notion_export.py` → Git commit
- **更新頻度**: 毎日 6:55 JST（daily-briefの5分前）
- **ローカル編集**: Obsidian Git プラグインで pull/push

## 📱 Obsidian セットアップ手順

### 1. このリポジトリをローカルにクローン
```bash
git clone https://github.com/cr0sswarp/indica-portal
```

### 2. Obsidianで開く
- Obsidianを起動 → 「フォルダを開く」→ `indica-portal/obsidian/` を選択

### 3. Obsidian Git プラグインをインストール
- Settings → Community plugins → Browse → "Obsidian Git" → Install → Enable
- 設定:
  - Auto pull interval: **60** （分）
  - Auto push after commit delay: **5** （秒）
  - Pull on startup: **ON**

### 4. 動作確認
- 毎朝 6:55 JST にNotionの最新内容が自動でこのフォルダに反映される
- Obsidianを開くたびに自動pullでNotionと同期される
- グラフビュー（Ctrl+G）でページ間のリンク構造を可視化できる

---

## _sync_log

最新の同期履歴は [[_sync_log]] を参照。
