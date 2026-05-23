#!/usr/bin/env python3
"""
TZI: Multi-match comparison report for jersey #6.

Reads jersey6_trajectory.json from each match directory and generates
a single HTML report comparing zone scores, progression, and field coverage
across all matches.

Usage:
    # Auto-discover all match_YYYYMMDD directories
    python multi_match_report.py

    # Specify match IDs explicitly
    python multi_match_report.py --matches 20260325 20260329

Output:
    data/tzi/multi_match_report.html
"""

import argparse
import base64
import json
import re
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from scipy.ndimage import gaussian_filter

# ── Constants ────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR     = PROJECT_ROOT / "data" / "tzi"
OUT_HTML     = DATA_DIR / "multi_match_report.html"

FW, FH = 105.0, 68.0

ALL_ZONES  = ["D1", "D2", "D3", "A1", "A2", "A3"]
ZONE_COLORS_HEX = {
    "D1": "#3498db", "D2": "#2980b9", "D3": "#1abc9c",
    "A1": "#e74c3c", "A2": "#e67e22", "A3": "#f1c40f",
}
MATCH_PALETTE = [
    "#58a6ff", "#3fb950", "#f0883e", "#d2a8ff",
    "#79c0ff", "#56d364", "#ffa657", "#bc8cff",
]


# ── Helpers ───────────────────────────────────────────────────────

def fx_to_zone(fx: float) -> str:
    if fx < 21:     return "D1"
    elif fx < 42:   return "D2"
    elif fx < 52.5: return "D3"
    elif fx < 63:   return "A1"
    elif fx < 84:   return "A2"
    else:           return "A3"


def encode_image(path: Path) -> str:
    """Return base64-encoded data-URI for image, or empty string."""
    if not path or not path.exists():
        return ""
    ext  = path.suffix.lower()
    mime = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def compute_zone_score(positions: list) -> dict:
    """
    Compute 5-metric zone score (each 0-20, total 0-100).
    P: Positioning (attacking-zone reach rate)
    M: Movement dynamism (distance per minute)
    D: Decision speed (position-change speed)
    V: Field vision coverage (x-range)
    B: Body axis stability (y-std)
    """
    if len(positions) < 2:
        return {"P": 0, "M": 0, "D": 0, "V": 0, "B": 0, "total": 0}

    xs    = [p["fx"] for p in positions]
    ys    = [p["fy"] for p in positions]
    times = [p["time_min"] for p in positions]

    # P: attacking zone rate
    atk = sum(1 for x in xs if x >= 52.5)
    p_score = min(20, int(atk / len(xs) * 40))

    # M: total distance / elapsed time
    total_dist = sum(
        np.sqrt((xs[i] - xs[i-1])**2 + (ys[i] - ys[i-1])**2)
        for i in range(1, len(xs))
    )
    elapsed = max(1, times[-1] - times[0])
    m_score = min(20, int(total_dist / elapsed * 2))

    # D: average time gap between sightings
    gaps = [times[i] - times[i-1] for i in range(1, len(times)) if times[i] > times[i-1]]
    avg_gap = np.mean(gaps) if gaps else 99
    d_score = min(20, max(0, int(20 - avg_gap * 0.5)))

    # V: x-range coverage
    x_range = max(xs) - min(xs)
    v_score = min(20, int(x_range / FW * 40))

    # B: y-stability
    y_std   = np.std(ys) if len(ys) > 1 else 10
    b_score = min(20, max(0, int(20 - y_std * 0.5)))

    total = p_score + m_score + d_score + v_score + b_score
    return {"P": p_score, "M": m_score, "D": d_score, "V": v_score, "B": b_score, "total": total}


def score_level(score: int) -> tuple:
    if score >= 90: return "Elite Zone",    "#e74c3c"
    if score >= 70: return "Near Zone",     "#e67e22"
    if score >= 50: return "Normal",        "#27ae60"
    if score >= 30: return "Low Focus",     "#f39c12"
    return             "Needs Review",      "#e74c3c"


def zone_distribution(positions: list) -> dict:
    dist = {z: 0 for z in ALL_ZONES}
    for p in positions:
        z = fx_to_zone(p.get("fx", 0))
        dist[z] = dist.get(z, 0) + 1
    return dist


