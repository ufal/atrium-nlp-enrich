#!/usr/bin/env python3
"""
build_manifest_row.py  –  Extract ordered text from one CSV/XLSX file, or from a TEITOK
file flexiconv converted (``api_flexiconv.sh``, ``FLEXICONV_ANNOTATE=true``), write it to a
temp text file, and print one TSV row to stdout:

    doc_id <TAB> page_count <TAB> /path/to/text_file

A ``.teitok.xml`` input contributes the rows ``teitok_read.read_teitok_rows()`` gives
keywords.py and llm-enrich (one per ``<lb/>`` line or text block), in document order. Stage
4 later takes the document's layout from the same file, so the text UDPipe sees and the
text the layout was built from are the same.

Next to ``<doc>.txt`` it writes ``<doc>.rows.tsv`` (``api_util/page_rows.py``): the page,
line, page label and text of every line, in the same order -- the page provenance stages
2-4 use instead of guessing pages from UDPipe's chunks (issue #38, A). Row text is
normalised so that one row is exactly one line of ``<doc>.txt``.

``--doc-id-only`` prints the doc_id the row would get and writes nothing; with
``--table-ids`` it also names the table document that claims a converted file as its
layout (``api_util/doc_identity.py``), so ``api_1_manifest.sh`` can skip it.
"""

import argparse
import csv
import os
import sys
from pathlib import Path

# Inject project root into sys.path so the vendored `atrium_document` resolves when this
# script is invoked directly (api_1_manifest.sh runs `python3 api_util/build_manifest_row.py`,
# which puts api_util/ — not the repo root — on sys.path). Same idiom as
# api_util/summarize_nt_udp.py.
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from api_util.page_rows import Row, normalize_row_text, rows_path_for, write_rows  # noqa: E402
from atrium_document import canonical_doc_id  # noqa: E402

csv.field_size_limit(sys.maxsize)

try:
    import openpyxl
except ImportError:
    openpyxl = None


def _read_csv(file_path):
    entries = []
    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                try:
                    p = int(row.get("page_num", 0) or 0)
                except (ValueError, TypeError):
                    p = 0
                try:
                    ln = int(row.get("line_num", 0) or 0)
                except (ValueError, TypeError):
                    ln = 0
                text = normalize_row_text(row.get("text"))
                if text:
                    label = (row.get("page_label") or "").strip()
                    entries.append({"p": p, "l": ln, "text": text, "label": label})
    except Exception as exc:
        print(f"[Error] reading CSV {file_path}: {exc}", file=sys.stderr)
    return entries


def _read_xlsx(file_path):
    if openpyxl is None:
        print("[Error] openpyxl is required for .xlsx files.", file=sys.stderr)
        return []
    entries = []
    try:
        wb = openpyxl.load_workbook(file_path, data_only=True)
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            headers = [cell.value for cell in ws[1]]
            if not headers or "text" not in headers:
                continue
            text_idx = headers.index("text")
            page_idx = headers.index("page_num") if "page_num" in headers else -1
            line_idx = headers.index("line_num") if "line_num" in headers else -1
            for row in ws.iter_rows(min_row=2, values_only=True):
                text_val = row[text_idx]
                text = normalize_row_text(text_val) if text_val is not None else ""
                if not text:
                    continue
                try:
                    p = int(row[page_idx]) if page_idx != -1 and row[page_idx] is not None else 0
                except (ValueError, TypeError):
                    p = 0
                try:
                    ln = int(row[line_idx]) if line_idx != -1 and row[line_idx] is not None else 0
                except (ValueError, TypeError):
                    ln = 0
                entries.append({"p": p, "l": ln, "text": text, "label": ""})
    except Exception as exc:
        print(f"[Error] reading XLSX {file_path}: {exc}", file=sys.stderr)
    return entries


