# import os, sys, re
# input_dir, manifest_path = sys.argv[1], sys.argv[2]
# doc_map = {}
# pattern = re.compile(r'^(.*)[-_](\d+)\.txt$')
#
# for root, dirs, files in os.walk(input_dir):
#     for f in files:
#         if f.endswith(".txt"):
#             match = pattern.match(f)
#             if match:
#                 doc_id = match.group(1)
#                 page_num = int(match.group(2))
#                 full_path = os.path.join(root, f)
#                 if doc_id not in doc_map: doc_map[doc_id] = []
#                 doc_map[doc_id].append((page_num, full_path))
#
# with open(manifest_path, 'w', encoding='utf-8') as out:
#     for doc_id in sorted(doc_map.keys()):
#         for pg, path in sorted(doc_map[doc_id], key=lambda x: x[0]):
#             out.write(f"{doc_id}\t{pg}\t{path}\n")

# api_util/manifest.py
import os
import sys
# import re
#
#
# def main():
#     if len(sys.argv) < 3:
#         print("Usage: manifest.py <input_dir> <manifest_path>")
#         sys.exit(1)
#
#     input_dir = sys.argv[1]
#     manifest_path = sys.argv[2]
#
#     doc_map = {}
#     # Regex: Matches "Name-123.txt" or "Name_123.txt"
#     # Group 1: DocID, Group 2: PageNum
#     pattern = re.compile(r'^(.*)[-_](\d+)\.txt$')
#
#     count_processed = 0
#     count_skipped = 0
#
#     print(f"[Manifest] Scanning: {input_dir}")
#
#     for root, dirs, files in os.walk(input_dir):
#         for f in files:
#             if not f.endswith(".txt"):
#                 continue
#
#             match = pattern.match(f)
#             if match:
#                 doc_id = match.group(1)
#                 page_num = int(match.group(2))
#                 full_path = os.path.join(root, f)
#
#                 if doc_id not in doc_map:
#                     doc_map[doc_id] = []
#                 doc_map[doc_id].append((page_num, full_path))
#                 count_processed += 1
#             else:
#                 # Warn user about files that don't match the expected format
#                 print(f"[Warn] Skipping file (no page number found): {f}", file=sys.stderr)
#                 count_skipped += 1
#
#     # Ensure output directory exists
#     os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
#
#     with open(manifest_path, 'w', encoding='utf-8') as out:
#         # Sort by DocID (alphabetical), then by PageNum (numerical)
#         for doc_id in sorted(doc_map.keys()):
#             # Sort the tuples by the first element (page_num)
#             pages = sorted(doc_map[doc_id], key=lambda x: x[0])
#             for pg, path in pages:
#                 out.write(f"{doc_id}\t{pg}\t{path}\n")
#
#     print(f"[Manifest] Done. Mapped {count_processed} files. Skipped {count_skipped}.")
#     print(f"[Manifest] Saved to: {manifest_path}")


import os
import sys
import csv
import glob

# Configuration
# Path to the directory containing document CSVs
INPUT_DIR = "../../ARUP/DOC_LINE_LANG_CLASS"


def get_sorted_text(csv_path):
    """
    Reads a CSV, sorts by page_num then line_num, and returns the full text.
    """
    entries = []
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Extract page and line numbers safely
                try:
                    p = int(row.get('page_num', 0))
                except ValueError:
                    p = 0
                try:
                    l = int(row.get('line_num', 0))
                except ValueError:
                    l = 0

                text = row.get('text', '').strip()
                if text:
                    entries.append({'p': p, 'l': l, 'text': text})

        # Sort by Page (primary) and Line (secondary)
        entries.sort(key=lambda x: (x['p'], x['l']))

        return "\n".join([e['text'] for e in entries])

    except Exception as e:
        sys.stderr.write(f"Error parsing {csv_path}: {e}\n")
        return None


def main():
    # Verify input directory
    if not os.path.isdir(INPUT_DIR):
        sys.stderr.write(f"Error: Directory {INPUT_DIR} not found.\n")
        sys.exit(1)

    # Find all CSV files in the directory
    csv_files = sorted(glob.glob(os.path.join(INPUT_DIR, "*.csv")))
    for file_path in csv_files:
        # Extract Doc ID from filename (e.g., "CTX123.csv" -> "CTX123")
        filename = os.path.basename(file_path)
        doc_id = os.path.splitext(filename)[0]

        # In a manifest-style output, we typically print metadata.
        # Since the bash script now handles the text extraction logic (using the python snippet provided earlier),
        # this script effectively acts as a dynamic manifest generator.

        # Output format: DOC_ID [TAB] FILE_PATH
        print(f"{doc_id}\t{file_path}")


if __name__ == "__main__":
    main()

