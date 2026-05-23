#!/usr/bin/env python3
"""
TZI: jersey6_trajectory.json + jersey_sightings.json から
羽瑠（#6）のゾーン分析レポートを生成する。

使い方:
    cd scripts/tzi
    python generate_zone_report.py
"""
import json
import sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from scipy.ndimage import gaussian_filter

PROJECT_ROOT = Path(__file__).parent.parent.parent
MATCH_DIR    = PROJECT_ROOT / "data" / "tzi" / "match_20260325"
TRAJ_JSON    = MATCH_DIR / "jersey6_trajectory.json"
SIGHT_JSON   = MATCH_DIR / "jersey_sightings.json"
SUMMARY_JSON = MATCH_DIR / "full_match_summary.json"
REPORT_HTML  = MATCH_DIR / "zone_report_jersey6.html"
ZONE_FIG     = MATCH_DIR / "zone_analysis_jersey6.png"

FW, FH = 105.0, 68.0

ZONE_COLORS = {
    "A1": "#e74c3c", "A2": "#e67e22", "A3": "#f1c40f",
    "D1": "#3498db", "D2": "#2980b9", "D3": "#1abc9c",
}

# ── ゾーン分類（fx基準）────────────────────────────────────────
def fx_to_zone(fx):
    if fx < 21:   return "D1"
    elif fx < 42: return "D2"
    elif fx < 63: return "D3"
    elif fx < 84: return "A2"  # note: skipping A1/A3 for simplicity w/o lane
    else:         return "A3"

def fx_fy_to_zone(fx, fy):
    """Approximate zone+lane based on field position."""
    if fx < 21:
        base = "D1"
    elif fx < 42:
        base = "D2"
    elif fx < 52.5:
        base = "D3"
    elif fx < 63:
        base = "A1"
    elif fx < 84:
        base = "A2"
    else:
        base = "A3"
    return base


def zone_to_x_center(zone):
    mapping = {"D1":10.5,"D2":31.5,"D3":47.25,"A1":57.75,"A2":73.5,"A3":94.5}
    return mapping.get(zone, 52.5)


def compute_zone_score(positions):
    """
    5指標でゾーンスコアを計算（各20点・合計100点）
    P: ポジショニング（A2/A3ゾーン到達率）
    M: 移動量（dynamism）
    D: 判断速度（ポジション変化の速さ）
    V: 視野の広さ（フィールドのカバー範囲）
    B: 身体の軸安定性（y座標の安定度）
    """
    if len(positions) < 2:
        return {"P":0,"M":0,"D":0,"V":0,"B":0,"total":0}

    xs = [p["fx"] for p in positions]
    ys = [p["fy"] for p in positions]
    times = [p["time_min"] for p in positions]

    # P: アタッキングゾーン到達率（A1/A2/A3）
    atk_count = sum(1 for x in xs if x >= 52.5)
    p_score = min(20, int(atk_count / len(xs) * 40))

    # M: 移動ダイナミクス（合計移動距離 / 時間）
    total_dist = sum(
        np.sqrt((xs[i]-xs[i-1])**2 + (ys[i]-ys[i-1])**2)
        for i in range(1, len(xs))
    )
    match_time = max(1, times[-1] - times[0])
    dist_per_min = total_dist / match_time
    m_score = min(20, int(dist_per_min * 2))

    # D: 判断速度（位置変化の平均速度）
    if len(times) >= 2:
        time_gaps = [times[i]-times[i-1] for i in range(1, len(times)) if times[i]-times[i-1] > 0]
        avg_gap = np.mean(time_gaps) if time_gaps else 99
        d_score = min(20, max(0, int(20 - avg_gap * 0.5)))
    else:
        d_score = 5

    # V: フィールドカバー範囲（x方向のレンジ）
    x_range = max(xs) - min(xs)
    v_score = min(20, int(x_range / FW * 40))

    # B: y軸安定性（標準偏差が低いほど高得点）
    y_std = np.std(ys) if len(ys) > 1 else 10
    b_score = min(20, max(0, int(20 - y_std * 0.5)))

    total = p_score + m_score + d_score + v_score + b_score
    return {"P":p_score,"M":m_score,"D":d_score,"V":v_score,"B":b_score,"total":total}


