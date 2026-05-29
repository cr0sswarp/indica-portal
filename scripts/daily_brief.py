"""
daily_brief.py
毎朝の統合ブリーフィング — Notion + Claude → HTML メール(PDF添付) → makino@indicalab.jp
"""

import os
import json
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from datetime import datetime, timezone, timedelta
from pathlib import Path
import anthropic
from notion_client import Client

# ── 定数 ──────────────────────────────────────────────────────
JST = timezone(timedelta(hours=9))
NOW_JST = datetime.now(JST)
TODAY_STR = NOW_JST.strftime("%Y-%m-%d")
TODAY_LABEL = NOW_JST.strftime("%Y年%-m月%-d日（%a）")
WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]
TODAY_LABEL = NOW_JST.strftime(f"%Y年%-m月%-d日（{WEEKDAY_JP[NOW_JST.weekday()]}）")
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GMAIL_ADDRESS     = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
NOTION_TOKEN      = os.environ.get("NOTION_TOKEN", "")
NOTION_PAGE_ID    = os.environ.get("NOTION_PAGE_ID", "")              # 株価ページ
NOTION_NAKAJIMA_PAGE_ID  = os.environ.get("NOTION_NAKAJIMA_PAGE_ID", "")
NOTION_FOUNDATION_PAGE_ID = os.environ.get("NOTION_FOUNDATION_PAGE_ID", "")  # 財団ページ（任意）

TO_ADDRESS = os.environ.get("BRIEF_TO", GMAIL_ADDRESS)

claude  = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
notion  = Client(auth=NOTION_TOKEN) if NOTION_TOKEN else None


# ── Notion テキスト取得 ────────────────────────────────────────
def fetch_notion_text(page_id: str, label: str = "") -> str:
    if not notion or not page_id:
        return ""
    try:
        blocks = notion.blocks.children.list(block_id=page_id)
        lines = []
        for b in blocks["results"][:40]:  # 最大40ブロック
            bt = b["type"]
            if bt in ("paragraph","heading_1","heading_2","heading_3",
                      "bulleted_list_item","numbered_list_item","quote","callout"):
                rich = b[bt].get("rich_text", [])
                line = "".join(r.get("plain_text","") for r in rich)
                if line.strip():
                    lines.append(line)
        text = "\n".join(lines)
        print(f"Notion [{label}] 取得: {len(text)} 文字")
        return text
    except Exception as e:
        print(f"Notion [{label}] エラー: {e}")
        return ""


def notion_page_url(page_id: str) -> str:
    clean = page_id.replace("-", "")
    return f"https://notion.so/{clean}"


# ── Claude でブリーフィング生成 ────────────────────────────────
def generate_brief(stock_ctx: str, nakajima_ctx: str, foundation_ctx: str) -> dict:
    sections = []
    if stock_ctx:
        sections.append(f"【株価分析（最新）】\n{stock_ctx[-3000:]}")
    if nakajima_ctx:
        sections.append(f"【中嶋メルマガ（最新要約）】\n{nakajima_ctx[-2000:]}")
    if foundation_ctx:
        sections.append(f"【財団設立進捗】\n{foundation_ctx[-2000:]}")

    context = "\n\n".join(sections) if sections else "（Notion データなし）"

    prompt = f"""あなたはINDICA LABS代表・牧野氏専属のAI-Native COOです。
以下のコンテキストを読み、本日({TODAY_LABEL})の朝のブリーフィングをJSON形式で生成してください。

牧野氏が「クリエイティブな判断と指示だけ」に集中できるよう、
低抽象度の情報処理は全てあなたが行い、意思決定が必要な事項だけを浮き彫りにしてください。

## 出力形式（JSON）:
{{
  "greeting": "短い挨拶文（20字以内、元気づける一言）",
  "today_priority": [
    {{"rank": 1, "item": "最重要事項（40字以内）", "action": "必要なアクション（30字以内）", "urgency": "高/中/低"}},
    {{"rank": 2, "item": "...", "action": "...", "urgency": "..."}}
  ],
  "decisions_needed": [
    "牧野氏の判断が必要な事項1（40字以内）",
    "牧野氏の判断が必要な事項2（40字以内）"
  ],
  "auto_handled": [
    "自動処理済みまたは委任可能な事項1（30字以内）",
    "自動処理済みまたは委任可能な事項2（30字以内）"
  ],
  "stock_insight": "本日の株価・投資観点での一言（60字以内）",
  "foundation_status": "財団設立進捗の一言（60字以内、情報がない場合は空文字）",
  "creative_focus": "本日牧野氏がクリエイティブエネルギーを注ぐべきテーマ（50字以内）",
  "coo_note": "COOからの一言メモ（40字以内）"
}}

## コンテキスト:
{context}

JSONのみ出力してください。"""

    msg = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )
    text = msg.content[0].text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except Exception:
        return {"greeting": "おはようございます", "today_priority": [],
                "decisions_needed": [], "auto_handled": [],
                "stock_insight": "", "foundation_status": "",
                "creative_focus": "本日もビジョンの具体化を", "coo_note": ""}


