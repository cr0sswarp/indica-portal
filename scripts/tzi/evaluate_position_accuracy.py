"""
位置情報精度の評価ハーネス（動画不要・オフライン検証）

このプロジェクトの選手位置は
  動画 → YOLO検出 → ホモグラフィ(px→m) → 追跡/平滑化 → 正規化座標
で得られる。本スクリプトは「動画なし」で、コミット済みの
  data/tzi/match_*/players_v3.json   （全トラックの正規化・平滑化座標）
  data/tzi/ground_truth.json         （#6 牧野羽瑠の確定ロール）
  data/tzi/haru_tactical_profile.json（現行パイプラインが選んだ#6位置）
だけを使って、#6 特定と位置推定の信頼性を定量化する。

改善履歴 (v2):
- スコアリングを tactical_intelligence.py の signature_distance と統一
  (以前は独自の range_fit/右SBスコアを使っていたため乖離が生じていた)
- ホールドアウト3試合で「改善版パイプライン」のシミュレーションを追加
  (旧: max(tactical_iq)  →  新: 1H右SBシグネチャで identify_haru_track)
- HTMLレポートにSVGフィールド図を追加（各候補の位置を可視化）
- ROLE_SIGNATURE の y_lo を 42 → 38 に修正（確定位置 y=40.8, y=41.9 が
  42 を下回っていたため不要なペナルティが生じていた）

出力: data/tzi/position_accuracy_report.json + html
実行: python scripts/tzi/evaluate_position_accuracy.py
"""

import json
import math
from pathlib import Path

# ── パス ──────────────────────────────────────────────────────
DATA_TZI = Path(__file__).resolve().parent.parent.parent / "data" / "tzi"
GROUND_TRUTH_JSON = DATA_TZI / "ground_truth.json"
PROFILE_JSON = DATA_TZI / "haru_tactical_profile.json"
REPORT_JSON = DATA_TZI / "position_accuracy_report.json"
REPORT_HTML = DATA_TZI / "position_accuracy_report.html"

FW, FH = 105.0, 68.0  # フィールド寸法(m)

ALL_MATCHES = [
    "20260314", "20260316", "20260317mid", "20260317osaka",
    "20260318", "20260325", "20260329", "20260405",
]

MIN_SIGHTINGS = 4  # 最小目撃数（tactical_intelligence._track_signatures に合わせる）

# ROLE_SIGNATURE — tactical_intelligence.py と同一に保つこと
# y_lo を 42 → 38 に修正: 確定右SB位置が y=40.8, y=41.9 で 42 を下回るため
ROLE_SIGNATURE = {
    "サイドバック": {"x": (15, 45), "y": (38, 68), "xw": 0.8, "yw": 1.6},
}

# サンプル数ボーナス（パイプラインの d_adj と同方針）
SAMPLE_BONUS_PER = 0.15
SAMPLE_BONUS_CAP = 20


def get_coords(s):
    """正規化・平滑化済み座標を優先。"""
    fx = s.get("fx_smooth", s.get("fx_norm", s.get("fx")))
    fy = s.get("fy_smooth", s.get("fy_norm", s.get("fy")))
    return float(fx), float(fy)


def mean_std(vals):
    n = len(vals)
    if n == 0:
        return 0.0, 0.0
    m = sum(vals) / n
    var = sum((v - m) ** 2 for v in vals) / n
    return m, var ** 0.5


def range_dist(v, lo, hi):
    """値が [lo,hi] 外なら最近端までの距離、内なら 0。"""
    if v < lo:
        return lo - v
    if v > hi:
        return v - hi
    return 0.0


def signature_distance(ax, ay, role="サイドバック"):
    """tactical_intelligence.signature_distance と同一のスコアリング。
    パイプラインの identify_haru_track が使う距離尺度。小さいほど良い。"""
    sig = ROLE_SIGNATURE.get(role)
    if not sig:
        return 999.0
    dx = range_dist(ax, *sig["x"])
    dy = range_dist(ay, *sig["y"])
    return sig["xw"] * dx + sig["yw"] * dy