def zone_level(score):
    if score >= 90: return "🔥 完全ゾーン", "#e74c3c"
    if score >= 70: return "⚡ 準ゾーン", "#e67e22"
    if score >= 50: return "✅ 通常", "#27ae60"
    if score >= 30: return "⚠️ 低集中", "#f39c12"
    return "❌ 要確認", "#e74c3c"


# ── データ読み込み ────────────────────────────────────────────
def load_data():
    with open(TRAJ_JSON) as f:
        traj = json.load(f)
    with open(SIGHT_JSON) as f:
        sightings = json.load(f)
    with open(SUMMARY_JSON) as f:
        summary = json.load(f)
    return traj, sightings, summary


# ── フィールド図生成 ───────────────────────────────────────────
def draw_field_analysis(positions, output_path):
    fig = plt.figure(figsize=(18, 10), facecolor='#0d1117')
    gs  = fig.add_gridspec(2, 3, hspace=0.35, wspace=0.3)

    # ── メインフィールドマップ ────────────────────────────────
    ax = fig.add_subplot(gs[:, :2], facecolor='#1a4a1a')
    ax.set_xlim(-2, FW+2); ax.set_ylim(-2, FH+2)
    ax.set_aspect('equal')

    # フィールドライン
    ax.add_patch(patches.Rectangle((0,0), FW, FH, fill=False, ec='white', lw=2))
    ax.axvline(FW/2, color='white', alpha=0.8, lw=1.5)
    ax.add_patch(patches.Circle((FW/2, FH/2), 9.15, fill=False, ec='white', alpha=0.4, lw=1))
    for px, pw in [(0, 16.5), (FW-16.5, 16.5)]:
        ax.add_patch(patches.Rectangle((px, 13.84), pw, 40.32, fill=False, ec='white', alpha=0.6, lw=1.2))
    for px, pw in [(0, 5.5), (FW-5.5, 5.5)]:
        ax.add_patch(patches.Rectangle((px, 24.84), pw, 18.32, fill=False, ec='white', alpha=0.4, lw=0.8))

    # ゾーン境界線
    for vx in [21, 42, 63, 84]:
        ax.axvline(vx, color='#555', alpha=0.5, lw=0.8, ls='--')

    # ゾーンラベル
    for zone, cx in [("D1",10.5),("D2",31.5),("D3",47.25),("A1",57.75),("A2",73.5),("A3",94.5)]:
        ax.text(cx, FH+1, zone, ha='center', color='#888', fontsize=9, fontweight='bold')

    # ヒートマップ
    xs = [p["fx"] for p in positions]
    ys = [p["fy"] for p in positions]
    if len(xs) >= 2:
        H, W = 340, 520
        grid = np.zeros((H, W))
        for x, y in zip(xs, ys):
            gx = int(np.clip(x/FW*(W-1), 0, W-1))
            gy = int(np.clip(y/FH*(H-1), 0, H-1))
            grid[gy, gx] += 1
        grid = gaussian_filter(grid, sigma=15)
        if grid.max() > 0:
            grid /= grid.max()
        ax.imshow(grid, extent=[0,FW,0,FH], origin='lower',
                  cmap='hot', alpha=0.45, aspect='auto', vmin=0, vmax=1)

    # トラジェクトリ
    h1 = [p for p in positions if p.get("half") == "1H"]
    h2 = [p for p in positions if p.get("half") == "2H"]
    for half_pts, color, label in [(h1, '#4fc3f7', '前半'), (h2, '#ffb74d', '後半')]:
        if not half_pts:
            continue
        hx = [p["fx"] for p in half_pts]
        hy = [p["fy"] for p in half_pts]
        ax.plot(hx, hy, 'o-', color=color, lw=1.5, ms=8, label=label,
                markeredgecolor='white', markeredgewidth=0.8, zorder=6)
        for i, p in enumerate(half_pts):
            ax.annotate(f"{p['time_min']:.0f}m",
                        xy=(p["fx"], p["fy"]),
                        xytext=(4, 4), textcoords='offset points',
                        fontsize=7, color='white', fontweight='bold', zorder=7)

    ax.set_title("🎯 Jersey #6 (羽瑠) フィールドポジション", color='white', fontsize=13, pad=12)
    ax.set_xlabel("← 自陣 ──────────── 敵陣 →", color='#aaa', fontsize=10)
    ax.set_ylabel("Field Width (m)", color='#aaa', fontsize=10)
    ax.tick_params(colors='#666')
    ax.legend(loc='upper right', facecolor='#222', labelcolor='white', fontsize=9)

    # ── ゾーン分布パイチャート ────────────────────────────────
    ax2 = fig.add_subplot(gs[0, 2], facecolor='#0d1117')
    zone_counts = {}
    for p in positions:
        z = fx_fy_to_zone(p["fx"], p["fy"])
        zone_counts[z] = zone_counts.get(z, 0) + 1
    if zone_counts:
        labels = list(zone_counts.keys())
        vals   = list(zone_counts.values())
        colors = [ZONE_COLORS.get(l, '#888') for l in labels]
        wedges, texts, autotexts = ax2.pie(
            vals, labels=labels, colors=colors, autopct='%1.0f%%',
            startangle=90, textprops={'color':'white', 'fontsize':9}
        )
        for at in autotexts:
            at.set_fontsize(8)
    ax2.set_title("ゾーン分布", color='white', fontsize=11)

    # ── タイムライン ──────────────────────────────────────────
    ax3 = fig.add_subplot(gs[1, 2], facecolor='#111827')
    all_times = [p["time_min"] for p in positions]
    all_fx    = [p["fx"] for p in positions]
    all_zones = [fx_fy_to_zone(p["fx"], p["fy"]) for p in positions]
    point_colors = [ZONE_COLORS.get(z, '#888') for z in all_zones]

    h1_times = [p["time_min"] for p in positions if p.get("half") == "1H"]
    h1_fx    = [p["fx"] for p in positions if p.get("half") == "1H"]
    h2_times = [p["time_min"] for p in positions if p.get("half") == "2H"]
    h2_fx    = [p["fx"] for p in positions if p.get("half") == "2H"]

    if h1_times:
        ax3.plot(h1_times, h1_fx, 'o-', color='#4fc3f7', lw=1.5, ms=5, label='前半')
    if h2_times:
        ax3.plot(h2_times, h2_fx, 's-', color='#ffb74d', lw=1.5, ms=5, label='後半')

    ax3.axhline(52.5, color='#e74c3c', alpha=0.4, lw=0.8, ls='--', label='敵陣境界')
    ax3.axhline(FW/2, color='white', alpha=0.25, lw=0.8)
    ax3.fill_between([0, 90], 63, FW, alpha=0.08, color='#e74c3c', label='A2/A3')

    ax3.set_xlim(0, 90); ax3.set_ylim(0, FW)
    ax3.set_xlabel("試合時間 (分)", color='#aaa', fontsize=9)
    ax3.set_ylabel("フィールドX座標 (m)", color='#aaa', fontsize=9)
    ax3.set_title("ポジション推移", color='white', fontsize=11)
    ax3.tick_params(colors='#666')
    ax3.legend(loc='upper left', facecolor='#1a1a2e', labelcolor='white', fontsize=7)

    plt.savefig(str(output_path), dpi=150, bbox_inches='tight', facecolor='#0d1117')
    plt.close()
    print(f"フィールド図保存: {output_path}")


