#!/usr/bin/env python3
"""
TZI: Cross-match validation report for right-back (#6) tracking accuracy.

Loads players_v3.json from all available matches, extracts #6 normalized positions,
and generates a multi-panel visualization showing positional consistency.

A right-back (#6) should appear at:
  - X: 15-80m (varies: 15-35m defensive, 60-80m overlapping in attack)
  - Y: 35-65m (right flank, consistently)

If Y is consistent across matches → tracking normalization is working.

Usage:
    python cross_match_validation.py
Output:
    data/tzi/cross_match_validation.png
    data/tzi/cross_match_validation.html
"""
import json
from pathlib import Path
from collections import defaultdict

import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_TZI     = PROJECT_ROOT / "data" / "tzi"

MATCH_ORDER = [
    "20260314", "20260316", "20260317mid", "20260317osaka",
    "20260318", "20260325", "20260329", "20260405",
]
MATCH_LABELS = {
    "20260314":      "vs埼玉大\n03/14",
    "20260316":      "vs岐阜協立\n03/16",
    "20260317mid":   "vs中京U-19\n03/17",
    "20260317osaka": "vs大阪学院\n03/17",
    "20260318":      "vs作新学院\n03/18",
    "20260325":      "vs立教大\n03/25",
    "20260329":      "vs川崎U-18\n03/29",
    "20260405":      "vs獨協大\n04/05",
}
FW, FH = 105.0, 68.0


def load_all():
    results = {}
    for mid in MATCH_ORDER:
        v3_path = DATA_TZI / f"match_{mid}" / "players_v3.json"
        if not v3_path.exists():
            continue
        d = json.load(open(v3_path))
        j6 = next((p for p in d["players"] if p.get("jersey_number") == 6), None)
        if not j6:
            continue
        sightings = j6["sightings"]
        results[mid] = {
            "player_id": j6["player_id"],
            "n": len(sightings),
            "flip_1h": d["direction"]["flip_1h"],
            "flip_2h": d["direction"]["flip_2h"],
            "positions": [
                {"fx": s.get("fx_norm", s["fx"]),
                 "fy": s.get("fy_norm", s["fy"]),
                 "half": s["half"],
                 "time_min": s["time_min"]}
                for s in sightings
            ],
        }
        fxs = [p["fx"] for p in results[mid]["positions"]]
        fys = [p["fy"] for p in results[mid]["positions"]]
        results[mid]["centroid_x"] = float(np.mean(fxs))
        results[mid]["centroid_y"] = float(np.mean(fys))
    return results


def _draw_field(ax):
    import matplotlib.patches as mpatches
    col = "#30363d"
    ax.add_patch(mpatches.Rectangle((0, 0), FW, FH, fill=False, edgecolor=col, lw=1.2))
    ax.axvline(FW / 2, color=col, lw=0.8)
    ax.add_patch(mpatches.Circle((FW/2, FH/2), 9.15, fill=False, edgecolor=col, lw=0.8))
    for x0 in [0, FW - 16.5]:
        ax.add_patch(mpatches.Rectangle((x0, (FH-40.32)/2), 16.5, 40.32,
                                         fill=False, edgecolor=col, lw=0.8))
    ax.add_patch(mpatches.Rectangle((0, (FH-7.32)/2), 2.44, 7.32,
                                     fill=False, edgecolor="#8b949e", lw=1))
    ax.add_patch(mpatches.Rectangle((FW-2.44, (FH-7.32)/2), 2.44, 7.32,
                                     fill=False, edgecolor="#8b949e", lw=1))
    # Right-back expected zone (X=15-80, Y=35-68)
    ax.add_patch(mpatches.Rectangle((15, 35), 65, 33,
                                     fill=True, facecolor="#3fb950", alpha=0.08,
                                     edgecolor="#3fb950", linestyle="--", lw=1))