# ── Data loading ──────────────────────────────────────────────────

def discover_matches() -> list:
    """Return sorted list of match IDs found in data/tzi/."""
    ids = []
    for d in sorted(DATA_DIR.iterdir()):
        if d.is_dir() and re.match(r"match_\d{8}$", d.name):
            ids.append(d.name.replace("match_", ""))
    return ids


def load_match_data(match_id: str):
    """
    Load all available data for a match.
    Returns None if jersey6_trajectory.json is missing or empty.
    """
    match_dir  = DATA_DIR / f"match_{match_id}"
    traj_path  = match_dir / "jersey6_trajectory.json"
    if not traj_path.exists():
        return None

    with open(traj_path, encoding="utf-8") as f:
        traj = json.load(f)

    positions = [
        p for p in traj.get("confirmed_positions", [])
        if "不明" not in p.get("note", "")
    ]
    if not positions:
        return None

    # Find heatmap image (prefer latest/precise versions)
    heatmap_path = None
    for candidate in [
        "heatmap_jersey6_latest.png",
        "heatmap_jersey6_precise.png",
        "heatmap_jersey6.png",
    ]:
        p = match_dir / candidate
        if p.exists():
            heatmap_path = p
            break

    scores    = compute_zone_score(positions)
    zone_dist = zone_distribution(positions)

    # Try to read match label from a summary JSON
    label = f"Match {match_id}"
    sp = match_dir / "full_match_summary.json"
    if sp.exists():
        with open(sp, encoding="utf-8") as f:
            sm = json.load(f)
        label = sm.get("match", label)

    return {
        "id":          match_id,
        "label":       label,
        "match_dir":   match_dir,
        "positions":   positions,
        "scores":      scores,
        "zone_dist":   zone_dist,
        "heatmap":     heatmap_path,
        "traj":        traj,
        "n_positions": len(positions),
        "n_raw":       len(traj.get("confirmed_positions", [])),
    }


# ── Chart generation ──────────────────────────────────────────────

def generate_score_chart(matches: list, out_path: Path) -> None:
    """Bar chart: total zone score per match, plus component breakdown."""
    n      = len(matches)
    totals = [m["scores"]["total"] for m in matches]
    cols   = [MATCH_PALETTE[i % len(MATCH_PALETTE)] for i in range(n)]

    components  = ["P", "M", "D", "V", "B"]
    comp_labels = {
        "P": "Positioning",
        "M": "Movement",
        "D": "Decision",
        "V": "Vision",
        "B": "Balance",
    }
    comp_colors = ["#58a6ff", "#3fb950", "#f0883e", "#d2a8ff", "#79c0ff"]

    fig, axes = plt.subplots(1, 2, figsize=(14, 5), facecolor="#0d1117")

    # Left: total score
    ax = axes[0]
    ax.set_facecolor("#161b22")
    bars = ax.bar(range(n), totals, color=cols, edgecolor="#30363d", linewidth=0.8)
    ax.set_xticks(range(n))
    ax.set_xticklabels([m["id"] for m in matches], color="#8b949e", fontsize=9, rotation=20, ha="right")
    ax.set_ylim(0, 100)
    ax.set_ylabel("Zone Score (0-100)", color="#8b949e", fontsize=10)
    ax.set_title("Total Zone Score per Match", color="white", fontsize=12, pad=10)
    ax.tick_params(colors="#666")
    ax.axhline(70, color="#e67e22", alpha=0.5, lw=1, ls="--")
    ax.axhline(50, color="#3fb950", alpha=0.3, lw=1, ls="--")
    ax.text(n - 0.5, 71, "Near Zone", color="#e67e22", fontsize=8, va="bottom")
    for spine in ax.spines.values():
        spine.set_color("#30363d")
    for bar, total in zip(bars, totals):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.5,
                str(total), ha="center", va="bottom", color="white", fontsize=9, fontweight="bold")

    # Right: stacked component breakdown
    ax2 = axes[1]
    ax2.set_facecolor("#161b22")
    bottoms = np.zeros(n)
    for comp, ccol in zip(components, comp_colors):
        vals = [m["scores"][comp] for m in matches]
        ax2.bar(range(n), vals, bottom=bottoms, color=ccol,
                label=f"{comp}: {comp_labels[comp]}", edgecolor="#0d1117", linewidth=0.5)
        bottoms += np.array(vals)
    ax2.set_xticks(range(n))
    ax2.set_xticklabels([m["id"] for m in matches], color="#8b949e", fontsize=9, rotation=20, ha="right")
    ax2.set_ylim(0, 100)
    ax2.set_ylabel("Score Components", color="#8b949e", fontsize=10)
    ax2.set_title("Score Component Breakdown", color="white", fontsize=12, pad=10)
    ax2.tick_params(colors="#666")
    ax2.legend(loc="upper left", facecolor="#21262d", labelcolor="white", fontsize=8, framealpha=0.9)
    for spine in ax2.spines.values():
        spine.set_color("#30363d")

    plt.tight_layout(pad=2)
    plt.savefig(str(out_path), dpi=150, bbox_inches="tight", facecolor="#0d1117")
    plt.close()
    print(f"  Score chart: {out_path}")


