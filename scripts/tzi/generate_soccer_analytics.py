#!/usr/bin/env python3
"""
TZI: Comprehensive Soccer Analytics Report
Generates full analysis for all matches including Japan vs England.

Analytics included:
- Player heatmaps (individual + team)
- Zone distribution (D1-A3)
- Formation shape diagram
- Team compactness (vertical/horizontal spread)
- Defensive line height
- Movement intensity (sprint estimation)
- Ball possession zone approximation
- Player count accuracy vs expected (22-40)
- All standard soccer positioning metrics

Usage:
    python generate_soccer_analytics.py
    python generate_soccer_analytics.py --match 20260325
    python generate_soccer_analytics.py --all

Output:
    data/tzi/match_YYYYMMDD/soccer_analytics.html
    data/tzi/match_YYYYMMDD/heatmap_team.png
    data/tzi/match_YYYYMMDD/formation_diagram.png
    data/tzi/soccer_analytics_all.html   (cross-match overview)
"""

import argparse
import base64
import json
import re
import sys
from collections import defaultdict
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from scipy.ndimage import gaussian_filter
from scipy.stats import gaussian_kde

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_TZI     = PROJECT_ROOT / "data" / "tzi"
FW, FH       = 105.0, 68.0

ALL_ZONES = ["D1", "D2", "D3", "A1", "A2", "A3"]
ZONE_BOUNDS = [0, 21, 42, 52.5, 63, 84, 105]
ZONE_COLORS = {
    "D1": "#3498db", "D2": "#2980b9", "D3": "#1abc9c",
    "A1": "#e74c3c", "A2": "#e67e22", "A3": "#f1c40f",
}

MATCH_META = {
    "20260314":    {"label": "vs 埼玉大",      "date": "2026-03-14", "comp": "TRM"},
    "20260316":    {"label": "vs 岐阜協立",    "date": "2026-03-16", "comp": "TRM"},
    "20260317mid": {"label": "vs 中京U-19 後半","date": "2026-03-17", "comp": "TRM"},
    "20260317osaka":{"label": "vs 大阪学院",   "date": "2026-03-17", "comp": "TRM"},
    "20260318":    {"label": "vs 作新学院",    "date": "2026-03-18", "comp": "TRM"},
    "20260325":    {"label": "vs 立教大",      "date": "2026-03-25", "comp": "TRM"},
    "20260329":    {"label": "vs 川崎U-18",   "date": "2026-03-29", "comp": "TRM"},
    "20260331_england": {"label": "日本代表 vs England", "date": "2026-03-31", "comp": "A代表"},
    "20260405":    {"label": "vs 獨協大",     "date": "2026-04-05", "comp": "TRM"},
}


# ── Data loading ──────────────────────────────────────────────────

def load_positions(match_dir: Path) -> list[dict]:
    """Load all player positions from best available source."""
    positions = []

    # Priority: players_v2.json > all_players_trajectory.json > jersey6_trajectory.json
    for fname in ["players_v2.json", "all_players_trajectory.json"]:
        p = match_dir / fname
        if p.exists():
            data = json.load(open(p))
            players = data.get("players", [])
            for pl in players:
                for s in pl.get("sightings", []):
                    positions.append({
                        "player_id": pl.get("player_id", "?"),
                        "jersey": pl.get("jersey_number"),
                        "fx": s["fx"], "fy": s["fy"],
                        "time_min": s["time_min"],
                        "half": s.get("half", "1H"),
                        "zone": s.get("zone", fx_to_zone(s["fx"])),
                    })
            break

    # England match: load separate team JSONs
    for fname in ["all_players_japan.json", "all_players_england.json"]:
        p = match_dir / fname
        if p.exists():
            data = json.load(open(p))
            team = data.get("team", "unknown")
            for det in data.get("detections", []):
                positions.append({
                    "player_id": team,
                    "jersey": None,
                    "fx": det["fx"], "fy": det["fy"],
                    "time_min": det["time_min"],
                    "half": "1H",
                    "zone": det.get("zone", fx_to_zone(det["fx"])),
                    "team": team,
                })

    return positions