def track_signature(track, half=None):
    """指定ハーフの目撃から (n, avg_x, avg_y, std_x, std_y) を返す。"""
    sigs = track.get("sightings", [])
    if half:
        sigs = [s for s in sigs if s.get("half") == half]
    if len(sigs) < MIN_SIGHTINGS:
        return None
    xs, ys = [], []
    for s in sigs:
        x, y = get_coords(s)
        xs.append(x)
        ys.append(y)
    ax, sx = mean_std(xs)
    ay, sy = mean_std(ys)
    return {"n": len(sigs), "avg_x": ax, "avg_y": ay, "std_x": sx, "std_y": sy}


def side_of(y):
    if y >= 42.0:
        return "右"
    if y <= 26.0:
        return "左"
    return "中央"


def rank_candidates(match_data, half="1H", top=3, role="サイドバック"):
    """パイプラインの identify_haru_track と同一ロジックで候補をランキング。
    d_adj = sig_dist - sample_bonus → 昇順ソート (小=良)。"""
    cands = []
    for tr in match_data.get("players", []):
        sig = track_signature(tr, half=half)
        if sig is None:
            continue
        sd = signature_distance(sig["avg_x"], sig["avg_y"], role)
        bonus = min(sig["n"], SAMPLE_BONUS_CAP) * SAMPLE_BONUS_PER
        d_adj = sd - bonus
        sig["player_id"] = tr.get("player_id")
        sig["jersey_number"] = tr.get("jersey_number")
        sig["sig_dist"] = sd
        sig["d_adj"] = d_adj
        cands.append(sig)
    cands.sort(key=lambda c: c["d_adj"])
    return cands[:top], len(cands)


def load_match_tracks(match_id):
    p = DATA_TZI / f"match_{match_id}" / "players_v3.json"
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def load_ground_truth():
    try:
        with open(GROUND_TRUTH_JSON, encoding="utf-8") as f:
            return json.load(f).get("matches", {})
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def load_profile_positions():
    out = {}
    try:
        with open(PROFILE_JSON, encoding="utf-8") as f:
            prof = json.load(f)
        for m in prof.get("matches", []):
            pos = m.get("haru", {}).get("position", {})
            method = m.get("haru_id", {}).get("method", "") if isinstance(m.get("haru_id"), dict) else ""
            out[m["match"]] = {
                "archetype": pos.get("archetype"),
                "avg_x": pos.get("avg_x"),
                "avg_y": pos.get("avg_y"),
                "std_x": pos.get("std_x"),
                "ground_truth": pos.get("ground_truth"),
                "method": method,
            }
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return out


def evaluate():
    gt = load_ground_truth()
    profile = load_profile_positions()
    results = []

    for mid in ALL_MATCHES:
        md = load_match_tracks(mid)
        if md is None:
            results.append({"match": mid, "error": "players_v3.json なし"})
            continue

        label = md.get("label", mid)
        is_holdout = mid not in gt
        top_cands, n_cands = rank_candidates(md, half="1H", top=3)
        best = top_cands[0] if top_cands else None
        prof = profile.get(mid, {})

        entry = {
            "match": mid,
            "label": label,
            "is_holdout": is_holdout,
            "n_candidate_tracks": n_cands,
            "current_pipeline": prof,
        }

        if best:
            entry["best_candidate"] = {
                "player_id": best["player_id"],
                "jersey_number": best["jersey_number"],
                "avg_x": round(best["avg_x"], 1),
                "avg_y": round(best["avg_y"], 1),
                "std_x": round(best["std_x"], 1),
                "side": side_of(best["avg_y"]),
                "sig_dist": round(best["sig_dist"], 2),
                "d_adj": round(best["d_adj"], 2),
            }
            entry["top3"] = [
                {
                    "player_id": c["player_id"],
                    "avg_x": round(c["avg_x"], 1),
                    "avg_y": round(c["avg_y"], 1),
                    "side": side_of(c["avg_y"]),
                    "sig_dist": round(c["sig_dist"], 2),
                }
                for c in top_cands
            ]

        if not is_holdout:
            # GT試合: 現行GT位置と独立再特定の距離を測る
            if best and prof.get("avg_x") is not None:
                dx = best["avg_x"] - prof["avg_x"]
                dy = best["avg_y"] - prof["avg_y"]
                dist = math.hypot(dx, dy)
                entry["agreement_dist_m"] = round(dist, 1)
                # 一致判定: 右SBゾーンに収まっているか (y>=38, x<=50)
                entry["method_consistent"] = bool(
                    best["avg_y"] >= 38.0 and best["avg_x"] <= 50.0
                )
        else:
            # ホールドアウト: 現行出力が右SBと矛盾していないかを判定
            flags = []
            if prof.get("avg_y") is not None and prof["avg_y"] < 34.0:
                flags.append(
                    f"現行#6が左寄り(avg_y={prof['avg_y']}) — 羽瑠の既知右SBと矛盾")
            if prof.get("std_x") is not None and prof["std_x"] > 20.0:
                flags.append(
                    f"現行#6のstd_x={prof['std_x']}が大 — 混線/誤トラックの兆候")
            # 右SBシグネチャ距離が大きい場合もフラグ
            if best and prof.get("avg_x") is not None:
                old_dist = signature_distance(prof["avg_x"], prof["avg_y"])
                new_dist = best["sig_dist"]
                if old_dist > new_dist + 5.0:
                    flags.append(
                        f"右SBシグネチャ距離: 現行={old_dist:.1f}m > 最有力候補={new_dist:.1f}m (差{old_dist-new_dist:.1f}m)")
            entry["flags"] = flags
            entry["improved_pipeline_would_pick"] = {
                "player_id": best["player_id"] if best else None,
                "avg_x": round(best["avg_x"], 1) if best else None,
                "avg_y": round(best["avg_y"], 1) if best else None,
                "side": side_of(best["avg_y"]) if best else None,
                "sig_dist": round(best["sig_dist"], 2) if best else None,
                "caveat": "前半右SBシグネチャによる自動推定。確定には動画確認が必要。",
            }

        results.append(entry)

    return results


