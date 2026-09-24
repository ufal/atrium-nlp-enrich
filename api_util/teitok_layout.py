"""teitok_layout.py -- a flexiconv TEITOK document as the layout source of the TEITOK writer.

``api_flexiconv.sh`` converts PDF, DOCX, PAGE XML, hOCR, ... to TEITOK. That file has the
document's text and, for layout formats, its geometry (``<pb facs>``, ``<lb bbox>``,
``<tok bbox>``), but no linguistic annotation. With ``FLEXICONV_ANNOTATE=true`` the pipeline
annotates it: the text goes through the usual manifest → UDPipe → NameTag stages, and stage 4
writes TEITOK format 2 with *this* file standing in for the ALTO file.

``parse_teitok_layout()`` therefore returns exactly what ``teitok_alto._parse_alto()`` returns
for ALTO -- ``(strings, pages, graphics, blocks, meta)`` -- so the alignment, the writer and
``document_hook.py`` need no second code path:

* **strings** -- one per ``<tok>`` (its form; ``<dtok>`` text ignored), with its ``bbox`` when
  it has one. Untokenized documents (txt, md, docx, ...) have no ``<tok>``: their strings are
  the words of each leaf text block, without coordinates. Either way the stream of characters
  is the text ``teitok_read.read_teitok_rows()`` gives stage 1, so every UDPipe token aligns.
* **pages** -- one per ``<pb>``, numbered 1..N in document order (text before the first
  ``<pb>`` is page 1, as in ``teitok_read``). A page's ``<surface>`` is the one ``pb@corresp``
  names, else the k-th ``<surface>`` of the ``<facsimile>``; its image is ``pb@facs``, else
  ``surface@facs``, else the surface's ``<graphic url>``; its size is ``pb@bbox``, else
  ``surface@lrx/lry``, else ``graphic@width/height``. Only pages with an image or a size get
  an entry, i.e. a ``<surface>`` in the output: a PDF page without an image stays a page
  break, not a facsimile. ``meta["page_labels"]`` keeps ``pb@n`` (``"I"``, ``"7a"``) for the
  writer's ``<pb n>``, and ``meta["page_count"]`` the number of pages.
* **blocks** -- the innermost ``div p head item cell l u ab quote`` around the text, with its
  ``bbox``. ``subtype`` is the element name (``p``, ``head``, ``item``, ...), or ``@type`` for a
  ``div``, so a converted document keeps its headings/paragraphs/list items as
  ``<div type="TextBlock" subtype=...>``.
* **lines** -- ``<lb/>`` (with its ``bbox``), carried on the strings as ALTO lines are.
* **meta** -- ``layout_source="teitok"``, the converter and its version (``appInfo``), and the
  original document's name (``note[@n="source_file"|"orgfile"]`` or the "Converted from" change).

Coordinates are taken as they are: flexiconv writes page-image pixels with the page origin,
which is the space the writer uses.
"""

import re
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from api_util.teitok_alto import _norm_lang  # noqa: E402
from api_util.teitok_read import _local, _tok_form, parse_teitok  # noqa: E402