def load_jersey6(match_dir: Path) -> list[dict]:
    p = match_dir / "jersey6_trajectory.json"
    if not p.exists():
        return []
    data = json.load(open(p))
    return [pos for pos in data.get("confirmed_positions", [])
            if "不明" not in pos.get("note", "")]


def load_subs(match_dir: Path) -> list[dict]:
    p = match_dir / "substitutions.json"
    return json.load(open(p)) if p.exists() else []


def fx_to_zone(fx):
    for i, (lo, hi) in enumerate(zip(ZONE_BOUNDS, ZONE_BOUNDS[1:])):
        if fx < hi:
            return ALL_ZONES[i]
    return "A3"


# ── Soccer metrics computation ────────────────────────────────────

def compute_metrics(positions: list[dict]) -> dict:
    if not positions:
        return {}

    xs = [p["fx"] for p in positions]
    ys = [p["fy"] for p in positions]

    # Zone distribution
    zone_dist = {z: 0 for z in ALL_ZONES}
    for p in positions:
        z = p.get("zone") or fx_to_zone(p["fx"])
        zone_dist[z] = zone_dist.get(z, 0) + 1
    total = max(sum(zone_dist.values()), 1)

    # Zone percentages
    zone_pct = {z: round(zone_dist[z] / total * 100, 1) for z in ALL_ZONES}

    # Attack vs Defence ratio
    attack_pct = (zone_dist["A1"] + zone_dist["A2"] + zone_dist["A3"]) / total * 100
    defence_pct = (zone_dist["D1"] + zone_dist["D2"] + zone_dist["D3"]) / total * 100

    # Team centroid (average position)
    centroid_x = float(np.mean(xs))
    centroid_y = float(np.mean(ys))

    # Vertical compactness (std of X positions = depth spread)
    v_compactness = float(np.std(xs)) if len(xs) > 1 else 0

    # Horizontal stretch (std of Y positions = width)
    h_stretch = float(np.std(ys)) if len(ys) > 1 else 0

    # Defensive line (X of the 4 deepest players)
    sorted_xs = sorted(xs)
    defensive_line = float(np.mean(sorted_xs[:4])) if len(sorted_xs) >= 4 else sorted_xs[0] if sorted_xs else 0

    # Attack height (X of the 3 highest players)
    attack_height = float(np.mean(sorted_xs[-3:])) if len(sorted_xs) >= 3 else sorted_xs[-1] if sorted_xs else 0

    # Team length (defensive line to attack height)
    team_length = attack_height - defensive_line

    # High press indicator: defensive line above 42m = pressing
    high_press = defensive_line > 42.0

    # Density in final third (>84m)
    final_third_pct = sum(1 for x in xs if x > 84) / len(xs) * 100

    # Movement intensity: compute per-player displacement between consecutive sightings
    by_player = defaultdict(list)
    for p in positions:
        by_player[p["player_id"]].append(p)
    total_dist = 0.0
    sprint_count = 0
    for pid, sights in by_player.items():
        sights.sort(key=lambda s: s["time_min"])
        for i in range(1, len(sights)):
            dx = sights[i]["fx"] - sights[i-1]["fx"]
            dy = sights[i]["fy"] - sights[i-1]["fy"]
            dt = max(sights[i]["time_min"] - sights[i-1]["time_min"], 0.01)
            dist = np.sqrt(dx**2 + dy**2)
            total_dist += dist
            speed = dist / dt  # m/min
            if speed > 15:  # >15 m/min between samples ≈ high intensity move
                sprint_count += 1

    avg_dist_per_player = total_dist / max(len(by_player), 1)

    # Possession zone approximation: mode zone (where most time is spent)
    possession_zone = max(zone_dist, key=zone_dist.get)

    # Ball touch zone approximation: area with highest player density
    if len(xs) >= 3:
        kde_x = gaussian_kde(xs)
        xgrid = np.linspace(0, FW, 100)
        density = kde_x(xgrid)
        peak_x = float(xgrid[np.argmax(density)])
        peak_zone = fx_to_zone(peak_x)
    else:
        peak_x = centroid_x
        peak_zone = fx_to_zone(peak_x)

    # Unique players
    n_players = len(set(p["player_id"] for p in positions))

    return {
        "n_positions": len(positions),
        "n_players": n_players,
        "zone_dist": zone_dist,
        "zone_pct": zone_pct,
        "attack_pct": round(attack_pct, 1),
        "defence_pct": round(defence_pct, 1),
        "centroid_x": round(centroid_x, 1),
        "centroid_y": round(centroid_y, 1),
        "v_compactness": round(v_compactness, 1),
        "h_stretch": round(h_stretch, 1),
        "defensive_line": round(defensive_line, 1),
        "attack_height": round(attack_height, 1),
        "team_length": round(team_length, 1),
        "high_press": high_press,
        "final_third_pct": round(final_third_pct, 1),
        "avg_dist_per_player": round(avg_dist_per_player, 1),
        "sprint_count": sprint_count,
        "possession_zone": possession_zone,
        "peak_density_x": round(peak_x, 1),
        "peak_zone": peak_zone,
    }


