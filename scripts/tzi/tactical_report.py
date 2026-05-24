#!/usr/bin/env python3
"""
TZI Tactical Report — プロフェッショナル・スカウティングレポート生成

tactical_intelligence.py の分析結果から、Hudl級のHTMLレポートを生成する。
レーダーチャート / ポジショナルグリッド / 認知タイムライン / クロス試合推移。
"""

import json
import math
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_TZI = PROJECT_ROOT / "data" / "tzi"

LANES_JP = ["左WG", "左HS", "中央", "右HS", "右WG"]
ZONES_JP = ["D1", "D2", "D3", "A1", "A2", "A3"]


def _radar_svg(metrics: dict, size=260) -> str:
    """5軸レーダーチャートをSVGで描画."""
    axes = [
        ("認知", metrics.get("cognition", 0)),
        ("原則", metrics.get("principle", 0)),
        ("創造", metrics.get("creativity", 0)),
        ("主役", metrics.get("protagonist", 0)),
        ("IQ",   metrics.get("tactical_iq", 0)),
    ]
    cx = cy = size / 2
    R = size / 2 - 42
    n = len(axes)
    pts, grid, labels = [], [], []
    for ring in (0.25, 0.5, 0.75, 1.0):
        ring_pts = []
        for i in range(n):
            ang = -math.pi / 2 + 2 * math.pi * i / n
            x = cx + R * ring * math.cos(ang)
            y = cy + R * ring * math.sin(ang)
            ring_pts.append(f"{x:.1f},{y:.1f}")
        grid.append(f'<polygon points="{" ".join(ring_pts)}" fill="none" '
                    f'stroke="#2a3550" stroke-width="1"/>')
    for i, (lbl, val) in enumerate(axes):
        ang = -math.pi / 2 + 2 * math.pi * i / n
        v = (val or 0) / 100
        x = cx + R * v * math.cos(ang)
        y = cy + R * v * math.sin(ang)
        pts.append(f"{x:.1f},{y:.1f}")
        lx = cx + (R + 24) * math.cos(ang)
        ly = cy + (R + 24) * math.sin(ang)
        labels.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" fill="#9fb3d9" font-size="12" '
            f'text-anchor="middle" dominant-baseline="middle">{lbl}</text>'
            f'<text x="{lx:.1f}" y="{ly+14:.1f}" fill="#5eead4" font-size="11" '
            f'font-weight="700" text-anchor="middle">{val or 0}</text>')
        grid.append(f'<line x1="{cx}" y1="{cy}" x2="{cx+R*math.cos(ang):.1f}" '
                    f'y2="{cy+R*math.sin(ang):.1f}" stroke="#2a3550" stroke-width="1"/>')
    return f'''<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}">
      {"".join(grid)}
      <polygon points="{" ".join(pts)}" fill="rgba(94,234,212,0.18)"
               stroke="#5eead4" stroke-width="2.5"/>
      {"".join(f'<circle cx="{p.split(",")[0]}" cy="{p.split(",")[1]}" r="3.5" fill="#5eead4"/>' for p in pts)}
      {"".join(labels)}
    </svg>'''


