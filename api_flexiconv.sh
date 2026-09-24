#!/usr/bin/env bash
# api_flexiconv.sh – convert non-tabular input documents directly to TEITOK XML with flexiconv.
#
# Reads INPUT_DOCS_DIR, converts every file whose extension is in FLEXICONV_FORMATS and
# writes <stem>.teitok.xml into TEITOK_FLEXICONV_DIR (see api_util/flexiconv_convert.py for
# the naming rule). By default that output is final: keywords.py and llm_run.py read it
# directly through api_util/teitok_read.py. With FLEXICONV_ANNOTATE=true (run_pipeline.py
# --with-flexiconv) it is an intermediate: stages 1-4 annotate it with UDPipe and NameTag
# and write TEITOK format 2 into TEITOK_OUTPUT_DIR, keeping its layout.
set -uo pipefail

# shellcheck disable=SC1090  # config path is dynamic (ATRIUM_CONFIG); not followed at lint time
source "${ATRIUM_CONFIG:-config_api.txt}"
# Not sourcing api_util/api_common.sh: it requires INPUT_TABLES_DIR to exist, which a
# documents-only run does not need (same reasoning as api_4_stats.sh's inline logging).

FLEXICONV_DIR="${TEITOK_FLEXICONV_DIR:-${TEITOK_OUTPUT_DIR}/flexiconv}"
mkdir -p "$FLEXICONV_DIR"

if [ -z "${FLEXICONV_FORMATS:-}" ]; then
    echo "FLEXICONV_FORMATS is empty. Skipping non-tabular processing."
    exit 0
fi
if [ ! -d "${INPUT_DOCS_DIR:-}" ]; then
    echo "INPUT_DOCS_DIR (${INPUT_DOCS_DIR:-unset}) does not exist. Nothing to convert."
    exit 0
fi

PARA_STATE=$(python3 atrium_paradata.py start \
    --program nlp-enrich \
    --paradata-dir "${PARADATA_DIR}" \
    --output-types xml \
    --component flexiconv \
    --config \
        "script=api_flexiconv" \
        "input_docs_dir=${INPUT_DOCS_DIR}" \
        "teitok_flexiconv_dir=${FLEXICONV_DIR}" \
        "flexiconv_formats=${FLEXICONV_FORMATS}" \
        "flexiconv_force=${FLEXICONV_FORCE:-false}")

# Allowed extensions as an exact-match alternation (extension compared case-insensitively).
FORMAT_PATTERN=$(echo "$FLEXICONV_FORMATS" | tr ',' ' ' | xargs | tr ' ' '|')
FORCE_FLAG=""
[ "${FLEXICONV_FORCE:-false}" = "true" ] && FORCE_FLAG="--force"

candidates=()
for f in "$INPUT_DOCS_DIR"/*; do
    [ -f "$f" ] || continue
    filename=$(basename -- "$f")
    ext=$(echo "${filename##*.}" | tr '[:upper:]' '[:lower:]')
    echo "$ext" | grep -Eqx "$FORMAT_PATTERN" || continue
    candidates+=("$f")
done
total=${#candidates[@]}

# Preflight (issue #38, E): without flexiconv every file would fail one by one and, recorded as
# skips, the stage used to finish green with nothing converted. Stop before the first file.
if [ "$total" -gt 0 ] && ! python3 api_util/flexiconv_convert.py --check; then
    python3 atrium_paradata.py skip \
        --state "$PARA_STATE" \
        --file  "$INPUT_DOCS_DIR" \
        --reason "flexiconv is not installed (pip install -r requirements_flexiconv.txt)"
    python3 atrium_paradata.py finish --state "$PARA_STATE" --input-total "$total"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [CRITICAL ERROR] flexiconv is not installed; ${total} document(s) not converted. Halting." \
        | tee -a "${LOG_FILE:-/dev/null}" >&2
    exit 3
fi

failed=0
# ${a[@]+...}: an empty array under `set -u` is an error in bash < 4.4 (macOS ships 3.2).
for f in ${candidates[@]+"${candidates[@]}"}; do
    filename=$(basename -- "$f")
    # shellcheck disable=SC2086  # FORCE_FLAG is empty or a single flag
    if python3 api_util/flexiconv_convert.py "$f" --out-dir "$FLEXICONV_DIR" \
            --formats "$FLEXICONV_FORMATS" $FORCE_FLAG; then
        python3 atrium_paradata.py success --state "$PARA_STATE" --type xml
    else
        # One line from the adapter already says why. Paradata has no "failed" record (the
        # hub-canonical logger knows success/skip), so the reason says it; the exit code below
        # is what stops the run.
        failed=$((failed + 1))
        python3 atrium_paradata.py skip \
            --state "$PARA_STATE" \
            --file  "$filename" \
            --reason "flexiconv conversion failed"
    fi
done

# TEITOK output gate for this second emitter (issue #28). flexiconv output is a different
# TEITOK profile than api_util/teitok_alto.py's, so it is checked against the TEITOK-core
# rules every TEITOK document must meet (--profile core), not against schemas/teitok/teitok.xsd;
# api_4_stats.sh in turn excludes this directory from its output-contract gate.
if ! python3 api_util/validate_teitok_xml.py "$FLEXICONV_DIR" --allow-empty --profile core; then
    python3 atrium_paradata.py skip \
        --state "$PARA_STATE" \
        --file  "$FLEXICONV_DIR" \
        --reason "flexiconv TEITOK output failed the TEITOK-core check"
    python3 atrium_paradata.py finish --state "$PARA_STATE" --input-total "$total"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [CRITICAL ERROR] flexiconv TEITOK output failed the TEITOK-core check. Halting." \
        | tee -a "${LOG_FILE:-/dev/null}" >&2
    exit 1
fi

python3 atrium_paradata.py finish --state "$PARA_STATE" --input-total "$total"
echo "flexiconv: ${total} candidate document(s), $((total - failed)) converted or kept, ${failed} failed -> ${FLEXICONV_DIR}"
if [ "$failed" -gt 0 ]; then
    # Every file was tried first, so the log lists all failures; then the stage fails like
    # api_2_udp.sh does, instead of passing an incomplete collection on (issue #38, E).
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [CRITICAL ERROR] flexiconv could not convert ${failed} of ${total} document(s). Halting." \
        | tee -a "${LOG_FILE:-/dev/null}" >&2
    exit 1
fi