# ── Chart generation ──────────────────────────────────────────────

def draw_field(ax, alpha_lines=0.4):
    """Draw a soccer field on a matplotlib axes (0→FW, 0→FH)."""
    ax.set_facecolor("#1a4a1a")
    # Outline
    ax.add_patch(patches.Rectangle((0, 0), FW, FH, lw=2, ec="white", fc="none", alpha=alpha_lines))
    # Centre line
    ax.axvline(FW/2, color="white", lw=1, alpha=alpha_lines)
    # Centre circle
    ax.add_patch(patches.Circle((FW/2, FH/2), 9.15, lw=1, ec="white", fc="none", alpha=alpha_lines))
    # Penalty areas
    for x_base, w in [(0, 16.5), (FW-16.5, 16.5)]:
        ax.add_patch(patches.Rectangle((x_base, (FH-40.3)/2), 16.5, 40.3, lw=1, ec="white", fc="none", alpha=alpha_lines))
    # Zone separators (D1-A3)
    for x in ZONE_BOUNDS[1:-1]:
        ax.axvline(x, color="yellow", lw=0.5, alpha=0.2, ls="--")
    ax.set_xlim(0, FW); ax.set_ylim(0, FH)
    ax.axis("off")


def generate_heatmap(positions, out_path: Path, title: str = "Team Heatmap",
                     color="hot", j6_positions=None):
    """Gaussian-smoothed heatmap on soccer field."""
    xs = [p["fx"] for p in positions]
    ys = [p["fy"] for p in positions]
    if len(xs) < 2:
        return None

    fig, ax = plt.subplots(figsize=(12, 7.5), facecolor="#0d1117")
    draw_field(ax)

    # Heatmap
    heatmap, xedges, yedges = np.histogram2d(xs, ys, bins=[52, 34],
                                              range=[[0, FW], [0, FH]])
    heatmap = gaussian_filter(heatmap, sigma=1.5)
    extent = [0, FW, 0, FH]
    im = ax.imshow(heatmap.T, extent=extent, origin="lower", cmap=color,
                   alpha=0.65, aspect="auto", vmin=0)

    # Jersey #6 overlay
    if j6_positions:
        j6xs = [p["fx"] for p in j6_positions]
        j6ys = [p["fy"] for p in j6_positions]
        ax.scatter(j6xs, j6ys, c="cyan", s=80, zorder=5, marker="*",
                   edgecolors="white", lw=0.5, label="#6 羽瑠")
        ax.legend(loc="upper right", facecolor="#0d1117", labelcolor="white", fontsize=9)

    # Zone labels
    for i, zone in enumerate(ALL_ZONES):
        cx = (ZONE_BOUNDS[i] + ZONE_BOUNDS[i+1]) / 2
        ax.text(cx, FH + 1.5, zone, ha="center", va="bottom",
                color=ZONE_COLORS[zone], fontsize=9, fontweight="bold")

    plt.colorbar(im, ax=ax, fraction=0.02, pad=0.02, label="Density")
    ax.set_title(title, color="white", fontsize=13, pad=14)
    plt.tight_layout()
    plt.savefig(str(out_path), dpi=140, bbox_inches="tight", facecolor="#0d1117")
    plt.close()
    return out_path


