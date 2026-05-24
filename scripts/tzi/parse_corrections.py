#!/usr/bin/env python3
"""
parse_corrections.py — Haru のテキスト修正を Claude API で JSON 化し適用する

Drive 構成:
    TZI/overlays/   → オーバーレイ動画 (Claude がアップロード)
    TZI/corrections/
        20260325_vs立教大/
            corrections.txt   ← Haru がここに書く

使い方:
    python scripts/tzi/parse_corrections.py              # 全修正ファイルを処理
    python scripts/tzi/parse_corrections.py --match 20260325
    python scripts/tzi/parse_corrections.py --dry-run    # 変更を書き込まない
"""

import argparse
import json
import os
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_TZI     = PROJECT_ROOT / "data" / "tzi"
CORR_DIR     = DATA_TZI / "corrections"
GT_PATH      = DATA_TZI / "ground_truth.json"
ROSTER_PATH  = DATA_TZI / "rosters.json"


# ─────────────────────────────────────────────────────────────────
# Claude API でテキストを構造化 JSON に変換
# ─────────────────────────────────────────────────────────────────

def parse_with_claude(match_id, raw_text):
    """Anthropic API を使って自由テキストを修正 JSON に変換する。"""
    try:
        import anthropic
    except ImportError:
        print("  [WARN] anthropic パッケージ未インストール → ローカルパーサーを使用")
        return parse_locally(match_id, raw_text)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("  [WARN] ANTHROPIC_API_KEY 未設定 → ローカルパーサーを使用")
        return parse_locally(match_id, raw_text)

    client = anthropic.Anthropic(api_key=api_key)

    prompt = f"""以下は soccer の試合映像(match_id={match_id})に関するレビューコメントです。
早稲田大学の#6番 牧野羽瑠の追跡精度について書かれています。

テキストを解析して、以下の JSON 形式に変換してください。
分からない項目は空リストのままにしてください。

出力形式 (JSON のみ、説明文なし):
{{
  "match": "{match_id}",
  "notes": "全体コメントをここにまとめる",
  "arrow_checks": [
    {{"time": "1H 10min", "status": "ok"}},
    {{"time": "1H 15min", "status": "wrong", "note": "具体的な間違いの説明"}}
  ],
  "position_fixes": [
    {{
      "jersey": 6,
      "half": "1H" or "2H",
      "from_min": 0.0,
      "to_min": 999.0,
      "role": "サイドバック" or "アンカー" or "セントラル" or "トップ下" or "トップ" or "センターバック",
      "label": "右SB" など表示用の名前,
      "note": "コメント"
    }}
  ],
  "jersey_fixes": [
    {{"time": "1H 15min", "correct_jersey": 6, "note": "説明"}}
  ],
  "free_comments": ["その他のコメント"]
}}

ルール:
- time は "1H 10min" または "2H 35min" 形式に統一 (分は小数点OK: "2H 29.5min")
- status は "ok" (正しい) か "wrong" (間違い) のみ
- role は上記6種類から最も近いものを選ぶ
- 数字は float/int で (文字列にしない)

レビューテキスト:
---
{raw_text}
---"""

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )
        raw_json = msg.content[0].text.strip()
        # JSON ブロック抽出
        m = re.search(r'\{[\s\S]+\}', raw_json)
        if m:
            raw_json = m.group(0)
        result = json.loads(raw_json)
        print("  [Claude] テキストを JSON に変換しました")
        return result
    except Exception as e:
        print(f"  [WARN] Claude API エラー ({e}) → ローカルパーサーを使用")
        return parse_locally(match_id, raw_text)