def _grid_svg(track: dict, w=340, h=230) -> str:
    """5レーン×6ゾーンのポジショナルグリッド(ヒートマップ)."""
    from collections import defaultdict
    cells = defaultdict(int)
    total = 0
    for s in track.get("sightings", []):
        fx = s.get("fx_smooth", s.get("fx_norm", s["fx"]))
        fy = s.get("fy_smooth", s.get("fy_norm", s["fy"]))
        li = min(4, max(0, int(fy / 13.6)))
        # zone idx
        bounds = [21, 42, 52.5, 63, 84, 105]
        zi = next((i for i, b in enumerate(bounds) if fx < b), 5)
        cells[(li, zi)] += 1
        total += 1
    cw, ch = w / 6, h / 5
    rects = []
    mx = max(cells.values()) if cells else 1
    for li in range(5):
        for zi in range(6):
            c = cells.get((li, zi), 0)
            inten = c / mx if mx else 0
            r = int(20 + inten * 60)
            g = int(30 + inten * 200)
            b = int(50 + inten * 120)
            x, y = zi * cw, li * ch
            rects.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{cw:.1f}" '
                         f'height="{ch:.1f}" fill="rgb({r},{g},{b})" '
                         f'stroke="#0d1117" stroke-width="1.5"/>')
            if c > 0:
                pct = c / total * 100
                rects.append(f'<text x="{x+cw/2:.1f}" y="{y+ch/2+4:.1f}" '
                             f'fill="#fff" font-size="11" font-weight="700" '
                             f'text-anchor="middle">{pct:.0f}%</text>')
    # 中央線 (ハーフライン) — D3とA1の境界
    half_x = bounds_to_x(52.5, w)
    rects.append(f'<line x1="{half_x:.1f}" y1="0" x2="{half_x:.1f}" y2="{h}" '
                 f'stroke="#5eead4" stroke-width="2" stroke-dasharray="5,4"/>')
    # 攻撃方向矢印
    rects.append(f'<text x="{w-8}" y="14" fill="#5eead4" font-size="11" '
                 f'text-anchor="end">攻撃→</text>')
    zlabels = "".join(
        f'<text x="{(i+0.5)*cw:.1f}" y="{h+14:.0f}" fill="#6b7a99" '
        f'font-size="10" text-anchor="middle">{ZONES_JP[i]}</text>'
        for i in range(6))
    llabels = "".join(
        f'<text x="-6" y="{(i+0.5)*ch+4:.1f}" fill="#6b7a99" font-size="10" '
        f'text-anchor="end">{LANES_JP[i]}</text>'
        for i in range(5))
    return f'''<svg viewBox="-44 0 {w+50} {h+22}" width="{w+50}" height="{h+22}">
      {"".join(rects)}{zlabels}{llabels}
    </svg>'''


def bounds_to_x(fx, w):
    return fx / 105.0 * w


def _score_color(v):
    if v is None: return "#6b7a99"
    if v >= 75: return "#5eead4"
    if v >= 55: return "#fbbf24"
    return "#f87171"


def _identification_block(r: dict) -> str:
    """羽瑠の特定根拠 (セグメント別トラック) とポジションチェンジ評価."""
    hid = r.get("haru_id", {})
    segs = hid.get("segments", [])
    note = hid.get("note", "")
    if not segs and hid.get("method") != "ground_truth":
        return (f'<div class="ident auto-note">グラウンドトゥルース未指定の'
                f'検証用試合。最も「デ・ヨング的」なトラックを自動推定。</div>')

    seg_html = ""
    for s in segs:
        cf = s.get("confidence")
        cf_txt = f"{int(cf*100)}%" if cf is not None else "—"
        cf_col = ("#5eead4" if (cf or 0) >= 0.6 else
                  "#fbbf24" if (cf or 0) >= 0.35 else "#f87171")
        pid = s.get("player_id") or "特定不可"
        seg_html += (f'<div class="seg"><span class="seg-h">{s["half"]}</span>'
                     f'<span class="seg-r">{s["label"]}</span>'
                     f'<span class="seg-p">{pid}</span>'
                     f'<span class="seg-c" style="color:{cf_col}">信頼度{cf_txt}</span></div>')

    pc = r.get("position_change")
    pc_html = ""
    if pc:
        for c in pc["changes"]:
            verdict_col = "#f87171" if c["hole"] else "#5eead4"
            adv = (f'{c["advance_m"]:+.0f}m前進' if c["advance_m"] is not None else "")
            pc_html += (
                f'<div class="pchg">'
                f'<div class="pchg-head"><b>{c["from"]} → {c["to"]}</b> '
                f'<span style="color:{verdict_col}">{c["verdict"]}</span></div>'
                f'<div class="pchg-body">空けた空間 {c["vacated_zone"]} → '
                f'移動先 {c["new_zone"]} ({adv})<br>'
                f'カバー: {("、".join(c["covered_by"]) if c["covered_by"] else "なし")} '
                f'· 根拠サンプル {c["evidence_n"]}点 (信頼度 {int(c["confidence"]*100)}%)</div>'
                f'</div>')

    note_html = f'<div class="ident-note">📋 {note}</div>' if note else ""
    skel_html = _skeleton_pitch(hid.get("skeleton", {}),
                                {s.get("player_id") for s in segs})
    return (f'<div class="ident">{note_html}'
            f'<div class="seg-list">{seg_html}</div>{pc_html}{skel_html}</div>')


