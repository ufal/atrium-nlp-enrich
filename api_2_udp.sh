#!/usr/bin/env bash
# api_2_udp.sh – UDPipe processing + paradata
set -euo pipefail
# shellcheck disable=SC1090  # config path is dynamic (ATRIUM_CONFIG); not followed at lint time
source "${ATRIUM_CONFIG:-config_api.txt}"

PARA_STATE=$(python3 atrium_paradata.py start \
    --program nlp-enrich \
    --paradata-dir "${OUTPUT_DIR}/paradata" \
    --output-types conllu \
    --config \
        "script=api_2_udp" \
        "model_udpipe=${MODEL_UDPIPE}" \
        "udpipe_url=${UDPIPE_URL}" \
        "word_chunk_limit=${WORD_CHUNK_LIMIT}" \
        "timeout=${TIMEOUT}" \
        "max_retries=${MAX_RETRIES}" \
        "manifest=${OUTPUT_DIR}/manifest.tsv" \
        "output_dir=${OUTPUT_DIR}/UDP")

TOTAL=$(tail -n +2 "${OUTPUT_DIR}/manifest.tsv" | wc -l)
mkdir -p "${OUTPUT_DIR}/UDP"

while IFS=$'\t' read -r file page path; do
    [ "$file" = "file" ] && continue
    out="${OUTPUT_DIR}/UDP/${file}.conllu"
    [ -f "$out" ] && continue

    mkdir -p "$(dirname "$out")"
    # shellcheck disable=SC2153  # CHUNK_DIR is provided by the sourced config file
    chunk_dir="${CHUNK_DIR}/${file}"
    mkdir -p "$chunk_dir"

    if ! python3 api_util/chunk.py "$path" "$chunk_dir" "$WORD_CHUNK_LIMIT"; then
        python3 atrium_paradata.py skip \
            --state "$PARA_STATE" \
            --file  "${file}:${page}" \
            --reason "the text could not be split into UDPipe chunks"
        echo "[CRITICAL ERROR] Chunking failed for ${file}. Halting pipeline." >&2
        exit 1
    fi

    # The client's exit code says why it stopped (api_util/lindat_errors.py, issue #41):
    # 1 nothing to annotate, 6 UDPipe did not answer, 7 it timed out, 8 it refused the request.
    # It is passed on unchanged, so the service can tell an outage from an empty run.
    rc=0
    python3 api_util/call_udpipe.py \
        --chunk-dir "$chunk_dir" \
        --model     "$MODEL_UDPIPE" \
        --output    "$out" \
        --url       "$UDPIPE_URL" \
        --timeout   "$TIMEOUT" \
        --retries   "$MAX_RETRIES" || rc=$?
    if [ "$rc" -eq 0 ]; then
        # Freeze the page provenance with the CoNLL-U it describes (api_util/page_rows.py):
        # TEMP is rewritten by every stage-1 run and is not kept by a container, while a
        # resumed run skips documents whose CoNLL-U exists (issue #38, A).
        rows_file="${path%.txt}.rows.tsv"
        if [ -f "$rows_file" ]; then
            cp "$rows_file" "${OUTPUT_DIR}/UDP/${file}.rows.tsv"
        else
            echo "[WARN] ${file}: no ${rows_file}; pages will be guessed (legacy)." >&2
        fi
        python3 atrium_paradata.py success --state "$PARA_STATE" --type conllu
    else
        # P1 FIX: Log the failure and exit immediately to halt the pipeline
        # 6, 7 and 8 travel on; anything else (an empty run, a crash, a usage error) stays 1.
        case "$rc" in
            6) reason="LINDAT UDPipe did not answer after ${MAX_RETRIES} retries" ;;
            7) reason="LINDAT UDPipe timed out (${TIMEOUT} s per attempt, ${MAX_RETRIES} retries)" ;;
            8) reason="LINDAT UDPipe refused the request" ;;
            *) reason="UDPipe produced nothing for the document"; rc=1 ;;
        esac
        python3 atrium_paradata.py skip \
            --state "$PARA_STATE" \
            --file  "${file}:${page}" \
            --reason "$reason"

        echo "[CRITICAL ERROR] UDPipe processing failed for ${file} (exit ${rc}). Halting pipeline." >&2
        exit "$rc"
    fi
done < "${OUTPUT_DIR}/manifest.tsv"

python3 atrium_paradata.py finish --state "$PARA_STATE" --input-total "$TOTAL"
