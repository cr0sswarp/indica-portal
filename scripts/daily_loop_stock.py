"""
daily_loop_stock.py
自己学習型成長株価予想 — Notion読み取り → Claude分析 → Notion書き込み
"""

import os
import json
from datetime import datetime, timezone, timedelta
import anthropic
from notion_client import Client

# ── 定数 ──────────────────────────────────────────────────────
JST = timezone(timedelta(hours=9))
NOW_JST = datetime.now(JST)
TODAY_STR = NOW_JST.strftime("%Y-%m-%d")

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_PAGE_ID = os.environ["NOTION_PAGE_ID"]

# ── クライアント初期化 ─────────────────────────────────────────
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
notion = Client(auth=NOTION_TOKEN)


def fetch_notion_page_text(page_id: str) -> str:
    """Notion ページのブロック内容をテキストとして取得"""
    blocks = notion.blocks.children.list(block_id=page_id)
    texts = []
    for block in blocks["results"]:
        bt = block["type"]
        if bt in ("paragraph", "heading_1", "heading_2", "heading_3",
                  "bulleted_list_item", "numbered_list_item", "quote", "callout"):
            rich = block[bt].get("rich_text", [])
            line = "".join(r.get("plain_text", "") for r in rich)
            if line.strip():
                texts.append(line)
    return "\n".join(texts)


def append_to_notion_page(page_id: str, content: str):
    """Notion ページに分析結果を追記"""
    # 日付ヘッダー
    notion.blocks.children.append(
        block_id=page_id,
        children=[
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": f"📅 {TODAY_STR} の学習ループ"}}]
                }
            },
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": content}}]
                }
            },
            {
                "object": "block",
                "type": "divider",
                "divider": {}
            }
        ]
    )


def run_stock_analysis(context: str) -> str:
    """Claude に株価分析・学習ループを実行させる"""
    today_formatted = NOW_JST.strftime("%Y年%m月%d日(%A)")

    system_prompt = """あなたは自己学習型の成長株価予想AIです。
毎日の市場情報とこれまでの予測履歴を学習し、マクロ経済・ミクロ経済の観点から
長期保有すべき銘柄のアービトラージ機会を見つけ出します。

分析結果は以下の構成で日本語で出力してください：
1. 【本日のマクロ環境】市場全体のコンテキスト（3〜5行）
2. 【注目銘柄 TOP3】理由付きで3銘柄（各2〜3行）
3. 【アービトラージ機会】具体的な戦略（3〜5行）
4. 【学習メモ】前回予測との差分・改善点（2〜3行）
5. 【明日の注目ポイント】1〜3点

簡潔かつ具体的に。投資助言ではなく学習・研究目的のシミュレーションとして出力。"""

    user_prompt = f"""本日は {today_formatted} です。

## これまでの株価予測コンテキスト（Notionより）:
{context[:6000]}

上記の情報を踏まえて、本日の自己学習型株価予想ループを実行してください。"""

    message = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": user_prompt}],
        system=system_prompt
    )
    return message.content[0].text


def main():
    print(f"[{TODAY_STR}] 自己学習型成長株価予想 — 開始")

    # 1. Notion からコンテキスト読み込み
    print("Notion からコンテキストを取得中...")
    try:
        context = fetch_notion_page_text(NOTION_PAGE_ID)
        print(f"取得完了: {len(context)} 文字")
    except Exception as e:
        print(f"Notion 取得エラー: {e}")
        context = "（Notion データ取得失敗 — デフォルト分析を実行）"

    # 2. Claude で分析
    print("Claude で株価予想ループを実行中...")
    analysis = run_stock_analysis(context)
    print("分析完了:")
    print(analysis)

    # 3. Notion に結果を追記
    print("Notion に結果を保存中...")
    try:
        append_to_notion_page(NOTION_PAGE_ID, analysis)
        print("Notion への書き込み完了")
    except Exception as e:
        print(f"Notion 書き込みエラー: {e}")

    print("✅ daily-loop-stock 完了")


if __name__ == "__main__":
    main()