def generate_formation_diagram(positions, metrics: dict, out_path: Path,
                                match_label: str, j6_positions=None):
    """Average position diagram (formation shape)."""
    by_player = defaultdict(list)
    for p in positions:
        by_player[p["player_id"]].append((p["fx"], p["fy"]))

    fig, ax = plt.subplots(figsize=(12, 7.5), facecolor="#0d1117")
    draw_field(ax)

    # Plot average position per player
    for pid, pts in by_player.items():
        avg_x = float(np.mean([p[0] for p in pts]))
        avg_y = float(np.mean([p[1] for p in pts]))
        n     = len(pts)
        size  = min(200, 60 + n * 8)
        ax.scatter(avg_x, avg_y, s=size, c="#58a6ff", alpha=0.8, zorder=4,
                   edgecolors="white", lw=0.8)
        ax.text(avg_x, avg_y - 2.5, pid, ha="center", va="top",
                color="white", fontsize=7, fontweight="bold")

    # Jersey #6 highlight
    if j6_positions:
        j6x = float(np.mean([p["fx"] for p in j6_positions]))
        j6y = float(np.mean([p["fy"] for p in j6_positions]))
        ax.scatter(j6x, j6y, s=300, c="cyan", zorder=6, marker="*",
                   edgecolors="white", lw=1)
        ax.text(j6x, j6y + 3, "#6", ha="center", color="cyan",
                fontsize=10, fontweight="bold")

    # Defensive line indicator
    dl = metrics.get("defensive_line", 0)
    ax.axvline(dl, color="#e74c3c", lw=1.5, ls="--", alpha=0.7, label=f"Def.Line {dl:.0f}m")
    ax.legend(loc="upper left", facecolor="#0d1117", labelcolor="white", fontsize=8)

    # Team centroid
    cx = metrics.get("centroid_x", 52)
    cy = metrics.get("centroid_y", 34)
    ax.scatter(cx, cy, s=120, c="yellow", marker="+", linewidths=2, zorder=7)

    ax.set_title(f"Formation Shape — {match_label}", color="white", fontsize=12, pad=10)
    plt.tight_layout()
    plt.savefig(str(out_path), dpi=140, bbox_inches="tight", facecolor="#0d1117")
    plt.close()
    return out_path


def generate_zone_timeline(positions, out_path: Path, match_label: str):
    """Zone occupancy over time (stacked area chart)."""
    # Sort by time and bin into 5-min windows
    times = sorted(set(round(p["time_min"]/5)*5 for p in positions))
    zone_over_time = {z: [] for z in ALL_ZONES}

    for t in times:
        window = [p for p in positions if abs(p["time_min"] - t) <= 2.5]
        total  = max(len(window), 1)
        zdist  = {z: 0 for z in ALL_ZONES}
        for p in window:
            zdist[p.get("zone") or fx_to_zone(p["fx"])] += 1
        for z in ALL_ZONES:
            zone_over_time[z].append(zdist[z] / total * 100)

    if not times:
        return None

    fig, ax = plt.subplots(figsize=(13, 5), facecolor="#0d1117")
    ax.set_facecolor("#161b22")
    bottom = np.zeros(len(times))
    for z in ALL_ZONES:
        vals = np.array(zone_over_time[z])
        col  = ZONE_COLORS[z]
        ax.bar(times, vals, bottom=bottom, width=4.5, color=col,
               alpha=0.8, label=z, edgecolor="none")
        bottom += vals

    # Half-time marker
    ax.axvline(45, color="white", lw=1, ls="--", alpha=0.5)
    ax.text(45, 103, "HT", ha="center", color="white", fontsize=8)

    ax.set_xlim(0, max(times) + 5)
    ax.set_ylim(0, 105)
    ax.set_xlabel("Match Time (min)", color="#8b949e")
    ax.set_ylabel("Zone Occupancy %", color="#8b949e")
    ax.set_title(f"Zone Occupancy Timeline — {match_label}", color="white", fontsize=12)
    ax.tick_params(colors="#666")
    ax.legend(loc="upper right", ncol=6, facecolor="#21262d",
              labelcolor="white", fontsize=8)
    plt.tight_layout()
    plt.savefig(str(out_path), dpi=130, bbox_inches="tight", facecolor="#0d1117")
    plt.close()
    return out_path


