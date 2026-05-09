"""
nakajima.py
中嶋聡「ざっくばらん」メルマガ → Claude要約 → PDF生成 → Notion保存
"""

import os
import imaplib
import email
from email.header import decode_header
from datetime import datetime, timezone, timedelta
from pathlib import Path
import anthropic
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ── 定数 ──────────────────────────────────────────────────────
JST = timezone(timedelta(hours=9))
NOW_JST = datetime.now(JST)
TODAY_STR = NOW_JST.strftime("%Y-%m-%d")
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_NAKAJIMA_PAGE_ID = os.environ.get("NOTION_NAKAJIMA_PAGE_ID", "")

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ── Gmail IMAP でメール取得 ──────────────────────────────────
def fetch_newsletter() -> str:
    """Gmail から最新のざっくばらんメールを取得"""
    print("Gmail に接続中...")
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
    mail.select("inbox")

    # 「ざっくばらん」または送信者で検索
    search_queries = [
        '(FROM "nakajima" SUBJECT "ざっくばらん")',
        '(FROM "nakajima" SUBJECT "ざっくばらん")',
        '(SUBJECT "ざっくばらん")',
        '(FROM "nakajima@")',
    ]

    messages = []
    for query in search_queries:
        _, data = mail.search(None, query)
        if data[0]:
            messages = data[0].split()
            print(f"検索クエリ '{query}' でメール {len(messages)} 件発見")
            break

    if not messages:
        print("ざっくばらんのメールが見つかりませんでした。最新メールで試行します。")
        _, data = mail.search(None, 'ALL')
        messages = data[0].split()[-5:]  # 直近5件

    # 最新のメールを取得
    latest_id = messages[-1]
    _, msg_data = mail.fetch(latest_id, "(RFC822)")
    raw_email = msg_data[0][1]
    msg = email.message_from_bytes(raw_email)

    # 件名デコード
    subject_raw = msg.get("Subject", "")
    subject_parts = decode_header(subject_raw)
    subject = "".join(
        part.decode(enc or "utf-8") if isinstance(part, bytes) else part
        for part, enc in subject_parts
    )
    print(f"件名: {subject}")

    # 本文取得
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain":
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                body = payload.decode(charset, errors="replace")
                break
            elif ctype == "text/html" and not body:
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                body = payload.decode(charset, errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        charset = msg.get_content_charset() or "utf-8"
        body = payload.decode(charset, errors="replace")

    mail.logout()
    print(f"メール本文取得完了: {len(body)} 文字")
    return f"件名: {subject}\n\n{body}"


# ── Claude で要約 ────────────────────────────────────────────
def summarize_newsletter(newsletter_text: str) -> dict:
    """Claude でメルマガを要約・インフォグラフィック用に構造化"""
    prompt = f"""以下は中嶋聡さんの週次メルマガ「ざっくばらん」です。
これを読んでA4一枚に収まるインフォグラフィック形式のサマリーを作成してください。

## 出力形式（JSON）:
{{
  "date": "発行日または本日日付",
  "issue_title": "今号のメインテーマ（20字以内）",
  "headline": "最も重要なメッセージ（40字以内）",
  "key_points": [
    "ポイント1（30字以内）",
    "ポイント2（30字以内）",
    "ポイント3（30字以内）"
  ],
  "deep_insight": "深い洞察・核心メッセージ（100字以内）",
  "action_items": [
    "今週実践すること1（30字以内）",
    "今週実践すること2（30字以内）"
  ],
  "quote": "メルマガからの印象的な一節（60字以内）",
  "full_summary": "全体サマリー（300字以内）"
}}

## メルマガ本文:
{newsletter_text[:8000]}

JSON のみ出力してください（```json ``` 不要）。"""

    message = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )

    import json
    text = message.content[0].text.strip()
    # JSON抽出
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


