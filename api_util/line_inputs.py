"""
line_inputs.py -- the text inputs of nlp-enrich, read the same way by stage 1 and by the service.

Stage 1 (``api_1_manifest.sh`` -> ``build_manifest_row.py``) and ``POST /enrich`` /
``POST /jobs`` (``service/enrichment.normalize_upload``) used to read the same kinds of file
with code of their own, and they differed: the service read a plain-text file and stage 1 did
not; stage 1 read a CSV without its byte-order mark and without the ``page``/``line``
spellings; the service dropped ``page_label``. Both now call this module (atrium-project#72,
the service-CLI alignment).

The inputs, recognised by name and, for XML, by content:

* a table, ``.csv`` (UTF-8, a BOM allowed) or ``.xlsx`` (every sheet whose first row has
  ``text``): the columns ``text`` (required), ``page_num`` or ``page``, ``line_num`` or
  ``line``, ``page_label``, and ``categ`` (ocr-postprocess's line category); its rows in
  (page, line) order;
* plain text, ``.txt``: one row per line with text; a form feed starts a page (what pdftotext
  writes between pages); a line keeps its number on its page, blank lines counted;
* TEITOK, ``*.teitok.xml`` or any ``.xml`` with ``<TEI`` in its first 4 KB (flexiconv's
  conversion of a PDF or DOCX): the rows ``teitok_read.read_teitok_rows()`` gives, in document
  order, the page being the ``<pb/>`` ordinal and the label its ``@n``. A file that breaks the
  TEITOK core rules is refused with the diagnostics.

``read_entries()`` keeps the page numbers as the input has them (0 for a table row without
one); ``read_rows()`` then counts page 0 as page 1, as stage 1 always did. The service writes the entries into its canonical table
(``write_table()``), which stage 1 reads back: the (page, line) sort of a table keeps a TEITOK
file's document order, since its keys never decrease along the document.

``skip_categories`` drops the rows of a table whose ``categ`` is one of them: the opt-in
``SKIP_UNTRUSTWORTHY_LINES`` (``atrium_vocab.UNTRUSTWORTHY_LINE_CATEGORIES``), off by default.
A record sent as the text is filtered always (``api_util/record_layout.text_lines``).
"""

from __future__ import annotations

import csv
import io
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from api_util.page_rows import Row, normalize_row_text  # noqa: E402

csv.field_size_limit(sys.maxsize)

TABLE_SUFFIXES = (".csv", ".xlsx")
TEXT_SUFFIX = ".txt"
TEITOK_SUFFIX = ".teitok.xml"
#: What an upload or a stage-1 input may be, by extension.
ACCEPTED = (".csv", ".xlsx", ".txt", ".xml")
#: The columns of the canonical table the service writes and stage 1 reads.
TABLE_COLUMNS = ("text", "page_num", "line_num", "page_label", "categ")

#: What cannot be part of a file name: control characters and path separators.
_UNSAFE_IN_NAME = re.compile(r"[\x00-\x1f\x7f/\\]")
#: A file name has 255 bytes; the longest suffix the stages add to a doc_id is under 30.
_MAX_DOC_ID_BYTES = 200
_DEFAULT_DOC_ID = "document"


@dataclass(frozen=True)
class Entry:
    """One text row of an input: a ``page_rows.Row`` with the table's ``categ``, if any."""

    page: int
    line: int
    label: str
    text: str
    categ: str = ""


class UnsupportedInput(ValueError):
    """A file of a kind nlp-enrich does not read as text. A ``ValueError``, so callers that
    catch that keep working; the service answers it with 415 ``unsupported_media_type``."""

    accepted = ACCEPTED


def is_teitok(name: str, head: bytes = b"") -> bool:
    """A ``*.teitok.xml`` file, or any ``.xml`` whose first 4 KB contain ``<TEI``."""
    lowered = (name or "").lower()
    if lowered.endswith(TEITOK_SUFFIX):
        return True
    return lowered.endswith(".xml") and b"<TEI" in head[:4096]