def generate_zone_comparison_chart(matches: list, out_path: Path) -> None:
    """Grouped bar chart: zone distribution per match."""
    n      = len(matches)
    zones  = ALL_ZONES
    x      = np.arange(len(zones))
    width  = 0.8 / max(n, 1)

    fig, ax = plt.subplots(figsize=(12, 5), facecolor="#0d1117")
    ax.set_facecolor("#161b22")

    for i, m in enumerate(matches):
        total = max(1, sum(m["zone_dist"].values()))
        pcts  = [m["zone_dist"].get(z, 0) / total * 100 for z in zones]
        offset = (i - n / 2 + 0.5) * width
        col    = MATCH_PALETTE[i % len(MATCH_PALETTE)]
        ax.bar(x + offset, pcts, width * 0.9, label=m["id"], color=col,
               edgecolor="#0d1117", linewidth=0.5)

    ax.set_xticks(x)
    ax.set_xticklabels(zones, color="white", fontsize=11)
    ax.set_ylabel("Zone Presence (%)", color="#8b949e", fontsize=10)
    ax.set_title("Zone Distribution Comparison - Jersey #6", color="white", fontsize=13, pad=10)
    ax.tick_params(colors="#666")
    ax.axvline(2.5, color="#444", lw=1, ls="--")
    ylim_top = ax.get_ylim()[1]
    ax.text(1.25, ylim_top * 0.97, "Defense", ha="center", color="#3498db", fontsize=9)
    ax.text(4.5,  ylim_top * 0.97, "Attack",  ha="center", color="#e74c3c", fontsize=9)
    ax.legend(facecolor="#21262d", labelcolor="white", fontsize=9)
    for spine in ax.spines.values():
        spine.set_color("#30363d")

    plt.tight_layout(pad=2)
    plt.savefig(str(out_path), dpi=150, bbox_inches="tight", facecolor="#0d1117")
    plt.close()
    print(f"  Zone comparison chart: {out_path}")


def generate_progression_chart(matches: list, out_path: Path) -> None:
    """
    Line chart showing jersey #6 field-x position over match time,
    one line per match. Useful for spotting progression patterns.
    """
    fig, ax = plt.subplots(figsize=(14, 5), facecolor="#0d1117")
    ax.set_facecolor("#111827")

    for i, m in enumerate(matches):
        col  = MATCH_PALETTE[i % len(MATCH_PALETTE)]
        pts  = sorted(m["positions"], key=lambda p: p["time_min"])
        if not pts:
            continue
        ts = [p["time_min"] for p in pts]
        xs = [p["fx"]       for p in pts]
        ax.plot(ts, xs, "o-", color=col, lw=1.8, ms=5,
                label=m["id"], markeredgecolor="#0d1117", markeredgewidth=0.5)

    ax.axhline(52.5, color="#e74c3c", alpha=0.4, lw=1, ls="--")
    ax.axhline(FW / 2, color="white", alpha=0.2, lw=0.8)
    ax.text(1, 54, "Attacking half boundary", color="#e74c3c", fontsize=8, alpha=0.7)

    ax.set_xlim(0, 90)
    ax.set_ylim(0, FW)
    ax.set_xlabel("Match Time (min)", color="#8b949e", fontsize=10)
    ax.set_ylabel("Field X Position (m)", color="#8b949e", fontsize=10)
    ax.set_title("Jersey #6 Field X Position over Time", color="white", fontsize=13, pad=10)
    ax.tick_params(colors="#666")
    ax.legend(facecolor="#21262d", labelcolor="white", fontsize=9)
    for spine in ax.spines.values():
        spine.set_color("#30363d")

    plt.tight_layout(pad=2)
    plt.savefig(str(out_path), dpi=150, bbox_inches="tight", facecolor="#0d1117")
    plt.close()
    print(f"  Progression chart: {out_path}")


