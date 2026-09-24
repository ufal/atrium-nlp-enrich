#!/usr/bin/env bash
# api_1_manifest.sh – generate manifest + paradata
set -euo pipefail
# shellcheck disable=SC1090  # config path is dynamic (ATRIUM_CONFIG); not followed at lint time
source "${ATRIUM_CONFIG:-config_api.txt}"

# FLEXICONV_ANNOTATE=true: documents converted by api_flexiconv.sh enter the linguistic
# stages too (their text here; their layout in stage 4, from the same file).
FLEXICONV_INPUT_DIR=""
if [[ "${FLEXICONV_ANNOTATE:-false}" == "true" ]]; then
    FLEXICONV_INPUT_DIR="${TEITOK_FLEXICONV_DIR:-${TEITOK_OUTPUT_DIR}/flexiconv}"
fi

# P1 FIX: Validate input directory exists before starting (a flexiconv-only run needs
# only the converted documents)
if [[ ! -d "${INPUT_TABLES_DIR}" ]] && [[ ! -d "${FLEXICONV_INPUT_DIR:-/nonexistent}" ]]; then
    echo "[ERROR] Input directory '${INPUT_TABLES_DIR}' does not exist. Aborting." >&2
    exit 1
fi

# ── paradata: start ───────────────────────────────────────────────────────────
PARA_STATE=$(python3 atrium_paradata.py start \
    --program nlp-enrich \
    --paradata-dir "${OUTPUT_DIR}/paradata" \
    --output-types tsv \
    --config \
        "script=api_1_manifest" \
        "input_dir=${INPUT_TABLES_DIR}" \
        "flexiconv_input_dir=${FLEXICONV_INPUT_DIR}" \
        "output_manifest=${OUTPUT_DIR}/manifest.tsv")
# ── end paradata start ────────────────────────────────────────────────────────

mkdir -p "${OUTPUT_DIR}"

# Write header if manifest does not exist yet
if [ ! -f "${OUTPUT_DIR}/manifest.tsv" ]; then
    echo -e "file\tpage\tpath" > "${OUTPUT_DIR}/manifest.tsv"
fi

TOTAL=0
TABLE_DOC_IDS=""  # newline-separated (no associative arrays: bash 3.2 on macOS)

for csv_file in "${INPUT_TABLES_DIR}"/*.csv "${INPUT_TABLES_DIR}"/*.xlsx; do
    [ -f "$csv_file" ] || continue
    TOTAL=$((TOTAL + 1))

    # build_manifest_row.py reads one CSV/XLSX, writes a temp .txt, and prints
    # a single TSV row:  doc_id <TAB> page_count <TAB> /path/to/text_file
    if NEW_ROW=$(python3 api_util/build_manifest_row.py "$csv_file" --text-dir "${TEMP_TXT_DIR:-./TEMP/TXT_EXTRACT}"); then

        DOC_ID=$(echo "$NEW_ROW" | cut -f1)
        TABLE_DOC_IDS+="${DOC_ID}"$'\n'

        if grep -q "^${DOC_ID}[[:space:]]" "${OUTPUT_DIR}/manifest.tsv"; then
            grep -v "^${DOC_ID}[[:space:]]" "${OUTPUT_DIR}/manifest.tsv" > "${OUTPUT_DIR}/manifest.tmp"
            mv "${OUTPUT_DIR}/manifest.tmp" "${OUTPUT_DIR}/manifest.tsv"
        fi

        echo "$NEW_ROW" >> "${OUTPUT_DIR}/manifest.tsv"
        python3 atrium_paradata.py success --state "$PARA_STATE" --type tsv
    else
        # P1 FIX: Log the failure and exit immediately to halt the pipeline
        python3 atrium_paradata.py skip \
            --state "$PARA_STATE" \
            --file  "$csv_file" \
            --reason "manifest row generation failed"

        echo "[CRITICAL ERROR] Manifest generation failed for ${csv_file}. Halting pipeline." >&2
        exit 1
    fi
done

# Converted documents. A table with the same doc_id (alto-postprocess's text-lines route
# writes DOC_LINE_CATEG/<doc>.csv for the same inputs) wins: its lines are categorised, and
# stage 4 still takes this document's layout from the converted file.
if [[ -n "$FLEXICONV_INPUT_DIR" ]]; then
    for teitok_file in "${FLEXICONV_INPUT_DIR}"/*.teitok.xml; do
        [ -f "$teitok_file" ] || continue
        TOTAL=$((TOTAL + 1))
        DOC_ID=$(python3 api_util/build_manifest_row.py "$teitok_file" --doc-id-only)
        if printf '%s' "$TABLE_DOC_IDS" | grep -Fxq -- "$DOC_ID"; then
            python3 atrium_paradata.py skip \
                --state "$PARA_STATE" \
                --file  "$teitok_file" \
                --reason "doc_id ${DOC_ID} already comes from a table input"
            continue
        fi
        if NEW_ROW=$(python3 api_util/build_manifest_row.py "$teitok_file" --text-dir "${TEMP_TXT_DIR:-./TEMP/TXT_EXTRACT}"); then
            if grep -q "^${DOC_ID}[[:space:]]" "${OUTPUT_DIR}/manifest.tsv"; then
                grep -v "^${DOC_ID}[[:space:]]" "${OUTPUT_DIR}/manifest.tsv" > "${OUTPUT_DIR}/manifest.tmp"
                mv "${OUTPUT_DIR}/manifest.tmp" "${OUTPUT_DIR}/manifest.tsv"
            fi
            echo "$NEW_ROW" >> "${OUTPUT_DIR}/manifest.tsv"
            python3 atrium_paradata.py success --state "$PARA_STATE" --type tsv
        else
            # an empty conversion (no text) costs only that document
            python3 atrium_paradata.py skip \
                --state "$PARA_STATE" \
                --file  "$teitok_file" \
                --reason "no text in converted document"
            echo "[WARN] ${teitok_file}: no text, not added to the manifest." >&2
        fi
    done
fi

python3 atrium_paradata.py finish --state "$PARA_STATE" --input-total "$TOTAL"
echo "[manifest] done: $TOTAL total, 0 errors"