def input_kind(name: str, head: bytes = b"") -> Optional[str]:
    """``"teitok"``, ``"csv"``, ``"xlsx"``, ``"txt"``, or None for a file not read as text."""
    if is_teitok(name, head):
        return "teitok"
    ext = os.path.splitext(name or "")[1].lower()
    if ext in TABLE_SUFFIXES or ext == TEXT_SUFFIX:
        return ext[1:]
    return None


def sanitize_doc_id(name: str) -> str:
    """The doc_id of an uploaded file or a record's id: its name without the input suffix, as
    the command line's stages derive it from a file of that name (``canonical_doc_id``).

    Only what cannot be part of a file name is replaced (control characters, path separators;
    a leading dot or dash is dropped), and the id is cut at 200 bytes. It used to replace
    everything outside ``[A-Za-z0-9._-]``, so the service called ``zpráva 1.csv`` ``zpr_va_1``
    where the command line says ``zpráva 1`` (atrium-project#72)."""
    stem = Path(str(name or "")).name
    for suffix in (TEITOK_SUFFIX, ".alto.xml"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    root, ext = os.path.splitext(stem)
    if ext.lower() in (".csv", ".xlsx", ".txt", ".xml"):
        stem = root
    safe = _UNSAFE_IN_NAME.sub("_", stem).strip().lstrip(".-")
    safe = safe.encode("utf-8")[:_MAX_DOC_ID_BYTES].decode("utf-8", "ignore").strip()
    return safe or _DEFAULT_DOC_ID


def _int(value: Any) -> int:
    """A page or line number; 0 when the cell is empty or not a number."""
    if value is None or isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0


def _cell(record: Dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in record:
            return record[name]
    return None


def _table_rows(records: Iterable[Dict[str, Any]], skip: frozenset) -> List[Entry]:
    """The rows of a table, in (page, line) order (a stable sort: equal keys keep file order)."""
    rows = []
    for record in records:
        text = normalize_row_text(record.get("text"))
        if not text:
            continue
        categ = str(record.get("categ") or "").strip()
        if categ in skip:
            continue
        rows.append(
            Entry(
                page=_int(_cell(record, "page_num", "page")),
                line=_int(_cell(record, "line_num", "line")),
                label=str(record.get("page_label") or "").strip(),
                text=text,
                categ=categ,
            )
        )
    rows.sort(key=lambda r: (r.page, r.line))
    return rows


def read_csv(data: bytes, skip_categories: Iterable[str] = ()) -> List[Entry]:
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if "text" not in [str(n or "").strip() for n in (reader.fieldnames or [])]:
        raise ValueError("CSV input must contain a 'text' column.")
    records = ({str(k).strip(): v for k, v in raw.items() if k is not None} for raw in reader)
    return _table_rows(records, frozenset(skip_categories))


def read_xlsx(data: bytes, skip_categories: Iterable[str] = ()) -> List[Entry]:
    try:
        import openpyxl  # type: ignore
    except ImportError as exc:  # pragma: no cover - a dependency of both images
        raise ValueError("openpyxl is required for .xlsx input.") from exc
    workbook = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    records: List[Dict[str, Any]] = []
    for sheet in workbook.worksheets:
        header: Optional[List[str]] = None
        for values in sheet.iter_rows(values_only=True):
            if header is None:
                header = [str(c).strip() if c is not None else "" for c in values]
                if "text" not in header:
                    break
                continue
            records.append({h: v for h, v in zip(header, values, strict=False) if h})
    return _table_rows(records, frozenset(skip_categories))


def read_txt(data: bytes) -> List[Entry]:
    """One row per line with text; a form feed starts the next page."""
    text = data.decode("utf-8-sig", errors="replace")
    rows = []
    for page, part in enumerate(text.split("\f"), start=1):
        for line, raw in enumerate(part.splitlines(), start=1):
            stripped = normalize_row_text(raw)
            if stripped:
                rows.append(Entry(page=page, line=line, label="", text=stripped))
    return rows


def read_teitok(data: bytes, path: Optional[Path] = None) -> List[Entry]:
    """The rows of a TEITOK file, in document order. Refuses a file that is not well-formed or
    breaks the TEITOK core rules (duplicate ids, dangling references), with the diagnostics."""
    from api_util.teitok_read import read_teitok_rows

    text = data.decode("utf-8-sig", errors="replace")
    try:
        from api_util.validate_teitok_xml import LxmlMissing, validate_xml_text

        errors = validate_xml_text(text, profile="core")
    except LxmlMissing:  # pragma: no cover - lxml ships in both images
        errors = []
    if errors:
        raise ValueError("Uploaded TEITOK is not usable: " + "; ".join(errors[:10]))

    def rows_of(source) -> List[dict]:
        try:
            return read_teitok_rows(source)
        except ET.ParseError as exc:
            raise ValueError(f"Uploaded TEITOK is not well-formed XML: {exc}") from exc

    if path is not None:
        found = rows_of(path)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp) / f"upload{TEITOK_SUFFIX}"
            scratch.write_text(text, encoding="utf-8")
            found = rows_of(scratch)
    rows = []
    for r in found:
        stripped = normalize_row_text(r["text"])
        if stripped:
            rows.append(
                Entry(
                    page=_int(r.get("page_idx", r["page_num"])),
                    line=_int(r["line_num"]),
                    label=str(r.get("page_label", "") or ""),
                    text=stripped,
                )
            )
    return rows


def read_entries(
    name: str, data: Optional[bytes] = None, *, skip_categories: Iterable[str] = ()
) -> List[Entry]:
    """The text rows of one input, page numbers as the input has them. ``name`` is the file's
    name (its path when ``data`` is None, and then the file is read). Raises
    ``UnsupportedInput`` for a file not read as text, ``ValueError`` for one that cannot be."""
    path = Path(name) if data is None else None
    if data is None:
        data = Path(name).read_bytes()
    kind = input_kind(str(name), data[:4096])
    if kind == "teitok":
        return read_teitok(data, path)
    if kind == "csv":
        return read_csv(data, skip_categories)
    if kind == "xlsx":
        return read_xlsx(data, skip_categories)
    if kind == "txt":
        return read_txt(data)
    ext = os.path.splitext(str(name) or "")[1].lower()
    raise UnsupportedInput(
        f"Unsupported file type '{ext}'. Allowed: .csv, .xlsx, .txt, and a TEITOK .xml "
        "(e.g. flexiconv's conversion of a PDF or DOCX)."
    )


def read_rows(
    name: str, data: Optional[bytes] = None, *, skip_categories: Iterable[str] = ()
) -> List[Row]:
    """The rows of one input in the order they go into ``<doc>.txt``, a row without a page
    counting as page 1 (stage 1's rule)."""
    return [
        Row(page=r.page or 1, line=r.line, label=r.label, text=r.text)
        for r in read_entries(name, data, skip_categories=skip_categories)
    ]


def highest_page(rows: Iterable[Dict[str, Any]]) -> int:
    """The highest page number among ``rows`` with text, as ``write_table`` reports it."""
    return max(
        (_int(_cell(r, "page_num", "page")) for r in rows if (r.get("text") or "").strip()),
        default=0,
    )


def write_table(rows: Iterable[Dict[str, Any]], path: Path) -> int:
    """Write ``rows`` (``text``, ``page_num``/``page``, ``line_num``/``line``, ``page_label``,
    ``categ``) as the canonical table stage 1 reads; rows without text are left out. Returns
    the highest page number written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    max_page = 0
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(TABLE_COLUMNS)
        for r in rows:
            text = (r.get("text") or "").strip()
            if not text:
                continue
            page = _int(_cell(r, "page_num", "page"))
            line = _int(_cell(r, "line_num", "line"))
            max_page = max(max_page, page)
            writer.writerow([text, page, line, r.get("page_label") or "", r.get("categ") or ""])
    return max_page


def as_dicts(entries: Iterable[Entry]) -> List[Dict[str, Any]]:
    """Entries as the service's table rows: ``text``, ``page_num``, ``line_num``,
    ``page_label``, and ``categ`` when the table has one."""
    out = []
    for e in entries:
        row: Dict[str, Any] = {
            "text": e.text,
            "page_num": e.page,
            "line_num": e.line,
            "page_label": e.label,
        }
        if e.categ:
            row["categ"] = e.categ
        out.append(row)
    return out