# 標準ロールのピッチ上相対座標 (x:0-105→0-100%, y:0-68→0-100%)
_SKEL_LAYOUT = {
    "GK": (5, 50), "LCB": (19, 70), "RCB": (19, 30), "LB": (29, 90),
    "RB": (29, 10), "DM": (40, 50), "LCM": (52, 65), "RCM": (52, 35),
    "LW": (72, 88), "RW": (72, 12), "CF": (85, 50),
}


def _skeleton_pitch(skeleton: dict, haru_pids: set) -> str:
    """復元したチーム骨格をミニピッチ上に描画 (羽瑠枠を強調)."""
    if not skeleton:
        return ""
    W, H = 360, 150
    dots = []
    for rk, info in skeleton.items():
        if rk not in _SKEL_LAYOUT:
            continue
        gx, gy = _SKEL_LAYOUT[rk]
        x, y = gx / 100 * W, gy / 100 * H
        pid = info.get("player_id", "")
        is_haru = pid in haru_pids
        col = "#5eead4" if is_haru else "#3b557f"
        rcol = "#0a0e1a"
        dots.append(
            f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{9 if is_haru else 7}" '
            f'fill="{col}" stroke="{rcol}" stroke-width="1.5"/>'
            f'<text x="{x:.0f}" y="{y+3:.0f}" font-size="8" fill="#0a0e1a" '
            f'font-weight="700" text-anchor="middle">{info["label"]}</text>'
            f'<text x="{x:.0f}" y="{y-12:.0f}" font-size="7.5" '
            f'fill="{"#5eead4" if is_haru else "#6b7a99"}" '
            f'text-anchor="middle">{pid}</text>')
    return (
        f'<div class="skel"><div class="skel-title">復元ラインアップ '
        f'(消去法スケルトン · <span style="color:#5eead4">緑=羽瑠枠</span>) '
        f'攻撃方向→</div>'
        f'<svg viewBox="0 0 {W} {H}" width="100%" style="max-width:{W}px">'
        f'<rect x="0" y="0" width="{W}" height="{H}" fill="#0d1f17" rx="6"/>'
        f'<line x1="{W/2}" y1="0" x2="{W/2}" y2="{H}" stroke="#1e3a2e" '
        f'stroke-width="1.5"/>'
        f'<circle cx="{W/2}" cy="{H/2}" r="20" fill="none" stroke="#1e3a2e" '
        f'stroke-width="1.5"/>{"".join(dots)}</svg></div>')


