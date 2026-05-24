#!/usr/bin/env python3
"""
TZI Tactical Intelligence Engine — 認知・創造性・原理原則の数値化

牧野羽瑠 (Haru Makino) のような「ポジションを超えた原理原則の体現者」
(フレンキー・デ・ヨング / トニー・クロース型) を分析するためのエンジン。

設計思想:
  「ポジションは試合ごとに変わる。だが原理原則は変わらない。
   そして決定的な瞬間に意図的にバランスを崩し、主役になる。」

このエンジンは固定ポジション前提を捨て、以下を測定する:

  1. ポジション推定 (Position Detection)
     - スペイン式 5レーン × 6ゾーン (30セル) グリッドで実プレー領域を特定
     - アーキタイプ分類: アンカー / セントラル / トップ / SB / CB

  2. 認知スコア (Cognición / Game Reading)
     - チーム重心に対する選手の「先行/遅行」を時系列相互相関で計測
     - ボールが来る前に正しい空間にいる = 高い認知 (lectura del juego)

  3. 原理原則スコア (Principios / Positional Play Adherence)
     - 検出ポジションに対する juego de posición 原則の遵守度
     - サポート角度・ライン間占有・幅と深さの提供

  4. 創造性スコア (Creatividad / Controlled Line-Breaking)
     - 単なる無秩序ではなく「高価値空間への意図的逸脱」を計測
     - ゾーン価値マップ × ポジション基準からの逸脱 = 真の創造性

  5. 主役度 (Protagonismo / Centrality)
     - チーム構造における結節点としての中心性

使い方:
    python tactical_intelligence.py                 # 全試合・自動推定
    python tactical_intelligence.py --match 20260325 # 単一試合

出力:
    data/tzi/tactical_intelligence.html  — プロフェッショナル・スカウティングレポート
    data/tzi/haru_tactical_profile.json  — 機械可読プロファイル
"""

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_TZI = PROJECT_ROOT / "data" / "tzi"
FW, FH = 105.0, 68.0

# ── スペイン式ポジショナルプレー・グリッド ─────────────────────
# 5 レーン (carriles) — 横方向 (Y: 0-68m), Waseda攻撃方向は X→105
LANES = [
    ("LW", "左ウイング",        0.0,  13.6),
    ("LH", "左ハーフスペース",  13.6, 27.2),
    ("C",  "中央",              27.2, 40.8),
    ("RH", "右ハーフスペース",  40.8, 54.4),
    ("RW", "右ウイング",        54.4, 68.0),
]
# 6 ゾーン (zonas) — 縦方向 (X: 0-105m)
ZONES = [
    ("D1", "自陣最終",  0.0,   21.0),
    ("D2", "自陣中盤",  21.0,  42.0),
    ("D3", "自陣前",    42.0,  52.5),
    ("A1", "敵陣入口",  52.5,  63.0),
    ("A2", "敵陣中盤",  63.0,  84.0),
    ("A3", "敵陣深部",  84.0,  105.0),
]

# ── ゾーン価値マップ (peligrosidad / 危険度) ──────────────────
# 5レーン × 6ゾーン = 30セル。ハーフスペース×敵陣 = 最高価値。
# モダンサッカーの「ライン間」「ハーフスペース」理論に基づく。
# 行 = レーン (LW,LH,C,RH,RW), 列 = ゾーン (D1..A3)
ZONE_VALUE = np.array([
    # D1   D2   D3   A1   A2   A3
    [0.10, 0.20, 0.35, 0.55, 0.70, 0.80],  # LW 左ウイング
    [0.15, 0.30, 0.50, 0.75, 0.90, 0.95],  # LH 左ハーフスペース ★
    [0.20, 0.35, 0.45, 0.60, 0.70, 0.85],  # C  中央
    [0.15, 0.30, 0.50, 0.75, 0.90, 0.95],  # RH 右ハーフスペース ★
    [0.10, 0.20, 0.35, 0.55, 0.70, 0.80],  # RW 右ウイング
])


def lane_idx(fy: float) -> int:
    for i, (_, _, lo, hi) in enumerate(LANES):
        if lo <= fy < hi:
            return i
    return 4 if fy >= FH else 0


