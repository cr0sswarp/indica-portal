#!/bin/bash
# TZI Full Analysis Pipeline v2
# Runs both v3 tracking (direction-normalized) + correction HTML + zone/analytics reports.
#
# Usage: bash scripts/tzi/run_full_pipeline.sh [--interval N] [--skip-tracking]
#   --interval N       sample every N minutes (default: 3)
#   --skip-tracking    skip track_players_v3 step (use existing players_v3.json)
#
set -e
cd "$(dirname "$0")/../.."   # project root

INTERVAL="${INTERVAL:-3}"
PYTHON="${PYTHON:-python3}"
LOG_DIR="data/tzi/logs"
SKIP_TRACKING="${SKIP_TRACKING:-no}"
mkdir -p "$LOG_DIR"

# Parse flags
for arg in "$@"; do
    case $arg in
        --interval=*) INTERVAL="${arg#*=}" ;;
        --interval)   shift; INTERVAL="$1" ;;
        --skip-tracking) SKIP_TRACKING="yes" ;;
    esac
done

echo "============================================"
echo " TZI Full Pipeline  $(date '+%Y-%m-%d %H:%M')"
echo " interval=${INTERVAL}min  skip_tracking=${SKIP_TRACKING}"
echo "============================================"

# ── v3 tracking: all matches in one run ─────────────────────────
if [ "$SKIP_TRACKING" = "no" ]; then
    echo ""
    echo "--- track_players_v3 (all matches) ---"
    $PYTHON scripts/tzi/track_players_v3.py \
        --match all \
        --interval "$INTERVAL" \
        --no-ocr \
        2>&1 | tee "$LOG_DIR/track_v3_all.log"

    # Run with OCR on the key match (立教大) to identify jersey numbers
    echo ""
    echo "--- track_players_v3 with OCR (20260325) ---"
    $PYTHON scripts/tzi/track_players_v3.py \
        --match 20260325 \
        --interval "$INTERVAL" \
        2>&1 | tee "$LOG_DIR/track_v3_20260325_ocr.log"
fi

# ── Extract jersey #6 from v3 results ───────────────────────────
echo ""
echo "--- auto_jersey6_from_v3 ---"
$PYTHON scripts/tzi/auto_jersey6_from_v3.py --match all 2>&1 | tee "$LOG_DIR/jersey6_v3.log"

# ── Per-match reports ────────────────────────────────────────────
run_match_reports() {
    local match_id="$1"
    local log="$LOG_DIR/match_${match_id}.log"
    echo ""
    echo "--- reports: match_${match_id} ---"
    $PYTHON scripts/tzi/generate_correction_html.py --match "$match_id" 2>&1 | tee "$log"
    $PYTHON scripts/tzi/generate_zone_report.py     --match "$match_id" 2>&1 | tee -a "$log" || true
    $PYTHON scripts/tzi/generate_soccer_analytics.py --match "$match_id" 2>&1 | tee -a "$log" || true
    echo "[DONE] match_${match_id}"
}

run_match_reports "20260314"
run_match_reports "20260316"
run_match_reports "20260317mid"
run_match_reports "20260317osaka"
run_match_reports "20260318"
run_match_reports "20260325"
run_match_reports "20260329"
run_match_reports "20260405"

# ── Cross-match validation ───────────────────────────────────────
echo ""
echo "--- cross_match_validation ---"
$PYTHON scripts/tzi/cross_match_validation.py 2>&1 | tee "$LOG_DIR/cross_match_validation.log"

# ── Multi-match comparison report ───────────────────────────────
echo ""
echo "--- multi_match_report ---"
$PYTHON scripts/tzi/multi_match_report.py 2>&1 | tee "$LOG_DIR/multi_match.log"

echo ""
echo "============================================"
echo " PIPELINE COMPLETE  $(date '+%Y-%m-%d %H:%M')"
echo " Reports in data/tzi/"
echo "============================================"
