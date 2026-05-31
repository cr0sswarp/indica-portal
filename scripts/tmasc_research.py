#!/usr/bin/env python3
"""
tmasc_research.py — T+MASC 深夜自動調査ジョブ

目的:
    エコノメソッド(Ekkono) の T+MASC / アヤックス TIPS / Joan Vila 史実に関する
    「未確認・深掘り論点」を Claude + Web Search で精査し、
    Obsidian Vault にレポートを出力する。

入出力:
    入力 : なし（調査論点は RESEARCH_QUESTIONS に定義）
    出力 : obsidian/research/T+MASC_調査_YYYY-MM-DD.md

環境変数:
    ANTHROPIC_API_KEY : Claude API キー（必須）

⚠️ 反ハルシネーション原則（CLAUDE.md 準拠）:
    一次ソースを引用し、裏が取れない事実は必ず「未確認」と明示する。
    もっともらしい略語・経歴・契約を推測で埋めない。
"""
import os
import datetime
import anthropic

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

JST = datetime.timezone(datetime.timedelta(hours=9))
TODAY = datetime.datetime.now(JST).strftime("%Y-%m-%d")

# ── 調査論点（[[13_TIPS_T+MASC比較]] の深夜調査ブリーフと同期）──────────
RESEARCH_QUESTIONS = """\
1. Joan Vila（Joan Vila i Bosch）の Ekkono / Soccer Services Barcelona への初期関与の有無。
   現状＝未確認。Ekkono 創始者は Carles Romagosa と David Hernández。
   Vila の直接関与を示す一次ソースがあるか厳密に探す（なければ「未確認」と結論）。
2. Joan Vila が久保建英を「見出した／育成した」具体的経緯。
   バルサキャンプ MVP 選出・Vila の役割を一次ソースで精密化する。
3. 岡田武史 × Joan Vila の正式契約の一次ソース（契約年・範囲・岡田メソッドへの反映）。
4. エコノメソッド T+MASC の各文字の意味の再確認。
   想定: T=Talent, M=Motor skills, A=Availability, S=Smartness, C=Commitment。
   これが正しいか、各要素の定義の詳細を裏取りする。
5. アヤックス TIPS（Technique/Insight/Personality/Speed）と T+MASC の対応関係の精緻化。
6. ヨハン・クライフ → アヤックス → バルサ → エコノ／岡田メソッド の系譜の一次ソース固め。
"""

PROMPT = f"""あなたは牧野家のセカンドブレイン（Obsidian）に保存する調査レポートを書くリサーチャーです。

⚠️ 最重要ルール（反ハルシネーション）:
- 検証可能な事実（人名・経歴・所属・契約・年号・略語の意味など）は必ず Web 検索で裏を取る。
- 裏が取れないものは断定せず「未確認」と明示する。推測で埋めない。
- 各事実に出典 URL を併記する。
- 一度でも不確実なら「未確認」と書く方が、誤情報を出すより遥かに良い。

以下の論点を Web 検索で精査し、日本語の Markdown レポートを書いてください。

# 調査論点
{RESEARCH_QUESTIONS}

# 出力フォーマット（Markdown）
- 各論点ごとに「## 論点N: <タイトル>」の見出し
- 各論点に必ず「**結論**: 確認済み / 部分確認 / 未確認」「**根拠**」「**出典**: URL」を含める
- 最後に「## 牧野家への要点（3行）」で締める
- 見出し以外の余計な前置き・後書きは不要
"""


def main() -> None:
    print(f"[{TODAY}] T+MASC 深夜調査 — 開始")
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 8}],
        messages=[{"role": "user", "content": PROMPT}],
    )

    # web search はサーバ側でループ実行され、最終テキストが text ブロックで返る
    parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    report = "\n".join(p for p in parts if p).strip()
    if not report:
        report = "（調査結果のテキストを取得できませんでした。手動確認が必要です。）"

    outdir = os.path.join("obsidian", "research")
    os.makedirs(outdir, exist_ok=True)
    outpath = os.path.join(outdir, f"T+MASC_調査_{TODAY}.md")

    header = (
        "---\n"
        "tags: [T+MASC, 調査, 深夜自動, Ekkono, TIPS, JoanVila]\n"
        f"updated: {TODAY}\n"
        "generated_by: tmasc_research.py（深夜自動調査）\n"
        "shared_with: 牧野羽瑠\n"
        "---\n\n"
        f"# 🌙 T+MASC 深夜自動調査レポート — {TODAY}\n\n"
        "> ⚠️ 自動生成。事実は出典 URL で裏取りされたもののみ採用。未確認は明示。\n"
        "> 関連: [[13_TIPS_T+MASC比較]] / [[11_T-MASCエージェント]]\n\n"
        "---\n\n"
    )

    with open(outpath, "w", encoding="utf-8") as f:
        f.write(header + report + "\n")

    print(f"[{TODAY}] 調査レポート出力: {outpath}")


if __name__ == "__main__":
    main()
