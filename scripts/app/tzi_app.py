#!/usr/bin/env python3
"""
TZI Soccer Analytics App - Streamlit prototype
Analyze match videos and show zone heatmaps.
"""

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import streamlit as st

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "tzi"))

st.set_page_config(
    page_title="TZI Soccer Analytics",
    page_icon="⚽",
    layout="wide",
)

st.title("⚽ TZI Soccer Analytics")
st.caption("Tactical Zone Intelligence — INDICA LABS")

# ── Sidebar ───────────────────────────────────────────────────────
with st.sidebar:
    st.header("設定")
    mode = st.radio("モード", ["既存試合を閲覧", "動画をアップロード"], index=0)

# ── Helper: load existing match data ─────────────────────────────
def load_match_data(match_dir: Path) -> dict | None:
    json_path = match_dir / "players_v3.json"
    if not json_path.exists():
        return None
    with open(json_path) as f:
        return json.load(f)


def draw_field(ax, fw=105, fh=68):
    """Draw a soccer field on matplotlib axes."""
    import matplotlib.patches as patches
    ax.set_facecolor("#4a7c59")
    ax.set_xlim(0, fw)
    ax.set_ylim(0, fh)
    ax.set_aspect("equal")
    # Touchlines
    rect = patches.Rectangle((0, 0), fw, fh, linewidth=2, edgecolor="white", facecolor="none")
    ax.add_patch(rect)
    # Center line
    ax.axvline(fw / 2, color="white", linewidth=1.5)
    # Center circle
    circle = patches.Circle((fw / 2, fh / 2), 9.15, linewidth=1.5, edgecolor="white", facecolor="none")
    ax.add_patch(circle)
    ax.plot(fw / 2, fh / 2, "wo", ms=3)
    # Penalty areas
    for x0 in [0, fw - 16.5]:
        pa = patches.Rectangle((x0, fh / 2 - 20.15), 16.5, 40.3,
                                linewidth=1.5, edgecolor="white", facecolor="none")
        ax.add_patch(pa)
    # Goals
    for x0, w in [(0, -2), (fw, 2)]:
        goal = patches.Rectangle((x0, fh / 2 - 3.66), w, 7.32,
                                  linewidth=2, edgecolor="yellow", facecolor="none")
        ax.add_patch(goal)
    # Zone lines
    for x in [21, 42, 52.5, 63, 84]:
        ax.axvline(x, color="white", linewidth=0.5, linestyle="--", alpha=0.4)
    ax.set_xlabel("Field Length (m)", color="white", fontsize=9)
    ax.set_ylabel("Width (m)", color="white", fontsize=9)
    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_edgecolor("white")