def zone_idx(fx: float) -> int:
    for i, (_, _, lo, hi) in enumerate(ZONES):
        if lo <= fx < hi:
            return i
    return 5 if fx >= FW else 0


def get_coords(s: dict):
    """正規化・平滑化済み座標を優先取得 (Waseda always attacks → 105)."""
    fx = s.get("fx_smooth", s.get("fx_norm", s["fx"]))
    fy = s.get("fy_smooth", s.get("fy_norm", s["fy"]))
    return float(fx), float(fy)


# ── ポジション・アーキタイプ推定 ─────────────────────────────

POSITION_ARCHETYPES = {
    "アンカー":     {"x": (30, 50), "lane": "C",  "x_var_max": 14, "desc": "守備的MF / ピボーテ"},
    "セントラル":   {"x": (40, 62), "lane": "H",  "x_var_max": 22, "desc": "中央MF / インテリオール"},
    "トップ下":     {"x": (58, 75), "lane": "CH", "x_var_max": 20, "desc": "攻撃的MF / メディアプンタ"},
    "トップ":       {"x": (70, 95), "lane": "CH", "x_var_max": 22, "desc": "FW / デランテロ"},
    "サイドバック": {"x": (25, 58), "lane": "W",  "x_var_max": 99, "desc": "SB / ラテラル"},
    "センターバック": {"x": (12, 38), "lane": "CH", "x_var_max": 14, "desc": "CB / セントラル"},
}


def detect_position(track: dict) -> dict:
    """位置シグネチャからポジション・アーキタイプを推定."""
    sigs = track["sightings"]
    xs = np.array([get_coords(s)[0] for s in sigs])
    ys = np.array([get_coords(s)[1] for s in sigs])
    ax, ay = float(np.mean(xs)), float(np.mean(ys))
    sx, sy = float(np.std(xs)), float(np.std(ys))

    li = lane_idx(ay)
    lane_code = LANES[li][0]
    lane_group = ("W" if lane_code in ("LW", "RW")
                  else "H" if lane_code in ("LH", "RH")
                  else "C")

    # スコアリング: 各アーキタイプとの適合度
    best, best_score = None, -1.0
    for name, arc in POSITION_ARCHETYPES.items():
        score = 0.0
        xlo, xhi = arc["x"]
        # X位置適合
        if xlo <= ax <= xhi:
            score += 2.0
        else:
            d = min(abs(ax - xlo), abs(ax - xhi))
            score += max(0, 2.0 - d / 15)
        # レーン適合
        want = arc["lane"]
        if want == "W" and lane_group == "W":
            score += 1.5
        elif want == "C" and lane_group == "C":
            score += 1.5
        elif want == "H" and lane_group == "H":
            score += 1.5
        elif want == "CH" and lane_group in ("C", "H"):
            score += 1.0
        # X分散適合 (SBは大きく動く / アンカー・CBは安定)
        if sx <= arc["x_var_max"]:
            score += 0.8
        if score > best_score:
            best_score, best = score, name

    return {
        "archetype": best,
        "desc": POSITION_ARCHETYPES[best]["desc"],
        "avg_x": round(ax, 1), "avg_y": round(ay, 1),
        "std_x": round(sx, 1), "std_y": round(sy, 1),
        "primary_lane": LANES[li][1],
        "lane_group": lane_group,
        "confidence": round(min(1.0, best_score / 4.3), 2),
    }


# ── 認知スコア (Cognición) ───────────────────────────────────