def parse_locally(match_id, raw_text):
    """シンプルな正規表現パーサー (API 不使用フォールバック)。"""
    result = {
        "match": match_id,
        "notes": "",
        "arrow_checks": [],
        "position_fixes": [],
        "jersey_fixes": [],
        "free_comments": [],
    }

    lines = raw_text.splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # 時刻パターン: 1H/前半/2H/後半 + 数字 + 分/min
        time_m = re.search(
            r'(1H|2H|前半|後半)\s*(\d+(?:[:.]\d+)?)\s*(?:分|min)?',
            line, re.IGNORECASE)
        half = None
        t_min = None
        if time_m:
            half_raw = time_m.group(1)
            half = "1H" if half_raw in ("1H", "前半") else "2H"
            raw_t = time_m.group(2).replace(":", ".")
            t_min = float(raw_t)
            time_str = f"{half} {t_min:.1f}min"

        # OK/NG 判定
        is_ok = bool(re.search(r'\bOK\b|合って|正しい|あってる', line, re.IGNORECASE))
        is_ng = bool(re.search(r'\bNG\b|間違|ズレ|違う|ちがう', line, re.IGNORECASE))

        if time_m and (is_ok or is_ng):
            result["arrow_checks"].append({
                "time": time_str,
                "status": "ok" if is_ok else "wrong",
                "note": line,
            })
            continue

        # ポジション変更
        pos_m = re.search(r'(右SB|左SB|ボランチ|アンカー|CB|センターバック|トップ下|FW)', line)
        if time_m and pos_m:
            role_map = {
                "右SB": "サイドバック", "左SB": "サイドバック",
                "ボランチ": "アンカー", "アンカー": "アンカー",
                "CB": "センターバック", "センターバック": "センターバック",
                "トップ下": "トップ下", "FW": "トップ",
            }
            pos_label = pos_m.group(1)
            result["position_fixes"].append({
                "jersey": 6,
                "half": half,
                "from_min": t_min,
                "to_min": 999.0,
                "role": role_map.get(pos_label, "アンカー"),
                "label": pos_label,
                "note": line,
            })
            continue

        # 背番号修正: "#X が #Y" 系
        jersey_m = re.search(r'#(\d+)[^#]*(?:が|は|→|->)\s*#(\d+)', line)
        if jersey_m:
            result["jersey_fixes"].append({
                "time": time_str if time_m else "不明",
                "correct_jersey": int(jersey_m.group(2)),
                "note": line,
            })
            continue

        # それ以外は自由コメント
        result["free_comments"].append(line)

    # notes としてまとめる
    result["notes"] = " / ".join(result["free_comments"][:3])
    return result


# ─────────────────────────────────────────────────────────────────
# ground_truth / rosters への反映
# ─────────────────────────────────────────────────────────────────

def apply_to_ground_truth(gt, match_id, position_fixes):
    if not position_fixes:
        return gt
    if match_id not in gt["matches"]:
        gt["matches"][match_id] = {"note": "", "segments": []}

    for fix in position_fixes:
        half   = fix.get("half")
        f_min  = float(fix.get("from_min", 0.0))
        t_min  = float(fix.get("to_min",   999.0))
        role   = fix.get("role")
        label  = fix.get("label", role)
        note   = fix.get("note", "")
        if not (half and role):
            continue

        segs = gt["matches"][match_id]["segments"]
        new_segs = []
        for seg in segs:
            if seg["half"] != half:
                new_segs.append(seg); continue
            lo, hi = seg.get("t_rel", [0.0, 999.0])
            if hi <= f_min or lo >= t_min:
                new_segs.append(seg)
            else:
                if lo < f_min: new_segs.append({**seg, "t_rel": [lo, f_min]})
                if hi > t_min: new_segs.append({**seg, "t_rel": [t_min, hi]})

        new_seg = {"half": half, "role": role, "label": label}
        if not (f_min == 0.0 and t_min == 999.0):
            new_seg["t_rel"] = [f_min, t_min]
        new_segs.append(new_seg)
        new_segs.sort(key=lambda s: (s["half"], s.get("t_rel", [0])[0]))
        gt["matches"][match_id]["segments"] = new_segs
        if note:
            gt["matches"][match_id]["note"] = note
        print(f"    ✓ {half} {f_min:.1f}-{t_min:.1f}min → {label}")

    return gt