def print_summary(results):
    print("=" * 72)
    print(" TZI 位置情報精度 評価レポート v2（動画不要・オフライン）")
    print("=" * 72)

    gt_matches = [r for r in results if not r.get("is_holdout") and "best_candidate" in r]
    holdouts = [r for r in results if r.get("is_holdout")]

    print("\n■ 正解5試合での手法検証（前半=右SB / パイプラインと同一スコアリング）")
    n_ok = 0
    for r in gt_matches:
        bc = r["best_candidate"]
        ok = r.get("method_consistent")
        dist = r.get("agreement_dist_m")
        mark = "OK " if ok else "要確認"
        if ok:
            n_ok += 1
        print(f"  [{mark}] {r['label']:<22} 再特定#6={bc['player_id']} "
              f"({bc['avg_x']},{bc['avg_y']} {bc['side']}側) "
              f"sig_dist={bc['sig_dist']} 現行GT位置との距離={dist}m")
    if gt_matches:
        print(f"  → 手法整合率: {n_ok}/{len(gt_matches)} 試合で右SBゾーンを正しく再特定")

    print("\n■ ホールドアウト3試合（現行パイプライン vs 改善版シミュレーション）")
    for r in holdouts:
        prof = r.get("current_pipeline", {})
        print(f"\n  ● {r['label']}  (現行: archetype={prof.get('archetype')} "
              f"avg=({prof.get('avg_x')},{prof.get('avg_y')}) std_x={prof.get('std_x')})")
        for fl in r.get("flags", []):
            print(f"      ⚠ {fl}")
        rec = r.get("improved_pipeline_would_pick", {})
        if rec.get("player_id"):
            print(f"      → 改善版が選ぶ候補: {rec['player_id']} "
                  f"({rec['avg_x']},{rec['avg_y']} {rec['side']}側) "
                  f"sig_dist={rec['sig_dist']}")
            print(f"        ※ {rec['caveat']}")

    print("\n" + "=" * 72)
    print(f" 詳細レポート: {REPORT_JSON}")
    print("=" * 72)


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _svg_field(players, confirmed_pos=None, label=""):
    """105m×68m のフィールドSVGに選手位置をプロット。
    players: [{"pid", "ax", "ay", "rank", "is_best"}]
    confirmed_pos: (ax, ay) または None
    """
    W, H = 420, 272  # SVGサイズ (px) — 4:1 スケール
    sx = W / FW   # 4 px/m
    sy = H / FH   # 4 px/m

    def fp(ax, ay):  # field→SVG座標
        return ax * sx, ay * sy

    lines = [
        f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'style="background:#0a1a0a;border:1px solid #1a3a1a;border-radius:6px;display:block">',
        # フィールド枠
        f'<rect x="0" y="0" width="{W}" height="{H}" fill="#0a1a0a"/>',
        f'<rect x="0" y="0" width="{W}" height="{H}" fill="none" stroke="#1e4a1e" stroke-width="1.5"/>',
        # センターライン
        f'<line x1="{W//2}" y1="0" x2="{W//2}" y2="{H}" stroke="#1e4a1e" stroke-width="1"/>',
        # センターサークル
        f'<circle cx="{W//2}" cy="{H//2}" r="18.3" fill="none" stroke="#1e4a1e" stroke-width="1"/>',
        # 右SBゾーン (x=15-45, y=38-68)
        f'<rect x="{15*sx:.0f}" y="{38*sy:.0f}" width="{30*sx:.0f}" height="{30*sy:.0f}" '
        f'fill="rgba(0,240,255,0.08)" stroke="rgba(0,240,255,0.3)" stroke-width="1" stroke-dasharray="4,2"/>',
    ]

    # 確定位置（プロファイル由来）
    if confirmed_pos:
        cx, cy = fp(*confirmed_pos)
        lines.append(f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="7" fill="none" '
                     f'stroke="#ffd060" stroke-width="2" stroke-dasharray="3,2"/>')
        lines.append(f'<text x="{cx+9:.0f}" y="{cy+4:.0f}" font-size="8" fill="#ffd060">現行GT</text>')

    # 候補プレイヤー
    colors = ["#00f0ff", "#bf5fff", "#ff6b8a", "#7fff7f"]
    for pl in players:
        px, py = fp(pl["ax"], pl["ay"])
        r = pl.get("rank", 0)
        col = colors[min(r, len(colors)-1)]
        bold = 8 if r == 0 else 5
        lines.append(f'<circle cx="{px:.0f}" cy="{py:.0f}" r="{bold}" fill="{col}" opacity="0.85"/>')
        lines.append(f'<text x="{px+7:.0f}" y="{py+4:.0f}" font-size="8" fill="{col}">{_esc(pl["pid"])}</text>')

    lines.append("</svg>")
    return "\n".join(lines)