def cognition_score(track: dict, team_centroid_series: dict) -> dict:
    """
    チーム重心に対する「先行性」を計測する。
    ボールが来る前に正しい空間に入る = 高い認知 (anticipación).

    手法: 連続フレームで、選手のX変化がチーム重心のX変化に
          「先行」しているか (選手が先に動くか) を相互相関で評価。
          正の lead = 選手がフェーズ変化を先読みしている。
    """
    sigs = sorted(track["sightings"], key=lambda s: s["time_min"])
    if len(sigs) < 4:
        return {"score": None, "lead_frames": None, "note": "サンプル不足"}

    # 選手のX系列 (時刻でソート)
    times = [s["time_min"] for s in sigs]
    player_x = np.array([get_coords(s)[0] for s in sigs])

    # 同時刻のチーム重心X (補間)
    tc_times = sorted(team_centroid_series.keys())
    tc_x = np.array([team_centroid_series[t][0] for t in tc_times])
    if len(tc_times) < 4:
        return {"score": None, "lead_frames": None, "note": "チーム重心不足"}

    interp_team_x = np.interp(times, tc_times, tc_x)

    # 選手の動きとチーム重心の動きの差分 (速度)
    dp = np.diff(player_x)
    dt = np.diff(interp_team_x)
    if len(dp) < 2 or np.std(dp) < 1e-6 or np.std(dt) < 1e-6:
        return {"score": 50, "lead_frames": 0, "note": "動き静的"}

    # lag=+1: 選手がチームより1フレーム先行
    # 正規化相互相関を lag=-1,0,+1 で計算
    def ncc(a, b):
        a = (a - a.mean()) / (a.std() + 1e-9)
        b = (b - b.mean()) / (b.std() + 1e-9)
        return float(np.mean(a * b))

    n = min(len(dp), len(dt))
    dp, dt = dp[:n], dt[:n]
    # 選手先行: 選手の現在の動きが、チームの「次の」動きと相関
    lead = ncc(dp[:-1], dt[1:]) if n > 2 else 0.0
    sync = ncc(dp, dt)
    lag = ncc(dp[1:], dt[:-1]) if n > 2 else 0.0

    # 先行性が同期・遅行を上回るほど高スコア
    raw = (lead - lag)  # -2..+2 程度
    score = int(np.clip(50 + raw * 35, 0, 100))

    if lead > sync and lead > lag:
        note = "フェーズ先読み型 (先に動く)"
    elif sync >= lead and sync >= lag:
        note = "同期型 (チームと連動)"
    else:
        note = "反応型 (ボールに反応)"

    return {"score": score, "lead": round(lead, 2),
            "sync": round(sync, 2), "lag": round(lag, 2), "note": note}


# ── 原理原則スコア (Principios) ──────────────────────────────

def principle_score(track: dict, position: dict) -> dict:
    """
    juego de posición 原則の遵守度。
    検出ポジションに応じた「あるべき振る舞い」との適合。

    評価軸:
      - Amplitud (幅): ウイング/SBは幅を取れているか
      - Profundidad (深さ): 適切な縦の存在感
      - Ocupación entrelíneas (ライン間占有): ハーフスペース活用
      - Equilibrio (バランス): 過度に持ち場を離れていないか
    """
    sigs = track["sightings"]
    n = len(sigs)
    cells = np.zeros((5, 6))
    for s in sigs:
        fx, fy = get_coords(s)
        cells[lane_idx(fy), zone_idx(fx)] += 1
    cells_norm = cells / max(cells.sum(), 1)

    arc = position["archetype"]
    lane_g = position["lane_group"]

    # ライン間 (ハーフスペース) 占有率
    halfspace_occ = cells_norm[1].sum() + cells_norm[3].sum()  # LH + RH
    # 幅占有 (両ウイング)
    width_occ = cells_norm[0].sum() + cells_norm[4].sum()
    # 中央占有
    central_occ = cells_norm[2].sum()
    # 縦の重心
    x_balance = float(np.mean([get_coords(s)[0] for s in sigs]))

    # ポジション別の理想プロファイル
    score = 50.0
    detail = []
    if arc in ("サイドバック",):
        # 幅を取るべき
        score += width_occ * 40
        detail.append(f"幅の提供 {width_occ*100:.0f}%")
        if halfspace_occ > 0.25:
            score += 10
            detail.append("内側レーン進入(偽SB的)")
    elif arc in ("アンカー", "センターバック"):
        # 中央安定 + 適度なライン間
        score += central_occ * 30 + halfspace_occ * 20
        detail.append(f"中央安定 {central_occ*100:.0f}%")
        if position["std_x"] < 15:
            score += 10
            detail.append("ポジション規律◎")
    elif arc in ("セントラル", "トップ下"):
        # ハーフスペース活用が生命線
        score += halfspace_occ * 50
        detail.append(f"ライン間占有 {halfspace_occ*100:.0f}%")
    elif arc == "トップ":
        # 深さと最終ライン駆け引き
        depth = cells_norm[:, 4:].sum()  # A2+A3
        score += depth * 45
        detail.append(f"敵陣深部 {depth*100:.0f}%")

    score = int(np.clip(score, 0, 100))
    return {"score": score, "halfspace_occ": round(halfspace_occ, 2),
            "width_occ": round(width_occ, 2), "central_occ": round(central_occ, 2),
            "detail": detail}