def apply_to_rosters(rosters, match_id, jersey_fixes):
    if not jersey_fixes:
        return rosters
    if match_id not in rosters["matches"]:
        rosters["matches"][match_id] = {
            "label": match_id,
            "waseda":   {"starters": [], "gk": None, "notes": {}},
            "opponent": {"starters": [], "gk": None, "notes": {}},
        }
    notes = rosters["matches"][match_id]["waseda"]["notes"]
    for fix in jersey_fixes:
        j    = fix.get("correct_jersey")
        note = fix.get("note", "")
        time = fix.get("time", "")
        if j is None: continue
        notes[str(j)] = f"{note} (@{time})" if time else note
        print(f"    ✓ #{j}: {notes[str(j)]}")
    return rosters


# ─────────────────────────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--match",   help="試合ID (例: 20260325)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not CORR_DIR.exists():
        print(f"[ERROR] {CORR_DIR} が存在しません")
        return

    # 試合IDフォルダを収集
    dirs = sorted(d for d in CORR_DIR.iterdir()
                  if d.is_dir() and not d.name.startswith("."))
    if args.match:
        dirs = [d for d in dirs if args.match in d.name]

    if not dirs:
        print(f"修正フォルダが見つかりません: {CORR_DIR}")
        print("  フォルダ名例: 20260325_vs立教大/")
        return

    print(f"=== 修正ファイルを処理 ({len(dirs)} フォルダ) ===")
    if args.dry_run:
        print("[DRY RUN] ファイルへの書き込みは行いません\n")

    gt      = json.loads(GT_PATH.read_text(encoding="utf-8"))
    rosters = json.loads(ROSTER_PATH.read_text(encoding="utf-8"))

    for d in dirs:
        txt_file = d / "corrections.txt"
        if not txt_file.exists():
            print(f"\n--- {d.name}: corrections.txt なし → スキップ ---")
            continue

        # フォルダ名から match_id を抽出 (先頭8桁の数字)
        m = re.match(r'^(\d{8})', d.name)
        if not m:
            print(f"\n--- {d.name}: match_id 不明 → スキップ ---")
            continue
        match_id = m.group(1)

        raw_text = txt_file.read_text(encoding="utf-8")
        print(f"\n--- {d.name} (match={match_id}) ---")
        print(f"  テキスト ({len(raw_text.splitlines())}行) を解析中...")

        parsed = parse_with_claude(match_id, raw_text)

        # 解析済み JSON をフォルダに保存（確認用）
        parsed_path = d / "corrections_parsed.json"
        if not args.dry_run:
            parsed_path.write_text(
                json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  JSON保存: {parsed_path.name}")

        # 矢印チェックのサマリー
        checks = parsed.get("arrow_checks", [])
        if checks:
            ok = sum(1 for c in checks if c.get("status") == "ok")
            ng = sum(1 for c in checks if c.get("status") == "wrong")
            print(f"  矢印チェック: OK={ok}  NG={ng}")
            for c in checks:
                if c.get("status") == "wrong":
                    print(f"    NG @ {c.get('time')}: {c.get('note','')}")

        # ground_truth / rosters に反映
        if not args.dry_run:
            gt      = apply_to_ground_truth(gt, match_id, parsed.get("position_fixes", []))
            rosters = apply_to_rosters(rosters, match_id, parsed.get("jersey_fixes", []))

        # 自由コメント表示
        for c in parsed.get("free_comments", []):
            print(f"  コメント: {c}")

    if not args.dry_run:
        GT_PATH.write_text(
            json.dumps(gt, ensure_ascii=False, indent=2), encoding="utf-8")
        ROSTER_PATH.write_text(
            json.dumps(rosters, ensure_ascii=False, indent=2), encoding="utf-8")
        print("\n✅ ground_truth.json / rosters.json を更新しました")
    else:
        print("\n[DRY RUN] --dry-run を外すと実際に書き込まれます")


if __name__ == "__main__":
    main()