# ── Insight generation ────────────────────────────────────────────

def generate_insights(matches: list) -> list:
    """Return list of plain-text insight strings."""
    insights = []
    if not matches:
        return ["No match data available."]

    scores  = [m["scores"]["total"] for m in matches]
    best_i  = int(np.argmax(scores))
    worst_i = int(np.argmin(scores))

    insights.append(
        f"Best performance: {matches[best_i]['id']} with zone score {scores[best_i]}/100."
    )
    insights.append(
        f"Lowest performance: {matches[worst_i]['id']} with zone score {scores[worst_i]}/100."
    )

    # Score trend
    if len(matches) >= 2:
        delta = scores[-1] - scores[0]
        if delta > 5:
            insights.append(
                f"Positive score trend: +{delta:.0f} points from {matches[0]['id']} "
                f"to {matches[-1]['id']}."
            )
        elif delta < -5:
            insights.append(
                f"Declining score trend: {delta:.0f} points from {matches[0]['id']} "
                f"to {matches[-1]['id']}."
            )
        else:
            insights.append(
                "Score is relatively stable across matches "
                f"(range: {min(scores)}-{max(scores)})."
            )

    # Dominant zone across all matches
    aggregate_zones = {z: 0 for z in ALL_ZONES}
    for m in matches:
        for z, cnt in m["zone_dist"].items():
            aggregate_zones[z] = aggregate_zones.get(z, 0) + cnt
    dom_zone = max(aggregate_zones, key=aggregate_zones.get)
    dom_pct  = aggregate_zones[dom_zone] / max(1, sum(aggregate_zones.values())) * 100
    insights.append(
        f"Most frequent zone overall: {dom_zone} ({dom_pct:.0f}% of sightings)."
    )

    # Attacking involvement
    atk_zones = ["A1", "A2", "A3"]
    for m in matches:
        total = max(1, sum(m["zone_dist"].values()))
        atk   = sum(m["zone_dist"].get(z, 0) for z in atk_zones)
        pct   = atk / total * 100
        if pct > 40:
            insights.append(
                f"{m['id']}: High attacking involvement - "
                f"{pct:.0f}% of sightings in A1-A3."
            )
        elif pct < 10:
            insights.append(
                f"{m['id']}: Low attacking zone presence - "
                f"only {pct:.0f}% of sightings in A1-A3."
            )

    # Component insights
    avg_scores = {
        k: np.mean([m["scores"][k] for m in matches])
        for k in ["P", "M", "D", "V", "B"]
    }
    weakest   = min(avg_scores, key=avg_scores.get)
    strongest = max(avg_scores, key=avg_scores.get)
    comp_names = {
        "P": "Positioning", "M": "Movement",
        "D": "Decision speed", "V": "Vision coverage", "B": "Body balance",
    }
    insights.append(
        f"Strongest metric: {comp_names[strongest]} (avg {avg_scores[strongest]:.1f}/20)."
    )
    insights.append(
        f"Weakest metric: {comp_names[weakest]} (avg {avg_scores[weakest]:.1f}/20) - "
        f"focus area for improvement."
    )

    return insights


# ── HTML assembly ─────────────────────────────────────────────────