# ── HTML メール生成 ────────────────────────────────────────────
def build_html_email(brief: dict) -> str:
    def priority_rows(items):
        if not items:
            return "<tr><td colspan='3' style='padding:12px;color:#666;'>（なし）</td></tr>"
        urgency_color = {"高": "#ff4757", "中": "#ffa502", "低": "#2ed573"}
        rows = ""
        for p in items:
            urg = p.get("urgency","中")
            color = urgency_color.get(urg, "#ffa502")
            rows += f"""
            <tr>
              <td style='padding:10px 8px;border-bottom:1px solid #1a1a3e;font-size:11px;color:{color};font-weight:bold;white-space:nowrap;'>{p.get('rank','')}</td>
              <td style='padding:10px 8px;border-bottom:1px solid #1a1a3e;color:#c0c8ff;font-size:13px;'>{p.get('item','')}</td>
              <td style='padding:10px 8px;border-bottom:1px solid #1a1a3e;color:#7986cb;font-size:12px;'>{p.get('action','')}</td>
            </tr>"""
        return rows

    def list_items(items, color="#c0c8ff"):
        if not items:
            return "<li style='color:#666;'>（なし）</li>"
        return "".join(f"<li style='color:{color};margin:6px 0;font-size:13px;'>{i}</li>" for i in items)

    notion_links = []
    if NOTION_PAGE_ID:
        notion_links.append(f'<a href="{notion_page_url(NOTION_PAGE_ID)}" style="color:#7986cb;text-decoration:none;margin-right:16px;">📈 株価分析</a>')
    if NOTION_NAKAJIMA_PAGE_ID:
        notion_links.append(f'<a href="{notion_page_url(NOTION_NAKAJIMA_PAGE_ID)}" style="color:#7986cb;text-decoration:none;margin-right:16px;">📧 中嶋メルマガ</a>')
    if NOTION_FOUNDATION_PAGE_ID:
        notion_links.append(f'<a href="{notion_page_url(NOTION_FOUNDATION_PAGE_ID)}" style="color:#7986cb;text-decoration:none;margin-right:16px;">🏛️ 財団設立</a>')
    notion_link_html = " ".join(notion_links) if notion_links else ""

    foundation_row = ""
    if brief.get("foundation_status"):
        foundation_row = f"""
        <tr>
          <td colspan='2' style='padding:16px 20px;background:#0d1b2a;border-top:1px solid #1a1a3e;'>
            <div style='font-size:11px;color:#546e7a;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px;'>🏛️ 財団設立進捗</div>
            <div style='color:#80cbc4;font-size:13px;'>{brief.get('foundation_status','')}</div>
          </td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="ja">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#06060f;font-family:'Helvetica Neue',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#06060f;">
<tr><td align="center" style="padding:20px 10px;">

  <!-- CARD -->
  <table width="600" cellpadding="0" cellspacing="0" border="0" style="background:#0d0d1f;border-radius:16px;overflow:hidden;border:1px solid #1a1a3e;max-width:600px;">

    <!-- HEADER -->
    <tr>
      <td colspan="2" style="background:#0d0d2f;padding:28px 28px 20px;border-bottom:2px solid #1a237e;">
        <div style="font-size:10px;color:#3949ab;letter-spacing:3px;text-transform:uppercase;margin-bottom:8px;">VALIENTE PORTAL · INDICA LABS</div>
        <div style="font-size:26px;font-weight:700;color:#e8eaf6;margin-bottom:4px;">🌅 本日のブリーフィング</div>
        <div style="font-size:14px;color:#7986cb;">{TODAY_LABEL}</div>
        <div style="margin-top:12px;padding:10px 14px;background:#13133a;border-radius:8px;border-left:3px solid #5c6bc0;">
          <span style="font-size:13px;color:#9fa8da;font-style:italic;">{brief.get('greeting','おはようございます')}</span>
        </div>
      </td>
    </tr>

    <!-- CREATIVE FOCUS -->
    <tr>
      <td colspan="2" style="padding:16px 28px;background:#0a0a20;border-bottom:1px solid #1a1a3e;">
        <div style="font-size:10px;color:#1565c0;letter-spacing:2px;text-transform:uppercase;margin-bottom:6px;">⚡ 本日のクリエイティブフォーカス</div>
        <div style="font-size:16px;font-weight:600;color:#82b1ff;">{brief.get('creative_focus','')}</div>
      </td>
    </tr>

    <!-- PRIORITIES -->
    <tr>
      <td colspan="2" style="padding:20px 28px 8px;">
        <div style="font-size:11px;color:#3949ab;letter-spacing:2px;text-transform:uppercase;margin-bottom:12px;">📌 本日の優先事項</div>
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr style="background:#13133a;">
            <th style="padding:8px;text-align:left;font-size:10px;color:#546e7a;letter-spacing:1px;width:30px;">優先</th>
            <th style="padding:8px;text-align:left;font-size:10px;color:#546e7a;letter-spacing:1px;">事項</th>
            <th style="padding:8px;text-align:left;font-size:10px;color:#546e7a;letter-spacing:1px;">アクション</th>
          </tr>
          {priority_rows(brief.get('today_priority',[]))}
        </table>
      </td>
    </tr>

    <!-- DECISIONS + AUTO -->
    <tr>
      <td width="50%" style="padding:16px 28px;vertical-align:top;border-top:1px solid #1a1a3e;">
        <div style="font-size:10px;color:#e53935;letter-spacing:2px;text-transform:uppercase;margin-bottom:8px;">🎯 牧野氏の判断が必要</div>
        <ul style="margin:0;padding-left:16px;">
          {list_items(brief.get('decisions_needed',[]),'#ef9a9a')}
        </ul>
      </td>
      <td width="50%" style="padding:16px 28px;vertical-align:top;border-top:1px solid #1a1a3e;border-left:1px solid #1a1a3e;">
        <div style="font-size:10px;color:#2e7d32;letter-spacing:2px;text-transform:uppercase;margin-bottom:8px;">✅ 自動処理済み / 委任可能</div>
        <ul style="margin:0;padding-left:16px;">
          {list_items(brief.get('auto_handled',[]),'#a5d6a7')}
        </ul>
      </td>
    </tr>

    <!-- STOCK INSIGHT -->
    <tr>
      <td colspan="2" style="padding:14px 28px;background:#0a0a1a;border-top:1px solid #1a1a3e;">
        <div style="font-size:10px;color:#546e7a;letter-spacing:2px;text-transform:uppercase;margin-bottom:6px;">📈 投資インサイト</div>
        <div style="color:#ffe082;font-size:13px;">{brief.get('stock_insight','')}</div>
      </td>
    </tr>

    <!-- FOUNDATION STATUS (conditional) -->
    {foundation_row}

    <!-- NOTION LINKS -->
    <tr>
      <td colspan="2" style="padding:16px 28px;border-top:1px solid #1a1a3e;">
        <div style="font-size:10px;color:#3949ab;letter-spacing:2px;text-transform:uppercase;margin-bottom:10px;">🔗 Notion で詳細を確認</div>
        <div>{notion_link_html if notion_link_html else '<span style="color:#555;">（Notion連携なし）</span>'}</div>
      </td>
    </tr>

    <!-- FOOTER -->
    <tr>
      <td colspan="2" style="padding:16px 28px;background:#080814;border-top:2px solid #1a237e;">
        <div style="font-size:11px;color:#3949ab;">COO NOTE: {brief.get('coo_note','')}</div>
        <div style="font-size:10px;color:#263238;margin-top:6px;">Generated by VALIENTE AI · INDICA LABS · {TODAY_STR}</div>
      </td>
    </tr>

  </table>
</td></tr>
</table>
</body>
</html>"""


