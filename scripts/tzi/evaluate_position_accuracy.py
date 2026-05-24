"""
位置情報精度の評価ハーネス（動画不要・オフライン検証）

このプロジェクトの選手位置は
  動画 → YOLO検出 → ホモグラフィ(px→m) → 追跡/平滑化 → 正規化座標
で得られる。本スクリプトは「動画なし」で、コミット済みの
  data/tzi/match_*/players_v3.json   （全トラックの正規化・平滑化座標）
  data/tzi/ground_truth.json         （#6 牧野羽瑠の確定ロール）
  data/tzi/haru_tactical_profile.json（現行パイプラインが選んだ#6位置）
だけを使って、#6 特定と位置推定の信頼性を定量化する。

なぜこれが「精度向上」になるか:
- 正解5試合で羽瑠は一貫して右SB（正規化座標で X=自陣寄り, Y=右タッチライン側）。
- この既知シグネチャで各試合の全トラックを採点し、最有力#6候補を独立に選び直す。
- 正解5試合で手法を検証（GT由来のパイプライン位置と一致するか）。
- ホールドアウト3試合で現行出力と比較し、右SBと矛盾する誤検出を検出・修正候補化。

注意: ホールドアウト試合の正解は意図的に未公開。本スクリプトの修正候補は
「羽瑠は前半=右SBで始まる」という強い横断事前分布に基づく推定であり、
最終確定には動画確認が必要（その旨をレポートに明記する）。

出力: data/tzi/position_accuracy_report.json + コンソールサマリ
実行: python scripts/tzi/evaluate_position_accuracy.py
"""

import json
from pathlib import Path

# ── パス ──────────────────────────────────────────────────────
DATA_TZI = Path(__file__).resolve().parent.parent.parent / "data" / "tzi"
GROUND_TRUTH_JSON = DATA_TZI / "ground_truth.json"
PROFILE_JSON = DATA_TZI / "haru_tactical_profile.json"
REPORT_JSON = DATA_TZI / "position_accuracy_report.json"
REPORT_HTML = DATA_TZI / "position_accuracy_report.html"

FW, FH = 105.0, 68.0  # フィールド寸法(m)。config.py と一致。

# 全試合（処理順 = 日付順）
ALL_MATCHES = [
    "20260314", "20260316", "20260317mid", "20260317osaka",
    "20260318", "20260325", "20260329", "20260405",
]

# #6 候補と見なす最小目撃数（tactical_intelligence._track_signatures に合わせる）
MIN_SIGHTINGS = 4

# 「右SB」シグネチャ。tactical_intelligence.py の ROLE_SIGNATURE["サイドバック"]
# をそのまま使用（正規化座標: X=15-42 自陣寄り, Y=42-68 右タッチライン側）。
RB_SIG = {"x": (15.0, 42.0), "y": (42.0, 68.0), "xw": 0.8, "yw": 1.6}
# 範囲外でスコアが0に落ちるまでの距離(m)。
DECAY_X, DECAY_Y = 22.0, 22.0
# 守備者として不自然に大きいX分散(=複数選手の混線/誤トラックの兆候)の閾値。
STD_X_SUSPECT = 20.0


def get_coords(s):
    """正規化・平滑化済み座標を優先（get_coords in tactical_intelligence と同方針）。"""
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


def range_fit(v, lo, hi, decay):
    """値 v が [lo,hi] にどれだけ収まるか [0,1]。範囲内=1, 外は距離で線形減衰。"""
    if lo <= v <= hi:
        return 1.0
    d = (lo - v) if v < lo else (v - hi)
    return max(0.0, 1.0 - d / decay)


def right_sb_score(sig):
    """右SBシグネチャ適合度 [0,1]（X/Yを重み付き平均）。"""
    xf = range_fit(sig["avg_x"], RB_SIG["x"][0], RB_SIG["x"][1], DECAY_X)
    yf = range_fit(sig["avg_y"], RB_SIG["y"][0], RB_SIG["y"][1], DECAY_Y)
    xw, yw = RB_SIG["xw"], RB_SIG["yw"]
    return (xw * xf + yw * yf) / (xw + yw)


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
    """現行パイプラインが選んだ#6位置 {match_id: {archetype, avg_x, avg_y, std_x, gt}}"""
    out = {}
    try:
        with open(PROFILE_JSON, encoding="utf-8") as f:
            prof = json.load(f)
        for m in prof.get("matches", []):
            pos = m.get("haru", {}).get("position", {})
            out[m["match"]] = {
                "archetype": pos.get("archetype"),
                "avg_x": pos.get("avg_x"),
                "avg_y": pos.get("avg_y"),
                "std_x": pos.get("std_x"),
                "ground_truth": pos.get("ground_truth"),
            }
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return out


def rank_candidates(match_data, half="1H", top=3):
    """全トラックを右SBスコアで採点し上位を返す。"""
    cands = []
    for tr in match_data.get("players", []):
        sig = track_signature(tr, half=half)
        if sig is None:
            continue
        sig["player_id"] = tr.get("player_id")
        sig["jersey_number"] = tr.get("jersey_number")
        sig["score"] = right_sb_score(sig)
        cands.append(sig)
    cands.sort(key=lambda c: c["score"], reverse=True)
    return cands[:top], len(cands)


