"""
notion_export.py
Notion ワークスペース → Obsidian Vault (Markdown) エクスポート
毎日 6:55 JST に GitHub Actions から実行
"""

import os
import re
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from notion_client import Client

JST = timezone(timedelta(hours=9))
TODAY_STR = datetime.now(JST).strftime("%Y-%m-%d")
VAULT_DIR = Path("obsidian")
VAULT_DIR.mkdir(exist_ok=True)

notion = Client(auth=os.environ["NOTION_TOKEN"])

# ── エクスポート対象ページ（Notionから取得したID）────────────────
TARGET_PAGES = {
    "外部脳ハブ": {
        "id": os.environ.get("NOTION_HUB_PAGE_ID", "34080324ec9381a5a658ed4b34123f8d"),
        "folder": ""
    },
    "株価予測AIシステム": {
        "id": os.environ.get("NOTION_PAGE_ID", "35680324ec93812ab3c1fe4eb4eac3f5"),
        "folder": "株価"
    },
    "AI_COMPANY実装マスタープラン": {
        "id": "36380324ec938131b047fcb5ba6bc2ea",
        "folder": "AI_COMPANY"
    },
}

# ── Notionブロック → Markdown 変換 ─────────────────────────────
def rich_text_to_md(rich_texts: list) -> str:
    result = ""
    for rt in rich_texts:
        text = rt.get("plain_text", "")
        ann = rt.get("annotations", {})
        if ann.get("bold"):
            text = f"**{text}**"
        if ann.get("italic"):
            text = f"*{text}*"
        if ann.get("code"):
            text = f"`{text}`"
        if ann.get("strikethrough"):
            text = f"~~{text}~~"
        href = rt.get("href")
        if href:
            text = f"[{text}]({href})"
        result += text
    return result


def blocks_to_markdown(blocks: list, depth: int = 0) -> str:
    lines = []
    indent = "  " * depth
    numbered_count = {}

    for block in blocks:
        bt = block.get("type", "")
        data = block.get(bt, {})
        rt = data.get("rich_text", [])
        text = rich_text_to_md(rt)

        if bt == "heading_1":
            lines.append(f"\n# {text}\n")
        elif bt == "heading_2":
            lines.append(f"\n## {text}\n")
        elif bt == "heading_3":
            lines.append(f"\n### {text}\n")
        elif bt == "paragraph":
            lines.append(f"{indent}{text}\n" if text else "")
        elif bt == "bulleted_list_item":
            lines.append(f"{indent}- {text}")
        elif bt == "numbered_list_item":
            lines.append(f"{indent}1. {text}")
        elif bt == "to_do":
            checked = "x" if data.get("checked") else " "
            lines.append(f"{indent}- [{checked}] {text}")
        elif bt == "toggle":
            lines.append(f"{indent}<details><summary>{text}</summary>\n")
            if block.get("has_children"):
                lines.append(f"{indent}</details>")
        elif bt == "quote":
            lines.append(f"{indent}> {text}")
        elif bt == "callout":
            emoji = data.get("icon", {}).get("emoji", "💡")
            lines.append(f"{indent}> {emoji} **{text}**")
        elif bt == "code":
            lang = data.get("language", "")
            code_text = "".join(r.get("plain_text", "") for r in rt)
            lines.append(f"```{lang}\n{code_text}\n```")
        elif bt == "divider":
            lines.append("---")
        elif bt in ("child_page", "child_database"):
            title = data.get("title", "")
            page_id = block.get("id", "").replace("-", "")
            lines.append(f"[[{title}]]")
        elif bt == "table":
            pass  # テーブルは子ブロックで処理
        elif bt == "table_row":
            cells = data.get("cells", [])
            row = " | ".join(rich_text_to_md(cell) for cell in cells)
            lines.append(f"| {row} |")
        elif bt == "image":
            url = data.get("external", {}).get("url") or data.get("file", {}).get("url", "")
            caption = rich_text_to_md(data.get("caption", []))
            lines.append(f"![{caption}]({url})")
        elif bt == "bookmark":
            url = data.get("url", "")
            caption = rich_text_to_md(data.get("caption", []))
            lines.append(f"[{caption or url}]({url})")
        elif bt == "embed":
            url = data.get("url", "")
            lines.append(f"[Embed: {url}]({url})")
        elif bt == "link_to_page":
            pid = (data.get("page_id") or data.get("database_id") or "").replace("-", "")
            lines.append(f"[[notion:{pid}]]")

        # 子ブロック再帰（has_childrenはAPIで取得済みの場合）
        children = block.get("_children", [])
        if children:
            lines.append(blocks_to_markdown(children, depth + 1))

    return "\n".join(line for line in lines if line is not None)


def fetch_blocks(page_id: str) -> list:
    """ブロックを再帰的に取得"""
    results = []
    cursor = None
    while True:
        resp = notion.blocks.children.list(
            block_id=page_id,
            start_cursor=cursor,
            page_size=100
        )
        for block in resp["results"]:
            if block.get("has_children"):
                try:
                    block["_children"] = fetch_blocks(block["id"])
                except Exception:
                    block["_children"] = []
            results.append(block)
        if not resp.get("has_more"):
            break
        cursor = resp["next_cursor"]
    return results