# ── 創造性スコア (Creatividad) ───────────────────────────────

def creativity_score(track: dict, position: dict) -> dict:
    """
    真の創造性 = 無秩序ではなく「高価値空間への意図的逸脱」。

    De Jong / Kroos の本質:
      彼らはランダムに動くのではない。相手の構造を破壊する
      「ライン間・ハーフスペース」へ、適切な瞬間に侵入する。

    計測:
      1. 空間エントロピー (どれだけ多様なセルを使うか)
      2. 高価値侵入度 (ゾーン価値マップで重み付けした逸脱)
      3. ライン突破指数 (ポジション基準ゾーンより前進した割合)
    """
    sigs = track["sightings"]
    n = len(sigs)
    cells = np.zeros((5, 6))
    for s in sigs:
        fx, fy = get_coords(s)
        cells[lane_idx(fy), zone_idx(fx)] += 1
    p = cells.flatten()
    p = p / max(p.sum(), 1)

    # 1. 正規化シャノンエントロピー (0-1)
    nonzero = p[p > 0]
    H = -np.sum(nonzero * np.log2(nonzero)) if len(nonzero) else 0.0
    H_max = math.log2(30)  # 30セル
    entropy_norm = H / H_max

    # 2. 高価値侵入度 — 訪問セルをゾーン価値で重み付け
    value_weighted = float(np.sum(cells * ZONE_VALUE) / max(cells.sum(), 1))

    # 3. ライン突破指数 — 平均X位置を超えて前進した割合
    xs = np.array([get_coords(s)[0] for s in sigs])
    median_x = np.median(xs)
    breaks = np.sum(xs > median_x + 12) / max(n, 1)  # 12m以上前進

    # 創造性 = エントロピー × 高価値侵入 × ライン突破 の調和
    # ただし「規律あるポジション」では適度なエントロピーが理想
    # → エントロピーは0.5-0.75が最良 (低すぎ=単調, 高すぎ=無秩序)
    entropy_quality = 1.0 - abs(entropy_norm - 0.62) / 0.62
    entropy_quality = max(0, entropy_quality)

    raw = (0.35 * entropy_quality +
           0.45 * value_weighted +
           0.20 * min(1.0, breaks * 2.5))
    score = int(np.clip(raw * 100, 0, 100))

    # 最高価値セル (どこで創造性を発揮したか)
    flat = cells.flatten() * ZONE_VALUE.flatten()
    top_cell = int(np.argmax(flat)) if flat.sum() > 0 else 0
    tl, tz = top_cell // 6, top_cell % 6
    hotspot = f"{LANES[tl][1]} × {ZONES[tz][1]}"

    return {"score": score, "entropy": round(entropy_norm, 2),
            "value_intrusion": round(value_weighted, 2),
            "line_break": round(float(breaks), 2),
            "creative_hotspot": hotspot}


# ── 主役度 (Protagonismo) ────────────────────────────────────

def protagonist_index(track: dict, all_tracks: list) -> dict:
    """
    チーム構造における結節点としての中心性。
    多くの味方とリンク可能な位置 (適度な距離) にいる頻度。
    """
    sigs = sorted(track["sightings"], key=lambda s: s["time_min"])
    if len(sigs) < 3:
        return {"score": None}

    # 各時刻で、他選手との「リンク可能距離(8-25m)」にいる味方数
    by_time = defaultdict(list)
    for t in all_tracks:
        for s in t["sightings"]:
            by_time[round(s["time_min"], 1)].append(get_coords(s))

    link_counts = []
    for s in sigs:
        t = round(s["time_min"], 1)
        me = get_coords(s)
        others = [o for o in by_time.get(t, []) if o != me]
        links = sum(1 for o in others
                    if 8 <= math.hypot(me[0] - o[0], me[1] - o[1]) <= 28)
        link_counts.append(links)

    avg_links = float(np.mean(link_counts)) if link_counts else 0
    score = int(np.clip(avg_links / 4 * 100, 0, 100))
    return {"score": score, "avg_links": round(avg_links, 1)}


