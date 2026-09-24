"""page_boxes.py -- rewrite TEITOK coordinates page by page (issue #38, C).

``POST /rescale`` and ``fix_teitok_bboxes.py`` used to scale every ``bbox`` of a document by
the size of its *first* ``<surface>`` and gave every ``<surface>`` that page's new size: fine
for one page, wrong for a document whose pages differ in size. They also let a shift push
coordinates below zero, which the next stage-4 gate then rejected, and left no trace in the
header.

This module walks the text with the regexes of ``api_util/bbox_scale.py`` (no XML parser, so
legacy exports that close ``<name>`` with ``</n>`` still work) and knows, at every ``bbox``,
which page it is on: the ``<surface>`` the last ``<pb corresp="#...">`` named, or -- for a
``<pb>`` without ``@corresp`` -- the k-th ``<surface>`` for the k-th ``<pb>`` (flexiconv's
and teitok_layout's rule). ``bbox_scale.py`` itself is untouched: atrium-llm-enrich vendors
it and pins its hash.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple
from xml.sax.saxutils import escape

from api_util.bbox_scale import BBOX_RE, LRX_RE, LRY_RE, SURFACE_RE

_ID_RE = re.compile(r'\b(?:xml:)?id\s*=\s*"([^"]*)"')
_CORRESP_RE = re.compile(r'\bcorresp\s*=\s*"#?([^"]*)"')
# <pb> tags and bbox attributes outside them, in document order
_WALK_RE = re.compile(r"<pb\b[^>]*>|" + BBOX_RE.pattern)
_REVISION_END_RE = re.compile(r"</revisionDesc\s*>")


@dataclass
class Surface:
    id: str
    width: Optional[int]
    height: Optional[int]


@dataclass
class Rewrite:
    """What a page-aware rewrite did: boxes rewritten and coordinates clamped."""

    boxes: int = 0
    clamped: int = 0
    pages: List[Dict[str, object]] = field(default_factory=list)


def _int(value) -> Optional[int]:
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def surfaces(xml_text: str) -> List[Surface]:
    """The document's ``<surface>`` elements with their ``lrx``/``lry``, in order."""
    out = []
    for tag in SURFACE_RE.findall(xml_text):
        sid = _ID_RE.search(tag)
        lrx, lry = LRX_RE.search(tag), LRY_RE.search(tag)
        out.append(
            Surface(
                id=sid.group(1) if sid else "",
                width=_int(lrx.group(2)) if lrx else None,
                height=_int(lry.group(2)) if lry else None,
            )
        )
    return out


def rewrite_page_boxes(
    xml_text: str,
    transform: Callable[[str, Optional[Surface]], Tuple[str, int]],
) -> Tuple[str, int]:
    """Rewrite every ``bbox`` with ``transform(value, surface)`` -> ``(new value, clamped)``,
    where ``surface`` is the page the box is on (None before a page with a surface).
    A ``<pb>``'s own ``bbox`` (the page extent) belongs to the page it opens. Returns the
    new text and the number of clamped coordinates."""
    by_id = {s.id: s for s in surfaces(xml_text) if s.id}
    ordered = surfaces(xml_text)
    state = {"surface": ordered[0] if ordered else None, "pbs": 0, "clamped": 0}

    def box(value):
        new, clamped = transform(value, state["surface"])
        state["clamped"] += clamped
        return f'bbox="{new}"'

    def repl(m: "re.Match[str]") -> str:
        text = m.group(0)
        if not text.startswith("<pb"):
            return box(m.group(1))
        corresp = _CORRESP_RE.search(text)
        if corresp:
            state["surface"] = by_id.get(corresp.group(1), state["surface"])
        elif state["pbs"] < len(ordered):
            state["surface"] = ordered[state["pbs"]]
        state["pbs"] += 1
        return BBOX_RE.sub(lambda b: box(b.group(1)), text)

    return _WALK_RE.sub(repl, xml_text), state["clamped"]


def set_surface_sizes(xml_text: str, size: Callable[[Surface], Tuple[int, int]]) -> str:
    """Give every ``<surface>`` with an extent the size ``size(surface)`` returns."""
    ordered = iter(surfaces(xml_text))

    def repl(m: "re.Match[str]") -> str:
        surface = next(ordered)
        if surface.width is None or surface.height is None:
            return m.group(0)
        w, h = size(surface)
        tag = LRX_RE.sub(rf"\g<1>{w}\g<3>", m.group(0))
        return LRY_RE.sub(rf"\g<1>{h}\g<3>", tag)

    return SURFACE_RE.sub(repl, xml_text)


def clamp_box(value: str, width: Optional[int], height: Optional[int]) -> Tuple[str, int]:
    """Clamp ``"x1 y1 x2 y2"`` to ``[0, width] x [0, height]`` (no upper bound when the
    extent is unknown). Returns the box and how many coordinates moved."""
    parts = value.split()
    if len(parts) != 4:
        return value, 0
    try:
        nums = [int(round(float(p))) for p in parts]
    except ValueError:
        return value, 0
    limits = [width, height, width, height]
    moved = 0
    for i, n in enumerate(nums):
        c = max(n, 0)
        if limits[i] is not None:
            c = min(c, limits[i])
        moved += c != n
        nums[i] = c
    return " ".join(map(str, nums)), moved


def add_change(xml_text: str, change_type: str, text: str, who: str = "atrium-nlp-enrich") -> str:
    """Append ``<change when who type>text</change>`` to ``<revisionDesc>`` (the TEITOK
    record of what happened to a document); unchanged when there is none."""
    today = datetime.date.today().isoformat()
    entry = (
        f'  <change when="{today}" who="{escape(who)}" type="{escape(change_type)}">'
        f"{escape(text)}</change>\n    "
    )
    return _REVISION_END_RE.sub(lambda m: entry + m.group(0), xml_text, count=1)