CSS = """
:root {
  --bg: #0d1117; --surface: #161b22; --surface2: #21262d;
  --border: #30363d; --text: #e6edf3; --muted: #8b949e;
  --accent: #58a6ff; --green: #3fb950; --red: #f85149;
  --orange: #f0883e;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font-family: 'Helvetica Neue', Arial, sans-serif; font-size: 14px;
  line-height: 1.5;
}
.header {
  background: linear-gradient(135deg, #161b22, #1a1f2e);
  padding: 32px 40px; border-bottom: 1px solid var(--border);
}
.header h1 { margin: 0; font-size: 22px; letter-spacing: 1.5px; }
.header .sub { color: var(--muted); margin-top: 6px; font-size: 12px; }
.container { max-width: 1300px; margin: 0 auto; padding: 32px 24px; }
.section-title {
  font-size: 16px; font-weight: 600; margin: 36px 0 14px;
  padding-bottom: 8px; border-bottom: 1px solid var(--border);
}
.card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 20px;
}
.grid-auto { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px,1fr)); gap: 16px; }
.match-card { position: relative; }
.match-id {
  font-size: 11px; font-weight: 700; color: var(--muted);
  text-transform: uppercase; letter-spacing: 1px; margin-bottom: 4px;
}
.match-label { font-size: 13px; margin-bottom: 12px; }
.score-big { font-size: 48px; font-weight: 700; line-height: 1; }
.score-level { font-size: 13px; font-weight: 600; margin-top: 4px; margin-bottom: 12px; }
.metric-rows { margin-top: 10px; }
.metric-row {
  display: flex; align-items: center; gap: 8px;
  padding: 4px 0; border-bottom: 1px solid var(--border); font-size: 12px;
}
.metric-row:last-child { border: none; }
.metric-key { width: 20px; font-weight: 700; color: var(--muted); }
.metric-bar-bg { flex: 1; background: var(--surface2); border-radius: 3px; height: 5px; }
.metric-bar    { height: 5px; border-radius: 3px; background: var(--accent); }
.metric-val    { width: 32px; text-align: right; color: var(--muted); }
.zone-tag {
  display: inline-block; padding: 2px 8px; border-radius: 4px;
  font-size: 11px; font-weight: 700; color: white;
}
.chart-img { width: 100%; border-radius: 8px; display: block; }
.heatmaps-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px; margin-top: 16px;
}
.heatmap-card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.heatmap-label {
  padding: 10px 14px; background: var(--surface2);
  font-size: 12px; font-weight: 600; color: var(--text);
}
.heatmap-img { width: 100%; display: block; max-height: 300px; object-fit: contain; background: #000; }
.no-heatmap { text-align: center; padding: 40px; color: var(--muted); font-size: 12px; font-style: italic; }
.insights-list { list-style: none; padding: 0; margin: 0; }
.insights-list li {
  padding: 10px 14px; border-bottom: 1px solid var(--border);
  font-size: 13px; display: flex; align-items: flex-start; gap: 10px;
}
.insights-list li:last-child { border: none; }
.insights-list li::before {
  content: '+'; color: var(--green); font-weight: 700;
  font-size: 16px; line-height: 1.2; flex-shrink: 0;
}
.zone-dist-row { display: flex; align-items: center; gap: 8px; margin: 5px 0; font-size: 12px; }
.zdist-label  { width: 26px; font-weight: 700; }
.zdist-bar-bg { flex: 1; background: var(--surface2); border-radius: 3px; height: 7px; }
.zdist-bar    { height: 7px; border-radius: 3px; }
.zdist-pct    { width: 36px; text-align: right; color: var(--muted); }
table.match-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.match-table th {
  background: var(--surface2); padding: 10px 12px;
  text-align: left; color: var(--muted); font-weight: 600;
}
.match-table td { padding: 9px 12px; border-bottom: 1px solid var(--border); }
.match-table tr:last-child td { border: none; }
"""


