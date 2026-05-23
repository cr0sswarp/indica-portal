#!/usr/bin/env python3
"""
TZI: Auto-extract jersey #6 trajectory from players_v3.json (direction-normalized).
Uses normalized field coordinates (Waseda always attacks right).

Usage:
    python auto_jersey6_from_v3.py --match 20260325
    python auto_jersey6_from_v3.py --match all
"""
import argparse
import json
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_TZI     = PROJECT_ROOT / "data" / "tzi"

MATCH_LABELS = {
    "20260314":      "vs埼玉大 (03/14)",
    "20260316":      "vs岐阜協立 (03/16)",
    "20260317mid":   "vs中京U-19後半 (03/17)",
    "20260317osaka": "vs大阪学院 (03/17)",
    "20260318":      "vs作新学院 (03/18)",
    "20260325":      "vs立教大 (03/25)",
    "20260329":      "vs川崎U-18 (03/29)",
    "20260405":      "vs獨協大 (04/05)",
}


def fx_to_zone(fx):
    if fx < 21:    return "D1"
    if fx < 42:    return "D2"
    if fx < 52.5:  return "D3"
    if fx < 63:    return "A1"
    if fx < 84:    return "A2"
    return "A3"


def process_match(match_id: str) -> bool:
    match_dir = DATA_TZI / f"match_{match_id}"
    v3_path   = match_dir / "players_v3.json"
    traj_path = match_dir / "jersey6_trajectory.json"

    if not v3_path.exists():
        print(f"  [{match_id}] players_v3.json not found — skip")
        return False

    data    = json.load(open(v3_path))
    players = data.get("players", [])

    j6 = next((p for p in players if p.get("jersey_number") == 6), None)
    if not j6:
        print(f"  [{match_id}] #6 not found in v3 OCR results")
        found = [(p["player_id"], p["jersey_number"]) for p in players if p.get("jersey_number")]
        if found:
            print(f"           Found: {found}")
        return False

    print(f"  [{match_id}] Found #{j6['jersey_number']} = {j6['player_id']}  ({j6['n_sightings']} sightings)")

    # Build positions from v3 normalized sightings
    auto_positions = []
    for s in j6["sightings"]:
        fx_n = s.get("fx_norm", s["fx"])
        fy_n = s.get("fy_norm", s["fy"])
        auto_positions.append({
            "time_min": s["time_min"],
            "half": s["half"],
            "fx": fx_n,
            "fy": fy_n,
            "zone": fx_to_zone(fx_n),
            "note": "auto_v3_normalized",
            "direction_flipped": s.get("direction_flipped", False),
        })

    # Merge with existing manual positions (manual take priority)
    if traj_path.exists():
        existing = json.load(open(traj_path))
        manual   = [p for p in existing.get("confirmed_positions", [])
                    if "auto_v" not in p.get("note", "")]
        manual_times = {round(p["time_min"], 1) for p in manual}
        auto_new = [p for p in auto_positions
                    if round(p["time_min"], 1) not in manual_times]
        merged = manual + auto_new
        print(f"           Merged {len(manual)} manual + {len(auto_new)} new auto = {len(merged)} total")
        shutil.copy(traj_path, match_dir / "jersey6_trajectory_manual.json")
    else:
        merged = auto_positions
        print(f"           New trajectory: {len(merged)} positions (normalized)")

    merged.sort(key=lambda p: p["time_min"])

    # Compute summary stats
    if merged:
        import numpy as np
        fxs = [p["fx"] for p in merged]
        fys = [p["fy"] for p in merged]
        print(f"           Centroid (norm): X={np.mean(fxs):.1f}m  Y={np.mean(fys):.1f}m")
        print(f"           Y range: {min(fys):.1f}-{max(fys):.1f}m  (right side if Y>34m)")

    traj = {
        "match":              MATCH_LABELS.get(match_id, match_id),
        "player":             "牧野羽瑠 #6",
        "auto_generated":     True,
        "normalized_coords":  True,
        "direction":          data.get("direction", {}),
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

    print(f"=== auto_jersey6_from_v3  ({len(matches)} matches) ===")
    success = 0
    for m in matches:
        if process_match(m):
            success += 1

    print(f"\nCompleted: {success}/{len(matches)} matches with #6 identified")


if __name__ == "__main__":
    main()