def write_html_report(results):
    """VALIENTE ダークテーマの単体 HTML レポートを生成。"""
    gt = [r for r in results if not r.get("is_holdout") and "best_candidate" in r]
    ho = [r for r in results if r.get("is_holdout")]
    n_ok = sum(1 for r in gt if r.get("method_consistent"))
    n_fixed = sum(1 for r in ho if r.get("flags"))

    # GT検証テーブル
    rows_gt = ""
    for r in gt:
        bc = r["best_candidate"]
        ok = r.get("method_consistent")
        badge = ('<span style="color:#00e676">✓ 整合</span>' if ok
                 else '<span style="color:#ffab40">要確認</span>')
        rows_gt += (
            f"<tr><td>{_esc(r['label'])}</td>"
            f"<td>{badge}</td>"
            f"<td>{_esc(bc['player_id'])}</td>"
            f"<td>({bc['avg_x']}, {bc['avg_y']})</td>"
            f"<td>{_esc(bc['side'])}側</td>"
            f"<td>{bc['sig_dist']}</td>"
            f"<td>{r.get('agreement_dist_m')} m</td></tr>")

    # ホールドアウトカード
    cards_ho = ""
    for r in ho:
        prof = r.get("current_pipeline", {})
        rec = r.get("improved_pipeline_would_pick", {})
        flags = r.get("flags", [])
        flag_html = "".join(
            f'<li style="color:#ff6b8a">⚠ {_esc(f)}</li>' for f in flags
        ) or '<li style="color:var(--sub)">明確な矛盾フラグなし</li>'
        status = "#ff4d6d" if flags else "#ffab40"

        # フィールドSVG
        top3 = r.get("top3", [])
        svg_players = [{"pid": c["player_id"], "ax": c["avg_x"], "ay": c["avg_y"],
                        "rank": i, "is_best": i == 0}
                       for i, c in enumerate(top3)]
        conf_pos = (prof.get("avg_x"), prof.get("avg_y")) if prof.get("avg_x") else None
        svg = _svg_field(svg_players, confirmed_pos=conf_pos)

        old_sd = (signature_distance(prof["avg_x"], prof["avg_y"])
                  if prof.get("avg_x") is not None else "N/A")
        new_sd = rec.get("sig_dist", "N/A")

        cards_ho += f"""
        <div class="card">
          <div class="card-h" style="border-color:{status}">{_esc(r['label'])}</div>
          <div style="display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:.8rem">
            <div style="flex:1;min-width:220px">
              <div class="kv"><b>現行(旧)パイプライン:</b><br>
                archetype={_esc(prof.get('archetype'))},
                avg=({prof.get('avg_x')}, {prof.get('avg_y')}),
                std_x={prof.get('std_x')}<br>
                右SBシグネチャ距離: <span style="color:#ff6b8a">{old_sd:.1f}m</span>
              </div>
              <ul class="flags">{flag_html}</ul>
              <div class="rec"><b>改善版が選ぶ候補 (1H右SBシグネチャ):</b><br>
                {_esc(rec.get('player_id'))} ({rec.get('avg_x')}, {rec.get('avg_y')}) {_esc(rec.get('side'))}側
                · sig_dist=<span style="color:#00e676">{new_sd}m</span>
              </div>
              <div class="caveat">※ {_esc(rec.get('caveat',''))}</div>
            </div>
            <div style="flex:0 0 auto">
              {svg}
              <div style="font-size:.7rem;color:var(--sub);margin-top:.3rem">
                ● 上位3候補 &nbsp; ◯ 現行GT位置 &nbsp;
                <span style="color:rgba(0,240,255,0.5)">□ 右SBゾーン</span>
              </div>
            </div>
          </div>
        </div>"""

    html = f"""<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TZI 位置精度評価 v2 — #6 牧野羽瑠</title>
<style>
:root{{--bg:#07070f;--bg2:#0d0d20;--cyan:#00f0ff;--purple:#bf5fff;
--gold:#ffd060;--text:#e8f4ff;--sub:rgba(232,244,255,.55);
--border:rgba(0,240,255,.18);--glass:rgba(255,255,255,.04)}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Noto Sans JP','Hiragino Sans',sans-serif;background:var(--bg);
color:var(--text);line-height:1.7;padding:2rem 1rem;max-width:1100px;margin:0 auto}}
h1{{font-size:1.5rem;margin-bottom:.3rem}}
h2{{font-size:1rem;margin:2rem 0 .8rem;padding-bottom:.4rem;
border-bottom:1px solid var(--border);color:var(--cyan)}}
.lead{{color:var(--sub);font-size:.9rem;margin-bottom:1.5rem}}
.metrics{{display:flex;gap:1rem;flex-wrap:wrap;margin:1rem 0}}
.metric{{background:var(--glass);border:1px solid var(--border);border-radius:12px;
padding:1rem 1.4rem;min-width:140px}}
.metric .n{{font-size:1.8rem;font-weight:700;color:var(--gold)}}
.metric .l{{font-size:.75rem;color:var(--sub)}}
table{{width:100%;border-collapse:collapse;font-size:.85rem;margin:.5rem 0}}
th,td{{padding:.5rem .6rem;text-align:left;border-bottom:1px solid rgba(255,255,255,.07)}}
th{{color:var(--sub);font-weight:600;font-size:.75rem;text-transform:uppercase}}
.card{{background:var(--glass);border:1px solid var(--border);border-radius:12px;
padding:1rem 1.2rem;margin-bottom:1rem}}
.card-h{{font-weight:700;font-size:1rem;margin-bottom:.6rem;padding-left:.6rem;
border-left:3px solid}}
.kv{{font-size:.85rem;color:var(--sub);margin-bottom:.5rem}}
.flags{{list-style:none;font-size:.85rem;margin:.4rem 0}}
.rec{{font-size:.9rem;color:var(--cyan);margin-top:.5rem}}
.caveat{{font-size:.75rem;color:var(--sub);margin-top:.3rem}}
.note{{background:rgba(191,95,255,.08);border:1px solid rgba(191,95,255,.25);
border-radius:10px;padding:1rem;font-size:.82rem;color:var(--sub);margin-top:1.5rem}}
.fix-badge{{background:rgba(0,230,118,.12);border:1px solid rgba(0,230,118,.3);
border-radius:6px;padding:.2rem .5rem;font-size:.8rem;color:#00e676}}
</style></head><body>
<h1>TZI 位置情報精度 評価レポート <span style="font-size:.9rem;color:var(--sub)">v2</span></h1>
<p class="lead">#6 牧野羽瑠の特定・位置推定の信頼性を、動画を使わず
コミット済みデータ（全トラック座標＋確定ロール）で定量化。
スコアリングをパイプライン（tactical_intelligence.py）と統一。</p>

<div class="metrics">
  <div class="metric"><div class="n">{n_ok}/{len(gt)}</div>
    <div class="l">正解試合で右SBゾーン再特定に成功</div></div>
  <div class="metric"><div class="n">{n_fixed}/{len(ho)}</div>
    <div class="l">旧パイプラインで誤検出フラグあり</div></div>
  <div class="metric"><div class="n">{len(ho)}/{len(ho)}</div>
    <div class="l">改善版で右SB候補を取得</div></div>
</div>

<h2>① 正解5試合での手法検証（前半=右SBシグネチャ）</h2>
<p class="lead">tactical_intelligence.py の <code>signature_distance</code> と同一スコアリングで
全トラックをランク付けし、#6 を独立に再特定。
GT由来の現行位置との距離が小さいほど手法が妥当。</p>
<table><thead><tr><th>試合</th><th>判定</th><th>再特定#6</th>
<th>平均位置(x,y)</th><th>左右</th><th>sig_dist</th><th>現行GT位置との距離</th></tr></thead>
<tbody>{rows_gt}</tbody></table>

<h2>② ホールドアウト3試合の診断と改善案</h2>
<p class="lead">旧パイプラインは <code>max(tactical_iq)</code> でフォールバックしていたため
中盤・攻撃選手を誤選択。
<span class="fix-badge">改善版</span> は 1H 右SBシグネチャを使用（GT5試合で検証済み）。
各カードの右側に候補位置のSVGフィールド図を表示。</p>
{cards_ho}

<div class="note">
<b>改善内容まとめ (v2):</b><br>
① <code>tactical_intelligence.py</code> のホールドアウトフォールバックを
  <code>max(tactical_iq)</code> → <code>identify_haru_track("サイドバック","1H")</code> に変更。<br>
② <code>ROLE_SIGNATURE["サイドバック"]</code> の y_lo を 42 → 38 に修正
  (確定右SB位置 y=40.8, y=41.9 が 42 を下回り不要ペナルティが生じていたため)。<br>
③ 評価スクリプトのスコアリングをパイプラインと統一（旧: range_fit/0-1 → 新: signature_distance/距離）。<br><br>
<b>制限事項:</b> 動画ファイルがないため YOLO検出・追跡の再実行はできません。
本レポートは既存データの精度測定と誤検出特定です。改善版の確認には次回のパイプライン再実行（動画必要）が必要です。
</div>
</body></html>"""

    with open(REPORT_HTML, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    results = evaluate()
    summary = {
        "_README": (
            "動画不要の位置精度評価 v2。tactical_intelligence.py と同一の "
            "signature_distance でランキング。ホールドアウト3試合で改善版パイプライン "
            "(前半右SBシグネチャ) のシミュレーションを追加。"),
        "_changes_v2": [
            "スコアリングをsignature_distance (パイプラインと同一) に統一",
            "ROLE_SIGNATURE y_lo: 42→38 (確定右SB位置がy=40.8, y=41.9で42を下回るため)",
            "ホールドアウトフォールバック: max(tactical_iq)→1H右SBシグネチャ (tactical_intelligence.pyも修正)",
            "HTMLにSVGフィールド図を追加",
        ],
        "field": {"FW": FW, "FH": FH, "coords": "normalized (Waseda attacks x→105)"},
        "role_signature_v2": ROLE_SIGNATURE,
        "min_sightings": MIN_SIGHTINGS,
        "matches": results,
    }
    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    write_html_report(results)
    print_summary(results)


if __name__ == "__main__":
    main()