# ── チーム重心系列 ───────────────────────────────────────────

def compute_team_centroid_series(all_tracks: list) -> dict:
    """各時刻のチーム重心 (X,Y) を返す."""
    by_time = defaultdict(list)
    for t in all_tracks:
        for s in t["sightings"]:
            by_time[round(s["time_min"], 1)].append(get_coords(s))
    series = {}
    for t, pts in by_time.items():
        if pts:
            arr = np.array(pts)
            series[t] = (float(arr[:, 0].mean()), float(arr[:, 1].mean()))
    return series


# ── 羽瑠トラック特定 ─────────────────────────────────────────
# 牧野羽瑠は試合ごと・試合中にポジションを変える (背番号6)。OCRは機能しない
# ため、Makino氏から得た「試合別・時間帯別の確定ポジション」を
# グラウンドトゥルースとして用い、位置シグネチャでトラックを特定する。
#
# 設計判断 (track_players_v3.py の作者注に基づく):
#   正規化座標 (Wasedaは常に x→105 へ攻撃, Yは反転しない) において
#   「右サイドバック」は X=15-40m(自陣寄り), Y=42-68m(右タッチライン側)。
#
# ── ロール別ターゲット・シグネチャ (正規化座標) ──────────────
ROLE_SIGNATURE = {
    #                X範囲(縦)      Y範囲(横:右=高Y)   X重み  Y重み
    "サイドバック": {"x": (15, 42), "y": (42, 68), "xw": 0.8, "yw": 1.6},
    "アンカー":     {"x": (28, 50), "y": (24, 44), "xw": 1.0, "yw": 1.0},
    "セントラル":   {"x": (38, 60), "y": (38, 56), "xw": 1.0, "yw": 1.3},
    "トップ下":     {"x": (58, 78), "y": (27, 48), "xw": 1.0, "yw": 0.8},
    "トップ":       {"x": (72, 98), "y": (24, 48), "xw": 1.2, "yw": 0.6},
    "センターバック": {"x": (10, 35), "y": (24, 44), "xw": 1.0, "yw": 1.0},
}

# 試合別・時間帯別の確定ポジション (Makino氏ヒアリング)。
# 5試合で実装/チューニング、残り3試合 (20260318/20260329/20260405) は
# 「ホールドアウト検証用」として意図的に未記入 → 自動推定にフォールバック。
HARU_GROUND_TRUTH = {
    "20260314": {  # 埼玉大 (前後半1本の結合動画)
        "note": "前半=右SB / 後半21:35〜ボランチ(6番)・試合終了まで",
        "segments": [
            {"half": "1H", "role": "サイドバック", "label": "右SB"},
            {"half": "2H", "role": "サイドバック", "label": "右SB",
             "t_rel": (0.0, 21.58)},
            {"half": "2H", "role": "アンカー",     "label": "ボランチ",
             "t_rel": (21.58, 999.0)},
        ],
    },
    "20260316": {  # 岐阜協立 (前後半1本の結合動画)
        "note": "90分通して右SB",
        "segments": [
            {"half": "1H", "role": "サイドバック", "label": "右SB"},
            {"half": "2H", "role": "サイドバック", "label": "右SB"},
        ],
    },
    "20260317mid": {  # 中京U-19
        "note": "前半22:15〜右SB(6番) / 後半ボランチスタート〜23:15頃",
        "segments": [
            {"half": "1H", "role": "サイドバック", "label": "右SB"},
            {"half": "2H", "role": "アンカー",     "label": "ボランチ"},
        ],
    },
    "20260317osaka": {  # 大阪学院
        "note": "前後半とも右SB(6番) ※後半14:50は交代の出入り",
        "segments": [
            {"half": "1H", "role": "サイドバック", "label": "右SB"},
            {"half": "2H", "role": "サイドバック", "label": "右SB"},
        ],
    },
    "20260325": {  # 立教 ※動画なし・既存3分データ
        "note": "前半=右SB / 後半29:30〜右ボランチ (ポジションチェンジ)",
        "segments": [
            {"half": "1H", "role": "サイドバック", "label": "右SB"},
            {"half": "2H", "role": "サイドバック", "label": "右SB",
             "t_rel": (0.0, 29.5)},
            {"half": "2H", "role": "セントラル",   "label": "右ボランチ",
             "t_rel": (29.5, 999.0)},
        ],
    },
}


