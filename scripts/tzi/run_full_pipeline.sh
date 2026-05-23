#!/bin/bash
# TZI Full Analysis Pipeline
# Runs track_all_players.py on every match, then generates correction HTMLs,
# zone reports, and a multi-match comparison report.
#
# Usage: bash scripts/tzi/run_full_pipeline.sh [--interval N]
#   --interval N  sample every N minutes (default: 3)
#
set -e
cd "$(dirname "$0")/../.."   # project root

INTERVAL="${INTERVAL:-3}"
PYTHON="${PYTHON:-python3}"
LOG_DIR="data/tzi/logs"
mkdir -p "$LOG_DIR"

echo "============================================"
echo " TZI Full Pipeline  $(date '+%Y-%m-%d %H:%M')"
echo " interval=${INTERVAL}min"
echo "============================================"

run_match() {
    local match_id="$1"
    local h1="$2"
    local h2="$3"
    local single="${4:-no}"   # pass "single" for single-video matches
    local log="$LOG_DIR/match_${match_id}.log"

    echo ""
    echo "--- match_${match_id} ---"

    if [ "$single" = "single" ]; then
        $PYTHON scripts/tzi/track_all_players.py \
            --match "$match_id" --single --h1 "$h1" \
            --interval "$INTERVAL" 2>&1 | tee "$log"
    else
        $PYTHON scripts/tzi/track_all_players.py \
            --match "$match_id" --h1 "$h1" --h2 "$h2" \
            --interval "$INTERVAL" 2>&1 | tee "$log"
    fi

    $PYTHON scripts/tzi/generate_correction_html.py --match "$match_id" 2>&1 | tee -a "$log"
    $PYTHON scripts/tzi/generate_zone_report.py --match "$match_id" 2>&1 | tee -a "$log"

    echo "[DONE] match_${match_id}"
}

# ── Waseda matches ──────────────────────────────────────────────
run_match "20260314" "26_03_14_I_TRM vs埼玉大.mp4" "" "single"
run_match "20260316" "26_03_16_I_vs 岐阜協立.mp4" "" "single"
run_match "20260317mid" "26_03_17_I_ vs中京U-19 後半.mp4" "" "single"
run_match "20260317osaka_h1" "26_03_17_I_ vs大阪学院 前半.mp4" "" "single"
run_match "20260317osaka" "26_03_17_I_ vs大阪学院 前半.mp4" "26_03_17_I_ vs大阪学院 後半.mp4"
run_match "20260318" "26_03_18_I_ vs作新学院 前半.mp4" "" "single"
run_match "20260325" "26_03_25_I_TRM vs立教大 前半.mp4" "26_03_25_I_TRM vs立教大 後半.mp4"
run_match "20260329" "26_03_29_I_TRM vs川崎U-18 前半.mp4" "26_03_29_I_TRM vs 川崎U-18 後半.mp4"
run_match "20260405" "26_04_05_I_TRM vs獨協大前半.mp4" "26_04_05_I_TRM vs獨協大後半.mp4"

# ── Multi-match comparison report ──────────────────────────────
echo ""
echo "--- multi_match_report ---"
$PYTHON scripts/tzi/multi_match_report.py 2>&1 | tee "$LOG_DIR/multi_match.log"

echo ""
echo "============================================"
echo " PIPELINE COMPLETE  $(date '+%Y-%m-%d %H:%M')"
echo " Reports in data/tzi/"
echo "============================================"