def fetch_page_title(page_id: str) -> str:
    try:
        page = notion.pages.retrieve(page_id=page_id)
        props = page.get("properties", {})
        for prop in props.values():
            if prop.get("type") == "title":
                rt = prop["title"]
                return "".join(r.get("plain_text", "") for r in rt)
    except Exception:
        pass
    return page_id


def export_page(name: str, page_id: str, folder: str):
    """1ページをMarkdownファイルとしてエクスポート"""
    clean_id = page_id.replace("-", "")
    print(f"  エクスポート中: {name} ({clean_id})")

    try:
        blocks = fetch_blocks(clean_id)
        title = fetch_page_title(clean_id)
        md_content = f"---\ntitle: {title}\nnotion_id: {clean_id}\nupdated: {TODAY_STR}\n---\n\n# {title}\n\n"
        md_content += blocks_to_markdown(blocks)

        # ファイルパス
        target_dir = VAULT_DIR / folder if folder else VAULT_DIR
        target_dir.mkdir(parents=True, exist_ok=True)

        # ファイル名: 日本語はそのまま保持（Obsidianは対応）
        safe_name = re.sub(r'[<>:"/\\|?*]', '_', name)
        file_path = target_dir / f"{safe_name}.md"
        file_path.write_text(md_content, encoding="utf-8")
        print(f"    → {file_path} ({len(md_content)} 文字)")
        return True
    except Exception as e:
        print(f"    ❌ エラー: {e}")
        return False


def create_index():
    """Obsidian vault のインデックスページを生成"""
    index = f"""---
title: VALIENTE Vault Index
updated: {TODAY_STR}
---

# 🧠 VALIENTE Vault — 牧野の外部脳

> Notionから自動同期 | 最終更新: {TODAY_STR}
> Source of Truth: [Notion 外部脳ハブ](https://www.notion.so/34080324ec9381a5a658ed4b34123f8d)

## 📂 ページ一覧

"""
    for name, info in TARGET_PAGES.items():
        folder = info["folder"]
        path = f"{folder}/{name}" if folder else name
        index += f"- [[{path}]]\n"

    index += f"""
---

## ⚙️ このVaultについて
- **同期元**: Notion ワークスペース（indica labs / 牧野英哉）
- **同期方法**: GitHub Actions → `notion_export.py` → Git commit
- **更新頻度**: 毎日 6:55 JST
- **ローカル編集**: Obsidian Git プラグインで pull/push

## 🔗 クイックリンク
- [[外部脳ハブ]] — メインハブ
- [[株価/株価予測AIシステム]] — AI株価分析
- [[AI_COMPANY/AI_COMPANY実装マスタープラン]] — 自動化設計書

"""
    index_path = VAULT_DIR / "README.md"
    index_path.write_text(index, encoding="utf-8")
    print(f"インデックス生成: {index_path}")


def create_obsidian_config():
    """Obsidian の最低限の設定ファイルを生成"""
    config_dir = VAULT_DIR / ".obsidian"
    config_dir.mkdir(exist_ok=True)

    # app.json - 基本設定
    app_config = {
        "legacyEditor": False,
        "livePreview": True,
        "defaultViewMode": "source",
        "readableLineLength": True,
        "strictLineBreaks": False
    }
    (config_dir / "app.json").write_text(
        json.dumps(app_config, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # graph.json - グラフビュー設定
    graph_config = {
        "collapse-filter": False,
        "search": "",
        "showTags": False,
        "showAttachments": False,
        "hideUnresolved": False,
        "showOrphans": True,
        "collapse-color-groups": False,
        "colorGroups": [],
        "collapse-display": False,
        "showArrow": True,
        "textFadeMultiplier": 0,
        "nodeSizeMultiplier": 1,
        "lineSizeMultiplier": 1,
        "collapse-forces": False,
        "repelStrength": 10,
        "linkStrength": 1,
        "linkDistance": 250,
        "scale": 1,
        "close": False
    }
    (config_dir / "graph.json").write_text(
        json.dumps(graph_config, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Obsidian設定生成: {config_dir}")


# ── メイン ────────────────────────────────────────────────────
def main():
    print(f"[{TODAY_STR}] Notion → Obsidian エクスポート開始")

    # Obsidian設定
    create_obsidian_config()

    # 各ページをエクスポート
    success = 0
    for name, info in TARGET_PAGES.items():
        if export_page(name, info["id"], info["folder"]):
            success += 1

    # インデックス生成
    create_index()

    # 同期ログ
    log_path = VAULT_DIR / "_sync_log.md"
    log_entry = f"- {TODAY_STR}: {success}/{len(TARGET_PAGES)} ページ同期成功\n"
    existing = log_path.read_text(encoding="utf-8") if log_path.exists() else "# Sync Log\n\n"
    if "# Sync Log" not in existing:
        existing = "# Sync Log\n\n" + existing
    lines = existing.split("\n")
    insert_idx = next((i for i, l in enumerate(lines) if l.startswith("- ")), 2)
    lines.insert(insert_idx, log_entry.strip())
    log_path.write_text("\n".join(lines[:52]), encoding="utf-8")  # 最大50エントリ保持

    print(f"✅ 完了: {success}/{len(TARGET_PAGES)} ページ → {VAULT_DIR}/")


if __name__ == "__main__":
    main()