def fig_to_b64(path: Path) -> str:
    if not path or not path.exists():
        return ""
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


# ── HTML report ───────────────────────────────────────────────────

def metric_chip(label, value, color="#58a6ff", unit=""):
    return f"""<div style="background:#21262d;border:1px solid #30363d;border-radius:8px;padding:12px 18px;min-width:130px;text-align:center">
  <div style="font-size:1.6rem;font-weight:700;color:{color}">{value}{unit}</div>
  <div style="font-size:.72rem;color:#8b949e;margin-top:2px">{label}</div>
</div>"""


def zone_bar(zone_pct: dict) -> str:
    rows = ""
    for z in ALL_ZONES:
        pct = zone_pct.get(z, 0)
        col = ZONE_COLORS[z]
        rows += f"""<tr>
          <td style="padding:4px 10px;white-space:nowrap">
            <span style="background:{col};color:#fff;padding:1px 8px;border-radius:3px;font-size:11px;font-weight:700">{z}</span>
          </td>
          <td style="padding:4px 8px;width:55%">
            <div style="background:#21262d;border-radius:3px;height:7px">
              <div style="background:{col};width:{min(pct,100):.1f}%;height:7px;border-radius:3px"></div>
            </div>
          </td>
          <td style="padding:4px 6px;font-size:11px;color:#8b949e">{pct:.1f}%</td>
        </tr>"""
    return f'<table style="width:100%;border-collapse:collapse">{rows}</table>'


def build_match_html(match_id: str, match_dir: Path, positions: list,
                     j6_pos: list, metrics: dict, subs: list,
                     heatmap_b64: str, formation_b64: str, timeline_b64: str) -> str:
    meta    = MATCH_META.get(match_id, {"label": match_id, "date": "", "comp": ""})
    n_sub   = len(subs)

    press_badge = ('<span style="background:#e74c3c;color:#fff;padding:2px 8px;border-radius:4px;font-size:11px">HIGH PRESS</span>'
                   if metrics.get("high_press") else
                   '<span style="background:#2c3e50;color:#aaa;padding:2px 8px;border-radius:4px;font-size:11px">MID BLOCK</span>')

    sub_rows = "".join(f"""<tr>
      <td style="padding:5px 10px">{s['time_min']}min</td>
      <td style="padding:5px 10px;color:#f85149">OUT #{s.get('player_out_jersey','?')} {s['player_out']}</td>
      <td style="padding:5px 10px;color:#3fb950">IN #{s.get('player_in_jersey','?')} {s['player_in']}</td>
      <td style="padding:5px 10px">{s.get('zone','?')}</td>
      <td style="padding:5px 10px">{int(s.get('confidence',0)*100)}%</td>
    </tr>""" for s in subs)

    img = lambda b64, alt: (f'<img src="{b64}" style="width:100%;border-radius:6px;border:1px solid #30363d">'
                             if b64 else f'<div style="padding:20px;color:#666;text-align:center">{alt}</div>')

    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TZI Soccer Analytics — {meta['label']}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0d1117;color:#e6edf3;font-family:'Segoe UI',Arial,sans-serif;font-size:14px}}