def _match_card(r: dict) -> str:
    haru = r.get("haru")
    if not haru:
        return f'''<div class="match-card empty">
          <h3>{r["label"]}</h3>
          <p class="muted">データ不足 — 追跡サンプルが少なく分析対象外</p>
        </div>'''

    pos = haru["position"]
    cog = haru["cognition"]
    pri = haru["principle"]
    cre = haru["creativity"]
    pro = haru["protagonist"]

    radar = _radar_svg({
        "cognition": cog.get("score") or 0,
        "principle": pri.get("score") or 0,
        "creativity": cre.get("score") or 0,
        "protagonist": pro.get("score") or 0,
        "tactical_iq": haru["tactical_iq"],
    })
    grid = _grid_svg(r["haru_track"])

    hid = r.get("haru_id", {})
    method = hid.get("method", "")
    conf = hid.get("confidence")
    if method == "ground_truth":
        conf_pct = f"{int(conf*100)}%" if conf is not None else "—"
        hint = (f'<span class="hint gt">確定ポジション (背番号6) · '
                f'特定信頼度 {conf_pct}</span>')
    else:
        hint = '<span class="hint auto">ホールドアウト検証 (自動推定)</span>'

    return f'''<div class="match-card">
      <div class="mc-head">
        <h3>{r["label"]}</h3>
        <div class="pos-badge">{pos["archetype"]} <small>{pos["desc"]}</small></div>
        {hint}
      </div>
      {_identification_block(r)}
      <div class="mc-body">
        <div class="radar-wrap">
          {radar}
          <div class="tiq">Tactical IQ<br><b style="color:{_score_color(haru["tactical_iq"])}">{haru["tactical_iq"]}</b></div>
        </div>
        <div class="grid-wrap">
          <div class="grid-title">ポジショナル・グリッド (5レーン×6ゾーン)</div>
          {grid}
          <div class="grid-meta">
            平均位置 ({pos["avg_x"]}, {pos["avg_y"]})m · 主レーン {pos["primary_lane"]} ·
            可動域 σ=({pos["std_x"]},{pos["std_y"]})
          </div>
        </div>
      </div>
      <div class="metrics-row">
        <div class="metric"><span class="ml">認知 Cognición</span>
          <span class="mv" style="color:{_score_color(cog.get("score"))}">{cog.get("score","—")}</span>
          <span class="mn">{cog.get("note","")}</span></div>
        <div class="metric"><span class="ml">原則 Principios</span>
          <span class="mv" style="color:{_score_color(pri.get("score"))}">{pri.get("score","—")}</span>
          <span class="mn">{" · ".join(pri.get("detail",[]))}</span></div>
        <div class="metric"><span class="ml">創造性 Creatividad</span>
          <span class="mv" style="color:{_score_color(cre.get("score"))}">{cre.get("score","—")}</span>
          <span class="mn">突破点: {cre.get("creative_hotspot","—")}</span></div>
        <div class="metric"><span class="ml">主役度 Protagonismo</span>
          <span class="mv" style="color:{_score_color(pro.get("score"))}">{pro.get("score","—")}</span>
          <span class="mn">平均リンク {pro.get("avg_links","—")}人</span></div>
      </div>
    </div>'''