BLOCK_TAGS = frozenset({"div", "p", "head", "item", "cell", "l", "u", "ab", "quote"})
# Leaf text blocks of untokenized documents (the rows teitok_read makes; no "div").
_LEAF_TAGS = frozenset({"p", "head", "item", "cell", "l", "u", "ab", "quote"})
_SKIP_TAGS = frozenset({"teiHeader", "facsimile", "standOff"})
_CONVERTED_FROM = re.compile(r"Converted from (?:\S+ file )?(\S+)")
_WS_RUN = re.compile(r"\s+")
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def is_teitok(path) -> bool:
    """True when ``path`` looks like TEI/TEITOK (``<TEI`` near the start of the file)."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(4096)
    except OSError:
        return False
    return b"<TEI" in head


def source_name(root) -> str:
    """The original file name a converter recorded in the TEITOK header, or ``""``."""
    notes = {}
    for el in root.iter():
        if _local(el.tag) == "note" and el.get("n") in ("source_file", "orgfile") and el.text:
            notes[el.get("n")] = el.text.strip()
    if notes.get("source_file"):
        return notes["source_file"]
    if notes.get("orgfile"):
        return Path(notes["orgfile"]).name
    for el in root.iter():
        if _local(el.tag) == "change" and el.text:
            match = _CONVERTED_FROM.search(el.text)
            if match:
                return match.group(1)
    return ""


def _ints(value, n=4):
    parts = (value or "").split()
    if len(parts) != n:
        return None
    try:
        return tuple(int(float(p)) for p in parts)
    except ValueError:
        return None


def _dimension(value) -> str:
    """``graphic@width``/``@height`` as a pixel count (``"1654"``, ``"1654px"``), else ``""``."""
    match = re.fullmatch(r"\s*(\d+)(?:\.\d+)?\s*(?:px)?\s*", value or "")
    return match.group(1) if match else ""


def _lang(el, inherited):
    return _norm_lang(el.get("lang") or el.get(_XML_LANG)) or inherited


def _is_leaf(el) -> bool:
    return not any(_local(d.tag) in BLOCK_TAGS for d in el.iter() if d is not el)


def _empty_meta():
    return {
        "source_image": "",
        "ocr_software": "",
        "ocr_version": "",
        "ocr_date": "",
        "measurement_unit": "pixel",
        "layout_source": "teitok",
        "converter": "",
        "converter_version": "",
        "orgfile": "",
        "page_labels": {},
        "page_count": 0,
    }


def parse_teitok_layout(path):
    """``(strings, pages, graphics, blocks, meta)`` of a converted TEITOK file -- the shape of
    ``teitok_alto._parse_alto()``. See the module docstring."""
    strings, pages, graphics, blocks = [], [], [], {}
    meta = _empty_meta()
    try:
        root = parse_teitok(path)
    except Exception as exc:
        print(f"  [Warn] Failed to parse TEITOK layout {path}: {exc}", file=sys.stderr)
        return strings, pages, graphics, blocks, meta

    for el in root.iter():
        if _local(el.tag) == "application" and el.get("ident") not in (
            None,
            "",
            "atrium-nlp-enrich",
        ):
            meta["converter"] = el.get("ident")
            meta["converter_version"] = el.get("version", "")
            break
    if not meta["converter"]:  # PAGE XML output has no appInfo, only the change record
        who = next((el.get("who") for el in root.iter() if _local(el.tag) == "change"), None)
        meta["converter"] = who or ""
    meta["orgfile"] = source_name(root)
    surfaces, surface_order = {}, []
    for el in root.iter():
        if _local(el.tag) == "surface":
            surface_order.append(el)
            if el.get("id"):
                surfaces[el.get("id")] = el

    text = next((el for el in root.iter() if _local(el.tag) == "text"), root)
    tokenized = any(_local(el.tag) == "tok" for el in text.iter())
    state = {"page": 0, "line": None, "line_bbox": "", "lines": 0, "blocks": 0, "pbs": 0}

    def page_idx():
        return state["page"] or 1

    def start_page(pb):
        # text before the first <pb> is page 1, so that <pb> starts page 2 (teitok_read)
        state["page"] = (state["page"] or (1 if strings else 0)) + 1
        state["line"], state["line_bbox"] = None, ""
        idx = state["page"]
        meta["page_count"] = idx
        label = (pb.get("n") or "").strip()
        if label and label != str(idx):
            meta["page_labels"][idx] = label
        corresp = (pb.get("corresp") or "").lstrip("#")
        if corresp:
            surface = surfaces.get(corresp)
        else:
            k = state["pbs"]  # no corresp: the k-th surface belongs to the k-th <pb>
            surface = surface_order[k] if k < len(surface_order) else None
        state["pbs"] += 1
        graphic = None
        if surface is not None:
            graphic = next((g for g in surface if _local(g.tag) == "graphic"), None)
        facs = (
            pb.get("facs")
            or (surface.get("facs") if surface is not None else "")
            or (graphic.get("url") if graphic is not None else "")
            or ""
        )
        width = height = ""
        size = _ints(pb.get("bbox"))
        if size:
            width, height = str(size[2]), str(size[3])
        elif surface is not None and surface.get("lrx") and surface.get("lry"):
            width, height = surface.get("lrx"), surface.get("lry")
        elif graphic is not None and graphic.get("width") and graphic.get("height"):
            width, height = _dimension(graphic.get("width")), _dimension(graphic.get("height"))
        if facs and not meta["source_image"]:
            meta["source_image"] = facs
        if facs or width:
            pages.append(
                {
                    "id": pb.get("id") or f"Page{idx}",
                    "width": width,
                    "height": height,
                    "idx": idx,
                    "ps_hpos": 0,
                    "ps_vpos": 0,
                    "ps_width": 0,
                    "ps_height": 0,
                    "facs": facs,
                }
            )

    def add_string(content, box, block_key, lang):
        entry = {
            "content": content,
            "left": box[0] if box else None,
            "top": box[1] if box else None,
            "right": box[2] if box else None,
            "bottom": box[3] if box else None,
            "page_idx": page_idx(),
            "block_id": block_key,
            "line_id": state["line"],
            "line_bbox": state["line_bbox"],
            "lang": lang,
        }
        strings.append(entry)

    def open_block(el):
        state["blocks"] += 1
        key = f"__teitok_block{state['blocks']}"
        box = _ints(el.get("bbox"))
        tag = _local(el.tag)
        blocks[key] = {
            "bbox": " ".join(map(str, box)) if box else "",
            "subtype": el.get("type") if tag == "div" else tag,
            "page_idx": page_idx(),
        }
        return key

    def visit(el, block_key, lang):
        tag = _local(el.tag)
        if tag in _SKIP_TAGS:
            return
        lang = _lang(el, lang)
        if tag == "pb":
            start_page(el)
            return
        if tag == "lb":
            state["lines"] += 1
            state["line"] = f"__teitok_line{state['lines']}"
            box = _ints(el.get("bbox"))
            state["line_bbox"] = " ".join(map(str, box)) if box else ""
            return
        if tag == "tok":
            form = _tok_form(el)
            if form:
                add_string(form, _ints(el.get("bbox")), block_key, lang)
            return
        if tag == "figure":
            box = _ints(el.get("bbox"))
            if box:
                graphics.append(
                    {
                        "type": "Illustration",
                        "id": el.get("id", ""),
                        "bbox": box,
                        "page_idx": page_idx(),
                    }
                )
        if tag in BLOCK_TAGS:
            block_key = open_block(el)
            if not tokenized and tag in _LEAF_TAGS and _is_leaf(el):
                words = _WS_RUN.sub(" ", "".join(el.itertext())).split()
                for word in words:
                    add_string(word, None, block_key, lang)
                # a page break inside the block starts the next page after it, as in
                # teitok_read's block rows (the text stream stage 1 sends to UDPipe)
                for inner in el.iter():
                    if _local(inner.tag) == "pb":
                        start_page(inner)
                return
        for child in el:
            if isinstance(child.tag, str):
                visit(child, block_key, lang)

    visit(text, None, _lang(root, None))
    return strings, pages, graphics, blocks, meta