def side_of(y):
    """正規化Y → 左右ラベル。Y>=42=右, Y<=26=左, それ以外=中央。"""
    if y >= 42.0:
        return "右"
    if y <= 26.0:
        return "左"
    return "中央"


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
            "current_pipeline": prof,  # 現行#6位置(GT5試合はGT由来 / 3試合は自動)
        }

        if best:
            entry["best_candidate"] = {
                "player_id": best["player_id"],
                "jersey_number": best["jersey_number"],
                "avg_x": round(best["avg_x"], 1),
                "avg_y": round(best["avg_y"], 1),
                "std_x": round(best["std_x"], 1),
                "side": side_of(best["avg_y"]),
                "rb_score": round(best["score"], 3),
            }
            entry["top3"] = [
                {"player_id": c["player_id"], "avg_x": round(c["avg_x"], 1),
                 "avg_y": round(c["avg_y"], 1), "side": side_of(c["avg_y"]),
                 "rb_score": round(c["score"], 3)}
                for c in top_cands
            ]

        # ── 検証 / フラグ ──
        if not is_holdout:
            # 正解試合: 前半=右SB(全5試合)。手法の妥当性を確認。
            # 現行パイプライン位置(GT由来)と独立再特定が一致するか距離で測る。
            if best and prof.get("avg_x") is not None:
                dx = best["avg_x"] - prof["avg_x"]
                dy = best["avg_y"] - prof["avg_y"]
                dist = (dx * dx + dy * dy) ** 0.5
                entry["agreement_dist_m"] = round(dist, 1)
                entry["method_consistent"] = bool(
                    best["avg_y"] >= 40.0 and best["avg_x"] <= 45.0
                )
        else:
            # ホールドアウト: 現行(自動)出力が右SBと矛盾していないかを判定。
            flags = []
            if prof.get("avg_y") is not None and prof["avg_y"] < 34.0:
                flags.append(
                    f"現行#6が左寄り(avg_y={prof['avg_y']}) — 羽瑠の既知右SBと矛盾")
            if prof.get("std_x") is not None and prof["std_x"] > STD_X_SUSPECT:
                flags.append(
                    f"現行#6のstd_x={prof['std_x']}が大 — 混線/誤トラックの兆候")
            entry["flags"] = flags
            # 右SBシグネチャに基づく修正候補（要・動画確認）
            if best:
                entry["recommended_haru_1H"] = {
                    "player_id": best["player_id"],
                    "avg_x": round(best["avg_x"], 1),
                    "avg_y": round(best["avg_y"], 1),
                    "side": side_of(best["avg_y"]),
                    "rb_score": round(best["score"], 3),
                    "caveat": "前半=右SB前提の推定。確定には動画確認が必要。",
                }

        results.append(entry)

    return results


