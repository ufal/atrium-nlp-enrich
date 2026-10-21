#!/usr/bin/env bash
# api_3_nt.sh – NameTag processing + paradata
set -euo pipefail
# shellcheck disable=SC1090  # config path is dynamic (ATRIUM_CONFIG); not followed at lint time
source "${ATRIUM_CONFIG:-config_api.txt}"

PARA_STATE=$(python3 atrium_paradata.py start \
    --program nlp-enrich \
    --paradata-dir "${PARADATA_DIR}" \
    --output-types tsv \
    --config \
        "script=api_3_nt" \
        "model_nametag=${MODEL_NAMETAG}" \
        "nametag_url=${NAMETAG_URL}" \
        "timeout=${TIMEOUT}" \
        "max_retries=${MAX_RETRIES}" \
        "conllu_input_dir=${CONLLU_INPUT_DIR}" \
        "output_dir=${TSV_INPUT_DIR}")

TOTAL=$(find "${OUTPUT_DIR}/UDP" -name '*.conllu' -type f | wc -l)
mkdir -p "${OUTPUT_DIR}/NE"

while IFS= read -r -d '' conllu; do
    rel_path="${conllu#"${OUTPUT_DIR}"/UDP/}"
    doc="${rel_path%.conllu}"
    out_dir="${TSV_INPUT_DIR}/${doc}"

    if [ -d "$out_dir" ]; then
        python3 atrium_paradata.py skip \
            --state "$PARA_STATE" \
            --file  "$doc" \
            --reason "output already exists"
        continue
    fi

    mkdir -p "$out_dir"

    # The client's exit code says why it stopped (api_util/lindat_errors.py, issue #41):
    # 6 NameTag did not answer, 7 it timed out, 8 it refused the request. Passed on unchanged.
    rc=0
    python3 api_util/call_nametag.py \
        --input      "$conllu" \
        --model      "$MODEL_NAMETAG" \
        --output-dir "$out_dir" \
        --url        "$NAMETAG_URL" \
        --timeout    "$TIMEOUT" \
        --retries    "$MAX_RETRIES" || rc=$?
    if [ "$rc" -eq 0 ]; then
        n_pages=$(find "$out_dir" -maxdepth 1 -name '*.tsv' 2>/dev/null | wc -l)
        python3 atrium_paradata.py success \
            --state "$PARA_STATE" --type tsv --count "$n_pages"
    else
        # P1 FIX: Log the failure and exit immediately to halt the pipeline
        # 6, 7 and 8 travel on; anything else (an empty run, a crash, a usage error) stays 1.
        case "$rc" in
            6) reason="LINDAT NameTag did not answer after ${MAX_RETRIES} retries" ;;
            7) reason="LINDAT NameTag timed out (${TIMEOUT} s per attempt, ${MAX_RETRIES} retries)" ;;
            8) reason="LINDAT NameTag refused the request" ;;
            *) reason="NameTag API call failed"; rc=1 ;;
        esac
        python3 atrium_paradata.py skip \
            --state "$PARA_STATE" \
            --file  "$doc" \
            --reason "$reason"
        # An empty output directory would make a resumed run skip the document as done.
        rmdir "$out_dir" 2>/dev/null || true

        echo "[CRITICAL ERROR] NameTag processing failed for ${doc} (exit ${rc}). Halting pipeline." >&2
        exit "$rc"
    fi
done < <(find "${CONLLU_INPUT_DIR}" -name '*.conllu' -type f -print0)

python3 atrium_paradata.py finish --state "$PARA_STATE" --input-total "$TOTAL"