# ── Gmail 送信 ─────────────────────────────────────────────────
def send_email(html_body: str, subject: str, pdf_path: Path | None = None):
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_ADDRESS
    msg["To"]      = TO_ADDRESS

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText("本日のブリーフィングをHTMLメールでご確認ください。", "plain", "utf-8"))
    alt.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alt)

    if pdf_path and pdf_path.exists():
        with open(pdf_path, "rb") as f:
            part = MIMEApplication(f.read(), Name=pdf_path.name)
        part["Content-Disposition"] = f'attachment; filename="{pdf_path.name}"'
        msg.attach(part)

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, TO_ADDRESS, msg.as_string())
    print(f"メール送信完了 → {TO_ADDRESS}")


# ── メイン ────────────────────────────────────────────────────
def main():
    print(f"[{TODAY_STR}] VALIENTE Daily Brief — 開始")

    # Notion からコンテキスト取得
    stock_ctx      = fetch_notion_text(NOTION_PAGE_ID, "株価")
    nakajima_ctx   = fetch_notion_text(NOTION_NAKAJIMA_PAGE_ID, "中嶋")
    foundation_ctx = fetch_notion_text(NOTION_FOUNDATION_PAGE_ID, "財団")

    # Claude でブリーフィング生成
    print("Claude でブリーフィング生成中...")
    brief = generate_brief(stock_ctx, nakajima_ctx, foundation_ctx)
    print(f"フォーカス: {brief.get('creative_focus','')}")

    # HTML メール生成
    html = build_html_email(brief)

    # PDF 添付（前回の中嶋PDFがあれば添付）
    pdf_files = sorted(OUTPUT_DIR.glob("nakajima_*.pdf"))
    latest_pdf = pdf_files[-1] if pdf_files else None

    # 送信
    subject = f"🌅 [{TODAY_LABEL}] VALIENTE Daily Brief — {brief.get('creative_focus','本日のブリーフィング')[:20]}"
    send_email(html, subject, latest_pdf)

    # HTML もローカルに保存（ポータル連携用）
    html_path = OUTPUT_DIR / f"brief_{TODAY_STR}.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"HTML保存: {html_path}")
    print("✅ Daily Brief 完了")


if __name__ == "__main__":
    main()