def print_summary(results):
    print("=" * 72)
    print(" TZI 位置情報精度 評価レポート（動画不要・オフライン検証）")
    print("=" * 72)

    gt_matches = [r for r in results if not r.get("is_holdout") and "best_candidate" in r]
    holdouts = [r for r in results if r.get("is_holdout")]

    print("\n■ 正解5試合での手法検証（前半=右SB / 独立再特定 vs 現行GT由来位置）")
    n_ok = 0
    for r in gt_matches:
        bc = r["best_candidate"]
        consistent = r.get("method_consistent")
        dist = r.get("agreement_dist_m")
        mark = "OK " if consistent else "要確認"
        if consistent:
            n_ok += 1
        print(f"  [{mark}] {r['label']:<22} 再特定#6={bc['player_id']} "
              f"({bc['avg_x']},{bc['avg_y']} {bc['side']}側) "
              f"score={bc['rb_score']} 現行との距離={dist}m")
    if gt_matches:
        print(f"  → 手法整合率: {n_ok}/{len(gt_matches)} 試合で右SBを正しく再特定")

    print("\n■ ホールドアウト3試合の診断（現行=自動推定 / 誤検出フラグ）")
    for r in holdouts:
        prof = r.get("current_pipeline", {})
        print(f"\n  ● {r['label']}  (現行: archetype={prof.get('archetype')} "
              f"avg=({prof.get('avg_x')},{prof.get('avg_y')}) "
              f"std_x={prof.get('std_x')})")
        for fl in r.get("flags", []):
            print(f"      ⚠ {fl}")
        if not r.get("flags"):
            print("      （現行出力に明確な矛盾フラグなし）")
        rec = r.get("recommended_haru_1H")
        if rec:
            print(f"      → 右SB修正候補: {rec['player_id']} "
                  f"({rec['avg_x']},{rec['avg_y']} {rec['side']}側) "
                  f"score={rec['rb_score']}")
            print(f"        ※ {rec['caveat']}")

    print("\n" + "=" * 72)
    print(f" 詳細レポート: {REPORT_JSON}")
    print("=" * 72)


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def write_html_report(results):
    """ポータルから開ける単体HTMLレポートを生成（VALIENTE ダークテーマ）。"""
    gt = [r for r in results if not r.get("is_holdout") and "best_candidate" in r]
    ho = [r for r in results if r.get("is_holdout")]
    n_ok = sum(1 for r in gt if r.get("method_consistent"))
    n_flagged = sum(1 for r in ho if r.get("flags"))

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
            f"<td>{bc['rb_score']}</td>"
            f"<td>{r.get('agreement_dist_m')} m</td></tr>")

    cards_ho = ""
    for r in ho:
        prof = r.get("current_pipeline", {})
        rec = r.get("recommended_haru_1H", {})
        flags = r.get("flags", [])
        flag_html = "".join(
            f'<li style="color:#ff6b8a">⚠ {_esc(f)}</li>' for f in flags
        ) or '<li style="color:var(--sub)">明確な矛盾フラグなし</li>'
        status = ("#ff4d6d" if flags else "#ffab40")
        cards_ho += f"""
        <div class="card">
          <div class="card-h" style="border-color:{status}">{_esc(r['label'])}</div>
          <div class="kv"><b>現行(自動)#6:</b> archetype={_esc(prof.get('archetype'))},
             avg=({prof.get('avg_x')}, {prof.get('avg_y')}), std_x={prof.get('std_x')}</div>
          <ul class="flags">{flag_html}</ul>
          <div class="rec"><b>右SB修正候補:</b> {_esc(rec.get('player_id'))}
             ({rec.get('avg_x')}, {rec.get('avg_y')}) {_esc(rec.get('side'))}側 ·
             score={rec.get('rb_score')}</div>
          <div class="caveat">※ {_esc(rec.get('caveat',''))}</div>
        </div>"""

    html = f"""<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TZI 位置精度評価 — #6 牧野羽瑠</title>
<style>
:root{{--bg:#07070f;--bg2:#0d0d20;--cyan:#00f0ff;--purple:#bf5fff;
--gold:#ffd060;--text:#e8f4ff;--sub:rgba(232,244,255,.55);
--border:rgba(0,240,255,.18);--glass:rgba(255,255,255,.04)}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Noto Sans JP','Hiragino Sans',sans-serif;background:var(--bg);
color:var(--text);line-height:1.7;padding:2rem 1rem;max-width:1000px;margin:0 auto}}
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
</style></head><body>
<h1>TZI 位置情報精度 評価レポート</h1>
<p class="lead">#6 牧野羽瑠の特定・位置推定の信頼性を、動画を使わず
コミット済みデータ（全トラック座標＋確定ロール）で定量化。</p>

<div class="metrics">
  <div class="metric"><div class="n">{n_ok}/{len(gt)}</div>
    <div class="l">正解試合で右SB再特定に成功</div></div>
  <div class="metric"><div class="n">{n_flagged}/{len(ho)}</div>
    <div class="l">ホールドアウトで誤検出フラグ</div></div>
</div>

<h2>① 正解5試合での手法検証（前半=右SB）</h2>
<p class="lead">既知の「右SBシグネチャ」で全トラックを採点し独立に#6を再特定。
GT由来の現行位置との距離が小さいほど手法が妥当。</p>
<table><thead><tr><th>試合</th><th>判定</th><th>再特定#6</th>
<th>平均位置(x,y)</th><th>左右</th><th>RBスコア</th><th>現行との距離</th></tr></thead>
<tbody>{rows_gt}</tbody></table>

<h2>② ホールドアウト3試合の診断</h2>
<p class="lead">正解未公開の3試合で、現行の自動推定#6が羽瑠の既知右SB役割と
矛盾していないかを判定。右SB修正候補を提示（確定には動画確認が必要）。</p>
{cards_ho}

<div class="note">
<b>このレポートの位置づけ:</b> 動画ファイルはこの環境に無いため、YOLO検出・追跡の
再実行やモデル学習はできません。本レポートは既存の検出結果に対する
<b>精度の測定と誤検出の特定</b>です。ホールドアウトの修正候補は
「羽瑠は前半=右SBで出場する」という横断的事前分布に基づく推定であり、
最終確定には動画確認のうえ <code>data/tzi/ground_truth.json</code> への追記を推奨します。
</div>
</body></html>"""
    with open(REPORT_HTML, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    results = evaluate()
    summary = {
        "_README": (
            "動画不要の位置精度評価。正解5試合で右SB特定手法を検証し、"
            "ホールドアウト3試合の#6誤検出を定量化。recommended_haru_1H は"
            "「前半=右SB」前提の推定で、確定には動画確認が必要。"),
        "field": {"FW": FW, "FH": FH, "coords": "normalized (Waseda attacks x→105)"},
        "right_sb_signature": RB_SIG,
        "min_sightings": MIN_SIGHTINGS,
        "matches": results,
    }
    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    write_html_report(results)
    print_summary(results)


if __name__ == "__main__":
    main()
