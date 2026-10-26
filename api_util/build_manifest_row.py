#!/usr/bin/env python3
"""
build_manifest_row.py  –  Extract ordered text from one input of stage 1 -- a CSV or XLSX table,
a plain-text file, or a TEITOK file (flexiconv's conversion, ``api_flexiconv.sh``) -- write it
to a temp text file, and print one TSV row to stdout:

    doc_id <TAB> page_count <TAB> /path/to/text_file

The input is read by ``api_util/line_inputs.py``, the reader the service's uploads go through
too (atrium-project#72): a table in (page, line) order, a text file's pages at its form feeds,
a TEITOK file in document order with the rows ``teitok_read.read_teitok_rows()`` gives
keywords.py and llm-enrich. Stage 4 later takes a TEITOK document's layout from the same file,
so the text UDPipe sees and the text the layout was built from are the same.
``--skip-untrustworthy-lines`` leaves out a table's rows whose ``categ`` is untrustworthy
(``atrium_vocab.UNTRUSTWORTHY_LINE_CATEGORIES``; the opt-in ``SKIP_UNTRUSTWORTHY_LINES``).

Next to ``<doc>.txt`` it writes ``<doc>.rows.tsv`` (``api_util/page_rows.py``): the page,
line, page label and text of every line, in the same order -- the page provenance stages
2-4 use instead of guessing pages from UDPipe's chunks (issue #38, A). Row text is
normalised so that one row is exactly one line of ``<doc>.txt``.

``--doc-id-only`` prints the doc_id the row would get and writes nothing; with
``--table-ids`` it also names the table document that claims a converted file as its
layout (``api_util/doc_identity.py``), so ``api_1_manifest.sh`` can skip it.
"""

import argparse
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

from api_util import line_inputs  # noqa: E402
from api_util.page_rows import rows_path_for, write_rows  # noqa: E402
from atrium_document import canonical_doc_id  # noqa: E402
from atrium_vocab import UNTRUSTWORTHY_LINE_CATEGORIES  # noqa: E402


def _entries(file_path, reader):
    """The rows of one input as ``{"p", "l", "text", "label"}``, page numbers as the input
    has them; [] with the reason on stderr when it cannot be read."""
    try:
        rows = reader(Path(file_path).read_bytes())
    except Exception as exc:
        print(f"[Error] reading {file_path}: {exc}", file=sys.stderr)
        return []
    return [{"p": r.page, "l": r.line, "text": r.text, "label": r.label} for r in rows]


def _read_csv(file_path):
    return _entries(file_path, line_inputs.read_csv)


def _read_xlsx(file_path):
    return _entries(file_path, line_inputs.read_xlsx)


def get_rows(file_path, skip_untrustworthy=False):
    """The lines of one input, in the order they go into ``<doc>.txt``, as ``page_rows.Row``s
    (a missing page number counts as page 1). [] when the input has no text, is not one stage
    1 reads, or cannot be read (the reason on stderr)."""
    skip = UNTRUSTWORTHY_LINE_CATEGORIES if skip_untrustworthy else ()
    try:
        return line_inputs.read_rows(str(file_path), skip_categories=skip)
    except line_inputs.UnsupportedInput:
        return []
    except (OSError, ValueError) as exc:
        print(f"[Error] reading {file_path}: {exc}", file=sys.stderr)
        return []


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
        "--skip-untrustworthy-lines",
        action="store_true",
        help="leave out a table's rows whose categ is untrustworthy (Trash, Garbage, Inverted)",
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
    rows = get_rows(args.input_file, skip_untrustworthy=args.skip_untrustworthy_lines)
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