.hero{{background:linear-gradient(135deg,#0f2027,#203a43,#2c5364);padding:28px 36px;border-bottom:1px solid #30363d}}
.hero h1{{font-size:1.5rem;color:#58a6ff;margin-bottom:4px}}.hero p{{color:#8b949e;font-size:.82rem}}
.chips{{display:flex;gap:12px;flex-wrap:wrap;padding:16px 30px;background:#161b22;border-bottom:1px solid #30363d}}
.content{{max-width:1300px;margin:0 auto;padding:28px 24px}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:24px}}
.section{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:18px;margin-bottom:20px}}
.section h2{{font-size:.95rem;color:#e6edf3;margin-bottom:14px;padding-bottom:8px;border-bottom:1px solid #30363d}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th{{background:#21262d;padding:7px 10px;text-align:left;color:#8b949e;font-weight:600}}
td{{border-bottom:1px solid #21262d;vertical-align:middle}}
</style></head><body>
<div class="hero">
  <h1>⚽ TZI Soccer Analytics — {meta['label']}</h1>
  <p>{meta['date']} | {meta['comp']} | Indica Labs TZI System</p>
</div>
<div class="chips">
  {metric_chip("Unique Players", metrics.get("n_players","?"), "#3fb950")}
  {metric_chip("Attack Zone %", f"{metrics.get('attack_pct',0):.0f}", "#e74c3c", "%")}
  {metric_chip("Defence Zone %", f"{metrics.get('defence_pct',0):.0f}", "#3498db", "%")}
  {metric_chip("Team Centroid", f"{metrics.get('centroid_x',0):.0f}", "#58a6ff", "m")}
  {metric_chip("Defensive Line", f"{metrics.get('defensive_line',0):.0f}", "#e67e22", "m")}
  {metric_chip("Team Length", f"{metrics.get('team_length',0):.0f}", "#d2a8ff", "m")}
  {metric_chip("V.Compactness", f"{metrics.get('v_compactness',0):.1f}", "#79c0ff", "m")}
  {metric_chip("H.Stretch", f"{metrics.get('h_stretch',0):.1f}", "#56d364", "m")}
  {metric_chip("Final Third %", f"{metrics.get('final_third_pct',0):.0f}", "#f1c40f", "%")}
  {metric_chip("Substitutions", n_sub, "#bc8cff")}
  <div style="display:flex;align-items:center;gap:8px">{press_badge}</div>
</div>
<div class="content">

  <div class="grid2">
    <div class="section">
      <h2>ゾーン別占有率 (Zone Distribution)</h2>
      {zone_bar(metrics.get("zone_pct",{}))}
      <div style="margin-top:12px;font-size:11px;color:#8b949e;display:flex;gap:16px">
        <span>主要占有ゾーン: <strong style="color:{ZONE_COLORS.get(metrics.get('possession_zone','D2'),'#fff')}">{metrics.get('possession_zone','?')}</strong></span>
        <span>ボール密集X: <strong style="color:#f1c40f">{metrics.get('peak_density_x',0):.0f}m ({metrics.get('peak_zone','?')})</strong></span>
      </div>
    </div>
    <div class="section">
      <h2>ポジショニング指標 (Positioning Metrics)</h2>
      <table><tbody>
        <tr><td style="padding:5px 8px;color:#8b949e">チーム重心X</td><td style="padding:5px 8px;font-weight:600">{metrics.get('centroid_x',0):.1f}m</td></tr>
        <tr><td style="padding:5px 8px;color:#8b949e">チーム重心Y</td><td style="padding:5px 8px;font-weight:600">{metrics.get('centroid_y',0):.1f}m</td></tr>
        <tr><td style="padding:5px 8px;color:#8b949e">守備ライン高さ</td><td style="padding:5px 8px;font-weight:600">{metrics.get('defensive_line',0):.1f}m</td></tr>
        <tr><td style="padding:5px 8px;color:#8b949e">最高到達点（攻撃）</td><td style="padding:5px 8px;font-weight:600">{metrics.get('attack_height',0):.1f}m</td></tr>
        <tr><td style="padding:5px 8px;color:#8b949e">チーム縦幅 (Team Length)</td><td style="padding:5px 8px;font-weight:600">{metrics.get('team_length',0):.1f}m</td></tr>
        <tr><td style="padding:5px 8px;color:#8b949e">縦コンパクトさ (V.Std)</td><td style="padding:5px 8px;font-weight:600">{metrics.get('v_compactness',0):.1f}m</td></tr>
        <tr><td style="padding:5px 8px;color:#8b949e">横幅 (H.Std)</td><td style="padding:5px 8px;font-weight:600">{metrics.get('h_stretch',0):.1f}m</td></tr>
        <tr><td style="padding:5px 8px;color:#8b949e">ハイプレス</td><td style="padding:5px 8px;font-weight:600">{"✅ Yes" if metrics.get('high_press') else "❌ No"}</td></tr>
        <tr><td style="padding:5px 8px;color:#8b949e">ファイナルサード滞在%</td><td style="padding:5px 8px;font-weight:600">{metrics.get('final_third_pct',0):.1f}%</td></tr>
        <tr><td style="padding:5px 8px;color:#8b949e">推定移動距離/選手</td><td style="padding:5px 8px;font-weight:600">{metrics.get('avg_dist_per_player',0):.1f}m</td></tr>
        <tr><td style="padding:5px 8px;color:#8b949e">高強度移動回数</td><td style="padding:5px 8px;font-weight:600">{metrics.get('sprint_count',0)}</td></tr>
      </tbody></table>
    </div>
  </div>

  <div class="section">
    <h2>ヒートマップ — 選手密度 (Player Density Heatmap)</h2>
    {img(heatmap_b64, "No heatmap available")}
  </div>

  <div class="section">
    <h2>フォーメーション図 — 平均ポジション (Average Formation)</h2>
    {img(formation_b64, "No formation diagram available")}
  </div>

  <div class="section">
    <h2>ゾーン推移タイムライン (Zone Occupancy Over Time)</h2>
    {img(timeline_b64, "No timeline available")}
  </div>

  {'<div class="section"><h2>交代記録 Substitutions (' + str(n_sub) + '件)</h2><table><thead><tr><th>Time</th><th>OUT</th><th>IN</th><th>Zone</th><th>Confidence</th></tr></thead><tbody>' + sub_rows + '</tbody></table></div>' if subs else ''}

</div>
<div style="text-align:center;padding:20px;color:#8b949e;font-size:11px">
  TZI — Tactical Zone Intelligence · Indica Labs · 2026
</div></body></html>"""


# ── Cross-match overview ──────────────────────────────────────────

def build_overview_html(all_results: list) -> str:
    rows = ""
    for r in all_results:
        m   = r["metrics"]
        meta= r["meta"]
        zp  = m.get("zone_pct", {})
        press= "🔴 HIGH" if m.get("high_press") else "🔵 MID"
        j6   = "✅" if r["has_j6"] else "—"

        def zpct(z):
            v = zp.get(z, 0)
            col = ZONE_COLORS.get(z, "#888")
            return f'<td style="text-align:center;padding:5px 8px;color:{col};font-weight:{"700" if v>20 else "400"}">{v:.0f}%</td>'

        rows += f"""<tr>
          <td style="padding:7px 12px;font-weight:600;white-space:nowrap">{meta['date']}</td>
          <td style="padding:7px 12px">{meta['label']}</td>
          <td style="padding:7px 12px;text-align:center">{m.get('n_players','?')}</td>
          {"".join(zpct(z) for z in ALL_ZONES)}
          <td style="padding:7px 12px;text-align:center;color:#e74c3c;font-weight:700">{m.get('attack_pct',0):.0f}%</td>
          <td style="padding:7px 12px;text-align:center">{m.get('defensive_line',0):.0f}m</td>
          <td style="padding:7px 12px;text-align:center">{m.get('team_length',0):.0f}m</td>
          <td style="padding:7px 12px;text-align:center">{m.get('centroid_x',0):.0f}m</td>
          <td style="padding:7px 12px;text-align:center;font-size:11px">{press}</td>
          <td style="padding:7px 12px;text-align:center">{j6}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TZI Soccer Analytics — 全試合サマリー</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0d1117;color:#e6edf3;font-family:'Segoe UI',Arial,sans-serif}}
.hero{{background:linear-gradient(135deg,#0f2027,#203a43,#2c5364);padding:28px 36px;border-bottom:1px solid #30363d}}
.hero h1{{font-size:1.6rem;color:#58a6ff}}.hero p{{color:#8b949e;font-size:.82rem;margin-top:4px}}
.content{{max-width:1500px;margin:0 auto;padding:28px 24px;overflow-x:auto}}
table{{border-collapse:collapse;font-size:12px;min-width:900px}}
th{{background:#21262d;padding:8px 10px;text-align:center;color:#8b949e;position:sticky;top:0}}
th:first-child,th:nth-child(2){{text-align:left}}
tr:hover td{{background:#161b22}}
td{{border-bottom:1px solid #21262d}}
</style></head><body>
<div class="hero">
  <h1>⚽ TZI Soccer Analytics — 全試合サマリー</h1>
  <p>Indica Labs TZI System · {len(all_results)} matches · 牧野羽瑠 #6 追跡</p>
</div>
<div class="content">
<table>
<thead><tr>
  <th>Date</th><th>Match</th><th>Players</th>
  {"".join(f'<th style="color:{ZONE_COLORS[z]}">{z}</th>' for z in ALL_ZONES)}
  <th>Attack%</th><th>Def.Line</th><th>Length</th><th>Centroid</th><th>Press</th><th>#6</th>
</tr></thead>
<tbody>{rows}</tbody>
</table>
</div>
<div style="text-align:center;padding:20px;color:#8b949e;font-size:11px">
  TZI — Tactical Zone Intelligence · Indica Labs · 2026
</div></body></html>"""


# ── Main ──────────────────────────────────────────────────────────

def process_match(match_id: str) -> dict | None:
    match_dir = DATA_TZI / f"match_{match_id}"
    if not match_dir.exists():
        return None

    meta = MATCH_META.get(match_id, {"label": match_id, "date": "", "comp": ""})
    print(f"\n=== {match_id} — {meta['label']} ===")

    positions = load_positions(match_dir)
    j6_pos    = load_jersey6(match_dir)
    subs      = load_subs(match_dir)

    if not positions:
        print(f"  No position data found — skip")
        return None

    print(f"  Positions: {len(positions)}  Players: {len(set(p['player_id'] for p in positions))}")
    print(f"  Jersey #6 positions: {len(j6_pos)}")

    metrics = compute_metrics(positions)
    print(f"  Centroid: {metrics['centroid_x']:.1f}m  Attack%: {metrics['attack_pct']}%  Press: {metrics['high_press']}")

    # Generate charts
    hm_path = match_dir / "heatmap_team.png"
    generate_heatmap(positions, hm_path, f"Player Heatmap — {meta['label']}", j6_positions=j6_pos)

    fm_path = match_dir / "formation_diagram.png"
    generate_formation_diagram(positions, metrics, fm_path, meta['label'], j6_positions=j6_pos)

    tl_path = match_dir / "zone_timeline.png"
    generate_zone_timeline(positions, tl_path, meta['label'])

    # Build HTML
    html = build_match_html(
        match_id, match_dir, positions, j6_pos, metrics, subs,
        fig_to_b64(hm_path), fig_to_b64(fm_path), fig_to_b64(tl_path)
    )
    html_path = match_dir / "soccer_analytics.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"  Report → {html_path}")

    return {
        "match_id":  match_id,
        "meta":      meta,
        "metrics":   metrics,
        "has_j6":    len(j6_pos) > 0,
        "html_path": html_path,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", default="all", help="Match ID or 'all'")
    args = ap.parse_args()

    if args.match == "all":
        match_ids = [d.name.replace("match_", "")
                     for d in sorted(DATA_TZI.iterdir())
                     if d.is_dir() and d.name.startswith("match_")]
    else:
        match_ids = [args.match]

    print(f"=== TZI Soccer Analytics ({len(match_ids)} matches) ===")

    all_results = []
    for mid in match_ids:
        result = process_match(mid)
        if result:
            all_results.append(result)

    # Cross-match overview
    if len(all_results) > 1:
        overview_html = build_overview_html(all_results)
        overview_path = DATA_TZI / "soccer_analytics_all.html"
        overview_path.write_text(overview_html, encoding="utf-8")
        print(f"\nOverview → {overview_path}")

    print(f"\n=== DONE: {len(all_results)} matches processed ===")


if __name__ == "__main__":
    main()
