"""teitok_read.py -- stdlib-only reader for TEITOK XML.

Canonical copy: atrium-nlp-enrich ``api_util/teitok_read.py``. atrium-llm-enrich vendors it
verbatim (its ``tests/test_vendored_teitok_parity.py`` pins the hash) -- change it here first.

Reads any TEITOK document the ecosystem meets, following the conventions of the TEITOK
tools themselves (flexipipe, flexiconv, teitok-tools):

* **Spacing is text-faithful**: whitespace between ``</tok>`` and the next ``<tok>`` is a
  space, no whitespace means ``SpaceAfter=No``. ``join="right"`` / ``spaceAfter="No"``
  (TEI-P5 style markers, written by our own writer too) also mean "no space".
* A token's form is its text; ``<dtok>`` children (syntactic words of a multi-word token)
  never contribute text.
* ``upos`` comes from ``@upos``, else ``@pos`` (TEITOK projects often name it so) -- never
  from ``@type``, which is the word/punctuation flag.
* **Rows** (one per text line for keywords/LLM): ``<s>`` elements (``@text`` preferred);
  documents without ``<s>`` -- flexiconv output -- fall back to ``<lb/>``-delimited lines
  when they are tokenized (PAGE XML, hOCR, ALTO) and to leaf text blocks (``<p>``,
  ``<head>``, ``<item>``, ...) when they are not (txt, md, docx, pdf, html, ...).
* Legacy exports that close ``<name>`` with ``</n>`` are repaired before parsing, and
  non-numeric ``<pb n>`` labels (``n="I"``) advance the page counter instead of crashing.
"""

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# Inject project root into sys.path so the vendored, hub-canonical `atrium_document` and
# `api_util.bbox_scale` resolve when this module is reached with only api_util/ on the path
# (keywords.py and llm_utils.py both insert api_util/ before importing it).
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from api_util.bbox_scale import fix_name_close_tags  # noqa: E402
from atrium_document import canonical_doc_id  # noqa: E402

# Elements whose end is a word boundary even when no whitespace follows them.
_BOUNDARY_TAGS = frozenset(
    {"s", "p", "div", "head", "item", "cell", "row", "l", "lg", "u", "ab", "quote", "note", "pb"}
)
# Leaf text blocks used as rows for untokenized documents.
_BLOCK_TAGS = frozenset({"p", "head", "item", "cell", "l", "u", "ab", "quote"})
# Subtrees that never carry running text.
_SKIP_TAGS = frozenset({"teiHeader", "facsimile", "standOff"})
_WS = re.compile(r"\s")
_WS_RUN = re.compile(r"\s+")


def doc_id_from_path(path: str | Path) -> str:
    """Strips a known pipeline suffix (.teitok.xml, .udpipe.conllu, .conllu, ...) to produce a
    clean document ID.

    Delegates to ``atrium_document.canonical_doc_id()`` -- the one derivation the whole
    ecosystem shares (issue atrium-project#10, D3). Kept as a named wrapper because
    keywords.py, llm_utils.py, llm_client_shared.py, xml_to_md.py and the tests call it.
    """
    return canonical_doc_id(path)


def parse_teitok(path: str | Path) -> ET.Element:
    """Reads a TEITOK/TEI XML file and returns its root element.

    Repairs the known ``<name>...</n>`` mis-close quirk first (see
    ``bbox_scale.fix_name_close_tags``), so a document that is well-formed except for that
    one documented quirk does not crash ``ET`` with an unhandled ``ParseError``.
    """
    text = Path(path).read_text(encoding="utf-8")
    fixed_text, _ = fix_name_close_tags(text)
    return ET.fromstring(fixed_text)


def _local(tag) -> str:
    return tag.split("}")[-1] if isinstance(tag, str) else ""


def _scope(root: ET.Element) -> ET.Element:
    """The ``<text>`` element when present (so header titles never become rows), else root."""
    if _local(root.tag) == "text":
        return root
    for el in root.iter():
        if _local(el.tag) == "text":
            return el
    return root


def _events(el: ET.Element):
    """Yield ``(kind, value)`` in document order: ``start``/``end`` elements, ``text`` chunks,
    and ``tok`` as one atomic event (its content and ``<dtok>`` children are not walked)."""
    if _local(el.tag) == "tok":
        yield ("tok", el)
        return
    yield ("start", el)
    if el.text:
        yield ("text", el.text)
    for child in el:
        if isinstance(child.tag, str) and _local(child.tag) not in _SKIP_TAGS:
            yield from _events(child)
        if child.tail:
            yield ("text", child.tail)
    yield ("end", el)


def _tok_form(tok: ET.Element) -> str:
    """Surface form: the token's text, excluding ``<dtok>`` subtrees."""
    parts = [tok.text or ""]
    for child in tok:
        if _local(child.tag) != "dtok":
            parts.append("".join(child.itertext()))
        parts.append(child.tail or "")
    return "".join(parts).strip()


def _token_records(scope: ET.Element) -> dict:
    """Map every ``<tok>`` element in ``scope`` to its reader record, spacing resolved."""
    records = {}
    prev = None
    gap_has_ws = False
    for kind, value in _events(scope):
        if kind == "tok":
            if prev is not None and not gap_has_ws:
                records[prev]["space_after"] = False
            explicit_no_space = value.get("join") == "right" or value.get("spaceAfter") == "No"
            records[value] = {
                "form": _tok_form(value),
                "lemma": value.get("lemma", ""),
                "upos": value.get("upos") or value.get("pos") or "",
                "space_after": not explicit_no_space,
            }
            prev = value
            gap_has_ws = False
        elif kind == "text":
            if _WS.search(value):
                gap_has_ws = True
        elif _local(value.tag) in _BOUNDARY_TAGS:
            gap_has_ws = True
    return records