def _read_teitok(file_path):
    from api_util.teitok_read import read_teitok_rows

    try:
        rows = read_teitok_rows(file_path)
    except Exception as exc:
        print(f"[Error] reading TEITOK {file_path}: {exc}", file=sys.stderr)
        return []
    entries = []
    for r in rows:
        text = normalize_row_text(r["text"])
        if text:
            # page_idx: the ordinal of the <pb> (what stage 4's layout counts); page_label:
            # its @n. Older readers without those keys give page_num for both.
            entries.append(
                {
                    "p": r.get("page_idx", r["page_num"]),
                    "l": r["line_num"],
                    "text": text,
                    "label": str(r.get("page_label", "") or ""),
                }
            )
    return entries


def get_rows(file_path):
    """The lines of one input, in the order they go into ``<doc>.txt``, as ``page_rows.Row``s
    (a missing page number counts as page 1). [] when the input has no text."""
    ext = os.path.splitext(file_path)[1].lower()
    if str(file_path).lower().endswith(".teitok.xml"):
        # document order, not (page, line): block rows restart their line count per page
        entries = _read_teitok(file_path)
    elif ext == ".csv":
        entries = sorted(_read_csv(file_path), key=lambda x: (x["p"], x["l"]))
    elif ext == ".xlsx":
        entries = sorted(_read_xlsx(file_path), key=lambda x: (x["p"], x["l"]))
    else:
        return []
    return [
        Row(page=e["p"] or 1, line=e["l"], label=e.get("label", ""), text=e["text"])
        for e in entries
    ]


def get_sorted_text_and_page_count(file_path):
    rows = get_rows(file_path)
    if not rows:
        return None, 0
    return "\n".join(r.text for r in rows), max(r.page for r in rows)


def main():
    default_text_dir = os.environ.get("TEMP_TXT_DIR", "./TEMP/TXT_EXTRACT")
    parser = argparse.ArgumentParser()
    parser.add_argument("input_file")
    parser.add_argument("--text-dir", default=default_text_dir)
    parser.add_argument("--doc-id", default=None, help="Logical document ID to use in manifest")
    parser.add_argument(
        "--doc-id-only", action="store_true", help="print the doc_id and exit (writes nothing)"
    )
    parser.add_argument(
        "--table-ids",
        default=None,
        help="with --doc-id-only on a converted *.teitok.xml: a file listing the table doc_ids "
        "(one per line); prints 'doc_id<TAB>claiming table id' (empty when none claims it)",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.input_file):
        print(f"[Error] File not found: {args.input_file}", file=sys.stderr)
        sys.exit(1)

    # canonical_doc_id(), not os.path.splitext(): this row IS the doc_id every later stage
    # inherits (UDP/<file>.conllu → NE/<file> → the document record), so a derivation that
    # strips only the last extension forks the whole run's identity on any multi-dot input
    # (issue atrium-project#10, D3).
    doc_id = args.doc_id or canonical_doc_id(args.input_file)
    if args.doc_id_only:
        if args.table_ids is not None:
            # issue #38, B: a table document may use this converted file as its layout
            # (doc_identity.find_converted); stage 1 then skips it, stage 4 takes its layout.
            from api_util.doc_identity import claimed_by

            with open(args.table_ids, encoding="utf-8") as fh:
                table_ids = [line.strip() for line in fh if line.strip()]
            print(f"{doc_id}\t{claimed_by(args.input_file, table_ids)}")
        else:
            print(doc_id)
        return
    rows = get_rows(args.input_file)
    if not rows:
        print(f"[Error] No text content found in {args.input_file}", file=sys.stderr)
        sys.exit(1)
    full_text = "\n".join(r.text for r in rows)
    page_count = max(r.page for r in rows)

    out_text_file = os.path.join(args.text_dir, f"{doc_id}.txt")
    os.makedirs(os.path.dirname(out_text_file), exist_ok=True)
    with open(out_text_file, "w", encoding="utf-8") as fh:
        fh.write(full_text)
    write_rows(rows_path_for(out_text_file), rows, source=args.input_file)

    print(f"{doc_id}\t{page_count}\t{out_text_file}")


if __name__ == "__main__":
    main()