def _range_dist(v: float, lo: float, hi: float) -> float:
    """値が[lo,hi]外なら最近端までの距離, 内なら0."""
    if v < lo:
        return lo - v
    if v > hi:
        return v - hi
    return 0.0


def signature_distance(xs: np.ndarray, ys: np.ndarray, role: str) -> float:
    """トラックの平均位置と、ロール理想シグネチャとの重み付き距離 (m)."""
    sig = ROLE_SIGNATURE.get(role)
    if not sig or len(xs) == 0:
        return 999.0
    ax, ay = float(np.mean(xs)), float(np.mean(ys))
    dx = _range_dist(ax, *sig["x"])
    dy = _range_dist(ay, *sig["y"])
    return sig["xw"] * dx + sig["yw"] * dy


def _half_rel_times(track: dict, half: str):
    """指定ハーフのsightingsを (相対時刻, sighting) で返す.
    相対時刻 = time_min - そのトラックの当該ハーフ最小time_min。"""
    hs = [s for s in track["sightings"] if s.get("half") == half]
    if not hs:
        return []
    t0 = min(s["time_min"] for s in hs)
    return [(s["time_min"] - t0, s) for s in hs]


def _segment_sightings(track: dict, seg: dict) -> list:
    """グラウンドトゥルース・セグメントに該当するsightingsを抽出."""
    if "t_rel" in seg:
        rel = _half_rel_times(track, seg["half"])
        lo, hi = seg["t_rel"]
        return [s for (tr, s) in rel if lo <= tr < hi]
    return [s for s in track["sightings"] if s.get("half") == seg["half"]]


def identify_haru_track(all_tracks: list, role: str, half: str | None,
                        min_n: int = 4):
    """指定ロール・ハーフに最も合致するトラックを返す.
    返り値: (best_idx, fit_conf, uniqueness). best_idx=Noneなら該当なし。

    - fit_conf: 選ばれたトラックのゾーン適合度 (0-1)
    - uniqueness: 2位候補との分離度 (0-1)。複数トラックが同ゾーンに
      該当すると低下 → 「これが羽瑠だ」の確実性を正直に反映。
    """
    scored = []
    for i, t in enumerate(all_tracks):
        sigs = ([s for s in t["sightings"] if s.get("half") == half]
                if half else t["sightings"])
        if len(sigs) < min_n:
            continue
        xs = np.array([get_coords(s)[0] for s in sigs])
        ys = np.array([get_coords(s)[1] for s in sigs])
        d = signature_distance(xs, ys, role)
        d_adj = d - min(len(sigs), 20) * 0.15  # サンプル数で僅かに優遇
        scored.append((d_adj, d, i))
    if not scored:
        return None, None, None
    scored.sort(key=lambda x: x[0])
    best_d_adj, best_d, best_i = scored[0]
    fit_conf = max(0.0, 1.0 - best_d / 40.0)
    # uniqueness: 2位とのゾーン距離差 (10m差で完全分離とみなす)
    if len(scored) > 1:
        margin = scored[1][0] - best_d_adj
        uniqueness = min(1.0, margin / 10.0)
    else:
        uniqueness = 1.0
    return best_i, round(fit_conf, 2), round(uniqueness, 2)