# ── PDF 生成 ─────────────────────────────────────────────────
def create_pdf(summary: dict) -> Path:
    """ReportLab でA4インフォグラフィックPDFを生成"""
    # Noto Sans CJK フォント登録
    font_paths = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJKjp-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]
    for fp in font_paths:
        if Path(fp).exists():
            try:
                pdfmetrics.registerFont(TTFont("NotoSans", fp))
                break
            except Exception:
                continue

    output_path = OUTPUT_DIR / f"nakajima_{TODAY_STR}.pdf"
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=20*mm, leftMargin=20*mm,
        topMargin=20*mm, bottomMargin=20*mm
    )

    # スタイル定義
    try:
        base_font = "NotoSans"
    except Exception:
        base_font = "Helvetica"

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", fontName=base_font, fontSize=22,
                                  textColor=colors.HexColor("#1a1a2e"), spaceAfter=6)
    subtitle_style = ParagraphStyle("subtitle", fontName=base_font, fontSize=13,
                                     textColor=colors.HexColor("#4a4a8a"), spaceAfter=4)
    head_style = ParagraphStyle("head", fontName=base_font, fontSize=11,
                                 textColor=colors.HexColor("#0077cc"), spaceBefore=8, spaceAfter=4)
    body_style = ParagraphStyle("body", fontName=base_font, fontSize=10,
                                 textColor=colors.HexColor("#333333"), spaceAfter=3, leading=16)
    quote_style = ParagraphStyle("quote", fontName=base_font, fontSize=10,
                                  textColor=colors.HexColor("#555555"), spaceAfter=3,
                                  leftIndent=10, borderPad=4)

    # コンテンツ構築
    story = []
    story.append(Paragraph(f"📧 ざっくばらん — {summary.get('date', TODAY_STR)}", title_style))
    story.append(Paragraph(summary.get("issue_title", ""), subtitle_style))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#0077cc")))
    story.append(Spacer(1, 4*mm))

    # ヘッドライン
    story.append(Paragraph("💡 今号のヘッドライン", head_style))
    story.append(Paragraph(summary.get("headline", ""), body_style))
    story.append(Spacer(1, 3*mm))

    # キーポイント
    story.append(Paragraph("📌 キーポイント", head_style))
    for i, pt in enumerate(summary.get("key_points", []), 1):
        story.append(Paragraph(f"{i}. {pt}", body_style))
    story.append(Spacer(1, 3*mm))

    # 深い洞察
    story.append(Paragraph("🔍 核心メッセージ", head_style))
    story.append(Paragraph(summary.get("deep_insight", ""), body_style))
    story.append(Spacer(1, 3*mm))

    # 引用
    story.append(Paragraph("📖 印象的な一節", head_style))
    story.append(Paragraph(f'「{summary.get("quote", "")}」', quote_style))
    story.append(Spacer(1, 3*mm))

    # アクションアイテム
    story.append(Paragraph("✅ 今週実践すること", head_style))
    for item in summary.get("action_items", []):
        story.append(Paragraph(f"• {item}", body_style))
    story.append(Spacer(1, 3*mm))

    # フルサマリー
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#cccccc")))
    story.append(Paragraph("📝 全体サマリー", head_style))
    story.append(Paragraph(summary.get("full_summary", ""), body_style))

    doc.build(story)
    print(f"PDF 生成完了: {output_path}")
    return output_path


# ── Notion に保存（任意） ─────────────────────────────────────
def save_to_notion(summary: dict):
    """Notion ページに要約を追記（NOTION_TOKEN が設定されている場合）"""
    if not NOTION_TOKEN or not NOTION_NAKAJIMA_PAGE_ID:
        print("Notion 保存: スキップ（環境変数未設定）")
        return

    from notion_client import Client
    notion = Client(auth=NOTION_TOKEN)
    notion.blocks.children.append(
        block_id=NOTION_NAKAJIMA_PAGE_ID,
        children=[
            {"object": "block", "type": "heading_2",
             "heading_2": {"rich_text": [{"type": "text", "text":
                 {"content": f"📧 {TODAY_STR} ざっくばらん要約"}}]}},
            {"object": "block", "type": "paragraph",
             "paragraph": {"rich_text": [{"type": "text", "text":
                 {"content": summary.get("full_summary", "")}}]}},
            {"object": "block", "type": "divider", "divider": {}}
        ]
    )
    print("Notion 保存完了")


# ── メイン ────────────────────────────────────────────────────
def main():
    print(f"[{TODAY_STR}] ざっくばらん要約 — 開始")

    # 1. メール取得
    newsletter_text = fetch_newsletter()

    # 2. Claude で要約
    print("Claude で要約中...")
    summary = summarize_newsletter(newsletter_text)
    print("要約完了:", summary.get("headline", ""))

    # 3. PDF 生成
    pdf_path = create_pdf(summary)
    print(f"PDF: {pdf_path}")

    # 4. Notion 保存（任意）
    save_to_notion(summary)

    print("✅ nakajima 完了")


if __name__ == "__main__":
    main()