def _score_card(m: dict, colour: str) -> str:
    scores      = m["scores"]
    level_str, level_col = score_level(scores["total"])
    metrics_html = ""
    for k in ["P", "M", "D", "V", "B"]:
        pct = scores[k] / 20 * 100
        metrics_html += (
            f'<div class="metric-row">'
            f'<span class="metric-key">{k}</span>'
            f'<div class="metric-bar-bg"><div class="metric-bar" style="width:{pct:.0f}%"></div></div>'
            f'<span class="metric-val">{scores[k]}/20</span>'
            f"</div>"
        )

    # Zone distribution mini-bars
    total_sights = max(1, sum(m["zone_dist"].values()))
    zone_bars = ""
    for z in ALL_ZONES:
        pct  = m["zone_dist"].get(z, 0) / total_sights * 100
        zcol = ZONE_COLORS_HEX.get(z, "#888")
        zone_bars += (
            f'<div class="zone-dist-row">'
            f'<span class="zdist-label">{z}</span>'
            f'<div class="zdist-bar-bg">'
            f'<div class="zdist-bar" style="width:{pct:.1f}%;background:{zcol}"></div>'
            f"</div>"
            f'<span class="zdist-pct">{pct:.0f}%</span>'
            f"</div>"
        )

    return f"""
<div class="card match-card" style="border-top:3px solid {colour}">
  <div class="match-id">{m["id"]}</div>
  <div class="match-label">{m["label"]}</div>
  <div class="score-big" style="color:{level_col}">{scores["total"]}</div>
  <div class="score-level" style="color:{level_col}">{level_str}</div>
  <div style="font-size:11px;color:var(--muted)">
    {m["n_positions"]} positions used / {m["n_raw"]} total
  </div>
  <div class="metric-rows">{metrics_html}</div>
  <div style="margin-top:12px;border-top:1px solid var(--border);padding-top:12px">
    <div style="font-size:11px;color:var(--muted);margin-bottom:6px">Zone Distribution</div>
    {zone_bars}
  </div>
</div>"""


def build_html(
    matches: list,
    score_chart_path: Path,
    zone_chart_path:  Path,
    prog_chart_path:  Path,
    insights: list,
) -> str:

    # Score cards
    score_cards_html = ""
    for i, m in enumerate(matches):
        col = MATCH_PALETTE[i % len(MATCH_PALETTE)]
        score_cards_html += _score_card(m, col)

    # Heatmaps
    heatmaps_html = ""
    for i, m in enumerate(matches):
        col = MATCH_PALETTE[i % len(MATCH_PALETTE)]
        if m["heatmap"]:
            uri = encode_image(m["heatmap"])
            img_tag = (
                f'<img class="heatmap-img" src="{uri}" alt="heatmap {m["id"]}">'
                if uri
                else '<div class="no-heatmap">Image too large to embed</div>'
            )
        else:
            img_tag = '<div class="no-heatmap">No heatmap available</div>'
        heatmaps_html += f"""
<div class="heatmap-card" style="border-top:3px solid {col}">
  <div class="heatmap-label">{m["id"]} &mdash; {m["label"]}</div>
  {img_tag}
</div>"""

    # Charts
    def chart_tag(path, alt):
        uri = encode_image(path)
        if uri:
            return f'<img class="chart-img" src="{uri}" alt="{alt}">'
        return f'<div style="color:var(--muted);font-style:italic">Chart not generated</div>'

    score_chart_tag = chart_tag(score_chart_path, "Zone Score Chart")
    zone_chart_tag  = chart_tag(zone_chart_path,  "Zone Distribution Chart")
    prog_chart_tag  = chart_tag(prog_chart_path,  "Progression Chart")

    # Insights list
    insights_html = "".join(f"<li>{ins}</li>" for ins in insights)

    # Summary comparison table
    table_rows = ""
    for i, m in enumerate(matches):
        s   = m["scores"]
        col = MATCH_PALETTE[i % len(MATCH_PALETTE)]
        lv, lc = score_level(s["total"])
        dom_zone = max(m["zone_dist"], key=lambda z: m["zone_dist"][z])
        zcol     = ZONE_COLORS_HEX.get(dom_zone, "#888")
        table_rows += (
            f"<tr>"
            f'<td><span style="display:inline-block;width:10px;height:10px;'
            f'border-radius:50%;background:{col};margin-right:6px"></span>{m["id"]}</td>'
            f"<td>{m['label']}</td>"
            f'<td><strong style="color:{lc}">{s["total"]}</strong></td>'
            f'<td style="color:{lc}">{lv}</td>'
            f"<td>{s['P']}/{s['M']}/{s['D']}/{s['V']}/{s['B']}</td>"
            f'<td><span class="zone-tag" style="background:{zcol}">{dom_zone}</span></td>'
            f"<td>{m['n_positions']}</td>"
            f"</tr>"
        )

    n_matches = len(matches)
    avg_score = round(np.mean([m["scores"]["total"] for m in matches]), 1) if matches else 0

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TZI Multi-Match Report -- Jersey #6</title>
<style>
{CSS}
</style>
</head>
<body>