def _cross_match_section(results: list) -> str:
    """クロス試合: 羽瑠の各指標推移を折れ線で."""
    valid = [r for r in results if r.get("haru")]
    if len(valid) < 2:
        return ""
    labels = [r["label"].split(" ")[0] for r in valid]
    series = {
        "認知": [r["haru"]["cognition"].get("score") or 0 for r in valid],
        "原則": [r["haru"]["principle"].get("score") or 0 for r in valid],
        "創造": [r["haru"]["creativity"].get("score") or 0 for r in valid],
        "IQ":   [r["haru"]["tactical_iq"] for r in valid],
    }
    colors = {"認知": "#60a5fa", "原則": "#a78bfa", "創造": "#5eead4", "IQ": "#fbbf24"}
    W, H = 820, 280
    pad = 44
    n = len(valid)
    xstep = (W - 2 * pad) / max(n - 1, 1)
    def yv(v): return H - pad - (v / 100) * (H - 2 * pad)
    lines = []
    for name, vals in series.items():
        pts = " ".join(f"{pad+i*xstep:.0f},{yv(v):.0f}" for i, v in enumerate(vals))
        lines.append(f'<polyline points="{pts}" fill="none" '
                     f'stroke="{colors[name]}" stroke-width="2.5"/>')
        for i, v in enumerate(vals):
            lines.append(f'<circle cx="{pad+i*xstep:.0f}" cy="{yv(v):.0f}" r="4" '
                         f'fill="{colors[name]}"/>')
    gridlines = "".join(
        f'<line x1="{pad}" y1="{yv(g):.0f}" x2="{W-pad}" y2="{yv(g):.0f}" '
        f'stroke="#1e2740" stroke-width="1"/>'
        f'<text x="{pad-8}" y="{yv(g)+4:.0f}" fill="#6b7a99" font-size="10" '
        f'text-anchor="end">{g}</text>'
        for g in (0, 25, 50, 75, 100))
    xlabels = "".join(
        f'<text x="{pad+i*xstep:.0f}" y="{H-pad+18:.0f}" fill="#9fb3d9" '
        f'font-size="10" text-anchor="middle">{lbl}</text>'
        for i, lbl in enumerate(labels))
    legend = "".join(
        f'<rect x="{pad+i*120}" y="8" width="12" height="12" fill="{colors[name]}"/>'
        f'<text x="{pad+i*120+18}" y="18" fill="#cbd5e1" font-size="12">{name}</text>'
        for i, name in enumerate(series))
    return f'''<section class="cross">
      <h2>クロス試合推移 — 原理原則は一貫しているか？</h2>
      <p class="muted">フレンキー・デ・ヨング型の評価軸。ポジションが変わっても
      原則(紫)が安定し、創造性(緑)が高水準で維持されているかを見る。</p>
      <svg viewBox="0 0 {W} {H}" width="100%" style="max-width:{W}px">
        {legend}{gridlines}{"".join(lines)}{xlabels}
      </svg>
    </section>'''


def _executive_summary(results: list) -> str:
    valid = [r for r in results if r.get("haru")]
    if not valid:
        return '<p class="muted">分析可能なデータがありません</p>'
    import numpy as np
    tiqs = [r["haru"]["tactical_iq"] for r in valid]
    cogs = [r["haru"]["cognition"].get("score") or 0 for r in valid]
    cres = [r["haru"]["creativity"].get("score") or 0 for r in valid]
    pris = [r["haru"]["principle"].get("score") or 0 for r in valid]
    archetypes = [r["haru"]["position"]["archetype"] for r in valid]
    from collections import Counter
    arc_count = Counter(archetypes)
    versatility = len(arc_count)

    avg_iq = int(np.mean(tiqs))
    pri_std = float(np.std(pris))
    consistency = "高い" if pri_std < 12 else ("中程度" if pri_std < 20 else "発展途上")

    arc_list = " / ".join(f"{a}×{c}" for a, c in arc_count.most_common())

    insight = []
    if versatility >= 3:
        insight.append(f"<b>{versatility}つの異なるポジション</b>でプレー。"
                       "デ・ヨング/クロース型のユーティリティ性を確認。")
    if pri_std < 15:
        insight.append("ポジションが変わっても<b>原理原則のブレが小さい</b>。"
                       "「どこでも同じ原則で最適化する」知性の証拠。")
    if np.mean(cres) >= 60:
        insight.append("創造性スコアが高水準。<b>意図的なライン突破</b>で"
                       "高価値空間に侵入する傾向。")
    if np.mean(cogs) >= 60:
        insight.append("認知スコア良好。<b>チームより先に動く</b>"
                       "フェーズ先読み (lectura del juego) の兆候。")

    return f'''<section class="exec">
      <div class="exec-grid">
        <div class="big-num"><span>{avg_iq}</span><label>平均 Tactical IQ</label></div>
        <div class="big-num"><span>{versatility}</span><label>習熟ポジション数</label></div>
        <div class="big-num"><span>{consistency}</span><label>原則一貫性</label></div>
        <div class="big-num"><span>{int(np.mean(cres))}</span><label>平均創造性</label></div>
      </div>
      <div class="exec-text">
        <p><b>習熟ポジション:</b> {arc_list}</p>
        <ul>{"".join(f"<li>{i}</li>" for i in insight)}</ul>
      </div>
    </section>'''