def _join_tokens(records: list) -> str:
    parts = []
    for rec in records:
        if not rec["form"]:
            continue
        parts.append(rec["form"])
        if rec["space_after"]:
            parts.append(" ")
    return "".join(parts).strip()


def pb_page_number(elem: ET.Element, page_num: int, first: bool) -> int:
    """Page number that starts at this ``<pb>`` (``page_num``: the current one; ``first``:
    no ``<pb>`` seen yet). Public so other TEITOK readers (llm-enrich ``xml_to_md``) number
    pages the same way.

    ``n`` is usually a plain page count, but archival front matter / appendices use roman
    numerals or other labels (``n="I"``, ``n="priloha1"``), and converters often omit it --
    those advance the counter instead of crashing; the document's first ``<pb>`` is page 1.
    """
    try:
        return int(elem.get("n"))
    except (TypeError, ValueError):
        return 1 if first else page_num + 1


def sentence_text(s_elem: ET.Element) -> str:
    """Surface text of one ``<s>``: ``@text`` when present, else its tokens with their spacing,
    else its plain text content (whitespace-normalised)."""
    text = s_elem.get("text")
    if text:
        return text
    records = _token_records(s_elem)
    if records:
        return _join_tokens(list(records.values()))
    return _WS_RUN.sub(" ", "".join(s_elem.itertext())).strip()


def _rows_from_sentences(root: ET.Element) -> list:
    rows = []
    page_num = 1
    line_num = 1
    seen_pb = False
    for elem in root.iter():
        tag = _local(elem.tag)
        if tag == "pb":
            page_num = pb_page_number(elem, page_num, first=not seen_pb)
            seen_pb = True
        elif tag == "lb":
            line_num += 1
        elif tag == "s":
            text = sentence_text(elem)
            if text:
                rows.append({"page_num": page_num, "line_num": line_num, "text": text})
    return rows


def _rows_from_lines(scope: ET.Element, records: dict) -> list:
    """Tokenized documents without ``<s>`` (flexiconv PAGE/hOCR/ALTO): one row per line."""
    rows = []
    page_num = 1
    seen_pb = False
    lines_on_page = 0
    current = []

    def flush():
        text = _join_tokens(current)
        if text:
            rows.append({"page_num": page_num, "line_num": max(1, lines_on_page), "text": text})
        current.clear()

    for kind, value in _events(scope):
        if kind == "tok":
            current.append(records[value])
        elif kind == "start" and _local(value.tag) == "pb":
            flush()
            page_num = pb_page_number(value, page_num, first=not seen_pb)
            seen_pb = True
            lines_on_page = 0
        elif kind == "start" and _local(value.tag) == "lb":
            flush()
            lines_on_page += 1
        elif kind == "end" and _local(value.tag) in _BOUNDARY_TAGS:
            flush()
    flush()
    return rows


def _rows_from_blocks(scope: ET.Element) -> list:
    """Untokenized documents (flexiconv txt/md/docx/pdf/html...): one row per leaf block."""
    rows = []
    page_num = 1
    seen_pb = False
    line_num = 0
    for elem in scope.iter():
        tag = _local(elem.tag)
        if tag == "pb":
            page_num = pb_page_number(elem, page_num, first=not seen_pb)
            seen_pb = True
            line_num = 0
        elif tag in _BLOCK_TAGS and not any(
            _local(d.tag) in _BLOCK_TAGS for d in elem.iter() if d is not elem
        ):
            text = _WS_RUN.sub(" ", "".join(elem.itertext())).strip()
            if text:
                line_num += 1
                rows.append({"page_num": page_num, "line_num": line_num, "text": text})
    return rows


def _rows(root: ET.Element) -> list:
    if any(_local(el.tag) == "s" for el in root.iter()):
        return _rows_from_sentences(root)
    scope = _scope(root)
    records = _token_records(scope)
    if records:
        return _rows_from_lines(scope, records)
    return _rows_from_blocks(scope)


def read_teitok_rows(path: str | Path) -> list[dict]:
    """
    Parses TEITOK XML.
    Returns: list of dicts [{"page_num": int, "line_num": int, "text": str}]
    """
    return _rows(parse_teitok(path))


def read_teitok_text(path: str | Path) -> str:
    """Returns the surface text as a single string."""
    rows = read_teitok_rows(path)
    return "\n".join(r["text"] for r in rows)


def read_teitok_tokens(path: str | Path) -> list[dict]:
    """
    Returns token-level annotations.
    Returns: list of dicts [{"form", "lemma", "upos", "space_after"}]

    Untokenized documents (no ``<tok>``: flexiconv's plain-text output, or ``<s text>``
    without tokens) yield the text of their rows split on whitespace, with empty
    ``lemma``/``upos`` -- enough for surface-text keyword methods (yake, keybert), not for
    the lemma-based legacy method.
    """
    root = parse_teitok(path)
    records = _token_records(_scope(root))
    if records:
        return list(records.values())
    return [
        {"form": word, "lemma": "", "upos": "", "space_after": True}
        for row in _rows(root)
        for word in row["text"].split()
    ]
