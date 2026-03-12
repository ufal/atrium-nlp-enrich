#!/bin/bash
source ./api_util/api_common.sh

echo "=========================================="
echo " STEP 2: UDPIPE PROCESSING"
echo "=========================================="
echo " Input dir  : $INPUT_TABLES_DIR"
echo " Output dir : $OUTPUT_DIR/UDP"
echo " Model      : $MODEL_UDPIPE"
echo " Chunk limit: $WORD_CHUNK_LIMIT words"
echo " Endpoint   : $UDPIPE_URL"
echo "=========================================="

# Setup Directories
mkdir -p "$OUTPUT_DIR/UDP" "$WORK_DIR/CHUNKS"
MANIFEST="$OUTPUT_DIR/manifest.tsv"

# Check Manifest
if [ ! -f "$MANIFEST" ]; then
    echo "Error: Manifest not found: $MANIFEST"
    echo "       Run ./api_1_manifest.sh first."
    exit 1
fi

log "Starting UDPipe processing..."

# Helper: Parse CSV, sort by Page/Line, write plain text to file
extract_sorted_text() {
    python3 -c "
import sys, csv

input_file = '$1'
output_file = '$2'

try:
    with open(input_file, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        data = []
        for row in reader:
            try:
                p = int(row.get('page_num', 0))
            except ValueError:
                p = 0
            try:
                l = int(row.get('line_num', 0))
            except ValueError:
                l = 0

            text_content = row.get('text', '')
            if text_content and text_content.strip():
                data.append({'p': p, 'l': l, 'text': text_content.strip()})

    data.sort(key=lambda x: (x['p'], x['l']))

    with open(output_file, 'w', encoding='utf-8') as out:
        for item in data:
            out.write(item['text'] + '\n')

except Exception as e:
    sys.stderr.write(f'Error parsing CSV {input_file}: {str(e)}\n')
    sys.exit(1)
"
}

doc_count=0
skipped_count=0
error_count=0

find "$INPUT_TABLES_DIR" -name "*.csv" | sort | while read csv_file; do

    doc_id=$(basename "$csv_file" .csv)
    final_conllu="$OUTPUT_DIR/UDP/${doc_id}.conllu"

    # Resume: skip already completed docs
    if [ -s "$final_conllu" ]; then
        continue
    fi

    log "Processing : $doc_id"

    # 1. Extract and sort text from CSV
    mkdir -p "$TEMP_TXT_DIR"
    raw_text_file="$TEMP_TXT_DIR/${doc_id}.txt"

    extract_sorted_text "$csv_file" "$raw_text_file"

    if [ ! -s "$raw_text_file" ]; then
        log "  Skipped  : $doc_id  (no valid text content)"
        rm -f "$raw_text_file"
        ((skipped_count++))
        continue
    fi

    # 2. Split text into chunks
    doc_chunk_dir="$CHUNK_DIR/${doc_id}"
    rm -rf "$doc_chunk_dir" && mkdir -p "$doc_chunk_dir"

    python3 api_util/chunk.py "$raw_text_file" "$doc_chunk_dir" "$WORD_CHUNK_LIMIT"

    chunk_files=$(ls "$doc_chunk_dir"/*.txt 2>/dev/null | sort -V)
    chunk_total=$(echo "$chunk_files" | wc -l)
    log "  Chunks   : $chunk_total  (limit: $WORD_CHUNK_LIMIT words each)"

    # 3. Process chunks with UDPipe API
    current_temp_file="${final_conllu}.tmp"
    : > "$current_temp_file"
    is_first_chunk=true
    chunk_num=0

    for chunk_file in $chunk_files; do
        [ -e "$chunk_file" ] || continue
        ((chunk_num++))
        resp_file="${chunk_file}.json"

        if api_call_with_retry "UDPipe" "$UDPIPE_URL" "$resp_file" \
            -F "data=@${chunk_file}" \
            -F "model=${MODEL_UDPIPE}" \
            -F "tokenizer=" \
            -F "tagger=" \
            -F "parser="; then

            raw_conllu=$(parse_json_result "$resp_file")

            if [ "$is_first_chunk" = true ]; then
                echo "$raw_conllu" >> "$current_temp_file"
                is_first_chunk=false
            else
                # Strip global headers from subsequent chunks for a valid single CoNLL-U doc
                echo "$raw_conllu" | grep -vE "^# (newdoc|newpar|generator|udpipe)" >> "$current_temp_file"
            fi

            # Ensure newline separator between chunks
            if [ -n "$(tail -n 1 "$current_temp_file")" ]; then
                echo "" >> "$current_temp_file"
            fi

            log "  Chunk    : $chunk_num/$chunk_total  OK"
        else
            log "  Chunk    : $chunk_num/$chunk_total  FAILED  ($(basename "$chunk_file"))"
        fi

        rate_limit
    done

    # 4. Finalize or discard
    if [ -s "$current_temp_file" ]; then
        mv "$current_temp_file" "$final_conllu"
        log "  Saved    : $final_conllu"
        ((doc_count++))
    else
        rm -f "$current_temp_file"
        log "  Error    : $doc_id  (output empty, API may have failed)"
        ((error_count++))
    fi

    # Cleanup temp files for this doc
    rm -f "$raw_text_file"
    rm -rf "$doc_chunk_dir"

done

echo "------------------------------------------"
echo " Processed : $doc_count documents"
echo " Skipped   : $skipped_count documents  (no text)"
echo " Errors    : $error_count documents"
echo " Output    : $OUTPUT_DIR/UDP"
echo "------------------------------------------"
echo "Next: ./api_3_nt.sh"