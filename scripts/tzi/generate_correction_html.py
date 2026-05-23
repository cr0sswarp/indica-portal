#!/usr/bin/env python3
"""
TZI: Generate an interactive HTML verification/correction page for jersey #6 identification.

For each sampled frame in the match directory, the page displays:
- The annotated frame image (embedded as base64)
- A table of all detected players and their field coordinates
- Context: prev / current / next frame side by side
- A summary table linking time -> recommended jersey #6 candidate

Since no JavaScript server is needed, the page is a static read-only
verification tool. After reviewing the page, the user can manually edit
jersey6_trajectory.json to correct misidentifications.

Usage:
    python generate_correction_html.py --match 20260325
    python generate_correction_html.py --match 20260329

Output:
    data/tzi/match_YYYYMMDD/correction_ui.html
"""

import argparse
import base64
import json
import re
import sys
from pathlib import Path

# ── Constants ────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent.parent
FW, FH = 105.0, 68.0

ZONE_COLORS = {
    "D1": "#3498db", "D2": "#2980b9", "D3": "#1abc9c",
    "A1": "#e74c3c", "A2": "#e67e22", "A3": "#f1c40f",
}


# ── Helpers ───────────────────────────────────────────────────────

def fx_to_zone(fx: float) -> str:
    if fx < 21:     return "D1"
    elif fx < 42:   return "D2"
    elif fx < 52.5: return "D3"
    elif fx < 63:   return "A1"
    elif fx < 84:   return "A2"
    else:           return "A3"


def encode_image(path: Path) -> str:
    """Return base64-encoded data-URI for an image (JPEG or PNG)."""
    if not path.exists():
        return ""
    ext = path.suffix.lower()
    mime = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def _time_from_filename(name: str) -> float:
    """Parse local_min float from filenames like annotated_1H_5.0min.jpg."""
    m = re.search(r"_(\d+(?:\.\d+)?)min", name)
    return float(m.group(1)) if m else 0.0


def _half_from_filename(name: str) -> str:
    m = re.search(r"_(1H|2H)_", name)
    return m.group(1) if m else "?H"


def _zone_badge(zone: str) -> str:
    col = ZONE_COLORS.get(zone, "#888")
    return f'<span class="zone-tag" style="background:{col}">{zone}</span>'


# ── Data loading ──────────────────────────────────────────────────

