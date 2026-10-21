"""record_layout.py -- an ATRIUM document record as the layout source of the TEITOK writer (#42).

A born-digital PDF has no ALTO. Its record, written by digital-convert (``POST /reformat``), has
the page geometry instead: ``pages[].canvas`` (``width``, ``height``, ``unit``) and
``lines[].bbox``, ``[x_min, y_min, x_max, y_max]`` with the origin top-left and y down, in the
page's canvas unit (``atrium_document.schema.json`` ``$defs/bbox``) -- TEITOK's own convention.

``parse_record_layout()`` therefore returns what ``teitok_alto._parse_alto()`` returns for ALTO --
``(strings, pages, graphics, blocks, meta)`` -- so the alignment, the writer and
``document_hook.py`` need no second code path, as for a flexiconv TEITOK file
(``teitok_layout.py``):

* **lines** -- ``text_lines()``: the record's ``lines[]`` that have text, in record order, without
  the categories ``atrium_vocab.UNTRUSTWORTHY_LINE_CATEGORIES`` names (the lines ``json_to_md``
  drops). ``record_rows()`` turns the same lines into the service's table, so a record sent
  alone is text and layout from one selection, and no line left out of one shifts the
  character alignment of the other.
* **pages** -- one per ``pages[]`` row with a canvas: its size and unit (the schema's ``px`` is
  ALTO's ``pixel``). A page without a canvas (a DOCX) gets no ``<surface>``. Pages are numbered
  by ``page_index``; ``meta["page_labels"]`` keeps a label that is not the number (``i``,
  ``ii``) for ``<pb n>``, and ``meta["page_count"]`` the number of pages, so a page without
  text (a scanned plate) still gets its ``<pb>``.
* **strings** -- the whitespace words of each line. A line with a ``bbox`` on a page with a
  canvas gives each word the share of the line box its characters take, along the box's
  longer side (vertical text runs down). The record has no word boxes, so these are
  approximate, and the TEITOK header says so. A line without a box (a DOCX, or a page re-read
  by OCR, W3 of atrium-digital-convert#4) gives words without coordinates: they still put
  their tokens on the right page and line.
* **blocks** -- ``lines[].group_id`` (a PDF text block per column, a DOCX paragraph or table
  cell) per page, with the union of its line boxes. ``subtype`` is the lines' ``style.region``
  (``page_header``, ``page_footer``, ``footnote``), so running heads stay recognisable.
* **meta** -- ``layout_source="record"``, the canvas unit, the original file name
  (``source.filename``), the record's file name and the converter: the first contributor that
  wrote ``lines``, with the date it did.

The writer scales the coordinates as it scales ALTO's (``teitok_alto._build_page_scale_map``):
to a page image, else by ``IMAGE_DPI`` (a ``pt`` is 1/72 inch, ``bbox_scale.unit_per_inch``),
else not at all.
"""

import collections
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from atrium_vocab import UNTRUSTWORTHY_LINE_CATEGORIES  # noqa: E402

RECORD_SUFFIX = ".document.json"
_WORD = re.compile(r"\S+")
# canvas.unit -> the writer's measurement unit (ALTO's names; bbox_scale.unit_per_inch)
_UNITS = {"px": "pixel", "pixel": "pixel", "pt": "pt"}
#: A line box this much taller than wide is vertical text: its words are stacked downwards.
_VERTICAL_RATIO = 1.5

Box = Tuple[float, float, float, float]


class TextLine(NamedTuple):
    """One line of the record the TEITOK is made of (``text_lines()``)."""

    page_idx: int
    text: str
    bbox: Optional[Box]
    group_id: Optional[str]
    region: Optional[str]
    lang: Optional[str]


