"""
cxo/dispatch.py
COO → CXO Sub-Agent Dispatch System（Archetype C: AI-Native）
1つの指示から複数のCXOエージェントが並列稼働し、統合レポートを返す
"""

import os
import json
import anthropic
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

JST = timezone(timedelta(hours=9))
TODAY_STR = datetime.now(JST).strftime("%Y-%m-%d")

claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# ── CXO エージェント定義（Archetype C: AI-Native Chief of Staff）
CXO_AGENTS = {
    "CFO": {
        "emoji": "💰",
        "title": "Chief Financial Officer",
        "persona": """あなたはINDICA LABSのAI-Native CFOです。
PayPal Mafia的な財務規律と、財団設立の財務構造の両立を担当します。
Aperioからのスピンアウト文化を持ち、スケールのための財務設計を行います。
常に: キャッシュポジション・財団拠出タイミング・投資リターンの視点で回答します。""",
        "domains": ["予算", "財務", "投資", "キャッシュ", "財団拠出", "コスト"]
    },
    "CMO": {
        "emoji": "📡",
        "title": "Chief Mission Officer",
        "persona": """あなたはINDICA LABSのAI-Native CMOです。
財団のビジョン・使命・コミュニケーション戦略を担当します。
社会インパクトとビジネス価値の両立、ブランド構築、ステークホルダーとの関係構築が専門です。
常に: メッセージの一貫性・ビジョンの具体化・外部発信の視点で回答します。""",
        "domains": ["ブランド", "コミュニケーション", "ビジョン", "PR", "採用", "パートナー"]
    },
    "CTO": {
        "emoji": "⚙️",
        "title": "Chief Technology Officer",
        "persona": """あなたはINDICA LABSのAI-Native CTOです。
Aperio時代の医療AI・デジタルパソロジーの技術的深度を持ち、
Claude API・GitHub Actions・Notion・MCP連携による自動化インフラを設計します。
常に: 自動化可能性・スケーラビリティ・技術的負債ゼロの視点で回答します。""",
        "domains": ["技術", "自動化", "AI", "システム", "インフラ", "API", "Claude", "MCP"]
    },
    "CLO": {
        "emoji": "⚖️",
        "title": "Chief Legal Officer",
        "persona": """あなたはINDICA LABSのAI-Native CLOです。
日本の公益財団法人・一般財団法人の設立要件と、グローバルな法務リスクを担当します。
財団設立のロードマップ（定款・評議員会・主務官庁認定）を管理します。
常に: コンプライアンス・リスク低減・設立スケジュールの視点で回答します。""",
        "domains": ["法務", "財団", "定款", "コンプライアンス", "契約", "規制", "認定"]
    },
    "CPO": {
        "emoji": "🎯",
        "title": "Chief People Officer",
        "persona": """あなたはINDICA LABSのAI-Native CPOです。
COO/EA候補のスカウト・評価・オンボーディング、そしてAI-Nativeチーム構築を担当します。
PayPal Mafia的な「優秀な人材を世界から召喚する」採用文化を実践します。
常に: 人材の質・文化適合・AI-Native度・グローバルネットワークの視点で回答します。""",
        "domains": ["採用", "人材", "組織", "チーム", "文化", "スカウト", "COO", "EA"]
    }
}


def route_to_agents(instruction: str) -> list[str]:
    """指示内容から関連するCXOエージェントを判定"""
    prompt = f"""以下の指示をどのCXO部門が担当すべきか判定してください。
複数可。CFO/CMO/CTO/CLO/CPOから選択。

指示: {instruction}

JSON配列のみ出力: ["CFO", "CTO"] のような形式"""

    msg = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=100,
        messages=[{"role": "user", "content": prompt}]
    )
    text = msg.content[0].text.strip()
    try:
        agents = json.loads(text)
        return [a for a in agents if a in CXO_AGENTS]
    except Exception:
        return list(CXO_AGENTS.keys())


