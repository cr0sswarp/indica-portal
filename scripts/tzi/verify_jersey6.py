#!/usr/bin/env python3
"""
TZI: Rigorous re-verification of #6 (right-back) tracking.

Dumps RAW (un-normalized) and NORMALIZED positions per half for the player
identified as #6, so we can check by hand whether:
  1. The OCR-identified #6 is plausible
  2. The direction normalization (180-deg rotation for flipped halves) is correct
  3. Which Y-side the player actually occupies in each half

Field geometry (from config homography):
  X=0   = left goal (one end)        X=105 = right goal (other end)
  Y=0   = FAR touchline (top of screen, away from camera)
  Y=68  = NEAR touchline (bottom of screen, closest to camera)

A right-back plays on the right side RELATIVE TO ATTACK DIRECTION.
When a team switches ends at half-time, attack direction flips 180 deg,
so the physical Y-side of the right-back ALSO flips. Correct normalization
of a flipped half is a full 180-deg rotation: x'=105-x, y'=68-y.
"""
import json
from pathlib import Path

import numpy as np

DATA = Path(__file__).parent.parent.parent / "data" / "tzi"
FW, FH = 105.0, 68.0

MATCHES = ["20260314", "20260316", "20260317mid", "20260317osaka",
           "20260318", "20260325", "20260329", "20260405"]


def summ(vals):
    if not vals:
        return "n/a"
    a = np.array(vals)
    return f"min={a.min():.1f} mean={a.mean():.1f} max={a.max():.1f}"


def main():
    for mid in MATCHES:
        p = DATA / f"match_{mid}" / "players_v3.json"
        if not p.exists():
            continue
        d = json.load(open(p))
        dir_info = d.get("direction", {})
        players = d.get("players", [])
        ocr = [(pl["player_id"], pl.get("jersey_number"))
               for pl in players if pl.get("jersey_number")]

        print("=" * 70)
        print(f"MATCH {mid}   players={len(players)}   "
              f"flip_1h={dir_info.get('flip_1h')}  flip_2h={dir_info.get('flip_2h')}")
        print(f"  OCR jerseys: {ocr if ocr else 'NONE'}")

        j6 = next((pl for pl in players if pl.get("jersey_number") == 6), None)
        if not j6:
            print("  #6 NOT identified by OCR")
            continue

        print(f"  #6 = {j6['player_id']}   n_sightings={j6['n_sightings']}")

        # Split sightings by half, show RAW and NORMALIZED
        for half in ("1H", "2H"):
            sl = [s for s in j6["sightings"] if s["half"] == half]
            if not sl:
                continue
            raw_x  = [s["fx"] for s in sl]
            raw_y  = [s["fy"] for s in sl]
            nrm_x  = [s.get("fx_norm", s["fx"]) for s in sl]
            nrm_y  = [s.get("fy_norm", s["fy"]) for s in sl]
            flipped = sl[0].get("direction_flipped", False)
            print(f"    [{half}] n={len(sl)} flipped={flipped}")
            print(f"       RAW  X: {summ(raw_x)}")
            print(f"       RAW  Y: {summ(raw_y)}")
            print(f"       NORM X: {summ(nrm_x)}")
            print(f"       NORM Y: {summ(nrm_y)}")


if __name__ == "__main__":
    main()
