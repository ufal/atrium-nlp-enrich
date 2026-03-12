#!/bin/bash
source ./api_util/api_common.sh

echo "=========================================="
echo " STEP 3: NAMETAG PROCESSING"
echo "=========================================="
echo " Input dir  : $OUTPUT_DIR/UDP"
echo " Output dir : $OUTPUT_DIR/NE"
echo " Model      : $MODEL_NAMETAG"
echo " Chunk size : $CHUNK_SIZE lines"
echo " Endpoint   : $NAMETAG_URL"
echo "=========================================="

mkdir -p "$OUTPUT_DIR/NE"

# Lines per chunk. 3000 is safe (~500KB–1MB depending on token density)
CHUNK_SIZE=3000

count=0
skipped_count=0
error_count=0

log "Starting NameTag processing..."

for conllu_file in "$OUTPUT_DIR/UDP"/*.conllu; do
    [ -e "$conllu_file" ] || continue

    filename=$(basename "$conllu_file")
    doc_id="${filename%.conllu}"
    doc_output_dir="$OUTPUT_DIR/NE/$doc_id"

    # Resume: skip already completed docs
    if [ -d "$doc_output_dir" ] && [ "$(ls -A "$doc_output_dir")" ]; then
        continue
    fi

    mkdir -p "$doc_output_dir"
    log "Processing : $doc_id"

    # 1. Strip generator headers for clean API input
    clean_input="${WORK_DIR}/temp_clean_${filename}"
    sed '/^# generator/d; /^# udpipe_model/d' "$conllu_file" > "$clean_input"

    # 2. Split into sentence-boundary-safe chunks
    chunk_dir="${WORK_DIR}/chunks_${doc_id}"
    mkdir -p "$chunk_dir"

    python3 -c "
import sys
infile = sys.argv[1]
out_prefix = sys.argv[2]
max_lines = int(sys.argv[3])

with open(infile, 'r', encoding='utf-8') as f:
    lines = f.readlines()

chunk_idx = 0
current_chunk = []

for line in lines:
    current_chunk.append(line)
    if len(current_chunk) >= max_lines and not line.strip():
        with open(f'{out_prefix}_{chunk_idx:03d}.tmp', 'w', encoding='utf-8') as out:
            out.writelines(current_chunk)
        current_chunk = []
        chunk_idx += 1

if current_chunk:
    with open(f'{out_prefix}_{chunk_idx:03d}.tmp', 'w', encoding='utf-8') as out:
        out.writelines(current_chunk)
" "$clean_input" "$chunk_dir/chunk" "$CHUNK_SIZE"

    chunk_files=("$chunk_dir"/*.tmp)
    chunk_total=${#chunk_files[@]}
    log "  Chunks   : $chunk_total  (limit: $CHUNK_SIZE lines each)"

    # 3. Process each chunk against NameTag API
    all_chunks_ok=true
    chunk_num=0

    for chunk_file in "${chunk_files[@]}"; do
        ((chunk_num++))
        chunk_name=$(basename "$chunk_file")
        chunk_resp="$chunk_dir/${chunk_name}.json"

        if api_call_with_retry "NameTag" "$NAMETAG_URL" "$chunk_resp" \
            -F "data=@${chunk_file}" -F "input=conllu" -F "output=conll" \
            -F "model=${MODEL_NAMETAG}"; then
            log "  Chunk    : $chunk_num/$chunk_total  OK"
        else
            log "  Chunk    : $chunk_num/$chunk_total  FAILED  ($chunk_name)"
            all_chunks_ok=false
            break
        fi

        sleep 0.2
    done

    # 4. Merge chunk responses and parse into per-page TSVs
    if [ "$all_chunks_ok" = true ]; then
        final_resp_file="$WORK_DIR/nametag_response_${filename}.json"

        python3 -c "
import sys, json, glob

outfile = sys.argv[1]
search_pattern = sys.argv[2]

files = sorted(glob.glob(search_pattern))
full_text_parts = []

for fpath in files:
    try:
        with open(fpath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            txt = data.get('result', '').strip()
            if txt:
                full_text_parts.append(txt)
    except Exception as e:
        sys.stderr.write(f'Error reading {fpath}: {e}\n')

merged_text = '\n\n'.join(full_text_parts)

with open(outfile, 'w', encoding='utf-8') as f:
    json.dump({'result': merged_text}, f, ensure_ascii=False)
" "$final_resp_file" "$chunk_dir/*.json"

        python3 api_util/nametag.py \
            "$conllu_file" \
            "$final_resp_file" \
            "$doc_output_dir" \
            "$doc_id"

        tsv_count=$(ls "$doc_output_dir"/*.tsv 2>/dev/null | wc -l)
        log "  Saved    : $doc_output_dir  ($tsv_count pages)"
        ((count++))

        rm -f "$final_resp_file"
    else
        log "  Error    : $doc_id  (chunk failure, output skipped)"
        ((error_count++))
    fi

    # Cleanup
    rm -rf "$chunk_dir"
    rm -f "$clean_input"

    rate_limit
done

echo "------------------------------------------"
echo " Processed : $count documents"
echo " Errors    : $error_count documents"
echo " Output    : $OUTPUT_DIR/NE"
echo "------------------------------------------"
echo "Next: ./api_4_stats.sh"