def generate_report(results: list) -> Path:
    cards = "".join(_match_card(r) for r in results)
    summary = _executive_summary(results)
    cross = _cross_match_section(results)

    html = f'''<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>牧野羽瑠 — 戦術知能プロファイル | TZI</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0a0e1a;color:#e6edf3;font-family:'Hiragino Sans','Segoe UI',sans-serif;line-height:1.6}}
.hero{{background:linear-gradient(135deg,#0a0e1a,#13203b 55%,#0d2818);padding:48px 40px 36px;border-bottom:1px solid #1e2740}}
.hero .eyebrow{{color:#5eead4;font-size:.8rem;letter-spacing:.25em;text-transform:uppercase}}
.hero h1{{font-size:2.1rem;margin:6px 0;background:linear-gradient(90deg,#5eead4,#60a5fa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.hero p{{color:#9fb3d9;font-size:.95rem;max-width:780px}}
.philo{{margin-top:16px;padding:14px 18px;border-left:3px solid #5eead4;background:rgba(94,234,212,.06);font-style:italic;color:#cbd5e1;max-width:780px;border-radius:0 8px 8px 0}}
.container{{max-width:1180px;margin:0 auto;padding:32px 24px}}
h2{{font-size:1.2rem;margin:36px 0 16px;padding-bottom:10px;border-bottom:1px solid #1e2740;color:#e6edf3}}
.muted{{color:#6b7a99;font-size:.85rem}}
.exec{{background:#0f1626;border:1px solid #1e2740;border-radius:14px;padding:24px;margin-bottom:8px}}
.exec-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:20px}}
.big-num{{text-align:center;background:#13203b;border-radius:10px;padding:18px 10px}}
.big-num span{{display:block;font-size:2.2rem;font-weight:800;color:#5eead4}}
.big-num label{{font-size:.75rem;color:#9fb3d9}}
.exec-text ul{{margin:10px 0 0 18px}}
.exec-text li{{margin:6px 0;color:#cbd5e1;font-size:.92rem}}
.match-grid{{display:grid;grid-template-columns:1fr;gap:20px}}
.match-card{{background:#0f1626;border:1px solid #1e2740;border-radius:14px;padding:22px;transition:border-color .2s}}
.match-card:hover{{border-color:#2e3f63}}
.match-card.empty{{opacity:.5}}
.mc-head{{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:18px}}
.mc-head h3{{font-size:1.15rem}}
.pos-badge{{background:linear-gradient(90deg,#1d3a5f,#1d5f4a);padding:5px 14px;border-radius:20px;font-size:.9rem;font-weight:700;color:#a7f3d0}}
.pos-badge small{{font-weight:400;color:#7dd3c0;font-size:.75rem}}
.hint{{font-size:.72rem;padding:3px 10px;border-radius:12px;background:#1e2740;color:#9fb3d9}}
.hint.auto{{background:#2d2438;color:#d8b4fe}}
.hint.gt{{background:#10331f;color:#86efac}}
.ident{{background:#0c1322;border:1px solid #1a2238;border-radius:10px;padding:12px 14px;margin-bottom:16px}}
.ident-note{{font-size:.8rem;color:#9fb3d9;margin-bottom:8px}}
.ident.auto-note{{font-size:.8rem;color:#d8b4fe}}
.seg-list{{display:flex;flex-direction:column;gap:4px}}
.seg{{display:flex;gap:10px;align-items:center;font-size:.8rem}}
.seg-h{{background:#1e2740;color:#9fb3d9;padding:1px 8px;border-radius:8px;font-size:.7rem;min-width:30px;text-align:center}}
.seg-r{{color:#a7f3d0;font-weight:700;min-width:80px}}
.seg-p{{color:#cbd5e1;min-width:48px}}
.seg-c{{font-size:.74rem}}
.pchg{{margin-top:10px;padding:10px 12px;background:#11192b;border-left:3px solid #5eead4;border-radius:0 8px 8px 0}}
.pchg-head{{font-size:.86rem;margin-bottom:4px}}
.pchg-body{{font-size:.76rem;color:#9fb3d9}}
.skel{{margin-top:12px}}
.skel-title{{font-size:.76rem;color:#9fb3d9;margin-bottom:6px}}
.mc-body{{display:grid;grid-template-columns:auto 1fr;gap:28px;align-items:center;margin-bottom:18px}}
.radar-wrap{{position:relative}}
.tiq{{position:absolute;bottom:6px;right:6px;text-align:center;font-size:.7rem;color:#9fb3d9}}
.tiq b{{font-size:1.6rem;font-weight:800}}
.grid-wrap{{min-width:0}}
.grid-title{{font-size:.8rem;color:#9fb3d9;margin-bottom:8px}}
.grid-meta{{font-size:.75rem;color:#6b7a99;margin-top:10px}}
.metrics-row{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;border-top:1px solid #1e2740;padding-top:16px}}
.metric{{display:flex;flex-direction:column;gap:2px}}
.metric .ml{{font-size:.78rem;color:#9fb3d9}}
.metric .mv{{font-size:1.7rem;font-weight:800;line-height:1}}
.metric .mn{{font-size:.72rem;color:#6b7a99}}
.cross{{margin-top:8px}}
footer{{text-align:center;padding:30px;color:#3f4a63;font-size:.78rem;border-top:1px solid #1e2740;margin-top:40px}}
@media(max-width:720px){{.exec-grid,.metrics-row{{grid-template-columns:repeat(2,1fr)}}.mc-body{{grid-template-columns:1fr}}}}
</style></head>
<body>
<div class="hero">
  <div class="eyebrow">TZI · Tactical Zone Intelligence</div>
  <h1>牧野羽瑠 — 戦術知能プロファイル</h1>
  <p>固定ポジションではなく「原理原則の体現者」として分析する。
  ポジションが変わっても juego de posición を貫き、決定的な瞬間に
  意図的にバランスを崩して主役になる — フレンキー・デ・ヨング / トニー・クロース型の評価。</p>
  <div class="philo">「ポジションは試合ごとに変わる。だが原則は変わらない。
  そして決定的な瞬間に、彼は意図的にバランスを崩し、主役になる。」</div>
</div>
<div class="container">
  <h2>エグゼクティブ・サマリー</h2>
  {summary}
  {cross}
  <h2>試合別 戦術知能カード</h2>
  <div class="match-grid">{cards}</div>
</div>
<footer>
  TZI Tactical Intelligence Engine · 認知→創造性スコアリング ·
  スペイン式ポジショナルプレー (5レーン×6ゾーン) 基盤<br>
  ※ 羽瑠(背番号6)の試合別・時間帯別確定ポジションに基づきトラックを特定。
  動画のある4試合は1分間隔サンプリング。特定信頼度・根拠サンプル数を各カードに明示。
</footer>
</body></html>'''

    out = DATA_TZI / "tactical_intelligence.html"
    out.write_text(html, encoding="utf-8")

    # 機械可読プロファイルも保存
    profile = {
        "matches": [{
            "match": r["match"], "label": r["label"],
            "haru": r["haru"], "haru_id": r.get("haru_id"),
            "skeleton": r.get("haru_id", {}).get("skeleton"),
            "position_change": r.get("position_change"),
        } for r in results if r.get("haru")]
    }
    (DATA_TZI / "haru_tactical_profile.json").write_text(
        json.dumps(profile, ensure_ascii=False, indent=2,
                   default=lambda o: None), encoding="utf-8")
    return out