# ── Mode 1: Browse existing matches ──────────────────────────────
if mode == "既存試合を閲覧":
    data_dir = PROJECT_ROOT / "data" / "tzi"
    match_dirs = sorted([d for d in data_dir.iterdir() if d.is_dir() and d.name.startswith("match_")])

    if not match_dirs:
        st.error("data/tzi/ に試合データが見つかりません")
        st.stop()

    match_labels = {}
    for d in match_dirs:
        json_path = d / "players_v3.json"
        if json_path.exists():
            with open(json_path) as f:
                j = json.load(f)
            match_labels[d.name] = j.get("label", d.name)

    if not match_labels:
        st.error("players_v3.json が見つかりません")
        st.stop()

    selected = st.selectbox(
        "試合を選択",
        list(match_labels.keys()),
        format_func=lambda k: f"{match_labels[k]} ({k})",
    )
    match_dir = data_dir / selected
    data = load_match_data(match_dir)

    if data is None:
        st.error("データ読み込み失敗")
        st.stop()

    # Metrics row
    stats = data.get("stats", {})
    players = data.get("players", [])
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("検出プレイヤー", len(players))
    col2.metric("サンプルフレーム", stats.get("n_frames", 0))
    col3.metric("ジャージ識別", stats.get("n_with_jersey", 0))
    elapsed = stats.get("elapsed_sec", 0)
    col4.metric("処理時間", f"{elapsed:.0f}秒")

    tabs = st.tabs(["ヒートマップ", "ゾーン分析", "プレイヤー詳細", "方向デバッグ"])

    with tabs[0]:
        # Show existing heatmap image if available
        heatmap_path = match_dir / "heatmap_v3.png"
        if heatmap_path.exists():
            st.image(str(heatmap_path), caption="ポジションヒートマップ (正規化)", use_container_width=True)
        else:
            # Generate on-the-fly with matplotlib
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            from scipy.ndimage import gaussian_filter

            fig, axes = plt.subplots(1, 2, figsize=(16, 6), facecolor="#1a1a2e")
            for ax in axes:
                ax.set_facecolor("#1a1a2e")

            all_sightings = []
            for p in players:
                for s in p.get("sightings", []):
                    all_sightings.append((s.get("fx_norm", s.get("fx", 0)), s.get("fy_norm", s.get("fy", 0))))

            if all_sightings:
                xs = [s[0] for s in all_sightings]
                ys = [s[1] for s in all_sightings]

                # Scatter plot
                draw_field(axes[0])
                axes[0].scatter(xs, ys, c="red", s=30, alpha=0.5, zorder=5)
                axes[0].set_title("個別ポジション", color="white")

                # Heatmap
                hmap, xedges, yedges = np.histogram2d(xs, ys, bins=[42, 27],
                                                        range=[[0, 105], [0, 68]])
                hmap = gaussian_filter(hmap.T, sigma=2)
                draw_field(axes[1])
                axes[1].imshow(hmap, origin="lower", extent=[0, 105, 0, 68],
                               cmap="hot", alpha=0.7, aspect="auto")
                axes[1].set_title("ヒートマップ", color="white")
            else:
                for ax in axes:
                    draw_field(ax)
                    ax.text(52.5, 34, "データなし", ha="center", va="center",
                            color="white", fontsize=14)

            plt.tight_layout()
            st.pyplot(fig)
            plt.close()

    with tabs[1]:
        # Zone distribution
        zone_order = ["D1", "D2", "D3", "A1", "A2", "A3"]
        zone_totals = {z: 0 for z in zone_order}
        for p in players:
            for z, cnt in p.get("zone_dist_norm", p.get("zone_dist", {})).items():
                if z in zone_totals:
                    zone_totals[z] += cnt

        total = sum(zone_totals.values())
        if total > 0:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(10, 4), facecolor="#1a1a2e")
            ax.set_facecolor("#1a1a2e")
            colors = ["#e74c3c", "#e67e22", "#f1c40f", "#2ecc71", "#3498db", "#9b59b6"]
            bars = ax.bar(zone_order, [zone_totals[z] for z in zone_order], color=colors)
            for bar, z in zip(bars, zone_order):
                cnt = zone_totals[z]
                pct = cnt / total * 100
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                        f"{pct:.0f}%", ha="center", va="bottom", color="white", fontsize=10)
            ax.set_title(f"ゾーン分布 (全プレイヤー, n={total})", color="white")
            ax.tick_params(colors="white")
            ax.set_facecolor("#1a1a2e")
            for spine in ax.spines.values():
                spine.set_color("gray")
            ax.set_ylabel("サイティング数", color="white")
            ax.axvline(2.5, color="white", linewidth=1, linestyle="--")
            ax.text(1.2, ax.get_ylim()[1] * 0.9, "← 守備側", color="gray", fontsize=9)
            ax.text(3.5, ax.get_ylim()[1] * 0.9, "攻撃側 →", color="gray", fontsize=9)
            plt.tight_layout()
            st.pyplot(fig)
            plt.close()

            # Right channel metric
            right = 0
            rb_zone = 0
            total_sight = 0
            for p in players:
                for s in p.get("sightings", []):
                    fy = s.get("fy_norm", s.get("fy", 0))
                    fx = s.get("fx_norm", s.get("fx", 0))
                    total_sight += 1
                    if fy > 34:
                        right += 1
                    if fy > 34 and fx < 52.5:
                        rb_zone += 1

            c1, c2, c3 = st.columns(3)
            c1.metric("右チャンネル占有率", f"{right/total_sight*100:.0f}%" if total_sight else "N/A")
            c2.metric("RB想定ゾーン", f"{rb_zone/total_sight*100:.0f}%" if total_sight else "N/A",
                      help="守備半分かつ右サイド(fy>34, fx<52.5)")
            c3.metric("攻撃ゾーン比率", f"{(zone_totals['A1']+zone_totals['A2']+zone_totals['A3'])/total*100:.0f}%")
        else:
            st.info("ゾーンデータがありません")

    with tabs[2]:
        # Player details table
        rows = []
        for p in players:
            jersey = p.get("jersey_number")
            n = p.get("n_sightings", 0)
            zones = p.get("zone_dist_norm", p.get("zone_dist", {}))
            dominant = max(zones, key=zones.get) if zones else "?"
            rows.append({
                "ID": p.get("player_id", "?"),
                "ジャージ": jersey if jersey else "-",
                "検出回数": n,
                "主要ゾーン": dominant,
                "ゾーン分布": str(dict(sorted(zones.items()))),
            })
        if rows:
            import pandas as pd
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True)

    with tabs[3]:
        # Direction debug image
        debug_path = match_dir / "direction_debug.png"
        if debug_path.exists():
            st.image(str(debug_path), caption="方向検出デバッグ", use_container_width=True)
        else:
            direction = data.get("direction", {})
            st.json(direction)

# ── Mode 2: Upload video ──────────────────────────────────────────
else:
    st.info("動画をアップロードして分析します。処理に数分かかります。")

    uploaded = st.file_uploader("動画ファイルをアップロード (.mp4)", type=["mp4", "avi", "mov"])
    half = st.selectbox("ハーフ", ["1H", "2H"])
    interval = st.slider("サンプリング間隔（分）", 1, 10, 3)

    if uploaded and st.button("分析開始 ▶", type="primary"):
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = Path(tmpdir) / uploaded.name
            with open(video_path, "wb") as f:
                f.write(uploaded.read())

            st.info(f"動画保存完了: {video_path.name} ({video_path.stat().st_size // 1024 // 1024} MB)")

            progress = st.progress(0, text="初期化中...")

            try:
                from track_players_v3 import process_video_half

                out_dir = Path(tmpdir) / "output"
                out_dir.mkdir()

                progress.progress(10, text="フレーム抽出中...")

                result = process_video_half(
                    video_path=str(video_path),
                    half=half,
                    out_dir=str(out_dir),
                    interval_min=interval,
                )

                progress.progress(90, text="ヒートマップ生成中...")

                if result:
                    st.success(f"分析完了: {len(result.get('players', []))} プレイヤー検出")
                    hmap = out_dir / "heatmap_v3.png"
                    if hmap.exists():
                        st.image(str(hmap), caption="ポジションヒートマップ", use_container_width=True)
                    with st.expander("Raw JSON"):
                        st.json(result)
                else:
                    st.warning("分析データが取得できませんでした")

                progress.progress(100, text="完了!")

            except ImportError as e:
                st.error(f"モジュールエラー: {e}")
                st.info("track_players_v3.py の process_video_half 関数が必要です")
            except Exception as e:
                st.error(f"分析エラー: {e}")
                import traceback
                st.code(traceback.format_exc())

# ── Footer ────────────────────────────────────────────────────────
st.divider()
st.caption("TZI — INDICA LABS | 春のために / For Haru ⚽")