<div class="header">
  <h1>TZI Multi-Match Report &mdash; Jersey #6</h1>
  <div class="sub">
    Tactical Zone Intelligence &nbsp;&middot;&nbsp; Indica Labs &nbsp;&middot;&nbsp;
    {n_matches} matches analysed &nbsp;&middot;&nbsp; Average zone score: {avg_score}/100
  </div>
</div>

<div class="container">

  <!-- Per-match score cards -->
  <div class="section-title">Per-Match Zone Scores</div>
  <div class="grid-auto">
    {score_cards_html}
  </div>

  <!-- Summary table -->
  <div class="section-title">Comparison Table</div>
  <div class="card">
    <table class="match-table">
      <thead>
        <tr>
          <th>Match ID</th>
          <th>Label</th>
          <th>Score</th>
          <th>Level</th>
          <th>P/M/D/V/B</th>
          <th>Dominant Zone</th>
          <th>Positions</th>
        </tr>
      </thead>
      <tbody>{table_rows}</tbody>
    </table>
  </div>

  <!-- Score chart -->
  <div class="section-title">Score Progression &amp; Breakdown</div>
  <div class="card">{score_chart_tag}</div>

  <!-- Zone comparison chart -->
  <div class="section-title">Zone Distribution Comparison</div>
  <div class="card">{zone_chart_tag}</div>

  <!-- Progression chart -->
  <div class="section-title">Field Position Progression (X-axis over time)</div>
  <div class="card">{prog_chart_tag}</div>

  <!-- Heatmaps side by side -->
  <div class="section-title">Heatmaps</div>
  <div class="heatmaps-grid">
    {heatmaps_html}
  </div>

  <!-- Key insights -->
  <div class="section-title">Key Insights</div>
  <div class="card">
    <ul class="insights-list">
      {insights_html}
    </ul>
  </div>

</div>

<div style="text-align:center;padding:24px;color:var(--muted);font-size:11px">
  TZI &mdash; Tactical Zone Intelligence &nbsp;&middot;&nbsp; Indica Labs &nbsp;&middot;&nbsp; 2026
</div>
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Generate a multi-match comparison report for jersey #6."
    )
    p.add_argument(
        "--matches", nargs="*",
        help="Match IDs to include (e.g. 20260325 20260329). "
             "Defaults to all match_YYYYMMDD directories in data/tzi/.",
    )
    return p.parse_args()


def main():
    args = parse_args()

    if args.matches:
        match_ids = args.matches
    else:
        match_ids = discover_matches()

    if not match_ids:
        print("ERROR: No match directories found in data/tzi/", file=sys.stderr)
        sys.exit(1)

    print(f"=== TZI: multi_match_report ===")
    print(f"Matches to process: {match_ids}")

    # Load data
    matches = []
    for mid in match_ids:
        data = load_match_data(mid)
        if data is None:
            print(f"  SKIP {mid}: jersey6_trajectory.json missing or empty")
            continue
        matches.append(data)
        print(f"  Loaded {mid}: {data['n_positions']} positions, score={data['scores']['total']}")

    if not matches:
        print("ERROR: No usable match data found.", file=sys.stderr)
        sys.exit(1)

    # Generate charts
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    score_chart = DATA_DIR / "multi_score_chart.png"
    zone_chart  = DATA_DIR / "multi_zone_chart.png"
    prog_chart  = DATA_DIR / "multi_progression_chart.png"

    print("\nGenerating charts...")
    generate_score_chart(matches, score_chart)
    generate_zone_comparison_chart(matches, zone_chart)
    generate_progression_chart(matches, prog_chart)

    # Generate insights
    insights = generate_insights(matches)
    print("\nInsights:")
    for ins in insights:
        print(f"  + {ins}")

    # Build HTML
    html = build_html(matches, score_chart, zone_chart, prog_chart, insights)
    OUT_HTML.write_text(html, encoding="utf-8")

    size_kb = OUT_HTML.stat().st_size // 1024
    print(f"\nReport saved : {OUT_HTML}  ({size_kb} KB)")
    print(f"Open in browser: file://{OUT_HTML}")


if __name__ == "__main__":
    main()
