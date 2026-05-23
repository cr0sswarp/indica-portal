#!/usr/bin/env python3
"""
TZI: Auto-extract jersey #6 trajectory from players_v2.json.
Merges with existing manual jersey6_trajectory.json if present.

Usage:
    python auto_jersey6_from_v2.py --match 20260325
    python auto_jersey6_from_v2.py --match all   # process all matches
"""
import argparse
import json
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_TZI     = PROJECT_ROOT / "data" / "tzi"

MATCH_LABELS = {
    "20260314": "vs埼玉大 (03/14)",
    "20260316": "vs岐阜協立 (03/16)",
    "20260317mid": "vs中京U-19後半 (03/17)",
    "20260317osaka": "vs大阪学院 (03/17)",
    "20260318": "vs作新学院 (03/18)",
    "20260325": "vs立教大 (03/25)",
    "20260329": "vs川崎U-18 (03/29)",
    "20260405": "vs獨協大 (04/05)",
}


def process_match(match_id: str) -> bool:
    match_dir  = DATA_TZI / f"match_{match_id}"
    v2_path    = match_dir / "players_v2.json"
    traj_path  = match_dir / "jersey6_trajectory.json"

    if not v2_path.exists():
        print(f"  [{match_id}] players_v2.json not found — skip")
        return False

    data    = json.load(open(v2_path))
    players = data.get("players", [])

    # Find jersey #6
    j6 = next((p for p in players if p.get("jersey_number") == 6), None)
    if not j6:
        print(f"  [{match_id}] #6 not auto-identified in OCR results")
        # Still output what we found
        found = [(p["player_id"], p["jersey_number"]) for p in players if p.get("jersey_number")]
        if found:
            print(f"           Found: {found}")
        return False

    print(f"  [{match_id}] Found #{j6['jersey_number']} = {j6['player_id']}  ({j6['n_sightings']} sightings)")

    # Build positions list from v2 sightings
    auto_positions = []
    for s in j6["sightings"]:
        auto_positions.append({
            "time_min": s["time_min"],
            "half": s["half"],
            "fx": s["fx"],
            "fy": s["fy"],
            "zone": s["zone"],
            "note": "auto_v2_ocr",
        })

    # Merge with existing manual positions
    if traj_path.exists():
        existing = json.load(open(traj_path))
        manual   = [p for p in existing.get("confirmed_positions", [])
                    if "auto_v2" not in p.get("note", "")]
        manual_times = {round(p["time_min"], 1) for p in manual}
        auto_new = [p for p in auto_positions
                    if round(p["time_min"], 1) not in manual_times]
        merged = manual + auto_new
        print(f"           Merged {len(manual)} manual + {len(auto_new)} new auto = {len(merged)} total")
        # Backup manual-only version
        shutil.copy(traj_path, match_dir / "jersey6_trajectory_manual.json")
    else:
        merged = auto_positions
        print(f"           New trajectory: {len(merged)} auto positions")

    merged.sort(key=lambda p: p["time_min"])

    traj = {
        "match": MATCH_LABELS.get(match_id, match_id),
        "player": "牧野羽瑠 #6",
        "auto_generated": True,
        "confirmed_positions": merged,
    }

    with open(traj_path, "w", encoding="utf-8") as f:
        json.dump(traj, f, ensure_ascii=False, indent=2)

    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", default="all")
    args = ap.parse_args()

    if args.match == "all":
        matches = [d.name.replace("match_", "")
                   for d in sorted(DATA_TZI.iterdir())
                   if d.is_dir() and d.name.startswith("match_")]
    else:
        matches = [args.match]

    print(f"=== auto_jersey6_from_v2  ({len(matches)} matches) ===")
    success = 0
    for m in matches:
        if process_match(m):
            success += 1

    print(f"\nCompleted: {success}/{len(matches)} matches with #6 identified")


if __name__ == "__main__":
    main()
