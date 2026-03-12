#!/bin/bash
source ./api_util/api_common.sh

# Resolve config aliases to local names
INPUT_UDP_DIR="$CONLLU_INPUT_DIR"
INPUT_TSV_DIR="$TSV_INPUT_DIR"
SUMMARY_OUT_DIR="$SUMMARY_OUTPUT_DIR"
TEITOK_OUT_DIR="$TEITOK_OUTPUT_DIR"
STATS_FILE="$OUTPUT_DIR/summary_ne_counts.csv"
INPUT_ALTO_DIR="$ALTO_DIR"

echo "=========================================="
echo " STEP 4: SUMMARIZATION & STATISTICS"
echo "=========================================="
echo " CoNLL-U dir : $INPUT_UDP_DIR"
echo " NE TSV dir  : $INPUT_TSV_DIR"
echo " Output dir  : $SUMMARY_OUT_DIR"
echo " Stats file  : $STATS_FILE"
echo " ALTO dir    : $INPUT_ALTO_DIR"
echo " TEITOK dir  : $TEITOK_OUT_DIR"
echo " Save CoNLL-U: ${SAVE_CONLLU_NE:-1}"
echo " Save CSV    : ${SAVE_CSV:-1}"
echo " Save TEITOK : ${SAVE_TEITOK:-0}"
echo "=========================================="

mkdir -p "$SUMMARY_OUT_DIR"
mkdir -p "$(dirname "$STATS_FILE")"

# 1. Merge CoNLL-U + NER TSVs into per-document outputs
log "Consolidating CoNLL-U and NER data..."

python3 api_util/summarize_nt_udp.py \
    --conllu-dir "$INPUT_UDP_DIR" \
    --tsv-dir    "$INPUT_TSV_DIR" \
    --out-dir    "$SUMMARY_OUT_DIR" \
    --alto-dir   "$INPUT_ALTO_DIR" \
    --tt-dir     "$TEITOK_OUT_DIR" \
    --save-conllu-ne "${SAVE_CONLLU_NE:-1}" \
    --save-csv       "${SAVE_CSV:-1}" \
    --save-teitok    "${SAVE_TEITOK:-0}"

if [ $? -eq 0 ]; then
    log "  Done     : consolidation complete"
else
    log "  Error    : summarize_nt_udp.py failed"
    exit 1
fi

# 2. Aggregate named entity counts across all documents
log "Aggregating entity statistics..."

python3 api_util/analyze.py "$INPUT_TSV_DIR" "$STATS_FILE"

if [ $? -eq 0 ]; then
    log "  Done     : $STATS_FILE"
else
    log "  Warning  : analyze.py encountered an issue  (stats may be incomplete)"
fi

echo "------------------------------------------"
echo " Output dir  : $SUMMARY_OUT_DIR"
echo " Stats file  : $STATS_FILE"
echo "------------------------------------------"
echo "Pipeline complete."