def generate_report(data):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.gridspec as gridspec
        from scipy.ndimage import gaussian_filter
    except ImportError:
        print("matplotlib/scipy not available")
        return

    n_matches = len(data)
    if n_matches == 0:
        print("No v3 data found")
        return

    matches = [m for m in MATCH_ORDER if m in data]
    n = len(matches)

    fig = plt.figure(figsize=(4 * min(n, 4) + 2, 5 * ((n + 3) // 4) + 4))
    fig.patch.set_facecolor("#0d1117")

    gs = gridspec.GridSpec((n + 3) // 4 + 1, min(n, 4),
                            figure=fig, hspace=0.5, wspace=0.3)

    # Per-match heatmaps
    for idx, mid in enumerate(matches):
        row = idx // 4
        col = idx % 4
        ax  = fig.add_subplot(gs[row, col])
        ax.set_facecolor("#161b22")
        ax.set_xlim(0, FW); ax.set_ylim(0, FH)
        ax.set_aspect("equal")

        label_en = MATCH_LABELS.get(mid, mid).replace("\n", " ")
        d = data[mid]
        ax.set_title(f"{label_en}\nflip1H={d['flip_1h']} flip2H={d['flip_2h']}",
                     color="#e6edf3", fontsize=7, pad=3)

        _draw_field(ax)

        fxs = [p["fx"] for p in d["positions"]]
        fys = [p["fy"] for p in d["positions"]]

        if len(fxs) >= 3:
            H, xe, ye = np.histogram2d(fxs, fys, bins=[18, 12],
                                        range=[[0, FW], [0, FH]])
            H = gaussian_filter(H.T, sigma=1.2)
            if H.max() > 0:
                ax.contourf(np.linspace(0, FW, 18), np.linspace(0, FH, 12),
                            H, levels=8, cmap="hot", alpha=0.75)

        ax.scatter(fxs, fys, c="cyan", s=15, alpha=0.8, zorder=5)
        ax.scatter([d["centroid_x"]], [d["centroid_y"]],
                   c="white", s=60, marker="X", zorder=6)
        ax.text(d["centroid_x"] + 1, d["centroid_y"] + 2,
                f"({d['centroid_x']:.0f},{d['centroid_y']:.0f})",
                color="white", fontsize=6, zorder=7)

        # Annotate attack direction arrow
        ax.annotate("", xy=(FW * 0.92, 5), xytext=(FW * 0.78, 5),
                    arrowprops=dict(arrowstyle="->", color="#3fb950", lw=1.5))
        ax.text(FW * 0.93, 5, "▶", color="#3fb950", fontsize=7)

        ax.tick_params(colors="#8b949e", labelsize=6)
        for sp in ax.spines.values():
            sp.set_edgecolor("#30363d")

    # Summary panel: Y distribution across matches
    ax_sum = fig.add_subplot(gs[-1, :])
    ax_sum.set_facecolor("#161b22")
    ax_sum.set_title("#6 Right-Back Y-Position Distribution (normalized) — right side = Y > 34m",
                     color="#e6edf3", fontsize=9, pad=4)

    colors_m = plt.cm.tab10(np.linspace(0, 1, len(matches)))
    for ci, mid in enumerate(matches):
        d = data[mid]
        fys = [p["fy"] for p in d["positions"]]
        if fys:
            label = MATCH_LABELS.get(mid, mid).replace("\n", " ")
            ax_sum.scatter(fys, [ci] * len(fys),
                           c=[colors_m[ci]], s=30, alpha=0.8, label=label)
            ax_sum.scatter([np.mean(fys)], [ci],
                           c=[colors_m[ci]], s=100, marker="|",
                           linewidths=3, zorder=5)

    ax_sum.axvline(34, color="#3fb950", lw=1.5, linestyle="--", label="Right side threshold (Y=34m)")
    ax_sum.axvline(FH / 2, color="#8b949e", lw=1, linestyle=":")
    ax_sum.set_xlim(0, FH)
    ax_sum.set_xlabel("Normalized Field Y (m)", color="#8b949e", fontsize=8)
    ax_sum.set_yticks(range(len(matches)))
    ax_sum.set_yticklabels([MATCH_LABELS.get(m, m).replace("\n", " ") for m in matches],
                            fontsize=7)
    ax_sum.tick_params(colors="#8b949e")
    for sp in ax_sum.spines.values():
        sp.set_edgecolor("#30363d")
    ax_sum.legend(fontsize=6, labelcolor="white",
                  facecolor="#21262d", edgecolor="#30363d",
                  loc="upper right", ncol=2)

    plt.suptitle("TZI Cross-Match Validation: #6 牧野羽瑠 (Normalized, Waseda Always Attacks →)",
                 color="#58a6ff", fontsize=11, y=0.99)

    out_img = DATA_TZI / "cross_match_validation.png"
    plt.savefig(str(out_img), dpi=120, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"Saved → {out_img}")
    return out_img


def build_html(data):
    rows = ""
    for mid in MATCH_ORDER:
        if mid not in data:
            continue
        d = data[mid]
        fxs = [p["fx"] for p in d["positions"]]
        fys = [p["fy"] for p in d["positions"]]
        on_right = sum(1 for y in fys if y >= 34) / len(fys) * 100 if fys else 0
        ok = "✓" if on_right >= 55 else "⚠"
        col = "#3fb950" if on_right >= 55 else "#f0883e"
        rows += f"""<tr>
          <td style="color:#58a6ff">{mid}</td>
          <td>{MATCH_LABELS.get(mid,'').replace(chr(10),' ')}</td>
          <td>{d['player_id']}</td>
          <td>{d['n']}</td>
          <td>{d['centroid_x']:.1f}m</td>
          <td>{d['centroid_y']:.1f}m</td>
          <td style="color:{col};font-weight:700">{on_right:.0f}% {ok}</td>
          <td>flip1H={d['flip_1h']} flip2H={d['flip_2h']}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8">
<title>TZI Cross-Match Validation</title>
<style>
* {{box-sizing:border-box;margin:0;padding:0}}
body {{background:#0d1117;color:#e6edf3;font-family:'Segoe UI',sans-serif}}
.hero {{background:linear-gradient(135deg,#0f2027,#203a43,#2c5364);padding:24px 32px;border-bottom:1px solid #30363d}}
.hero h1 {{font-size:1.3rem;color:#58a6ff}} .hero p {{font-size:.82rem;color:#8b949e;margin-top:4px}}
.content {{max-width:1100px;margin:0 auto;padding:24px 20px}}
h2 {{font-size:1rem;padding-bottom:8px;border-bottom:1px solid #30363d;margin:24px 0 14px}}
table {{width:100%;border-collapse:collapse;font-size:12px}}
th {{background:#21262d;padding:8px 10px;text-align:left;color:#8b949e}}
td {{padding:7px 10px;border-bottom:1px solid #21262d}}
tr:hover td {{background:#161b22}}
img {{max-width:100%;border-radius:8px;margin:12px 0}}
.note {{background:#21262d;border:1px solid #30363d;border-radius:6px;padding:12px 16px;font-size:12px;color:#8b949e;margin-bottom:16px}}
</style></head><body>
<div class="hero">
  <h1>TZI Cross-Match Validation — #6 牧野羽瑠 Right-Back Tracking</h1>
  <p>Direction-normalized positions across all matches. Right-back should show Y ≥ 34m consistently.</p>
</div>
<div class="content">
  <div class="note">
    <strong style="color:#e6edf3">Validation Criterion:</strong>
    A right-back should appear on the right side of the field (Y ≥ 34m) in ≥55% of sightings
    in normalized coordinates (where Waseda always attacks toward X=105).
    If the heatmap concentrates at center-line or wrong side, it indicates tracking error.
  </div>
  <img src="cross_match_validation.png" alt="Cross-match validation heatmaps">
  <h2>Per-Match Summary</h2>
  <table><thead><tr>
    <th>Match ID</th><th>Opponent</th><th>Track ID</th><th>Sightings</th>
    <th>Centroid X</th><th>Centroid Y</th><th>% Right Side</th><th>Direction</th>
  </tr></thead><tbody>{rows}</tbody></table>
</div>
<div style="text-align:center;padding:20px;color:#8b949e;font-size:11px">
TZI v3 Cross-Match Validation · Indica Labs · 2026</div>
</body></html>"""

    out_html = DATA_TZI / "cross_match_validation.html"
    out_html.write_text(html, encoding="utf-8")
    print(f"Saved → {out_html}")


def main():
    print("=== TZI Cross-Match Validation ===")
    data = load_all()
    print(f"Loaded {len(data)} matches with #6 identified")

    for mid, d in data.items():
        fxs = [p["fx"] for p in d["positions"]]
        fys = [p["fy"] for p in d["positions"]]
        on_right = sum(1 for y in fys if y >= 34) / len(fys) * 100 if fys else 0
        print(f"  {mid}: n={d['n']}  cX={d['centroid_x']:.1f}m  cY={d['centroid_y']:.1f}m  "
              f"right_side={on_right:.0f}%  flip1H={d['flip_1h']}  flip2H={d['flip_2h']}")

    out = generate_report(data)
    build_html(data)
    print("\nDone.")


if __name__ == "__main__":
    main()
