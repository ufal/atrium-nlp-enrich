#!/usr/bin/env python3
"""flexiconv_report.py -- the "Checking a real collection" table for flexiconv output (#10).

Reads every ``*.teitok.xml`` in a directory (normally ``$TEITOK_FLEXICONV_DIR``, written by
``api_flexiconv.sh``) the way the pipeline does and prints one Markdown row per document:

* **Input** -- the source file the TEITOK header names (``note[@n="source_file"]`` or
  ``orgfile``, else the ``Converted from ...`` change text) and its format;
* **Pages** -- ``<pb>`` count;
* **Rows / Tokens** -- what ``teitok_read`` gives keywords.py and llm-enrich;
* **Elements with bbox** -- elements inside ``<text>`` carrying a ``bbox``: the layout kept
  from PAGE XML / hOCR / ALTO ("—" for none);
* **``--profile core``** -- ``validate_teitok_xml``'s TEITOK-core verdict.

Usage:
    python3 api_util/flexiconv_report.py "$TEITOK_FLEXICONV_DIR" [--inputs "$INPUT_DOCS_DIR"]

``--inputs`` also lists the input files that produced no TEITOK file (matched by file name
stem, the adapter's naming rule). Exit status 0 when every document converted, passes the
core profile and yields at least one row; 1 otherwise; 2 on usage errors.
"""

import argparse
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from api_util.flexiconv_convert import FLEXICONV_EXTENSIONS  # noqa: E402
from api_util.teitok_layout import source_name  # noqa: E402
from api_util.teitok_read import (  # noqa: E402
    _local,
    parse_teitok,
    read_teitok_rows,
    read_teitok_tokens,
)
from api_util.validate_teitok_xml import validate_document  # noqa: E402

_SUFFIX = ".teitok.xml"


def describe(path) -> dict:
    """One report row for one flexiconv TEITOK file."""
    path = Path(path)
    row = {"file": path.name, "source": "", "format": "", "pages": 0, "rows": 0, "tokens": 0}
    row["bbox"] = 0
    try:
        root = parse_teitok(path)
    except Exception as exc:  # unreadable output is a finding, not a crash
        row["core"] = [f"not readable: {exc}"]
        return row
    source = source_name(root)
    row["source"] = source
    row["format"] = Path(source).suffix.lstrip(".").lower() if source else ""
    row["pages"] = sum(1 for el in root.iter() if _local(el.tag) == "pb")
    body = [el for el in root.iter() if _local(el.tag) == "text"]
    scope = body[0] if body else root
    row["bbox"] = sum(1 for el in scope.iter() if el.get("bbox"))
    row["rows"] = len(read_teitok_rows(path))
    row["tokens"] = len(read_teitok_tokens(path))
    row["core"] = validate_document(path, profile="core")
    return row


def _ok(row) -> bool:
    return not row["core"] and row["rows"] > 0


def markdown(rows, missing=()) -> str:
    lines = [
        "| Input | Pages | Rows | Tokens | Elements with bbox | `--profile core` |",
        "|-------|-------|------|--------|--------------------|------------------|",
    ]
    for row in rows:
        label = row["source"] or row["file"]
        if row["format"]:
            label = f"{row['format']} `{label}`"
        core = "✅" if not row["core"] else "❌ " + row["core"][0].replace("|", "\\|")
        lines.append(
            f"| {label} | {row['pages'] or '—'} | {row['rows']} | {row['tokens']} | "
            f"{row['bbox'] or '—'} | {core} |"
        )
    for name in missing:
        lines.append(f"| `{name}` | — | — | — | — | ❌ no TEITOK output |")
    return "\n".join(lines)


def _missing_inputs(inputs_dir, outputs) -> list:
    """Convertible input files with no ``<stem>.teitok.xml`` / ``<stem>.<ext>.teitok.xml``."""
    produced = {p.name[: -len(_SUFFIX)] for p in outputs}
    missing = []
    for src in sorted(Path(inputs_dir).iterdir()):
        ext = src.suffix.lstrip(".").lower()
        if not src.is_file() or ext not in FLEXICONV_EXTENSIONS:
            continue
        if src.stem not in produced and f"{src.stem}.{ext}" not in produced:
            missing.append(src.name)
    return missing


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("teitok_dir", help="directory of flexiconv *.teitok.xml output")
    parser.add_argument("--inputs", default=None, help="INPUT_DOCS_DIR, to list unconverted files")
    args = parser.parse_args(argv)

    target = Path(args.teitok_dir)
    if not target.is_dir():
        print(f"[ERROR] not a directory: {target}", file=sys.stderr)
        return 2
    outputs = sorted(target.glob(f"*{_SUFFIX}"))
    missing = []
    if args.inputs:
        if not Path(args.inputs).is_dir():
            print(f"[ERROR] not a directory: {args.inputs}", file=sys.stderr)
            return 2
        missing = _missing_inputs(args.inputs, outputs)
    rows = [describe(p) for p in outputs]
    print(markdown(rows, missing))
    good = sum(1 for r in rows if _ok(r))
    print(
        f"\n{good}/{len(rows) + len(missing)} document(s) converted, readable and TEITOK-core valid"
    )
    return 0 if good == len(rows) + len(missing) and (rows or missing) else 1


if __name__ == "__main__":
    sys.exit(main())