# ── HTML レポート生成 ─────────────────────────────────────────
def generate_html_report(traj, sightings, summary, scores, positions):
    zone_label, zone_color = zone_level(scores["total"])

    # スコアバー（f-string ネスト回避のため事前生成）
    score_bars = ""
    for k, v in [("P",scores["P"]),("M",scores["M"]),("D",scores["D"]),("V",scores["V"]),("B",scores["B"])]:
        w = f"{v/20*100:.0f}%"
        score_bars += f"""<div class="score-row">
          <span style="width:12px;font-weight:700">{k}</span>
          <div class="bar"><div class="bar-fill" style="width:{w}"></div></div>
          <span style="width:36px;text-align:right;font-size:14px;font-weight:600">{v}/20</span>
        </div>"""
    h6 = sightings.get("6", [])

    # ゾーンヒストグラム
    zone_dist = {}
    for p in positions:
        z = fx_fy_to_zone(p["fx"], p["fy"])
        zone_dist[z] = zone_dist.get(z, 0) + 1
    total_pts = max(1, sum(zone_dist.values()))

    zone_bars = ""
    for z in ["D1","D2","D3","A1","A2","A3"]:
        pct = zone_dist.get(z, 0) / total_pts * 100
        col = ZONE_COLORS.get(z, "#888")
        zone_bars += f"""
        <div class="zone-bar-row">
          <span class="zone-label">{z}</span>
          <div class="zone-bar-bg">
            <div class="zone-bar-fill" style="width:{pct:.1f}%;background:{col}"></div>
          </div>
          <span class="zone-pct">{pct:.0f}%</span>
        </div>"""

    # タイムライン
    timeline_rows = ""
    for p in sorted(positions, key=lambda x: x["time_min"]):
        z = fx_fy_to_zone(p["fx"], p["fy"])
        col = ZONE_COLORS.get(z, "#888")
        note = p.get("note", "")
        half = p.get("half", "?")
        timeline_rows += f"""
        <tr>
          <td>{half} {p['time_min']:.1f}m</td>
          <td style="font-family:monospace">({p['fx']:.1f}, {p['fy']:.1f})</td>
          <td><span class="zone-tag" style="background:{col}">{z}</span></td>
          <td class="note">{note[:50]}</td>
        </tr>"""

    # ゾーントリガー（A2/A3 の瞬間から）
    atk_moments = [p for p in positions if p["fx"] >= 63]
    triggers_html = ""
    if atk_moments:
        for p in atk_moments[:5]:
            z = fx_fy_to_zone(p["fx"], p["fy"])
            col = ZONE_COLORS.get(z, "#888")
            triggers_html += f"""
            <div class="trigger-card">
              <span class="zone-tag" style="background:{col}">{z}</span>
              <strong>{p.get('half','?')} {p['time_min']:.0f}分</strong>
              ← 敵陣深く侵入 (X={p['fx']:.1f}m)
            </div>"""
    else:
        triggers_html = "<p style='color:#aaa'>アタッキングゾーン到達記録なし（このデータセット内）</p>"

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>TZI ゾーン分析レポート — Jersey #6 牧野羽瑠</title>
<style>
  :root {{
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #e6edf3; --muted: #8b949e; --accent: #58a6ff;
  }}
  body {{ margin:0; background:var(--bg); color:var(--text); font-family:'Helvetica Neue',sans-serif; }}
  .header {{ background:linear-gradient(135deg,#1a1a2e,#16213e); padding:32px 40px; border-bottom:1px solid var(--border); }}
  .header h1 {{ margin:0; font-size:24px; letter-spacing:2px; }}
  .header .sub {{ color:var(--muted); margin-top:6px; font-size:13px; }}
  .container {{ max-width:1100px; margin:0 auto; padding:32px 24px; }}
  .grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-bottom:24px; }}
  .card {{ background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:20px; }}
  .card h3 {{ margin:0 0 16px; font-size:14px; text-transform:uppercase; letter-spacing:1px; color:var(--muted); }}
  .score-big {{ font-size:56px; font-weight:700; line-height:1; margin:8px 0; }}
  .zone-tag {{ padding:3px 10px; border-radius:4px; font-size:11px; font-weight:700; color:white; }}
  .score-row {{ display:flex; justify-content:space-between; align-items:center; padding:6px 0; border-bottom:1px solid var(--border); }}
  .score-row:last-child {{ border:none; }}
  .bar {{ background:#21262d; border-radius:3px; height:6px; flex:1; margin:0 12px; }}
  .bar-fill {{ background:var(--accent); border-radius:3px; height:6px; transition:width .3s; }}
  .zone-bar-row {{ display:flex; align-items:center; gap:8px; margin:5px 0; }}
  .zone-label {{ width:28px; font-weight:700; font-size:12px; }}
  .zone-bar-bg {{ flex:1; background:#21262d; border-radius:3px; height:8px; }}
  .zone-bar-fill {{ height:8px; border-radius:3px; }}
  .zone-pct {{ width:36px; text-align:right; font-size:12px; color:var(--muted); }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th {{ background:#21262d; padding:10px 12px; text-align:left; color:var(--muted); font-weight:600; }}
  td {{ padding:9px 12px; border-bottom:1px solid var(--border); }}
  .note {{ color:var(--muted); font-size:11px; }}
  .trigger-card {{ background:#21262d; border-radius:6px; padding:10px 14px; margin:6px 0; font-size:13px; display:flex; align-items:center; gap:10px; }}
  .section-title {{ font-size:16px; font-weight:600; margin:32px 0 12px; padding-bottom:8px; border-bottom:1px solid var(--border); }}
  .field-img {{ width:100%; border-radius:8px; }}
  .verdict {{ font-size:22px; font-weight:700; }}
  .match-stat {{ display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid var(--border); font-size:13px; }}
</style>
</head>
<body>
<div class="header">
  <h1>🎯 TZI ゾーン分析レポート</h1>
  <div class="sub">早稲田 vs 立教  · 2026-03-25  · Jersey #6 牧野羽瑠</div>
</div>
<div class="container">

  <div class="grid-2">

    <!-- ゾーンスコア -->
    <div class="card">
      <h3>Total Zone Score</h3>
      <div class="score-big" style="color:{zone_color}">{scores['total']}</div>
      <div class="verdict">{zone_label}</div>
      <div style="margin-top:20px">
        {score_bars}
      </div>
    </div>

    <!-- マッチサマリー -->
    <div class="card">
      <h3>マッチサマリー</h3>
      <div class="match-stat"><span>試合</span><span>{summary.get('match','')}</span></div>
      <div class="match-stat"><span>ポゼッション（早稲田）</span><span>{summary.get('possession_full',{}).get('waseda_pct',0):.1f}%</span></div>
      <div class="match-stat"><span>ポゼッション（立教）</span><span>{summary.get('possession_full',{}).get('rikkyo_pct',0):.1f}%</span></div>
      <div class="match-stat"><span>アタック侵入（早稲田）</span><span>{summary.get('attack_entries_waseda_final_third',0)} 回</span></div>
      <div class="match-stat"><span>アタック侵入（立教）</span><span>{summary.get('attack_entries_rikkyo_final_third',0)} 回</span></div>
      <div class="match-stat"><span>#6 確認ポジション数</span><span>{len(positions)} 点</span></div>
      <div class="match-stat"><span>分析バージョン</span><span>{summary.get('version','')}</span></div>
    </div>

  </div>

  <!-- フィールド図 -->
  <div class="section-title">📍 フィールドポジションマップ</div>
  <img src="zone_analysis_jersey6.png" class="field-img" alt="Field Analysis">

  <div class="grid-2" style="margin-top:20px">
    <!-- ゾーン分布 -->
    <div class="card">
      <h3>ゾーン分布</h3>
      {zone_bars}
      <div style="margin-top:12px;font-size:12px;color:var(--muted)">
        D1-D3 = 自陣  ·  A1-A3 = 敵陣
      </div>
    </div>

    <!-- ゾーン誘発トリガー -->
    <div class="card">
      <h3>🔑 ゾーン入りトリガー</h3>
      {triggers_html}
      <div style="margin-top:16px;font-size:12px;color:var(--muted)">
        アタッキングゾーン（A1-A3）での検出瞬間を特定。
        この瞬間の試合映像フレームを確認し、動き・判断パターンを言語化することで
        毎試合ゾーンを再現するルーティンを構築できる。
      </div>
    </div>
  </div>

  <!-- タイムライン -->
  <div class="section-title">📊 ポジションタイムライン</div>
  <div class="card">
    <table>
      <thead><tr><th>時刻</th><th>座標 (m)</th><th>ゾーン</th><th>メモ</th></tr></thead>
      <tbody>{timeline_rows}</tbody>
    </table>
  </div>

  <!-- 次のアクション -->
  <div class="section-title">📝 次の試合へのアクション</div>
  <div class="card">
    <ol style="line-height:2;color:var(--text)">
      <li>アタッキングゾーン到達率を高める → 試合前に「A2/A3侵入イメージ」を3回反復</li>
      <li>ポジション変化の速さ（D指標）を改善 → ボール受け前に次の動き先を決定</li>
      <li>フィールドカバー範囲（V指標）を拡大 → 視野確認ルーティンを組み込む</li>
      <li>次の試合映像を Google Drive にアップロードし再分析を実行</li>
    </ol>
    <div style="margin-top:16px;background:#21262d;border-radius:6px;padding:12px;font-size:12px;color:var(--muted)">
      <strong style="color:{zone_color}">現在のゾーンスコア: {scores['total']}/100</strong><br>
      目標: 70点以上（準ゾーン）を毎試合安定させる → 90点以上（完全ゾーン）の試合を増やす
    </div>
  </div>

</div>
<div style="text-align:center;padding:20px;color:var(--muted);font-size:11px">
  TZI — Tactical Zone Intelligence  ·  Indica Labs  ·  2026
</div>
</body>
</html>"""
    with open(REPORT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTMLレポート保存: {REPORT_HTML}")
    return REPORT_HTML


# ── メイン ────────────────────────────────────────────────────
def main():
    print("TZI ゾーン分析レポート生成中...")

    traj, sightings, summary = load_data()

    # trajectory.json の確認済みポジションを使う
    positions = [
        p for p in traj["confirmed_positions"]
        if "不明" not in p.get("note", "")
    ]
    print(f"使用ポジション: {len(positions)} 点 / {len(traj['confirmed_positions'])} 点")

    # スコア計算
    scores = compute_zone_score(positions)
    label, color = zone_level(scores["total"])
    print(f"\n─── ゾーンスコア ───")
    print(f"P ポジショニング: {scores['P']:2d}/20")
    print(f"M 動きの流動性: {scores['M']:2d}/20")
    print(f"D 判断速度:     {scores['D']:2d}/20")
    print(f"V 視野の広さ:   {scores['V']:2d}/20")
    print(f"B 身体の軸:     {scores['B']:2d}/20")
    print(f"──────────────────")
    print(f"TOTAL: {scores['total']}/100  {label}")

    # フィールド図生成
    draw_field_analysis(positions, ZONE_FIG)

    # HTMLレポート生成
    report_path = generate_html_report(traj, sightings, summary, scores, positions)

    print(f"\n✅ 完了！")
    print(f"  図:      {ZONE_FIG}")
    print(f"  レポート: {report_path}")
    print(f"\n  ブラウザで開く: open {report_path}")


if __name__ == "__main__":
    main()