def identify_haru(all_tracks: list, profiles: list, match_id: str) -> dict:
    """羽瑠を特定する。
    グラウンドトゥルースがあれば各セグメントのロール・シグネチャで特定。
    無ければ (ホールドアウト3試合) 従来の自動推定にフォールバック。

    返り値: {"primary_idx", "segments":[...], "confidence", "method"}
    """
    gt = HARU_GROUND_TRUTH.get(match_id)
    if gt:
        seg_results = []
        for seg in gt["segments"]:
            idx, fit, uniq = identify_haru_track(all_tracks, seg["role"], seg["half"])
            # 総合信頼度 = ゾーン適合度 × 一意性 (どちらも高い時のみ高信頼)
            conf = (round(fit * (0.5 + 0.5 * uniq), 2)
                    if (fit is not None and uniq is not None) else None)
            seg_results.append({
                "half": seg["half"], "role": seg["role"],
                "label": seg.get("label", seg["role"]),
                "t_rel": seg.get("t_rel"),
                "track_idx": idx,
                "player_id": all_tracks[idx]["player_id"] if idx is not None else None,
                "confidence": conf,
                "fit": fit, "uniqueness": uniq,
            })
        # primary = 最初のセグメント (常に1H右SB) のトラック
        primary = next((s["track_idx"] for s in seg_results
                        if s["track_idx"] is not None), None)
        confs = [s["confidence"] for s in seg_results if s["confidence"] is not None]
        return {
            "primary_idx": primary,
            "segments": seg_results,
            "confidence": round(float(np.mean(confs)), 2) if confs else None,
            "method": "ground_truth",
            "note": gt.get("note", ""),
        }
    # ── ホールドアウト: 自動推定 (検証用) ──
    valid = [(i, p) for i, p in enumerate(profiles)
             if all_tracks[i]["n_sightings"] >= 6]
    pool = valid if valid else list(enumerate(profiles))
    idx = max(pool, key=lambda x: x[1]["tactical_iq"])[0]
    return {
        "primary_idx": idx,
        "segments": [],
        "confidence": None,
        "method": "auto (holdout検証)",
        "note": "グラウンドトゥルース未指定 → 自動推定",
    }


# ── トラック総合分析 ─────────────────────────────────────────

def analyze_track(track: dict, all_tracks: list, team_series: dict,
                  role_override: str | None = None) -> dict:
    pos = detect_position(track)
    if role_override and role_override in POSITION_ARCHETYPES:
        # グラウンドトゥルースのロールで上書き (原則・創造性スコアを正しく評価)
        pos["archetype"] = role_override
        pos["desc"] = POSITION_ARCHETYPES[role_override]["desc"]
        pos["ground_truth"] = True
    cog = cognition_score(track, team_series)
    pri = principle_score(track, pos)
    cre = creativity_score(track, pos)
    pro = protagonist_index(track, all_tracks)

    # タクティカルIQ = 重み付き合成
    parts, weights = [], []
    if cog["score"] is not None: parts.append(cog["score"]); weights.append(0.25)
    parts.append(pri["score"]); weights.append(0.30)
    parts.append(cre["score"]); weights.append(0.30)
    if pro.get("score") is not None: parts.append(pro["score"]); weights.append(0.15)
    tiq = int(np.average(parts, weights=weights)) if parts else 0

    return {
        "player_id": track["player_id"],
        "n_sightings": track["n_sightings"],
        "position": pos,
        "cognition": cog,
        "principle": pri,
        "creativity": cre,
        "protagonist": pro,
        "tactical_iq": tiq,
    }


# ── ポジションチェンジ & 「穴」分析 ──────────────────────────

def position_change_analysis(haru_res: dict, all_tracks: list) -> dict | None:
    """ロールが変わるセグメント境界で「効果的な移動か / 穴を開けたか」を評価.

    羽瑠が元ポジション(例:右SB)を離れた後、その空間を味方が
    カバーしたか(=チームとして機能)、空いたまま(=穴)かを測る。
    データが疎なため confidence を必ず併記する。
    """
    def _seg_sights(track, seg):
        tr = seg.get("t_rel")
        if tr:
            rel = _half_rel_times(track, seg["half"])
            lo, hi = tr
            return [s for (t, s) in rel if lo <= t < hi]
        return [s for s in track["sightings"] if s.get("half") == seg["half"]]

    segs = haru_res.get("segments", [])
    changes = []
    for a, b in zip(segs, segs[1:]):
        if a["role"] == b["role"] or a["track_idx"] is None or b["track_idx"] is None:
            continue
        ta, tb = all_tracks[a["track_idx"]], all_tracks[b["track_idx"]]
        # 元ロール(a)での羽瑠の占有ゾーン重心
        sa = _seg_sights(ta, a)
        if not sa:
            continue
        vac_x = float(np.mean([get_coords(s)[0] for s in sa]))
        vac_y = float(np.mean([get_coords(s)[1] for s in sa]))
        # 移動後(b)の時間帯に、空いた空間(vac)を誰かがカバーしたか
        b_sigs = _seg_sights(tb, b)
        b_times = {round(s["time_min"], 1) for s in b_sigs}
        cover = []
        for t in all_tracks:
            if t is ta or t is tb:
                continue
            for s in t["sightings"]:
                if round(s["time_min"], 1) in b_times:
                    cx, cy = get_coords(s)
                    if math.hypot(cx - vac_x, cy - vac_y) <= 12.0:
                        cover.append(t["player_id"])
                        break
        new_x = float(np.mean([get_coords(s)[0] for s in b_sigs])) if b_sigs else None
        new_y = float(np.mean([get_coords(s)[1] for s in b_sigs])) if b_sigs else None
        n_evid = len(sa) + len(b_sigs)
        changes.append({
            "from": a["label"], "to": b["label"],
            "vacated_zone": f"X={vac_x:.0f}m Y={vac_y:.0f}m",
            "new_zone": (f"X={new_x:.0f}m Y={new_y:.0f}m" if new_x else "不明"),
            "advance_m": round(new_x - vac_x, 1) if new_x else None,
            "covered_by": sorted(set(cover)),
            "hole": len(cover) == 0,
            "evidence_n": n_evid,
            "confidence": round(min(1.0, n_evid / 12.0), 2),
            "verdict": ("味方がカバー(構造維持)" if cover
                        else "カバー無し(穴の可能性)"),
        })
    return {"changes": changes} if changes else None


