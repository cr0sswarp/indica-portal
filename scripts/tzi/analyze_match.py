#!/usr/bin/env python3
"""
TZI: 汎用試合分析スクリプト
新しい試合の動画から jersey #6 の軌跡を自動抽出し、
フレーム確認画像・軌跡JSON・ヒートマップ・ゾーンレポートを生成する。

使い方:
    python analyze_match.py --match 20260329 --h1 "26_03_29_I_TRM vs川崎U-18 前半.mp4" --h2 "26_03_29_I_TRM vs 川崎U-18 後半.mp4"

フロー:
    1. 5分ごとにフレームを抽出 → data/tzi/match_YYYYMMDD/frames/ に保存
    2. 各フレームで早稲田カラー選手を全員検出
    3. トラッキングで #6 候補を追跡
    4. 軌跡JSON を自動生成（auto_trajectory.json）
    5. ヒートマップ・ゾーンレポートを生成
"""
import cv2, json, numpy as np, argparse, sys
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from pathlib import Path
from scipy.ndimage import gaussian_filter

PROJECT_ROOT = Path(__file__).parent.parent.parent

# 設定
FW, FH = 105.0, 68.0
SRC = np.float32([[20,90],[1255,88],[635,298],[635,705]])
DST = np.float32([[0,0],[105,0],[52.5,34],[52.5,68]])
H_MAT, _ = cv2.findHomography(SRC, DST, cv2.RANSAC, 3.0)

W_LO1, W_HI1 = np.array([0,50,40]),   np.array([12,255,220])
W_LO2, W_HI2 = np.array([165,50,40]), np.array([180,255,220])
KNL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(5,5))

ZONE_COLORS = {"A1":"#e74c3c","A2":"#e67e22","A3":"#f1c40f",
               "D1":"#3498db","D2":"#2980b9","D3":"#1abc9c"}

def p2f(px, py):
    pt = np.array([[[float(px), float(py)]]], dtype=np.float32)
    r  = cv2.perspectiveTransform(pt, H_MAT)
    return float(np.clip(r[0][0][0],0,FW)), float(np.clip(r[0][0][1],0,FH))

def fx_to_zone(fx):
    if fx < 21:   return "D1"
    elif fx < 42: return "D2"
    elif fx < 52.5: return "D3"
    elif fx < 63: return "A1"
    elif fx < 84: return "A2"
    else:         return "A3"