def load(src) -> Dict[str, Any]:
    """The record as a dict, from a dict, the bytes of its JSON, or a path."""
    if isinstance(src, dict):
        return src
    if isinstance(src, (bytes, bytearray)):
        data = json.loads(bytes(src).decode("utf-8-sig"))
    else:
        data = json.loads(Path(src).read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("an ATRIUM document record is a JSON object")
    return data


def _bbox(value) -> Optional[Box]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x1, y1, x2, y2 = (float(v) for v in value)
    except (TypeError, ValueError):
        return None
    if x2 < x1 or y2 < y1:
        return None
    return x1, y1, x2, y2


def _canvas(page) -> Optional[Tuple[float, float, str]]:
    """``(width, height, unit)`` of a ``pages[]`` row with a usable canvas, else None."""
    canvas = page.get("canvas") if isinstance(page, dict) else None
    if not isinstance(canvas, dict):
        return None
    try:
        width, height = float(canvas.get("width") or 0), float(canvas.get("height") or 0)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    unit = str(canvas.get("unit") or "px").strip()  # the schema's default
    return width, height, _UNITS.get(unit.lower(), unit)


def _page_index(record) -> Dict[str, int]:
    """``{page label: page_index}``; a row without ``page_index`` counts by its position."""
    index: Dict[str, int] = {}
    for pos, page in enumerate(record.get("pages") or [], start=1):
        if not isinstance(page, dict) or page.get("page") is None:
            continue
        idx = page.get("page_index")
        index.setdefault(str(page["page"]), idx if isinstance(idx, int) and idx > 0 else pos)
    return index


def _num(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def text_lines(src) -> List[TextLine]:
    """The lines the TEITOK is made of: ``lines[]`` with text, in record order, without
    untrustworthy categories (see the module docstring). A line names its page by label; a label
    ``pages[]`` does not list is numbered after the last known page."""
    record = load(src)
    index = _page_index(record)
    out = []
    for row in record.get("lines") or []:
        if not isinstance(row, dict):
            continue
        text = row.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        if row.get("categ") in UNTRUSTWORTHY_LINE_CATEGORIES:
            continue
        label = str(row.get("page", "1"))
        if label not in index:
            index[label] = max(index.values(), default=0) + 1
        style = row.get("style") if isinstance(row.get("style"), dict) else {}
        group = row.get("group_id")
        out.append(
            TextLine(
                page_idx=index[label],
                text=text,
                bbox=_bbox(row.get("bbox")),
                group_id=str(group) if group is not None else None,
                region=style.get("region"),
                lang=row.get("lang"),
            )
        )
    return out


def record_rows(src) -> List[Dict[str, Any]]:
    """The service's table of a record sent without one: ``text``, ``page_num`` (the page
    index) and ``line_num`` (1-based per page), from the same lines as the layout."""
    rows, per_page = [], collections.Counter()
    for line in text_lines(src):
        per_page[line.page_idx] += 1
        rows.append(
            {
                "text": line.text.strip(),
                "page_num": line.page_idx,
                "line_num": per_page[line.page_idx],
            }
        )
    return rows


def record_has_geometry(src) -> bool:
    """True when the record can be a layout: a page with a canvas and, on it, a line with a box.
    One JSON read, no schema validation; an unreadable record is not one."""
    try:
        record = load(src)
    except (OSError, ValueError):
        return False
    canvases = {
        str(p.get("page"))
        for p in record.get("pages") or []
        if _canvas(p) and p.get("page") is not None
    }
    return any(
        isinstance(row, dict) and str(row.get("page")) in canvases and _bbox(row.get("bbox"))
        for row in record.get("lines") or []
    )


def word_boxes(text: str, box: Optional[Box]) -> List[Tuple[str, Optional[Box]]]:
    """``(word, box)`` per whitespace word of ``text``: the share of the line ``box`` the word's
    characters take, along the box's longer side; ``None`` boxes without a line box."""
    matches = list(_WORD.finditer(text))
    if box is None or not matches:
        return [(m.group(), None) for m in matches]
    x1, y1, x2, y2 = box
    start = matches[0].start()
    length = matches[-1].end() - start
    vertical = len(matches) > 1 and (y2 - y1) > _VERTICAL_RATIO * (x2 - x1)
    out = []
    for m in matches:
        a, b = (m.start() - start) / length, (m.end() - start) / length
        if vertical:
            word = (x1, y1 + a * (y2 - y1), x2, y1 + b * (y2 - y1))
        else:
            word = (x1 + a * (x2 - x1), y1, x1 + b * (x2 - x1), y2)
        out.append((m.group(), tuple(round(v, 3) for v in word)))
    return out


def _converter(record) -> Tuple[str, str, str]:
    """``(program, version, date)`` of the first contributor that wrote ``lines``."""
    for entry in (record.get("provenance") or {}).get("contributors") or []:
        if not isinstance(entry, dict):
            continue
        blocks = entry.get("blocks") or []
        if isinstance(blocks, str):
            blocks = blocks.split(",")
        if "lines" in {str(b).strip() for b in blocks}:
            date = str(entry.get("at") or "")[:10]
            return str(entry.get("program") or ""), str(entry.get("version") or ""), date
    return "", "", ""


def _empty_meta():
    return {
        "source_image": "",
        "ocr_software": "",
        "ocr_version": "",
        "ocr_date": "",
        "measurement_unit": "pixel",
        "layout_source": "record",
        "converter": "",
        "converter_version": "",
        "converted_on": "",
        "orgfile": "",
        "record_file": "",
        "page_labels": {},
        "page_count": 0,
    }


def parse_record_layout(path):
    """``(strings, pages, graphics, blocks, meta)`` of an ATRIUM document record -- the shape of
    ``teitok_alto._parse_alto()``. See the module docstring."""
    from api_util.teitok_alto import _norm_lang  # teitok_alto dispatches here

    strings, pages, graphics, blocks = [], [], [], {}
    meta = _empty_meta()
    try:
        record = load(path)
    except (OSError, ValueError) as exc:
        print(f"  [Warn] Failed to read the record {path}: {exc}", file=sys.stderr)
        return strings, pages, graphics, blocks, meta

    meta["record_file"] = Path(path).name
    meta["orgfile"] = str((record.get("source") or {}).get("filename") or "")
    meta["converter"], meta["converter_version"], meta["converted_on"] = _converter(record)

    canvases = {}
    index = _page_index(record)
    for label, idx in index.items():
        if label != str(idx):
            meta["page_labels"][idx] = label
    for page in record.get("pages") or []:
        canvas = _canvas(page)
        if canvas is None or page.get("page") is None:
            continue
        idx = index[str(page["page"])]
        canvases[idx] = canvas
        pages.append(
            {
                "id": f"page-{idx}",
                "width": canvas[0],
                "height": canvas[1],
                "idx": idx,
                "ps_hpos": 0,
                "ps_vpos": 0,
                "ps_width": 0,
                "ps_height": 0,
                "unit": canvas[2],
            }
        )
    if pages:
        meta["measurement_unit"] = pages[0]["unit"]

    lines = text_lines(record)
    meta["page_count"] = max([*index.values(), *(line.page_idx for line in lines), 0])
    for k, line in enumerate(lines, start=1):
        box = line.bbox if line.page_idx in canvases else None
        block_id = None
        if line.group_id is not None:
            block_id = f"__record_block{line.page_idx}:{line.group_id}"
            block = blocks.setdefault(
                block_id, {"box": None, "subtype": None, "page_idx": line.page_idx}
            )
            if box is not None:
                old = block["box"]
                block["box"] = box if old is None else (
                    min(old[0], box[0]), min(old[1], box[1]), max(old[2], box[2]), max(old[3], box[3])
                )  # fmt: skip
            block["subtype"] = block["subtype"] or line.region
        line_bbox = " ".join(_num(v) for v in box) if box is not None else ""
        lang = _norm_lang(line.lang)
        for word, wbox in word_boxes(line.text, box):
            strings.append(
                {
                    "content": word,
                    "left": wbox[0] if wbox else None,
                    "top": wbox[1] if wbox else None,
                    "right": wbox[2] if wbox else None,
                    "bottom": wbox[3] if wbox else None,
                    "page_idx": line.page_idx,
                    "block_id": block_id,
                    "line_id": f"__record_line{k}",
                    "line_bbox": line_bbox,
                    "lang": lang,
                }
            )
    for block in blocks.values():
        box = block.pop("box")
        block["bbox"] = " ".join(_num(v) for v in box) if box is not None else ""
    return strings, pages, graphics, blocks, meta