# ── 試合分析 ─────────────────────────────────────────────────

def analyze_match(match_id: str) -> dict | None:
    path = DATA_TZI / f"match_{match_id}" / "players_v3.json"
    if not path.exists():
        return None
    with open(path) as f:
        data = json.load(f)
    tracks = data["players"]
    if not tracks:
        return {"match": match_id, "label": data.get("label", match_id),
                "haru": None, "all_profiles": []}

    team_series = compute_team_centroid_series(tracks)
    profiles = [analyze_track(t, tracks, team_series) for t in tracks]

    haru_res = identify_haru(tracks, profiles, match_id)
    haru_idx = haru_res["primary_idx"]
    if haru_idx is None:
        return {"match": match_id, "label": data.get("label", match_id),
                "haru": None, "all_profiles": profiles, "haru_id": haru_res}

    # primaryロールでグラウンドトゥルース上書き再計算
    primary_role = None
    if haru_res["segments"]:
        primary_role = haru_res["segments"][0]["role"]
    haru_profile = analyze_track(tracks[haru_idx], tracks, team_series,
                                 role_override=primary_role)

    pos_change = position_change_analysis(haru_res, tracks)

    return {
        "match": match_id,
        "label": data.get("label", match_id),
        "haru": haru_profile,
        "haru_track": tracks[haru_idx],
        "haru_id": haru_res,
        "position_change": pos_change,
        "all_profiles": profiles,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", default="all")
    args = ap.parse_args()

    from tactical_report import generate_report  # noqa

    matches = (sorted(p.parent.name.replace("match_", "")
                      for p in DATA_TZI.glob("match_*/players_v3.json"))
               if args.match == "all" else [args.match])

    results = []
    for m in matches:
        r = analyze_match(m)
        if r:
            results.append(r)
            haru = r.get("haru")
            hid = r.get("haru_id", {})
            if haru:
                method = hid.get("method", "?")
                conf = hid.get("confidence")
                print(f"\n{r['label']}  [{method}"
                      f"{f' conf={conf}' if conf is not None else ''}]:")
                print(f"  羽瑠: {haru['player_id']} "
                      f"[{haru['position']['archetype']}]  "
                      f"TacticalIQ={haru['tactical_iq']}")
                print(f"    認知={haru['cognition']['score']} "
                      f"原則={haru['principle']['score']} "
                      f"創造={haru['creativity']['score']} "
                      f"主役={haru['protagonist'].get('score')}")
                for s in hid.get("segments", []):
                    print(f"    └ {s['half']} {s['label']}: "
                          f"{s['player_id']} (conf={s['confidence']})")
                pc = r.get("position_change")
                if pc:
                    for c in pc["changes"]:
                        print(f"    ⇄ {c['from']}→{c['to']}: {c['verdict']} "
                              f"前進{c['advance_m']}m "
                              f"(evid={c['evidence_n']}, conf={c['confidence']})")
            else:
                print(f"\n{r['label']}: データ不足 (羽瑠特定できず)")

    out = generate_report(results)
    print(f"\n✓ レポート生成: {out}")
