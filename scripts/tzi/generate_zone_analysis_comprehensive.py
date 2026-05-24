#!/usr/bin/env python3
"""
TZI: Comprehensive Zone Analysis — Team + Right-Channel Report.

Reads all players_v3.json files and produces a comprehensive HTML training
material covering:
  1. Match-by-match Waseda team zone distribution
  2. Right-channel (Y > 34m) occupancy — proxy for right-back coverage
  3. Attack-zone vs defensive-zone balance per match
  4. Cross-match trends with training recommendations

NOTE: Individual #6 identification via OCR is unreliable in this footage
(panning ball-tracking camera + fixed homography). This report uses TEAM-LEVEL
zone distribution as the primary analysis lens.

Output: data/tzi/zone_analysis_comprehensive.html
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
    "20260314":      "vs埼玉大\n(03/14)",
    "20260316":      "vs岐阜協立\n(03/16)",
    "20260317mid":   "vs中京U-19\n(03/17)",
    "20260317osaka": "vs大阪学院\n(03/17)",
    "20260318":      "vs作新学院\n(03/18)",
    "20260325":      "vs立教大\n(03/25)",
    "20260329":      "vs川崎U-18\n(03/29)",
    "20260405":      "vs獨協大\n(04/05)",
}
ZONES = ["D1", "D2", "D3", "A1", "A2", "A3"]
ZONE_X = {"D1": (0, 21), "D2": (21, 42), "D3": (42, 52.5),
           "A1": (52.5, 63), "A2": (63, 84), "A3": (84, 105)}
FW, FH = 105.0, 68.0


def load_match(mid):
    p = DATA_TZI / f"match_{mid}" / "players_v3.json"
    if not p.exists():
        return None
    return json.load(open(p))


def analyze_match(mid, data):
    """Extract zone distribution, right-channel %, attack bias."""
    dir_info = data.get("direction", {})
    players  = data.get("players", [])

    # Collect all normalized sightings
    all_sightings = []
    for pl in players:
        for s in pl.get("sightings", []):
            all_sightings.append({
                "fx": s.get("fx_norm", s["fx"]),
                "fy": s.get("fy_norm", s["fy"]),
                "half": s["half"],
                "zone": s.get("zone_norm", s.get("zone", "?")),
                "player": pl["player_id"],
                "jersey": pl.get("jersey_number"),
            })

    if not all_sightings:
        return None

    fxs = [s["fx"] for s in all_sightings]
    fys = [s["fy"] for s in all_sightings]

    # Zone distribution
    zone_counts = defaultdict(int)
    for s in all_sightings:
        z = s.get("zone", "?")
        if z in ZONES:
            zone_counts[z] += 1
    total = sum(zone_counts.values()) or 1
    zone_pct = {z: round(zone_counts[z] / total * 100, 1) for z in ZONES}

    # Right-channel (Y > 34m): how much coverage on the right side
    right = [s for s in all_sightings if s["fy"] > 34]
    right_pct = round(len(right) / len(all_sightings) * 100, 1)

    # Right-channel in defensive half (D1+D2+D3) — right-back zone
    right_def = [s for s in all_sightings if s["fy"] > 34 and s["fx"] < 52.5]
    def_total = [s for s in all_sightings if s["fx"] < 52.5]
    rb_zone_pct = round(len(right_def) / max(len(def_total), 1) * 100, 1)

    # Attack bias: % in attacking half (A1+A2+A3)
    atk = [s for s in all_sightings if s["fx"] > 52.5]
    atk_pct = round(len(atk) / len(all_sightings) * 100, 1)

    # Per-half spread
    h1 = [s for s in all_sightings if s["half"] == "1H"]
    h2 = [s for s in all_sightings if s["half"] == "2H"]

    # Jersey #6 stats (if available)
    j6 = next((pl for pl in players if pl.get("jersey_number") == 6), None)
    j6_note = ""
    if j6:
        j6_fxs = [s.get("fx_norm", s["fx"]) for s in j6["sightings"]]
        j6_fys = [s.get("fy_norm", s["fy"]) for s in j6["sightings"]]
        j6_note = (f"OCR識別 #6={j6['player_id']} "
                   f"n={j6['n_sightings']} "
                   f"Xmean={np.mean(j6_fxs):.0f}m Ymean={np.mean(j6_fys):.0f}m "
                   f"⚠精度未検証")

    return {
        "mid":         mid,
        "n":           len(all_sightings),
        "players":     len(players),
        "flip_1h":     dir_info.get("flip_1h"),
        "flip_2h":     dir_info.get("flip_2h"),
        "zone_pct":    zone_pct,
        "right_pct":   right_pct,
        "rb_zone_pct": rb_zone_pct,
        "atk_pct":     atk_pct,
        "cx":          round(np.mean(fxs), 1),
        "cy":          round(np.mean(fys), 1),
        "n_1h":        len(h1),
        "n_2h":        len(h2),
        "j6_note":     j6_note,
    }


def _zone_bar(pct, zone):
    """HTML for a zone percentage bar."""
    is_atk = zone.startswith("A")
    color = "#3fb950" if is_atk else "#58a6ff"
    return (f'<div style="display:flex;align-items:center;margin:2px 0">'
            f'<span style="width:30px;font-size:11px;color:#8b949e">{zone}</span>'
            f'<div style="flex:1;background:#21262d;border-radius:3px;height:14px">'
            f'<div style="width:{pct}%;background:{color};height:100%;border-radius:3px">'
            f'</div></div>'
            f'<span style="width:40px;text-align:right;font-size:11px;color:#e6edf3">'
            f'{pct:.0f}%</span></div>')


def build_html(results):
    # Summary table rows
    rows = ""
    for r in results:
        if not r:
            continue
        mid = r["mid"]
        label = MATCH_LABELS.get(mid, mid).replace("\n", " ")
        rb_ok = r["rb_zone_pct"] >= 30
        rb_col = "#3fb950" if rb_ok else "#f0883e"
        atk_high = r["atk_pct"] >= 55
        atk_col  = "#3fb950" if atk_high else "#58a6ff"
        flip = f"1H:{'↔' if r['flip_1h'] else '→'} 2H:{'↔' if r['flip_2h'] else '→'}"
        rows += f"""<tr>
          <td style="color:#58a6ff;font-weight:600">{mid}</td>
          <td>{label}</td>
          <td style="text-align:center">{r['players']}</td>
          <td style="text-align:center">{r['n']}</td>
          <td style="text-align:center">{r['cx']:.0f}m</td>
          <td style="text-align:center">{r['cy']:.0f}m</td>
          <td style="text-align:center;color:{atk_col};font-weight:700">{r['atk_pct']:.0f}%</td>
          <td style="text-align:center">{r['right_pct']:.0f}%</td>
          <td style="text-align:center;color:{rb_col};font-weight:700">{r['rb_zone_pct']:.0f}%</td>
          <td style="font-size:11px;color:#8b949e">{flip}</td>
        </tr>"""

    # Per-match zone breakdown cards
    cards = ""
    for r in results:
        if not r:
            continue
        mid = r["mid"]
        label = MATCH_LABELS.get(mid, mid).replace("\n", " ")
        zone_bars = "".join(_zone_bar(r["zone_pct"].get(z, 0), z) for z in ZONES)
        rb_col = "#3fb950" if r["rb_zone_pct"] >= 30 else "#f0883e"
        j6_html = (f'<div style="margin-top:8px;padding:6px;background:#161b22;'
                   f'border-radius:4px;font-size:10px;color:#f0883e">'
                   f'{r["j6_note"]}</div>') if r["j6_note"] else ""
        cards += f"""
        <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;
                    padding:16px;flex:1;min-width:240px;max-width:320px">
          <div style="font-weight:700;color:#58a6ff;font-size:13px">{mid}</div>
          <div style="color:#8b949e;font-size:12px;margin-bottom:10px">{label}</div>
          {zone_bars}
          <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">
            <span style="font-size:11px;background:#21262d;padding:3px 8px;
                         border-radius:4px;color:#58a6ff">
              攻撃 {r['atk_pct']:.0f}%</span>
            <span style="font-size:11px;background:#21262d;padding:3px 8px;
                         border-radius:4px;color:#e6edf3">
              右側 {r['right_pct']:.0f}%</span>
            <span style="font-size:11px;background:#21262d;padding:3px 8px;
                         border-radius:4px;color:{rb_col};font-weight:700">
              右守備 {r['rb_zone_pct']:.0f}%</span>
          </div>
          {j6_html}
          <div style="margin-top:8px;font-size:10px;color:#8b949e">
            n={r['n']} | players={r['players']} |
            1H:{r['n_1h']}pt 2H:{r['n_2h']}pt
          </div>
        </div>"""

    # Limitations notice
    limitation = """
    <div style="background:#21262d;border:1px solid #f0883e;border-radius:8px;
                padding:16px 20px;margin-bottom:24px">
      <h3 style="color:#f0883e;font-size:14px;margin-bottom:8px">
        ⚠ 分析精度についての注記</h3>
      <ul style="color:#8b949e;font-size:12px;line-height:1.8;padding-left:16px">
        <li><strong style="color:#e6edf3">カメラ制限:</strong>
            ボール追尾の単一パン・ズームカメラに<strong>固定ホモグラフィ</strong>を適用しているため、
            フレームごとに座標精度が変動します。ゾーンレベルの傾向は参考値としてご利用ください。</li>
        <li><strong style="color:#e6edf3">OCR精度:</strong>
            小さなブロブからの背番号読み取りは信頼性が低く、#6の個人同定は2試合のみ・精度未検証です。
            本レポートは主にチーム全体のゾーン分布を示します。</li>
        <li><strong style="color:#e6edf3">幻影検出:</strong>
            ベンチや影などが選手として誤検出される場合があります。</li>
        <li><strong style="color:#e6edf3">改善への道:</strong>
            広角固定カメラ + フィールドライン検出によるフレームごとのホモグラフィが正確な個人追跡には必要です。</li>
      </ul>
    </div>"""

    html = f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8">
<title>TZI 総合ゾーン分析 — 牧野羽瑠 #6 トレーニング素材</title>
<style>
* {{box-sizing:border-box;margin:0;padding:0}}
body {{background:#0d1117;color:#e6edf3;font-family:'Segoe UI',system-ui,sans-serif;
       line-height:1.6}}
.hero {{background:linear-gradient(135deg,#0f2027,#203a43,#2c5364);
        padding:28px 36px;border-bottom:1px solid #30363d}}
.hero h1 {{font-size:1.4rem;color:#58a6ff}}
.hero p  {{font-size:.85rem;color:#8b949e;margin-top:4px}}
.content {{max-width:1300px;margin:0 auto;padding:28px 24px}}
h2 {{font-size:1rem;border-bottom:1px solid #30363d;padding-bottom:8px;
     margin:28px 0 16px;color:#e6edf3}}
h3 {{font-size:.9rem;color:#58a6ff;margin:16px 0 8px}}
table {{width:100%;border-collapse:collapse;font-size:12px}}
th {{background:#21262d;padding:9px 10px;text-align:left;color:#8b949e;
     font-weight:500}}
td {{padding:8px 10px;border-bottom:1px solid #21262d}}
tr:hover td {{background:#161b22}}
.cards {{display:flex;flex-wrap:wrap;gap:16px;margin-top:16px}}
.badge {{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px}}
.green  {{background:#1f4d2a;color:#3fb950}}
.blue   {{background:#1a2e50;color:#58a6ff}}
.orange {{background:#4d2c1a;color:#f0883e}}
.insight {{background:#21262d;border-left:3px solid #3fb950;padding:12px 16px;
           border-radius:0 6px 6px 0;margin:12px 0;font-size:13px}}
</style></head><body>
<div class="hero">
  <h1>TZI 総合ゾーン分析 — 牧野羽瑠 #6 トレーニング素材</h1>
  <p>2026年春季 早稲田大学 全8試合 · 早稲田の攻撃方向に統一した正規化座標</p>
  <p style="margin-top:4px">目的: 試合中に常にゾーンに入れる状況を作る · 右サイドバックの活用エリア分析</p>
</div>
<div class="content">

  {limitation}

  <h2>📊 全試合サマリー</h2>
  <table><thead><tr>
    <th>試合ID</th><th>相手</th><th>選手数</th><th>サイティング</th>
    <th>重心X</th><th>重心Y</th>
    <th>攻撃ゾーン率</th><th>右サイド率</th>
    <th>右守備ゾーン率</th><th>方向</th>
  </tr></thead><tbody>{rows}</tbody></table>

  <div style="margin-top:12px;font-size:11px;color:#8b949e">
    攻撃ゾーン率: A1+A2+A3の占有% | 右サイド率: Y>34m(右タッチライン側)の% |
    右守備ゾーン率: 守備ハーフ(X<52.5)かつY>34mの% (右サイドバックの活動域)
  </div>

  <h2>🗺 試合別ゾーン分布</h2>
  <div class="cards">{cards}</div>

  <h2>💡 戦術的インサイト</h2>

  <h3>右チャンネルカバレッジ</h3>
  <div class="insight">
    右サイドバック(#6)が「常にゾーンに入れる状況」を作るには、
    <strong>守備側右チャンネル(D1-D3 × Y>34m)</strong>の
    カバレッジが30%以上であることが目安。
    現在のデータではチームレベルの右側占有率を追跡しており、
    右守備ゾーン率の低い試合では中央に集中する傾向が見られます。
  </div>

  <h3>攻守バランス</h3>
  <div class="insight">
    攻撃ゾーン(A1-A3)が55%以上 = 早稲田が主導権を持つ試合。
    このとき右SBはオーバーラップ頻度が高くなり、A2-A3ゾーンへの
    侵入が増えます。守備的な試合(攻撃率<45%)では深いポジションで
    スタートする回数が増えます。
  </div>

  <h3>Training Focus — #6 牧野羽瑠</h3>
  <div class="insight">
    <strong>【守備時】</strong> D1-D2 × Y>34m をデフォルトポジションとして維持。
    ボールが逆サイド(Y<34)にある時もY>34のゾーンを確保し、
    カウンターアタックに対して幅を保つ。<br><br>
    <strong>【攻撃時】</strong> ボール保持時に A2(Y>34)へのオーバーラップを
    タイミングよく実行。ハーフスペース(A1-A2境界)へのランが
    相手の守備ブロックを広げる効果的なアクション。<br><br>
    <strong>【切り替え】</strong> ロスト直後の即時ネガトランジション:
    D2 × Y>34m へのリトリートを3秒以内に完了するのが目標値。
  </div>

  <h2>🗓 試合分析注記</h2>
  <p style="font-size:12px;color:#8b949e;margin-top:8px">
    各試合のより詳細な分析は match_*/tracking_report_v3.html を参照。<br>
    クロスマッチ検証: cross_match_validation.html | 多試合比較: multi_match_report (準備中)
  </p>

  <h2>🔧 技術改善ロードマップ</h2>
  <table><thead><tr>
    <th>優先度</th><th>課題</th><th>改善案</th><th>工数</th>
  </tr></thead><tbody>
    <tr><td><span class="badge orange">HIGH</span></td>
        <td>固定ホモグラフィ → パンカメラで座標ずれ</td>
        <td>フィールドライン検出によるフレームごとホモグラフィ</td>
        <td>2-3日</td></tr>
    <tr><td><span class="badge orange">HIGH</span></td>
        <td>OCRによる#6識別が2/8試合のみ</td>
        <td>広角固定カメラ + 高解像度録画で番号視認性向上</td>
        <td>撮影改善</td></tr>
    <tr><td><span class="badge blue">MED</span></td>
        <td>幻影検出(ベンチ・影)</td>
        <td>グリーン芝マスクによる検出バリデーション</td>
        <td>4時間</td></tr>
    <tr><td><span class="badge blue">MED</span></td>
        <td>20260316: 選手数51→28(まだ多い)</td>
        <td>Re-IDの類似度閾値・マージ距離の調整</td>
        <td>2時間</td></tr>
    <tr><td><span class="badge green">LOW</span></td>
        <td>方向判定の精度</td>
        <td>GK(#1)位置活用 + メジアンX使用</td>
        <td>1時間</td></tr>
  </tbody></table>

</div>
<div style="text-align:center;padding:20px;color:#8b949e;font-size:11px">
TZI v3 総合ゾーン分析 · Indica Labs / 牧野羽瑠 Development Project · 2026</div>
</body></html>"""

    out = DATA_TZI / "zone_analysis_comprehensive.html"
    out.write_text(html, encoding="utf-8")
    print(f"Saved → {out}")
    return out


def main():
    print("=== TZI Comprehensive Zone Analysis ===")
    results = []
    for mid in MATCH_ORDER:
        data = load_match(mid)
        if data is None:
            print(f"  [{mid}] no data")
            results.append(None)
            continue
        r = analyze_match(mid, data)
        results.append(r)
        if r:
            print(f"  {mid}: n={r['n']} atk={r['atk_pct']:.0f}% "
                  f"right={r['right_pct']:.0f}% rb_zone={r['rb_zone_pct']:.0f}%")

    valid = [r for r in results if r]
    print(f"\nAnalyzed {len(valid)}/{len(MATCH_ORDER)} matches")
    build_html(results)
    print("Done.")


if __name__ == "__main__":
    main()
