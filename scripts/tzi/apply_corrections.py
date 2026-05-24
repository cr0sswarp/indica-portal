#!/usr/bin/env python3
"""
apply_corrections.py — Driveの修正ファイルをground_truth.json / rosters.jsonに反映

使い方:
    python scripts/tzi/apply_corrections.py              # corrections/ 内を全て処理
    python scripts/tzi/apply_corrections.py --match 20260325
    python scripts/tzi/apply_corrections.py --dry-run   # 実際には書き込まない

Driveとの連携:
    bash scripts/sync_corrections.sh  # Drive → data/tzi/corrections/ に同期
    python scripts/tzi/apply_corrections.py              # 同期後にこれを実行
"""

import argparse
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_TZI     = PROJECT_ROOT / "data" / "tzi"
CORR_DIR     = DATA_TZI / "corrections"
GT_PATH      = DATA_TZI / "ground_truth.json"
ROSTER_PATH  = DATA_TZI / "rosters.json"


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  保存: {path.name}")


def apply_position_fixes(gt_data, match_id, position_fixes, dry_run):
    """position_fixes を ground_truth.json の segments に反映する。"""
    if not position_fixes:
        return gt_data

    if match_id not in gt_data["matches"]:
        gt_data["matches"][match_id] = {"note": "", "segments": []}

    for fix in position_fixes:
        if fix.get("_example"):
            continue  # テンプレート例行をスキップ

        half    = fix.get("half")
        from_m  = fix.get("from_min", 0.0)
        to_m    = fix.get("to_min", 999.0)
        role    = fix.get("role")
        label   = fix.get("label", role)
        note    = fix.get("note", "")

        if not (half and role):
            print(f"    [SKIP] half/role が未入力: {fix}")
            continue

        # 同じ half の既存セグメントを削除して置き換え
        segs = gt_data["matches"][match_id]["segments"]

        # 既存のセグメントから対象範囲を除外
        new_segs = []
        for seg in segs:
            if seg["half"] != half:
                new_segs.append(seg)
                continue
            lo, hi = seg.get("t_rel", [0.0, 999.0])
            # 完全に範囲外なら残す
            if hi <= from_m or lo >= to_m:
                new_segs.append(seg)
            else:
                # 部分的に重なるセグメントは分割
                if lo < from_m:
                    new_segs.append({**seg, "t_rel": [lo, from_m]})
                if hi > to_m:
                    new_segs.append({**seg, "t_rel": [to_m, hi]})

        # 新しいセグメントを追加
        new_seg = {"half": half, "role": role, "label": label}
        if not (from_m == 0.0 and to_m == 999.0):
            new_seg["t_rel"] = [from_m, to_m]
        new_segs.append(new_seg)
        new_segs.sort(key=lambda s: (s["half"], s.get("t_rel", [0])[0]))

        gt_data["matches"][match_id]["segments"] = new_segs

        action = "[DRY]" if dry_run else "✓"
        print(f"    {action} position: {half} {from_m:.1f}-{to_m:.1f}min → {label} ({role})")
        if note:
            gt_data["matches"][match_id]["note"] = note

    return gt_data


def apply_jersey_fixes(roster_data, match_id, jersey_fixes, dry_run):
    """jersey_fixes を rosters.json の notes に反映する。"""
    if not jersey_fixes:
        return roster_data

    if match_id not in roster_data["matches"]:
        roster_data["matches"][match_id] = {
            "label": match_id,
            "waseda": {"starters": [], "gk": None, "notes": {}},
            "opponent": {"starters": [], "gk": None, "notes": {}}
        }

    notes = roster_data["matches"][match_id]["waseda"]["notes"]

    for fix in jersey_fixes:
        if fix.get("_example"):
            continue

        jersey = fix.get("correct_jersey")
        note   = fix.get("note", "")
        time   = fix.get("time", "")

        if jersey is None:
            continue

        key = str(jersey)
        entry = f"{note} (@{time})" if time else note
        notes[key] = entry

        action = "[DRY]" if dry_run else "✓"
        print(f"    {action} jersey #{jersey}: {entry}")

    return roster_data


def process_correction_file(corr_path, gt_data, roster_data, dry_run):
    """1つの修正ファイルを処理する。"""
    print(f"\n--- {corr_path.name} ---")
    try:
        corr = load_json(corr_path)
    except json.JSONDecodeError as e:
        print(f"  [ERROR] JSON parse error: {e}")
        return gt_data, roster_data

    match_id = corr.get("match")
    if not match_id:
        print("  [SKIP] match フィールドなし")
        return gt_data, roster_data

    reviewer = corr.get("reviewer", "不明")
    reviewed = corr.get("reviewed_at", "未設定")
    notes    = corr.get("notes", "")
    print(f"  試合: {match_id}  レビュワー: {reviewer}  日時: {reviewed}")
    if notes:
        print(f"  コメント: {notes}")

    # position_fixes
    gt_data = apply_position_fixes(
        gt_data, match_id, corr.get("position_fixes", []), dry_run)

    # jersey_fixes
    roster_data = apply_jersey_fixes(
        roster_data, match_id, corr.get("jersey_fixes", []), dry_run)

    # arrow_checks サマリー
    checks = [c for c in corr.get("arrow_checks", []) if not c.get("_example")]
    if checks:
        ok  = sum(1 for c in checks if c.get("status") == "ok")
        ng  = sum(1 for c in checks if c.get("status") == "wrong")
        print(f"  矢印チェック: OK={ok}  NG={ng}")
        for c in checks:
            if c.get("status") == "wrong":
                print(f"    NG @ {c.get('time')}: {c.get('note','')}")

    # free_comments
    comments = corr.get("free_comments", [])
    if comments:
        print("  自由コメント:")
        for c in comments:
            print(f"    - {c}")

    return gt_data, roster_data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--match",   help="特定の試合IDのみ処理 (例: 20260325)")
    ap.add_argument("--dry-run", action="store_true", help="変更をファイルに書き込まない")
    args = ap.parse_args()

    if not CORR_DIR.exists():
        print(f"[ERROR] corrections ディレクトリが見つかりません: {CORR_DIR}")
        return

    # 修正ファイルを収集（TEMPLATE は除外）
    corr_files = sorted(CORR_DIR.glob("corrections_*.json"))
    if args.match:
        corr_files = [f for f in corr_files if args.match in f.name]

    if not corr_files:
        print("修正ファイルが見つかりません")
        print(f"  場所: {CORR_DIR}")
        print(f"  ファイル名: corrections_YYYYMMDD.json")
        return

    print(f"修正ファイル {len(corr_files)} 件を処理します")
    if args.dry_run:
        print("[DRY RUN] ファイルへの書き込みは行いません")

    gt_data     = load_json(GT_PATH)
    roster_data = load_json(ROSTER_PATH)

    for cf in corr_files:
        gt_data, roster_data = process_correction_file(
            cf, gt_data, roster_data, args.dry_run)

    if not args.dry_run:
        save_json(GT_PATH, gt_data)
        save_json(ROSTER_PATH, roster_data)
        print("\n完了: ground_truth.json と rosters.json を更新しました")
    else:
        print("\n[DRY RUN] 完了。--dry-run を外すと実際に書き込まれます")


if __name__ == "__main__":
    main()