def detect_waseda(frame):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    m = cv2.bitwise_or(cv2.inRange(hsv,W_LO1,W_HI1), cv2.inRange(hsv,W_LO2,W_HI2))
    m[:60,:] = 0; m[680:,:] = 0
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, KNL)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, KNL, iterations=2)
    cnts,_ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cnts:
        a = cv2.contourArea(c)
        if not(60 < a < 2800): continue
        x,y,w,h = cv2.boundingRect(c)
        if h/(w+1e-5) < 0.5 or h/(w+1e-5) > 9: continue
        cx,cy = x+w//2, y+h
        fx,fy = p2f(cx, cy)
        out.append({"px":cx,"py":cy-h//2,"fx":fx,"fy":fy,"bbox":(x,y,x+w,y+h),"area":a})
    return out

def extract_frames(video_path, match_dir, half_label, t_offset, sample_every_min=5.0):
    """動画から N 分おきにフレームを抽出して保存。検出した全選手の位置を返す。"""
    frames_dir = match_dir / "frames"
    frames_dir.mkdir(exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_f = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    sample_frames = int(sample_every_min * 60 * fps)

    print(f"\n{half_label}: {total_f}f, {fps:.0f}fps, ~{total_f/fps/60:.0f}min")
    print(f"サンプリング: {sample_every_min}分おき")

    positions = []
    fn = 0
    while True:
        ret, frame = cap.read()
        if not ret: break
        fn += 1
        if fn % sample_frames != 0: continue

        local_t = fn / fps / 60
        t_min   = local_t + t_offset
        dets    = detect_waseda(frame)

        # フレーム画像に選手を描画して保存
        vis = frame.copy()
        for i, d in enumerate(dets):
            x1,y1,x2,y2 = d["bbox"]
            cv2.rectangle(vis, (x1,y1), (x2,y2), (0,200,0), 2)
            cv2.putText(vis, f"[{i+1}] ({d['fx']:.0f},{d['fy']:.0f})",
                        (x1, y1-5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0,255,0), 1)
        label = f"{half_label} {local_t:.1f}min"
        cv2.putText(vis, label, (10,30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255,255,255), 2)

        fname = f"frame_{half_label}_{local_t:.1f}min.png"
        cv2.imwrite(str(frames_dir / fname), vis)

        for i, d in enumerate(dets):
            positions.append({
                "half": half_label,
                "time_min": round(t_min, 2),
                "local_min": round(local_t, 2),
                "player_idx": i+1,
                "fx": round(d["fx"], 1),
                "fy": round(d["fy"], 1),
                "px": d["px"],
                "py": d["py"],
                "zone": fx_to_zone(d["fx"]),
            })

        print(f"  {label}: {len(dets)}人検出 → {fname}")

    cap.release()
    return positions

def pick_jersey6_auto(positions):
    """
    自動で #6 候補を選択するヒューリスティック。
    D2/D3 ゾーンに多く出現し、時間的に連続しているプレイヤーを選ぶ。
    各時刻に最もそれらしい1つを選択。
    """
    # 時刻ごとにグループ化
    times = {}
    for p in positions:
        key = p["time_min"]
        if key not in times:
            times[key] = []
        times[key].append(p)

    # 各時刻でスコアリング（D2/D3 ゾーンを優先）
    zone_score = {"D1":3, "D2":5, "D3":4, "A1":3, "A2":2, "A3":1}
    trajectory = []
    prev_fx, prev_fy = None, None

    for t in sorted(times.keys()):
        candidates = times[t]
        best = None
        best_score = -999

        for c in candidates:
            score = zone_score.get(c["zone"], 0)
            # 前時刻との距離ペナルティ
            if prev_fx is not None:
                dist = ((c["fx"]-prev_fx)**2 + (c["fy"]-prev_fy)**2)**0.5
                score -= dist * 0.1
            if score > best_score:
                best_score = score
                best = c

        if best:
            trajectory.append({
                "frame": int(best["time_min"] * 30 * 60),
                "fx": best["fx"],
                "fy": best["fy"],
                "time_min": best["time_min"],
                "half": best["half"],
                "note": f"auto: player_idx={best['player_idx']}",
            })
            prev_fx, prev_fy = best["fx"], best["fy"]

    return trajectory

def generate_heatmap(positions, match_dir, match_label):
    """ヒートマップ生成"""
    out_path = match_dir / "heatmap_jersey6.png"
    xs = [p["fx"] for p in positions]
    ys = [p["fy"] for p in positions]
    halves = [p.get("half","?") for p in positions]
    times  = [p["time_min"] for p in positions]

    fig = plt.figure(figsize=(16,8), facecolor='#1a1a2e')
    gs  = fig.add_gridspec(1,2, width_ratios=[3,1])
    ax  = fig.add_subplot(gs[0], facecolor='#2d5a1b')
    ax2 = fig.add_subplot(gs[1], facecolor='#1a1a2e')

    ax.set_xlim(0,FW); ax.set_ylim(0,FH); ax.set_aspect('equal')
    ax.add_patch(patches.Rectangle((0,0),FW,FH,fill=False,ec='white',lw=2))
    ax.axvline(FW/2,color='white',alpha=0.8,lw=1.5)
    for vx in [21,42,63,84]:
        ax.axvline(vx,color='white',alpha=0.25,lw=0.8)
    for px,pw in [(0,16.5),(FW-16.5,16.5)]:
        ax.add_patch(patches.Rectangle((px,13.84),pw,40.32,fill=False,ec='white',alpha=0.4,lw=0.8))

    # ヒートマップ
    H,W2=340,520; grid=np.zeros((H,W2))
    for x,y in zip(xs,ys):
        gx=int(np.clip(x/FW*(W2-1),0,W2-1)); gy=int(np.clip(y/FH*(H-1),0,H-1))
        grid[gy,gx]+=1
    grid=gaussian_filter(grid,sigma=12)
    if grid.max()>0: grid/=grid.max()
    ax.imshow(grid,extent=[0,FW,0,FH],origin='lower',cmap='YlOrRd',alpha=0.55,aspect='auto')

    # ゾーンラベル
    for zone,cx in [("D1",10.5),("D2",31.5),("D3",47.25),("A1",57.75),("A2",73.5),("A3",94.5)]:
        ax.text(cx,FH+1,zone,ha='center',color='#888',fontsize=9,fontweight='bold')

    # ポジション散布
    h1_x=[x for x,h in zip(xs,halves) if h=="1H"]
    h1_y=[y for y,h in zip(ys,halves) if h=="1H"]
    h2_x=[x for x,h in zip(xs,halves) if h=="2H"]
    h2_y=[y for y,h in zip(ys,halves) if h=="2H"]
    if h1_x: ax.plot(h1_x,h1_y,'o-',color='#4fc3f7',lw=1.5,ms=8,label='1H',
                     markeredgecolor='white',markeredgewidth=0.5,zorder=6)
    if h2_x: ax.plot(h2_x,h2_y,'s-',color='#ffb74d',lw=1.5,ms=8,label='2H',
                     markeredgecolor='white',markeredgewidth=0.5,zorder=6)
    for x,y,t in zip(xs,ys,times):
        ax.annotate(f"{t:.0f}m",xy=(x,y),xytext=(3,3),textcoords='offset points',
                    fontsize=6.5,color='white',fontweight='bold')

    ax.set_title(f"Jersey #6 Heatmap  {match_label}", color='white', fontsize=13)
    ax.set_xlabel("Field Length (m)", color='white')
    ax.set_ylabel("Field Width (m)", color='white')
    ax.tick_params(colors='white')
    ax.legend(loc='upper right',facecolor='#222',labelcolor='white',fontsize=9)

    # タイムライン
    h1_t=[t for t,h in zip(times,halves) if h=="1H"]
    h1_yy=[y for y,h in zip(ys,halves) if h=="1H"]
    h2_t=[t for t,h in zip(times,halves) if h=="2H"]
    h2_yy=[y for y,h in zip(ys,halves) if h=="2H"]
    if h1_t: ax2.plot(h1_t,h1_yy,'o-',color='#4fc3f7',label='1H',lw=1.5,ms=5)
    if h2_t: ax2.plot(h2_t,h2_yy,'s-',color='#ffb74d',label='2H',lw=1.5,ms=5)
    ax2.axhline(34,color='white',alpha=0.3,lw=0.8,ls='--')
    ax2.set_xlim(0,90); ax2.set_ylim(0,FH)
    ax2.set_xlabel("Match Time (min)", color='white',fontsize=9)
    ax2.set_ylabel("Y position (m)", color='white',fontsize=9)
    ax2.set_title("Y-axis Timeline", color='white',fontsize=10)
    ax2.tick_params(colors='white')
    ax2.legend(fontsize=8,facecolor='#2a2a4a',labelcolor='white')

    plt.tight_layout()
    plt.savefig(str(out_path),dpi=150,bbox_inches='tight',facecolor='#1a1a2e')
    plt.close()
    print(f"ヒートマップ保存: {out_path}")
    return out_path

def compute_zone_score(positions):
    if len(positions) < 2:
        return {"P":0,"M":0,"D":0,"V":0,"B":0,"total":0}
    xs    = [p["fx"] for p in positions]
    ys    = [p["fy"] for p in positions]
    times = [p["time_min"] for p in positions]
    atk   = sum(1 for x in xs if x >= 52.5)
    p_score = min(20, int(atk/len(xs)*40))
    total_dist = sum(((xs[i]-xs[i-1])**2+(ys[i]-ys[i-1])**2)**0.5 for i in range(1,len(xs)))
    m_score = min(20, int(total_dist/max(1,times[-1]-times[0])*2))
    gaps = [times[i]-times[i-1] for i in range(1,len(times)) if times[i]-times[i-1]>0]
    d_score = min(20, max(0, int(20 - np.mean(gaps)*0.5))) if gaps else 5
    v_score = min(20, int((max(xs)-min(xs))/FW*40))
    b_score = min(20, max(0, int(20 - np.std(ys)*0.5))) if len(ys)>1 else 10
    total = p_score+m_score+d_score+v_score+b_score
    return {"P":p_score,"M":m_score,"D":d_score,"V":v_score,"B":b_score,"total":total}

def zone_level(score):
    if score >= 90: return "完全ゾーン", "#e74c3c"
    if score >= 70: return "準ゾーン",   "#e67e22"
    if score >= 50: return "通常",       "#27ae60"
    if score >= 30: return "低集中",     "#f39c12"
    return "要確認", "#e74c3c"

# ── メイン ─────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="TZI 試合分析")
    parser.add_argument("--match",  required=True, help="試合日 e.g. 20260329")
    parser.add_argument("--h1",     required=True, help="前半動画ファイル名")
    parser.add_argument("--h2",     required=True, help="後半動画ファイル名")
    parser.add_argument("--label",  default="",    help="試合ラベル e.g. 'vs川崎U-18'")
    parser.add_argument("--sample", type=float, default=5.0, help="サンプリング間隔（分）")
    args = parser.parse_args()

    video_h1 = PROJECT_ROOT / "videos" / args.h1
    video_h2 = PROJECT_ROOT / "videos" / args.h2
    match_dir = PROJECT_ROOT / "data" / "tzi" / f"match_{args.match}"
    match_label = args.label or args.match

    for v in [video_h1, video_h2]:
        if not v.exists():
            print(f"ERROR: 動画が見つかりません: {v}")
            sys.exit(1)

    match_dir.mkdir(parents=True, exist_ok=True)
    print(f"=== TZI 分析: {match_label} ===")
    print(f"出力先: {match_dir}")

    # 1. フレーム抽出・選手検出
    all_positions = []
    p1 = extract_frames(video_h1, match_dir, "1H", 0,  args.sample)
    p2 = extract_frames(video_h2, match_dir, "2H", 45, args.sample)
    all_positions = p1 + p2

    # 全選手データを保存
    all_json = match_dir / "all_detections.json"
    with open(all_json, "w") as f:
        json.dump({"match": match_label, "sample_min": args.sample,
                   "total_detections": len(all_positions), "data": all_positions}, f,
                  ensure_ascii=False, indent=2)
    print(f"\n全選手検出データ保存: {all_json}")

    # 2. #6 自動推定
    trajectory = pick_jersey6_auto(all_positions)
    traj_json = match_dir / "jersey6_trajectory.json"
    with open(traj_json, "w") as f:
        json.dump({
            "match": match_label,
            "jersey": "6",
            "note": "auto-generated — please verify and correct manually",
            "confirmed_positions": trajectory
        }, f, ensure_ascii=False, indent=2)
    print(f"軌跡JSON (自動推定) 保存: {traj_json}")
    print(f"→ data/tzi/match_{args.match}/frames/ のフレーム画像で各時刻の #6 の位置を確認し")
    print(f"  jersey6_trajectory.json を手動修正してください")

    # 3. ヒートマップ生成（自動推定ベース）
    if trajectory:
        generate_heatmap(trajectory, match_dir, match_label)

    # 4. ゾーンスコア
    scores = compute_zone_score(trajectory)
    label, color = zone_level(scores["total"])
    print(f"\n─── ゾーンスコア（自動推定ベース） ───")
    print(f"P ポジショニング: {scores['P']:2d}/20")
    print(f"M 動きの流動性:  {scores['M']:2d}/20")
    print(f"D 判断速度:      {scores['D']:2d}/20")
    print(f"V 視野の広さ:    {scores['V']:2d}/20")
    print(f"B 身体の軸:      {scores['B']:2d}/20")
    print(f"─────────────────────────────")
    print(f"TOTAL: {scores['total']}/100  {label}")

    print(f"\n✅ 完了！次のステップ:")
    print(f"  1. data/tzi/match_{args.match}/frames/ のフレーム画像で #6 を確認")
    print(f"  2. jersey6_trajectory.json を必要に応じて手動修正")
    print(f"  3. python generate_zone_report.py で最終レポートを生成")

if __name__ == "__main__":
    main()