def run_agent(agent_key: str, instruction: str, context: str = "") -> dict:
    """特定のCXOエージェントを実行"""
    agent = CXO_AGENTS[agent_key]
    prompt = f"""{agent['persona']}

## 代表からの指示:
{instruction}

## 追加コンテキスト:
{context if context else '（なし）'}

## 今日の日付: {TODAY_STR}

以下のJSON形式で回答してください:
{{
  "assessment": "状況評価・分析（100字以内）",
  "actions": ["具体的アクション1（40字以内）", "アクション2", "アクション3"],
  "escalate_to_ceo": "代表の判断が必要な事項（60字以内、不要なら空文字）",
  "timeline": "完了目標時期（例: 今週中、来月末）",
  "auto_can_do": "AIで自動化できる部分（40字以内）"
}}

JSONのみ出力してください。"""

    msg = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}]
    )
    text = msg.content[0].text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        result = json.loads(text)
        result["agent"] = agent_key
        result["emoji"] = agent["emoji"]
        result["title"] = agent["title"]
        return result
    except Exception:
        return {
            "agent": agent_key, "emoji": agent["emoji"], "title": agent["title"],
            "assessment": text[:200], "actions": [], "escalate_to_ceo": "",
            "timeline": "", "auto_can_do": ""
        }


def dispatch(instruction: str, context: str = "", target_agents: list[str] | None = None) -> dict:
    """
    COO dispatch: 指示を関連CXOに並列送信し、統合レポートを返す

    Args:
        instruction: 代表からの指示
        context: 追加コンテキスト（Notionデータ等）
        target_agents: 指定エージェント（Noneの場合は自動判定）
    """
    print(f"\n{'='*60}")
    print(f"COO DISPATCH | {TODAY_STR}")
    print(f"指示: {instruction}")
    print(f"{'='*60}")

    if target_agents is None:
        target_agents = route_to_agents(instruction)
    print(f"担当エージェント: {', '.join(target_agents)}")

    # 並列実行
    results = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(run_agent, ak, instruction, context): ak
            for ak in target_agents
        }
        for future in as_completed(futures):
            ak = futures[future]
            try:
                results[ak] = future.result()
                print(f"  ✅ {ak}: {results[ak].get('assessment','')[:50]}")
            except Exception as e:
                print(f"  ❌ {ak}: {e}")

    # COOが統合サマリーを生成
    results_text = json.dumps(results, ensure_ascii=False, indent=2)
    summary_prompt = f"""あなたはINDICA LabsのAI-Native COOです。
各CXOからの報告を統合し、代表（牧野氏）への簡潔なサマリーを生成してください。

## 指示:
{instruction}

## 各CXOの報告:
{results_text}

## 出力（JSON）:
{{
  "executive_summary": "3行以内の経営サマリー",
  "ceo_decisions": ["代表が判断すべき事項1", "事項2"],
  "next_24h": ["次の24時間でやること1", "やること2", "やること3"],
  "auto_scheduled": ["自動実行に回せること1", "こと2"]
}}

JSONのみ出力してください。"""

    msg = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        messages=[{"role": "user", "content": summary_prompt}]
    )
    text = msg.content[0].text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        summary = json.loads(text)
    except Exception:
        summary = {"executive_summary": text[:300], "ceo_decisions": [], "next_24h": [], "auto_scheduled": []}

    return {
        "instruction": instruction,
        "date": TODAY_STR,
        "agents": results,
        "coo_summary": summary
    }


def print_report(report: dict):
    """ターミナル向けレポート表示"""
    s = report.get("coo_summary", {})
    print(f"\n{'='*60}")
    print("📋 COO 統合レポート")
    print(f"{'='*60}")
    print(f"\n🎯 エグゼクティブサマリー:\n{s.get('executive_summary','')}")

    if s.get("ceo_decisions"):
        print("\n🔴 代表の判断が必要:")
        for d in s["ceo_decisions"]:
            print(f"  • {d}")

    if s.get("next_24h"):
        print("\n⚡ 次の24時間:")
        for a in s["next_24h"]:
            print(f"  → {a}")

    if s.get("auto_scheduled"):
        print("\n🤖 自動化に回せること:")
        for a in s["auto_scheduled"]:
            print(f"  ✅ {a}")

    print("\n── 各CXO詳細 ──────────────────────────────")
    for ak, ag in report.get("agents", {}).items():
        print(f"\n{ag['emoji']} {ag['title']}:")
        print(f"  評価: {ag.get('assessment','')}")
        for act in ag.get("actions", []):
            print(f"  → {act}")
        if ag.get("escalate_to_ceo"):
            print(f"  🔴 代表へ: {ag['escalate_to_ceo']}")
    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    import sys
    instruction = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "財団設立の現状確認と今週の優先アクションを教えてください"
    report = dispatch(instruction)
    print_report(report)
