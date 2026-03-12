#!/bin/bash
source ./api_util/api_common.sh

echo "=========================================="
echo " STEP 1: MANIFEST GENERATION"
echo "=========================================="
echo " Input dir  : $INPUT_TABLES_DIR"
echo " Manifest   : $OUTPUT_DIR/manifest.tsv"
echo " Text cache : $WORK_DIR/TEXT_CACHE"
echo "=========================================="

# We create a cache directory for the extracted text
TEXT_CACHE_DIR="$WORK_DIR/TEXT_CACHE"
MANIFEST="$OUTPUT_DIR/manifest.tsv"

mkdir -p "$WORK_DIR" "$TEXT_CACHE_DIR"

# Python Helper: Extract & Sort Text
# Reads a CSV, sorts by page/line, and prints the full text.
extract_csv_text() {
    python3 -c "
import sys, csv

try:
    with open('$1', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        data = []
        for row in reader:
            try: p = int(row.get('page_num', 0))
            except: p = 0
            try: l = int(row.get('line_num', 0))
            except: l = 0

            if row.get('text') and str(row.get('text')).strip():
                data.append({'p': p, 'l': l, 'text': row['text']})

    data.sort(key=lambda x: (x['p'], x['l']))

    for item in data:
        print(item['text'])

except Exception as e:
    sys.stderr.write(f'[Error parsing $1]: {e}\n')
"
}

# Check if directory exists
if [ ! -d "$INPUT_TABLES_DIR" ]; then
    echo "Error: Input directory does not exist: $INPUT_TABLES_DIR"
    exit 1
fi

# Initialize/Clear manifest
: > "$MANIFEST"

echo "Scanning: $INPUT_TABLES_DIR"
echo "------------------------------------------"

count=0
skipped=0

find "$INPUT_TABLES_DIR" -name "*.csv" | sort | while read -r csv_file; do

    filename=$(basename "$csv_file")
    doc_id="${filename%.*}"
    target_txt="$TEXT_CACHE_DIR/${doc_id}.txt"

    extract_csv_text "$csv_file" > "$target_txt"

    if [ -s "$target_txt" ]; then
        echo -e "${doc_id}\t1\t${target_txt}" >> "$MANIFEST"
        ((count++))
        echo -ne "  Indexed : $count docs\r"
    else
        rm -f "$target_txt"
        ((skipped++))
        echo "  Skipped : $doc_id  (empty or unreadable)"
    fi
done

echo ""
echo "------------------------------------------"
echo " Indexed  : $count documents"
echo " Skipped  : $skipped documents"
echo " Manifest : $MANIFEST"
echo " Cache    : $TEXT_CACHE_DIR"
echo "------------------------------------------"
echo "Next: ./api_2_udp.sh"