def load_trajectory(match_dir: Path) -> list:
    """Load jersey6_trajectory.json confirmed positions."""
    traj_path = match_dir / "jersey6_trajectory.json"
    if not traj_path.exists():
        return []
    with open(traj_path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("confirmed_positions", [])


def load_all_detections(match_dir: Path) -> dict:
    """
    Load all_detections.json if present (produced by analyze_match.py).
    Returns dict: time_min -> list of detection dicts.
    """
    det_path = match_dir / "all_detections.json"
    if not det_path.exists():
        return {}
    with open(det_path, encoding="utf-8") as f:
        raw = json.load(f)
    # Normalize: raw may be a list of dicts with 'time_min' key
    grouped = {}
    for item in (raw if isinstance(raw, list) else []):
        key = item.get("time_min", item.get("t_min", 0))
        grouped.setdefault(key, []).append(item)
    return grouped


def collect_frame_images(match_dir: Path) -> list:
    """
    Collect annotated frame images from frames_annotated/ or frames/.
    Returns sorted list of Path objects.
    """
    for sub in ("frames_annotated", "frames"):
        d = match_dir / sub
        if d.exists():
            imgs = sorted(
                [p for p in d.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png")],
                key=lambda p: (_half_from_filename(p.name), _time_from_filename(p.name)),
            )
            if imgs:
                return imgs
    return []


# ── HTML generation ───────────────────────────────────────────────

CSS = """
:root {
  --bg: #0d1117; --surface: #161b22; --surface2: #21262d;
  --border: #30363d; --text: #e6edf3; --muted: #8b949e;
  --accent: #58a6ff; --green: #3fb950; --red: #f85149;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: 'Helvetica Neue', Arial, sans-serif;
  font-size: 14px;
  line-height: 1.5;
}
.header {
  background: linear-gradient(135deg, #161b22, #1a1f2e);
  padding: 28px 40px;
  border-bottom: 1px solid var(--border);
  position: sticky; top: 0; z-index: 100;
}
.header h1 { margin: 0; font-size: 20px; letter-spacing: 1px; }
.header .sub { color: var(--muted); margin-top: 4px; font-size: 12px; }
.container { max-width: 1400px; margin: 0 auto; padding: 28px 24px; }

/* Summary table */
.summary-section { margin-bottom: 36px; }
.section-title {
  font-size: 15px; font-weight: 600;
  margin: 0 0 14px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}
.summary-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.summary-table th {
  background: var(--surface2); padding: 9px 12px;
  text-align: left; color: var(--muted); font-weight: 600;
  position: sticky; top: 80px;
}
.summary-table td { padding: 8px 12px; border-bottom: 1px solid var(--border); }
.summary-table tr:hover td { background: var(--surface2); }
.zone-tag {
  display: inline-block; padding: 2px 8px; border-radius: 4px;
  font-size: 11px; font-weight: 700; color: white;
}
.manual-badge {
  display: inline-block; padding: 2px 8px; border-radius: 4px;
  font-size: 11px; font-weight: 600; background: #1f4e2e; color: var(--green);
}
.auto-badge {
  display: inline-block; padding: 2px 8px; border-radius: 4px;
  font-size: 11px; font-weight: 600; background: #1f2e3a; color: var(--accent);
}
.unknown-badge {
  display: inline-block; padding: 2px 8px; border-radius: 4px;
  font-size: 11px; font-weight: 600; background: #3a1f1f; color: var(--red);
}

/* Frame grid */
.frames-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
  gap: 20px;
}
.frame-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}
.frame-card.is-unknown { border-color: #5a2020; }
.frame-card.is-manual  { border-color: #1a4a2e; }
.frame-header {
  padding: 10px 14px;
  background: var(--surface2);
  font-size: 12px;
  font-weight: 600;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.frame-img {
  width: 100%; display: block;
  max-height: 260px; object-fit: contain;
  background: #000;
}
.frame-body { padding: 12px 14px; }
.det-table { width: 100%; border-collapse: collapse; font-size: 11px; margin-top: 6px; }
.det-table th {
  background: #0d1117; padding: 5px 8px;
  text-align: left; color: var(--muted);
}
.det-table td { padding: 5px 8px; border-bottom: 1px solid #21262d; }
.det-table tr.is-j6 td { background: #1a3020; }
.det-table tr.is-j6 td:first-child::before {
  content: '#6 ';
  color: var(--green); font-weight: 700;
}
.coord { font-family: monospace; color: var(--muted); }
.no-frame { color: var(--muted); font-style: italic; font-size: 12px; text-align: center; padding: 20px; }

/* Context strip */
.ctx-strip {
  display: grid;
  grid-template-columns: 1fr 2fr 1fr;
  gap: 4px;
  margin-bottom: 8px;
}
.ctx-thumb { text-align: center; }
.ctx-thumb img { width: 100%; border-radius: 4px; border: 1px solid var(--border); }
.ctx-thumb .ctx-label { font-size: 10px; color: var(--muted); margin-top: 2px; }
.ctx-thumb.ctx-current img { border-color: var(--accent); }

/* Correction hint */
.correction-hint {
  background: #1a2030;
  border: 1px solid #2a3555;
  border-radius: 6px;
  padding: 10px 14px;
  font-size: 12px;
  color: #aac4f0;
  margin-bottom: 8px;
  line-height: 1.6;
}

/* Stats bar */
.stats-bar {
  display: flex; gap: 20px; flex-wrap: wrap;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 14px 20px; margin-bottom: 28px;
  font-size: 12px;
}
.stat-item strong { color: var(--accent); font-size: 18px; display: block; line-height: 1; }
.stat-item span   { color: var(--muted); }
"""


def _det_rows_html(dets: list, j6_fx: float | None, j6_fy: float | None) -> str:
    """Generate <tr> rows for detection table."""
    if not dets:
        return '<tr><td colspan="5" style="color:#666;font-style:italic">No detection data</td></tr>'
    rows = ""
    for i, d in enumerate(dets):
        fx   = d.get("fx", 0)
        fy   = d.get("fy", 0)
        zone = d.get("zone") or fx_to_zone(fx)
        zcol = ZONE_COLORS.get(zone, "#888")

        # Highlight row if this is the known jersey-6 position
        is_j6 = (
            j6_fx is not None and j6_fy is not None
            and abs(fx - j6_fx) < 3.0 and abs(fy - j6_fy) < 3.0
        )
        row_cls = ' class="is-j6"' if is_j6 else ""
        rows += (
            f"<tr{row_cls}>"
            f"<td>{i + 1}</td>"
            f'<td class="coord">({fx:.1f}, {fy:.1f})</td>'
            f'<td><span class="zone-tag" style="background:{zcol}">{zone}</span></td>'
            f"<td>{d.get('px', '-')}, {d.get('py', '-')}</td>"
            f"<td>{d.get('area', '-')}</td>"
            f"</tr>"
        )
    return rows


def _note_badge(note: str) -> str:
    note_l = note.lower()
    if "不明" in note or "unknown" in note_l:
        return '<span class="unknown-badge">Unknown</span>'
    if "手動修正" in note or "manual" in note_l:
        return '<span class="manual-badge">Manual</span>'
    return '<span class="auto-badge">Auto</span>'


def build_html(
    match_id: str,
    frames: list,
    trajectory: list,
    all_detections: dict,
    match_dir: Path,
) -> str:
    """Build the full HTML string."""

    # Build time -> trajectory entry lookup
    traj_by_time: dict = {}
    for entry in trajectory:
        key = round(entry["time_min"], 1)
        traj_by_time[key] = entry

    # Stats
    n_confirmed = len(trajectory)
    n_unknown   = sum(1 for e in trajectory if "不明" in e.get("note", ""))
    n_manual    = sum(1 for e in trajectory if "手動修正" in e.get("note", ""))
    n_auto      = n_confirmed - n_unknown - n_manual

    # ── Summary table ─────────────────────────────────────────────
    summary_rows = ""
    for entry in sorted(trajectory, key=lambda e: e["time_min"]):
        zone = fx_to_zone(entry.get("fx", 0))
        zcol = ZONE_COLORS.get(zone, "#888")
        half = entry.get("half", "?")
        t    = entry["time_min"]
        fx   = entry.get("fx", 0)
        fy   = entry.get("fy", 0)
        note = entry.get("note", "")
        badge = _note_badge(note)
        summary_rows += (
            f"<tr>"
            f"<td>{half} {t:.1f}m</td>"
            f'<td class="coord">({fx:.1f}, {fy:.1f})</td>'
            f'<td><span class="zone-tag" style="background:{zcol}">{zone}</span></td>'
            f"<td>{badge}</td>"
            f"<td style='font-size:11px;color:var(--muted)'>{note[:60]}</td>"
            f"</tr>"
        )

    # ── Frame cards ───────────────────────────────────────────────
    frame_cards_html = ""
    for idx, img_path in enumerate(frames):
        half_lbl  = _half_from_filename(img_path.name)
        local_min = _time_from_filename(img_path.name)

        # Find matching trajectory entry (±0.3 min tolerance)
        traj_entry = None
        for e in trajectory:
            if e.get("half") == half_lbl and abs(e["time_min"] - local_min) < 0.3:
                traj_entry = e
                break
            # Also try matching by rounding
            if abs(round(e["time_min"], 1) - round(local_min, 1)) < 0.3:
                traj_entry = e
                break

        j6_fx = traj_entry["fx"] if traj_entry else None
        j6_fy = traj_entry["fy"] if traj_entry else None

        # Detections for this time point
        t_key = round(local_min, 1)
        dets  = all_detections.get(t_key, all_detections.get(round(local_min, 0), []))

        # Card class
        card_cls = "frame-card"
        if traj_entry:
            note = traj_entry.get("note", "")
            if "不明" in note:
                card_cls += " is-unknown"
            elif "手動修正" in note:
                card_cls += " is-manual"

        # Context strip: prev / current / next
        prev_img = frames[idx - 1] if idx > 0 else None
        next_img = frames[idx + 1] if idx < len(frames) - 1 else None

        def _thumb(p, label, is_current=False):
            if p is None:
                return f'<div class="ctx-thumb"><div class="no-frame">—</div><div class="ctx-label">{label}</div></div>'
            uri  = encode_image(p)
            cur  = ' ctx-current' if is_current else ''
            tag  = f'<img src="{uri}" alt="{label}">' if uri else '<div class="no-frame">no image</div>'
            return f'<div class="ctx-thumb{cur}">{tag}<div class="ctx-label">{label}</div></div>'

        ctx_html = (
            '<div class="ctx-strip">'
            + _thumb(prev_img,      "prev")
            + _thumb(img_path,      f"{half_lbl} {local_min:.1f}m", is_current=True)
            + _thumb(next_img,      "next")
            + "</div>"
        )

        # Main image (full size)
        main_uri = encode_image(img_path)
        main_img_tag = (
            f'<img class="frame-img" src="{main_uri}" alt="{img_path.name}">'
            if main_uri
            else '<div class="no-frame">Image not found</div>'
        )

        # Header
        badge_html = ""
        if traj_entry:
            badge_html = _note_badge(traj_entry.get("note", ""))
            badge_html += f" &nbsp;fx={j6_fx:.1f} fy={j6_fy:.1f}"
        frame_card_header = (
            f'<div class="frame-header">'
            f'<span>{half_lbl} {local_min:.1f}min  |  {img_path.name}</span>'
            f"<span>{badge_html}</span>"
            f"</div>"
        )

        # Detection table
        det_rows = _det_rows_html(dets, j6_fx, j6_fy)

        # Correction hint
        hint = ""
        if traj_entry and "不明" in traj_entry.get("note", ""):
            hint = (
                '<div class="correction-hint">'
                "<strong>Unknown position</strong> — review this frame and update "
                "<code>jersey6_trajectory.json</code> with the correct fx/fy. "
                "Remove the <em>unknown</em> note after correction."
                "</div>"
            )

        # Assemble card
        frame_cards_html += f"""
<div class="{card_cls}" id="frame-{idx}">
  {frame_card_header}
  {ctx_html}
  {main_img_tag}
  <div class="frame-body">
    {hint}
    <table class="det-table">
      <thead>
        <tr>
          <th>#</th>
          <th>Field (m)</th>
          <th>Zone</th>
          <th>Pixel (px,py)</th>
          <th>Area</th>
        </tr>
      </thead>
      <tbody>
        {det_rows}
      </tbody>
    </table>
  </div>
</div>"""

    # ── Assemble full page ────────────────────────────────────────
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TZI Correction UI — match_{match_id}</title>
<style>
{CSS}
</style>
</head>
<body>

<div class="header">
  <h1>TZI Correction UI &mdash; match_{match_id}</h1>
  <div class="sub">
    Read-only verification page. Review frame detections, then manually edit
    <code>jersey6_trajectory.json</code> to correct jersey #6 positions.
    Green-highlighted rows = current jersey #6 candidate in that frame.
  </div>
</div>

<div class="container">

  <!-- Stats -->
  <div class="stats-bar">
    <div class="stat-item"><strong>{n_confirmed}</strong><span>Total positions</span></div>
    <div class="stat-item"><strong style="color:var(--green)">{n_manual}</strong><span>Manual corrections</span></div>
    <div class="stat-item"><strong style="color:var(--accent)">{n_auto}</strong><span>Auto-detected</span></div>
    <div class="stat-item"><strong style="color:var(--red)">{n_unknown}</strong><span>Unknown / uncertain</span></div>
    <div class="stat-item"><strong>{len(frames)}</strong><span>Sampled frames</span></div>
  </div>

  <!-- Trajectory summary table -->
  <div class="summary-section">
    <div class="section-title">Jersey #6 Trajectory Summary</div>
    <table class="summary-table">
      <thead>
        <tr>
          <th>Time</th>
          <th>Field coords (m)</th>
          <th>Zone</th>
          <th>Source</th>
          <th>Note</th>
        </tr>
      </thead>
      <tbody>
        {summary_rows}
      </tbody>
    </table>
  </div>

  <!-- Frame-by-frame inspection -->
  <div class="section-title">Frame-by-Frame Inspection</div>
  <p style="color:var(--muted);font-size:12px;margin-top:-8px;margin-bottom:20px">
    Each card shows: context strip (prev / current / next frame),
    the annotated frame at full width, and a table of all detected players.
    Rows highlighted in green match the current jersey #6 trajectory entry.
    Cards with a red border = unknown/uncertain positions.
    Cards with a green border = manually corrected positions.
  </p>
  <div class="frames-grid">
    {frame_cards_html}
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
        description="Generate a read-only HTML correction page for jersey #6 identification."
    )
    p.add_argument("--match", required=True,
                   help="Match date string, e.g. 20260325")
    return p.parse_args()


def main():
    args      = parse_args()
    match_dir = PROJECT_ROOT / "data" / "tzi" / f"match_{args.match}"

    if not match_dir.exists():
        print(f"ERROR: match directory not found: {match_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"=== TZI: generate_correction_html  match={args.match} ===")
    print(f"Match dir: {match_dir}")

    trajectory     = load_trajectory(match_dir)
    all_detections = load_all_detections(match_dir)
    frames         = collect_frame_images(match_dir)

    print(f"Trajectory entries : {len(trajectory)}")
    print(f"Detection records  : {sum(len(v) for v in all_detections.values())}")
    print(f"Frame images found : {len(frames)}")

    if not trajectory and not frames:
        print("WARNING: No trajectory data and no frame images found.", file=sys.stderr)
        print("         Run analyze_match.py or track_all_players.py first.", file=sys.stderr)

    html     = build_html(args.match, frames, trajectory, all_detections, match_dir)
    out_path = match_dir / "correction_ui.html"
    out_path.write_text(html, encoding="utf-8")

    size_kb = out_path.stat().st_size // 1024
    print(f"\nHTML saved : {out_path}  ({size_kb} KB)")
    print(f"Open in browser: file://{out_path}")


if __name__ == "__main__":
    main()
