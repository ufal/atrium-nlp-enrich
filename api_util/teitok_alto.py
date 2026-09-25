"""teitok_alto.py — Produce TEITOK XML from a NER-enriched CoNLL-U + ALTO file.

The output follows the conventions the TEITOK tools themselves read and write (flexipipe,
flexiconv, teitok-tools, xmltokenizer). ``appInfo`` stamps it as ``teitok-2``, and
``schemas/teitok/README.md`` describes the format:

* **Namespace-off root**: ``<TEI xmlnsoff="http://www.tei-c.org/ns/1.0">`` and plain ``@id``.
* **Text-faithful spacing**: whitespace between ``</tok>`` and the next ``<tok>`` is a space;
  no whitespace means ``SpaceAfter=No`` (also across ``<lb/>`` and ``</name>``; the trailing
  space of an entity sits inside its ``</name>``). ``join="right"`` is kept as the TEI-P5
  style marker that the ATRIUM readers and the XSD already know.
* **Multi-word tokens**: ``<tok>abych<dtok form="aby" …/><dtok form="bych" …/></tok>``. The
  surface token carries the text and the bbox; the ``<dtok>`` children carry the syntactic
  words (lemma, upos, head, …).
* **Ids** are TEITOK-native and assigned once, in ``parse_and_align_conllu()``, so the
  writer and ``document_hook.py`` can never disagree: ``w-N`` (surface token,
  document-global), ``w-N.K`` (``dtok``), ``s-N``, ``n-N`` (``<name>``), ``facs-P``
  (``<surface>``), ``pb-P``, ``lb-P.L``, ``b-P.K`` (``<div>``) and ``fig-P.K``.
  ``@head`` is the head word's id, and ``@ord`` its sentence-local index.
* **Entities**: ``<name id type sameAs>`` with coarse ``@type`` PER/ORG/LOC/MISC
  (``ner_types.py``) and the raw NameTag label in ``@cnec``, ``@onto`` or ``@archaeo``.
* **Coordinates**: ``bbox="x1 y1 x2 y2"`` in page-image pixels with the page's top-left
  corner as origin (``bbox_origin="page"``, the TEITOK norm), or relative to the ALTO
  PrintSpace (``bbox_origin="printspace"``, for page images cropped to the print area).
  ``<surface lrx lry>`` always describes the coordinate space the bboxes use.
* **Language**: ``@lang`` on ``<TEI>`` and ``profileDesc/langUsage`` come from the ALTO
  ``LANG`` attributes (majority), else from the UDPipe model name, else they are omitted.
* **Pages** are layout-first (issue #38): a token is on the page of the layout string it
  aligned to, else on the page of its line in stage 1's rows file (``page_rows.py``; for a
  document without a layout the rows *are* its layout -- ``<pb>`` and ``<lb>`` without
  coordinates), else on the page of the token before it. ``<pb/>`` may come inside ``<s>``
  and ``<name>`` when a sentence or an entity runs over a page break (the anchor
  xmltokenizer and flexiconv allow there); pages only move forward; ``pb@n`` is the page
  label; ``pb@facs``/``@corresp``/``@bbox="0 0 W H"`` only for a page with a ``<surface>``.
  UDPipe chunk starts (``# chunk_start``, formerly ``# page_break = true``) are never pages.
* **Split-off punctuation** that shares a layout string with a word has no bbox of its own
  (flexiconv's ALTO and hOCR import do the same); the word keeps the string's box.
* **Layout source**: ``alto_path`` is an ALTO file, or a TEITOK file converted by flexiconv
  (``api_flexiconv.sh``, ``FLEXICONV_ANNOTATE=true``). The latter is read by
  ``api_util/teitok_layout.py`` into the same structures: its ``<pb facs>``, ``<lb bbox>``,
  ``<tok bbox>`` and text blocks take the place of ALTO pages, lines, strings and blocks, and
  the header names flexiconv and the original document.
"""

import bisect
import collections
import datetime
import difflib
import re
import struct
import sys
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape

from api_util import page_rows as _page_rows
from api_util.bbox_scale import dpi_scale, scale_bbox_coords
from api_util.ner_types import CNEC_TO_CONLL, TAGSET_ATTRIBUTE, coarse_type, tagset
from atrium_document import canonical_doc_id

# The authority the hub's atrium_vocab.CNEC_TO_ENTITY_TYPE names
# ("atrium-nlp-enrich/api_util/teitok_alto.py _CNEC_TO_CONLL"). The map itself lives in
# ner_types.py next to the OntoNotes and archaeological maps; this is the same object.
_CNEC_TO_CONLL = CNEC_TO_CONLL

#: Format stamp written to ``appInfo`` (``<application ident="atrium-nlp-enrich">``).
#: Bump it whenever the shape of the output changes in a way readers can notice.
WRITER_FORMAT = "teitok-2"
BBOX_ORIGINS = ("page", "printspace")

_IMAGE_EXTS = (".png", ".PNG", ".jpg", ".JPG", ".jpeg", ".JPEG", ".tiff", ".TIFF", ".tif", ".TIF")

# UDPipe model-name prefix / ALTO language name → ISO 639-1.
_LANG_NAMES = {
    "czech": "cs",
    "slovak": "sk",
    "english": "en",
    "german": "de",
    "polish": "pl",
    "french": "fr",
    "italian": "it",
    "spanish": "es",
    "russian": "ru",
    "ukrainian": "uk",
    "hungarian": "hu",
    "slovenian": "sl",
    "croatian": "hr",
    "serbian": "sr",
    "dutch": "nl",
    "latin": "la",
}
_LANG_ISO3 = {
    "ces": "cs",
    "cze": "cs",
    "slk": "sk",
    "slo": "sk",
    "eng": "en",
    "deu": "de",
    "ger": "de",
    "pol": "pl",
    "fra": "fr",
    "fre": "fr",
    "lat": "la",
}


# Local wrapper to avoid rewriting complex formatting clusters in the loop
def _scale_bbox_str(x1, y1, x2, y2, sx, sy, dx=0, dy=0):
    return scale_bbox_coords(f"{x1} {y1} {x2} {y2}", sx, sy, dx, dy)


def _scale_bbox_tuple(bbox_tuple, sx, sy, dx=0, dy=0):
    x1, y1, x2, y2 = bbox_tuple
    return scale_bbox_coords(f"{x1} {y1} {x2} {y2}", sx, sy, dx, dy)


def _build_page_scale_map(
    alto_pages,
    image_dir,
    doc_id,
    measurement_unit="pixel",
    dpi=None,
    alto_dpi=None,
    bbox_origin="page",
):
    """Per page: ``(sx, sy, surface_w, surface_h, dx, dy, image_ext)``.

    ``bbox_origin="page"``: no shift, and the reference extent is the ALTO Page.
    ``bbox_origin="printspace"``: shift by PrintSpace HPOS/VPOS, and the reference extent
    is the PrintSpace. This mode is for page images cropped to the print area, so tier 1
    also divides by the PrintSpace size. Pages without a PrintSpace fall back to "page".
    Tier 1 = companion image, tier 2 = ``dpi`` (via ``bbox_scale.dpi_scale``), tier 3 =
    raw ALTO units.

    Two silent fall-backs are reported on stderr, once per document, because they break
    the overlay on the page image without breaking the file (issue #38, pitfalls R1/R2): an
    image folder with no ``{doc_id}-{N}.<ext>`` for a page (its boxes stay unscaled and its
    ``facs`` name is a guess), and tier 3 with a ``MeasurementUnit`` other than pixels.
    """
    printspace = bbox_origin == "printspace"
    scale_map = {}
    missing_images, unreadable_images, raw_unit_pages = [], [], []
    for pg in alto_pages:
        idx = pg["idx"]
        try:
            page_w = float(pg.get("width") or 0)
            page_h = float(pg.get("height") or 0)
        except (ValueError, TypeError):
            page_w = page_h = 0.0
        ps_w = float(pg.get("ps_width") or 0)
        ps_h = float(pg.get("ps_height") or 0)
        if printspace and ps_w > 0 and ps_h > 0:
            ref_w, ref_h = ps_w, ps_h
            dx, dy = pg.get("ps_hpos", 0), pg.get("ps_vpos", 0)
        else:
            ref_w, ref_h = page_w, page_h
            dx = dy = 0

        img_dims = None
        img_ext = ".png"  # Default fallback

        img_path = _find_page_image(image_dir, doc_id, idx, pg.get("facs"))
        if img_path:
            img_dims = _read_image_dimensions(img_path)
            img_ext = img_path.suffix  # Dynamically capture extension
            if not img_dims:
                unreadable_images.append(img_path.name)
        elif image_dir:
            missing_images.append(idx)

        # Tier 1: Companion image present
        if img_dims and ref_w > 0 and ref_h > 0:
            sx = img_dims[0] / ref_w
            sy = img_dims[1] / ref_h
            scale_map[idx] = (sx, sy, img_dims[0], img_dims[1], dx, dy, img_ext)

        # Tier 1b: an image but no page size (a converted TEITOK layout source whose
        # coordinates are already image pixels): scale 1, surface = the image
        elif img_dims:
            scale_map[idx] = (1.0, 1.0, img_dims[0], img_dims[1], dx, dy, img_ext)

        # Tier 2: User-set DPI -> math delegated to bbox_scale
        elif dpi and ref_w > 0 and ref_h > 0:
            sx, sy = dpi_scale(measurement_unit, dpi, alto_dpi)
            scale_map[idx] = (sx, sy, round(ref_w * sx), round(ref_h * sy), dx, dy, img_ext)

        # Tier 3: Fallback
        else:
            if (measurement_unit or "pixel").lower() != "pixel":
                raw_unit_pages.append(idx)
            scale_map[idx] = (
                1.0,
                1.0,
                int(ref_w) if ref_w else None,
                int(ref_h) if ref_h else None,
                dx,
                dy,
                img_ext,
            )
    if missing_images:
        shown = ", ".join(str(i) for i in missing_images[:5])
        if len(missing_images) > 5:
            shown += f" (+{len(missing_images) - 5} more)"
        print(
            f"  [Warn] {doc_id}: no page image in {image_dir} for page(s) {shown} (looked for "
            f"{doc_id}-<N> with {', '.join(sorted({e.lower() for e in _IMAGE_EXTS}))}); those "
            "pages keep unscaled layout coordinates and a guessed .png facs name",
            file=sys.stderr,
        )
    if unreadable_images:
        print(
            f"  [Warn] {doc_id}: cannot read the pixel size of {', '.join(unreadable_images[:5])}"
            " (PNG, JPEG and TIFF are read); those pages keep unscaled layout coordinates",
            file=sys.stderr,
        )
    if raw_unit_pages:
        print(
            f"  [Warn] {doc_id}: ALTO MeasurementUnit is {measurement_unit} and there is no page "
            "image or IMAGE_DPI, so bboxes stay in ALTO units, not image pixels (set "
            "INPUT_PAGES_DIR or IMAGE_DPI)",
            file=sys.stderr,
        )
    return scale_map


def _attr(value: str) -> str:
    return escape(value, {'"': "&quot;"})


def _unit_per_inch(unit):
    return {"inch1200": 1200, "mm10": 254}.get(unit, None)


def _read_image_dimensions(path):
    path = Path(path)
    if not path.exists():
        return None
    try:
        with open(path, "rb") as fh:
            header = fh.read(26)
            if header[:8] == b"\x89PNG\r\n\x1a\n":
                w = struct.unpack(">I", header[16:20])[0]
                h = struct.unpack(">I", header[20:24])[0]
                return (w, h)
            if header[:2] == b"\xff\xd8":
                fh.seek(2)
                while True:
                    marker = fh.read(2)
                    if len(marker) < 2:
                        break
                    if marker[0] != 0xFF:
                        break
                    seg_len = struct.unpack(">H", fh.read(2))[0]
                    if marker[1] in (
                        0xC0,
                        0xC1,
                        0xC2,
                        0xC3,
                        0xC5,
                        0xC6,
                        0xC7,
                        0xC9,
                        0xCA,
                        0xCB,
                        0xCD,
                        0xCE,
                        0xCF,
                    ):
                        fh.read(1)
                        h = struct.unpack(">H", fh.read(2))[0]
                        w = struct.unpack(">H", fh.read(2))[0]
                        return (w, h)
                    fh.read(seg_len - 2)
                return None
            if header[:2] in (b"II", b"MM"):
                endian = "<" if header[:2] == b"II" else ">"
                fh.seek(4)
                ifd_offset = struct.unpack(endian + "I", fh.read(4))[0]
                fh.seek(ifd_offset)
                num_entries = struct.unpack(endian + "H", fh.read(2))[0]
                w = h = None
                for _ in range(num_entries):
                    tag = struct.unpack(endian + "H", fh.read(2))[0]
                    typ = struct.unpack(endian + "H", fh.read(2))[0]
                    fh.read(4)
                    val_bytes = fh.read(4)
                    fmt = endian + ("H" if typ == 3 else "I")
                    val = struct.unpack(fmt, val_bytes[: struct.calcsize(fmt)])[0]
                    if tag == 256:
                        w = val
                    elif tag == 257:
                        h = val
                    if w is not None and h is not None:
                        return (w, h)
        return None
    except Exception:
        return None


def _find_page_image(image_dir, doc_id, page_idx, facs=None):
    """``{doc_id}-{N}.<ext>`` in ``image_dir``; for a layout source that names its page image
    (``<pb facs>``), that file (as given, or its base name) first."""
    if not image_dir:
        return None
    base = Path(image_dir)
    if facs:
        for candidate in (base / facs, base / Path(facs).name):
            if candidate.is_file():
                return candidate
    for ext in _IMAGE_EXTS:
        candidate = base / f"{doc_id}-{page_idx}{ext}"
        if candidate.exists():
            return candidate
    return None


def _norm_lang(value):
    """ISO 639-1 code for an ALTO ``LANG`` value or a UDPipe model name, else None."""
    if not value:
        return None
    v = value.strip().lower()
    if v in _LANG_NAMES:
        return _LANG_NAMES[v]
    base = re.split(r"[-_]", v)[0]
    if base in _LANG_NAMES:
        return _LANG_NAMES[base]
    if base in _LANG_ISO3:
        return _LANG_ISO3[base]
    if len(base) == 2 and base.isalpha():
        return base
    return None


def _majority_lang(strings):
    counts = collections.Counter(s["lang"] for s in strings if s.get("lang"))
    return counts.most_common(1)[0][0] if counts else None


def _box(el):
    """``(hpos, vpos, hpos+width, vpos+height)`` as ints, or None."""
    try:
        h = float(el.get("HPOS", 0) or 0)
        v = float(el.get("VPOS", 0) or 0)
        w = float(el.get("WIDTH", 0) or 0)
        e = float(el.get("HEIGHT", 0) or 0)
    except (ValueError, TypeError):
        return None
    return (int(h), int(v), int(h + w), int(v + e))


def _parse_alto(alto_path):
    alto_strings = []
    alto_pages = []
    alto_graphics = []
    alto_blocks = {}
    alto_meta = {
        "source_image": "",
        "ocr_software": "",
        "ocr_version": "",
        "ocr_date": "",
        "measurement_unit": "pixel",
    }

    if not (alto_path and Path(alto_path).exists()):
        return alto_strings, alto_pages, alto_graphics, alto_blocks, alto_meta

    try:
        tree = ET.parse(alto_path)
        root = tree.getroot()
        ns_uri = ""
        if root.tag.startswith("{"):
            ns_uri = root.tag[1 : root.tag.index("}")]
        if root.tag.split("}")[-1] == "TEI":
            # A flexiconv TEITOK file (api_flexiconv.sh) stands in for ALTO: same result
            # shape, its own <pb>/<lb>/<tok bbox> geometry (FLEXICONV_ANNOTATE).
            from api_util.teitok_layout import parse_teitok_layout

            return parse_teitok_layout(alto_path)
        if root.tag.split("}")[-1].lower() != "alto":
            # PAGE XML / hOCR share element names (Page, TextLine) but not ALTO's
            # attributes; they enter the pipeline through flexiconv (api_flexiconv.sh).
            print(
                f"  [Warn] {alto_path} is not ALTO (root <{root.tag.split('}')[-1]}>); "
                "ignoring it -- convert PAGE XML / hOCR with api_flexiconv.sh",
                file=sys.stderr,
            )
            return alto_strings, alto_pages, alto_graphics, alto_blocks, alto_meta

        def _tag(local):
            return f"{{{ns_uri}}}{local}" if ns_uri else local

        for desc in root.iter(_tag("Description")):
            for img_info in desc.iter(_tag("fileName")):
                if img_info.text:
                    alto_meta["source_image"] = img_info.text.strip()
            for mu in desc.iter(_tag("MeasurementUnit")):
                if mu.text:
                    alto_meta["measurement_unit"] = mu.text.strip()
            for ocr in desc.iter(_tag("ocrProcessingStep")):
                for dt in ocr.iter(_tag("processingDateTime")):
                    if dt.text:
                        alto_meta["ocr_date"] = dt.text.strip()
                for sw in ocr.iter(_tag("softwareName")):
                    if sw.text:
                        alto_meta["ocr_software"] = sw.text.strip()
                for swv in ocr.iter(_tag("softwareVersion")):
                    if swv.text:
                        alto_meta["ocr_version"] = swv.text.strip()

        # ALTO <Tags>: TAGREFS on a TextBlock name layout/structure tags; their LABEL
        # becomes the TEITOK <div subtype>.
        tag_labels = {}
        for tags in root.iter(_tag("Tags")):
            for tag_el in tags:
                if tag_el.get("ID") and tag_el.get("LABEL"):
                    tag_labels[tag_el.get("ID")] = tag_el.get("LABEL")

        for page_idx, page in enumerate(root.iter(_tag("Page")), start=1):
            page_w_str = page.get("WIDTH", "") or ""
            page_h_str = page.get("HEIGHT", "") or ""
            ps_hpos = ps_vpos = ps_w = ps_h = 0
            for ps in page.iter(_tag("PrintSpace")):
                try:
                    ps_hpos = int(float(ps.get("HPOS", 0) or 0))
                    ps_vpos = int(float(ps.get("VPOS", 0) or 0))
                    ps_w = int(float(ps.get("WIDTH", 0) or 0))
                    ps_h = int(float(ps.get("HEIGHT", 0) or 0))
                except (ValueError, TypeError):
                    pass
                break
            alto_pages.append(
                {
                    "id": page.get("ID", f"Page{page_idx}"),
                    "width": page_w_str,
                    "height": page_h_str,
                    "idx": page_idx,
                    "ps_hpos": ps_hpos,
                    "ps_vpos": ps_vpos,
                    "ps_width": ps_w,
                    "ps_height": ps_h,
                }
            )
            for block_seq, block in enumerate(page.iter(_tag("TextBlock")), start=1):
                # ALTO ids are optional; a synthetic key keeps unnamed blocks and lines
                # apart (they used to collapse into one block / one line per page).
                block_id = block.get("ID") or f"__block{page_idx}.{block_seq}"
                block_lang = _norm_lang(block.get("LANG"))
                subtype = next(
                    (
                        tag_labels[r]
                        for r in (block.get("TAGREFS") or "").split()
                        if r in tag_labels
                    ),
                    None,
                )
                bbox = _box(block)
                alto_blocks[block_id] = {
                    "bbox": " ".join(map(str, bbox)) if bbox else "",
                    "subtype": subtype,
                    "page_idx": page_idx,
                }
                for line_seq, line in enumerate(block.iter(_tag("TextLine")), start=1):
                    line_id = line.get("ID") or f"__line{page_idx}.{block_seq}.{line_seq}"
                    line_lang = _norm_lang(line.get("LANG")) or block_lang
                    lbox = _box(line)
                    line_bbox = " ".join(map(str, lbox)) if lbox else ""
                    for string in line.iter(_tag("String")):
                        content = string.get("CONTENT", "")
                        if not content:
                            continue
                        sbox = _box(string)
                        if sbox is None:
                            continue
                        alto_strings.append(
                            {
                                "content": content,
                                "left": sbox[0],
                                "top": sbox[1],
                                "right": sbox[2],
                                "bottom": sbox[3],
                                "page_idx": page_idx,
                                "block_id": block_id,
                                "line_id": line_id,
                                "line_bbox": line_bbox,
                                "lang": _norm_lang(string.get("LANG")) or line_lang,
                            }
                        )
            for gtag in ("Illustration", "GraphicalElement"):
                for graphic in page.iter(_tag(gtag)):
                    gbox = _box(graphic)
                    if gbox is None:
                        continue
                    alto_graphics.append(
                        {
                            "type": gtag,
                            "id": graphic.get("ID", ""),
                            "bbox": gbox,
                            "page_idx": page_idx,
                        }
                    )
    except Exception as exc:
        print(f"  [Warn] Failed to parse ALTO {alto_path}: {exc}", file=sys.stderr)
    return alto_strings, alto_pages, alto_graphics, alto_blocks, alto_meta


def _align_tokens_to_alto(tokens, alto_strings):
    if not alto_strings or not tokens:
        return [None] * len(tokens)

    def norm(s):
        return unicodedata.normalize("NFC", s).lower()

    alto_char_list = []
    alto_char_to_idx = []
    for idx, s in enumerate(alto_strings):
        for ch in norm(s["content"]):
            if ch.strip():
                alto_char_list.append(ch)
                alto_char_to_idx.append(idx)

    CHUNK_SIZE = 5000
    bboxes = [None] * len(tokens)
    tok_char_list = []
    tok_char_to_tok_idx = []
    for t_idx, tok in enumerate(tokens):
        for ch in norm(tok.get("form", "")):
            if ch.strip():
                tok_char_list.append(ch)
                tok_char_to_tok_idx.append(t_idx)

    tok_str = "".join(tok_char_list)
    alto_str = "".join(alto_char_list)
    tok_to_alto_indices = collections.defaultdict(list)

    for i in range(0, len(tok_str), CHUNK_SIZE):
        tok_chunk = tok_str[i : i + CHUNK_SIZE]
        window_start = max(0, i - 1000)
        window_end = min(len(alto_str), i + CHUNK_SIZE + 1000)
        alto_chunk = alto_str[window_start:window_end]
        sm = difflib.SequenceMatcher(None, tok_chunk, alto_chunk, autojunk=False)
        for block in sm.get_matching_blocks():
            i_chunk, j_chunk, n = block
            for k in range(n):
                global_t_idx = i + i_chunk + k
                global_a_idx = window_start + j_chunk + k
                if global_t_idx < len(tok_char_to_tok_idx) and global_a_idx < len(alto_char_to_idx):
                    t_idx = tok_char_to_tok_idx[global_t_idx]
                    a_idx = alto_char_to_idx[global_a_idx]
                    tok_to_alto_indices[t_idx].append(a_idx)

    for t_idx in range(len(tokens)):
        a_indices = tok_to_alto_indices.get(t_idx)
        if not a_indices:
            continue
        first_a = alto_strings[a_indices[0]]
        page_indices = set(alto_strings[a]["page_idx"] for a in a_indices)
        if len(page_indices) > 1:
            form = tokens[t_idx].get("form", "?")
            print(
                f"  [Warn] Token '{form}' spans pages {sorted(page_indices)}; "
                "using first matched page for bbox assignment.",
                file=sys.stderr,
            )
        # A layout source may carry strings without coordinates (untokenized text, or
        # punctuation flexiconv did not box): they still place the token on its page,
        # block and line; the box comes from the matched strings that have one.
        boxed = [alto_strings[a] for a in a_indices if alto_strings[a].get("left") is not None]
        bboxes[t_idx] = {
            "strings": frozenset(a_indices),
            "left": min(s["left"] for s in boxed) if boxed else None,
            "top": min(s["top"] for s in boxed) if boxed else None,
            "right": max(s["right"] for s in boxed) if boxed else None,
            "bottom": max(s["bottom"] for s in boxed) if boxed else None,
            "page_idx": first_a["page_idx"],
            "block_id": first_a["block_id"],
            "line_id": first_a["line_id"],
            "line_bbox": first_a["line_bbox"],
        }
    return bboxes


#: Below this share of tokens aligned to a layout source, the writer warns: text and layout
#: probably come from different readers (e.g. alto-postprocess ``text-lines`` and flexiconv).
MIN_ALIGNMENT = 0.9


def _monotone_keep(values):
    """Positions of a longest non-decreasing subsequence of ``values``."""
    tails, tails_pos, prev = [], [], [-1] * len(values)
    for i, v in enumerate(values):
        k = bisect.bisect_right(tails, v)
        if k == len(tails):
            tails.append(v)
            tails_pos.append(i)
        else:
            tails[k] = v
            tails_pos[k] = i
        prev[i] = tails_pos[k - 1] if k else -1
    keep, i = set(), tails_pos[-1] if tails_pos else -1
    while i != -1:
        keep.add(i)
        i = prev[i]
    return keep


def _row_box(place):
    """A coordinate-free box for a unit placed by the rows file (a table-only document):
    its page and line, no coordinates -- the *rows layout*."""
    return {
        "left": None,
        "top": None,
        "right": None,
        "bottom": None,
        "page_idx": place.page,
        "block_id": None,
        "line_id": f"__row{place.row}",
        "line_bbox": "",
    }


def _resolve_pages(sentences, units, boxes, layout_pages, has_layout, rows, doc_id):
    """Give every surface unit its page, ``_page`` -- layout first (issue #38, A):

    1. the page of the layout string it aligned to;
    2. else its line in the rows file (stage 1's ``<doc>.rows.tsv``): without a layout, the
       rows *are* the layout (page and line, no coordinates); with one, a row page counts
       only when the layout has that page, and never beyond the next aligned token's page;
    3. else the page of the unit before it -- or, for a document with neither a layout nor
       rows, the old per-page convention (``# sent_id = 1`` restarting), as NameTag's page
       files and the summary read it (``page_rows.legacy_sentence_pages``).

    Pages only move forward. Aligned pages that break that order are outliers (the longest
    non-decreasing run of aligned pages is kept): such a unit loses its box, which belongs to
    another page. Returns the number of outliers."""
    places = _page_rows.place_units(sentences, rows, doc_id)[0] if rows else [None] * len(units)
    aligned = [i for i, b in enumerate(boxes) if b is not None and b.get("page_idx") is not None]
    keep = {aligned[j] for j in _monotone_keep([boxes[i]["page_idx"] for i in aligned])}
    outliers = len(aligned) - len(keep)
    next_kept = [None] * len(units)
    upcoming = None
    for i in range(len(units) - 1, -1, -1):
        if i in keep:
            upcoming = boxes[i]["page_idx"]
        next_kept[i] = upcoming
    legacy = []
    if not rows and not has_layout:
        for sent, sent_page in zip(
            sentences, _page_rows.legacy_sentence_pages(sentences), strict=True
        ):
            legacy += [sent_page] * len(sent["surface"])
    page = 0
    for i, unit in enumerate(units):
        box, place = boxes[i], places[i]
        if box is not None and box.get("page_idx") is not None and i not in keep:
            box = None
        if box is None and place is not None and not has_layout:
            box = _row_box(place)
        if box is not None and box.get("page_idx") is not None:
            candidate = box["page_idx"]
        elif place is not None and (not has_layout or place.page in layout_pages):
            candidate = place.page
            if next_kept[i] is not None:
                candidate = min(candidate, next_kept[i])
        elif legacy:
            candidate = legacy[i]
        else:
            candidate = page or 1
        page = max(page, candidate)
        unit["_bbox"] = box
        unit["_page"] = page
        for word in unit["words"]:
            word["_bbox"] = box
            word["_page_idx"] = page
    return outliers


def _unbox_split_punctuation(units):
    """Split-off punctuation that shares a layout string with a word gets no bbox (U1): the
    word keeps the string's box, as flexiconv does for ALTO and hOCR (``alto.py``,
    ``hocr.py``). The punctuation keeps its page and line."""
    for i, unit in enumerate(units):
        box = unit.get("_bbox")
        if not has_coords(box) or not box.get("strings"):
            continue
        if not all(w.get("upos") == "PUNCT" for w in unit["words"]):
            continue
        for j in (i - 1, i + 1):
            if not 0 <= j < len(units):
                continue
            other = units[j].get("_bbox")
            if (
                other
                and other.get("strings")
                and not all(w.get("upos") == "PUNCT" for w in units[j]["words"])
                and box["strings"] & other["strings"]
            ):
                unboxed = dict(box, left=None, top=None, right=None, bottom=None)
                unit["_bbox"] = unboxed
                for word in unit["words"]:
                    word["_bbox"] = unboxed
                break


def _bio_to_code(ner_tag):
    if not ner_tag or ner_tag in ("O", "_"):
        return ""
    primary = ner_tag.split("|")[0]
    return primary[2:] if primary.startswith(("B-", "I-")) else ""


def _group_ner_spans(tokens):
    groups = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        ner = tok.get("ner", "")
        if ner and ner not in ("O", "_") and ner.startswith("B-"):
            span = [tok]
            i += 1
            while i < len(tokens):
                nxt = tokens[i].get("ner", "")
                if nxt and nxt.startswith("I-"):
                    span.append(tokens[i])
                    i += 1
                else:
                    break
            groups.append({"kind": "name", "tokens": span, "code": _bio_to_code(ner)})
        else:
            groups.append({"kind": "plain", "tokens": [tok]})
            i += 1
    return groups


def _unit_bio(unit):
    """``("B"|"I"|"O", code)`` for a surface token: B when any of its words begins an
    entity, I when one continues one (entity spans are widened to whole surface tokens)."""
    tags = [(w.get("ner") or "").split("|")[0] for w in unit["words"]]
    for tag in tags:
        if tag.startswith("B-"):
            return "B", tag[2:]
    for tag in tags:
        if tag.startswith("I-"):
            return "I", tag[2:]
    return "O", ""


def _group_surface_spans(units):
    """Entity spans over one sentence's surface tokens (same B/I rule as ``_group_ner_spans``)."""
    groups = []
    for unit in units:
        bio, code = _unit_bio(unit)
        if bio == "B":
            groups.append({"kind": "name", "units": [unit], "code": code})
        elif bio == "I" and groups and groups[-1]["kind"] == "name":
            groups[-1]["units"].append(unit)
        else:
            groups.append({"kind": "plain", "units": [unit]})
    return groups


def _parse_misc(misc_str):
    if misc_str == "_" or not misc_str:
        return {}
    misc = {}
    for item in misc_str.split("|"):
        if "=" in item:
            k, v = item.split("=", 1)
            misc[k] = v
        else:
            misc[item] = "Yes"
    return misc


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _assign_ids(sentences):
    """Assign every TEITOK id once, on the parsed dicts: ``_xml_id`` on sentences, surface
    tokens and words, ``names`` (entity groups with ``_xml_id``) on sentences, and
    ``_name_id`` on every word inside an entity."""
    w_count = s_count = n_count = 0
    for sent in sentences:
        s_count += 1
        sent["_xml_id"] = f"s-{s_count}"
        for unit in sent["surface"]:
            w_count += 1
            unit["_xml_id"] = f"w-{w_count}"
            if unit["mwt"]:
                for k, word in enumerate(unit["words"], start=1):
                    word["_xml_id"] = f"w-{w_count}.{k}"
            else:
                unit["words"][0]["_xml_id"] = unit["_xml_id"]
        sent["names"] = _group_surface_spans(sent["surface"])
        for grp in sent["names"]:
            if grp["kind"] != "name":
                continue
            n_count += 1
            grp["_xml_id"] = f"n-{n_count}"
            for unit in grp["units"]:
                for word in unit["words"]:
                    word["_name_id"] = grp["_xml_id"]


def parse_and_align_conllu(
    conllu_path,
    alto_path=None,
    doc_id=None,
    image_dir=None,
    dpi=None,
    alto_dpi=None,
    bbox_origin="page",
    rows=None,
):
    """Parse a NER-merged CoNLL-U file and align its tokens to ALTO bboxes.

    Single source of truth for the parse+align step so both the TEITOK XML
    writer (``write_teitok_merged``) and any downstream consumer that needs
    the same token/bbox data (e.g. building the ``entities``/``pages``
    blocks of the paired ``atrium_document`` record, see
    ``api_util/document_hook.py``) read the CoNLL-U + ALTO pair exactly once
    and agree on the same token→bbox alignment and the same TEITOK ids.
    Returns ``None`` when the CoNLL-U file cannot be read.

    Each sentence has ``tokens`` (syntactic words; the hook's contract) and ``surface``
    (surface tokens: a plain word, or a multi-word token ``{"form", "space_after",
    "words": [...], "mwt": True}`` built from a CoNLL-U range line). ALTO alignment runs
    on surface forms, because that is the text the page shows. Words inherit their
    surface token's ``_bbox`` and point back to it through ``_surface``.

    ``rows`` (``page_rows.Row`` list, stage 1's ``<doc>.rows.tsv``) says which line and page
    each token came from. Every surface token and word gets ``_page`` (see
    ``_resolve_pages``); a document without a layout source takes lines and pages from the
    rows (words carry it as ``_page_idx``). ``page_order`` lists every page the document has (layout pages, row pages, token
    pages), ``page_labels`` the ``pb@n`` of pages whose label is not their number.
    """
    alto_strings, alto_pages, alto_graphics, alto_blocks, alto_meta = _parse_alto(alto_path)

    # canonical_doc_id() for the fallback, not Path.stem (issue atrium-project#10, D3):
    # _doc_id ends up in the TEITOK <title> and in the graphic file names the facsimile
    # points to, so "X.udpipe" from an X.udpipe.conllu input would point at a document
    # nothing else in the pipeline calls by that name.
    _doc_id = doc_id or canonical_doc_id(conllu_path)
    if not alto_strings:
        print(
            f"  [TEITOK] No ALTO input for {_doc_id}; producing text-only XML without bboxes.",
            file=sys.stderr,
        )

    effective_image_dir = image_dir
    if not effective_image_dir and alto_path:
        candidate = Path(alto_path).parent
        if any(candidate.glob("*.png")) or any(candidate.glob("*.jpg")):
            effective_image_dir = candidate

    scale_map = _build_page_scale_map(
        alto_pages,
        effective_image_dir,
        _doc_id,
        measurement_unit=alto_meta.get("measurement_unit", "pixel"),
        dpi=dpi,
        alto_dpi=alto_dpi,
        bbox_origin=bbox_origin,
    )

    sentences = []
    current_tok = []
    current_units = []
    open_mwt = None
    sent_id = sent_text = None
    conllu_meta = {}
    pending_chunk_start = False

    def _flush():
        nonlocal current_tok, current_units, pending_chunk_start, open_mwt
        if current_tok:
            sentences.append(
                {
                    "id": sent_id,
                    "text": sent_text,
                    "tokens": current_tok,
                    "surface": [u for u in current_units if u["words"]],
                    # a UDPipe chunk starts here: a line boundary, never a page (#38, A)
                    "chunk_start": pending_chunk_start,
                }
            )
            current_tok = []
            current_units = []
            pending_chunk_start = False
        open_mwt = None

    try:
        with open(conllu_path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.rstrip("\n")
                if line.startswith("# generator ="):
                    conllu_meta["generator"] = line.split("=", 1)[1].strip()
                if line.startswith("# udpipe_model ="):
                    conllu_meta["udpipe_model"] = line.split("=", 1)[1].strip()
                if line.startswith("# udpipe_model_licence ="):
                    conllu_meta["udpipe_model_licence"] = line.split("=", 1)[1].strip()
                if line.strip().startswith(_page_rows.CHUNK_MARKERS):
                    pending_chunk_start = True
                    continue
                if line.startswith("# sent_id"):
                    sent_id = line.split("=", 1)[1].strip() if "=" in line else None
                    continue
                if line.startswith("# text"):
                    sent_text = line.split("=", 1)[1].strip() if "=" in line else None
                    continue
                if not line.strip() or line.startswith("#"):
                    if not line.strip():
                        _flush()
                    continue
                cols = line.split("\t")
                if len(cols) < 10 or "." in cols[0]:
                    continue
                misc = _parse_misc(cols[9])
                if "-" in cols[0]:
                    # Multi-word token range line ("3-4 abych"): the surface token.
                    start, _, end = cols[0].partition("-")
                    open_mwt = {
                        "form": cols[1],
                        "space_after": misc.get("SpaceAfter", "Yes") != "No",
                        "words": [],
                        "mwt": True,
                        "range": (_as_int(start), _as_int(end)),
                        "misc": cols[9],
                    }
                    current_units.append(open_mwt)
                    continue
                word = {
                    "id": cols[0],
                    "form": cols[1],
                    "lemma": cols[2],
                    "upos": cols[3],
                    "xpos": cols[4],
                    "feats": cols[5],
                    "head": cols[6],
                    "deprel": cols[7],
                    "space_after": misc.get("SpaceAfter", "Yes") != "No",
                    "ner": misc.get("NER", ""),
                }
                word_no = _as_int(cols[0])
                if (
                    open_mwt is not None
                    and word_no is not None
                    and open_mwt["range"][1] is not None
                    and word_no <= open_mwt["range"][1]
                ):
                    open_mwt["words"].append(word)
                    word["_surface"] = open_mwt
                    if word_no == open_mwt["range"][1]:
                        open_mwt = None
                else:
                    open_mwt = None
                    unit = {
                        "form": word["form"],
                        "space_after": word["space_after"],
                        "words": [word],
                        "mwt": False,
                        "misc": cols[9],
                    }
                    word["_surface"] = unit
                    current_units.append(unit)
                current_tok.append(word)
        _flush()
    except Exception as exc:
        print(f"  [Error] Reading CoNLL-U {conllu_path}: {exc}", file=sys.stderr)
        return None

    # Words inside a multi-word token: no space between them, the token's spacing after
    # the last one -- so joining the words of a sentence never invents a space in "abych".
    for sent in sentences:
        for unit in sent["surface"]:
            if unit["mwt"]:
                for word in unit["words"]:
                    word["space_after"] = False
                unit["words"][-1]["space_after"] = unit["space_after"]

    all_units = [unit for sent in sentences for unit in sent["surface"]]
    all_bboxes = _align_tokens_to_alto(all_units, alto_strings)
    has_layout = bool(alto_strings)
    layout_pages = {pg["idx"] for pg in alto_pages} | {s["page_idx"] for s in alto_strings}
    layout_pages |= set(range(1, int(alto_meta.get("page_count") or 0) + 1))
    outliers = _resolve_pages(
        sentences, all_units, all_bboxes, layout_pages, has_layout, rows, _doc_id
    )
    _unbox_split_punctuation(all_units)

    _assign_ids(sentences)

    matched = sum(1 for b in all_bboxes if b is not None)
    if alto_meta.get("layout_source") == "teitok":
        boxed = sum(1 for u in all_units if has_coords(u.get("_bbox")))
        print(f"  [layout] placed {matched}/{len(all_units)} tokens, {boxed} with a bbox")
    elif has_layout:
        print(f"  [ALTO] matched {matched}/{len(all_units)} tokens to ALTO bboxes")
    if outliers:
        print(
            f"  [TEITOK] {_doc_id}: {outliers} token(s) aligned to a page out of reading "
            f"order; their boxes were dropped",
            file=sys.stderr,
        )
    if has_layout and all_units and matched / len(all_units) < MIN_ALIGNMENT:
        print(
            f"  [TEITOK] {_doc_id}: only {matched}/{len(all_units)} tokens align to the layout "
            f"source; are the text and the layout read from the same document version?",
            file=sys.stderr,
        )

    page_order = set(layout_pages) | {u["_page"] for u in all_units}
    if not has_layout:
        page_order |= {r.page for r in rows or []}
    page_labels = {}
    page_labels.update(_page_rows.page_labels(rows))
    page_labels.update(alto_meta.get("page_labels") or {})

    return {
        "doc_id": _doc_id,
        "sentences": sentences,
        "conllu_meta": conllu_meta,
        "alto_strings": alto_strings,
        "alto_pages": alto_pages,
        "alto_graphics": alto_graphics,
        "alto_blocks": alto_blocks,
        "alto_meta": alto_meta,
        "scale_map": scale_map,
        "lang": _majority_lang(alto_strings) or _norm_lang(conllu_meta.get("udpipe_model")),
        "bbox_origin": bbox_origin,
        "page_order": sorted(page_order) or [1],
        "page_labels": page_labels,
        "alignment": {"matched": matched, "total": len(all_units), "outliers": outliers},
    }


# ──────────────────────────────────────────────────────────────────────────────
# Serialisation
# ──────────────────────────────────────────────────────────────────────────────


class _Coords:
    """Scales ALTO coordinates for one page and clamps what falls outside it (negative
    values: content in the margin while ``bbox_origin="printspace"``)."""

    def __init__(self):
        self.page = None
        self.clamped = 0
        self.sx = self.sy = 1.0
        self.dx = self.dy = 0

    def set_page(self, scale):
        self.sx, self.sy, _, _, self.dx, self.dy, _ = scale

    def fmt(self, x1, y1, x2, y2):
        scaled = _scale_bbox_str(x1, y1, x2, y2, self.sx, self.sy, self.dx, self.dy).split()
        values = []
        for v in scaled:
            n = int(v)
            if n < 0:
                self.clamped += 1
                n = 0
            values.append(str(n))
        return " ".join(values)

    def fmt_str(self, raw):
        parts = (raw or "").split()
        if len(parts) != 4:
            return ""
        return self.fmt(*(int(p) for p in parts))


def _word_attrs(word, head_ids, with_form=False):
    """Linguistic attributes of one syntactic word, in upstream TEITOK order."""
    attrs = []
    if word.get("id"):
        attrs.append(f'ord="{_attr(word["id"])}"')
    if with_form:
        attrs.append(f'form="{_attr(word["form"])}"')
    for key in ("lemma", "upos", "xpos", "feats"):
        if word.get(key) and word[key] != "_":
            attrs.append(f'{key}="{_attr(word[key])}"')
    head = word.get("head")
    if head and head not in ("0", "_"):
        attrs.append(f'head="{_attr(head_ids.get(head, head))}"')
    if word.get("deprel") and word["deprel"] != "_":
        attrs.append(f'deprel="{_attr(word["deprel"])}"')
    return attrs


def has_coords(bbox) -> bool:
    """True for an aligned token box that has coordinates (layout sources may give a token
    its page/block/line without a box)."""
    return bool(bbox) and bbox.get("left") is not None


def _tok_xml(unit, head_ids, coords):
    """One surface ``<tok>`` (with ``<dtok>`` children for a multi-word token)."""
    words = unit["words"]
    all_punct = all(w.get("upos") == "PUNCT" for w in words)
    attrs = [f'id="{unit["_xml_id"]}"', f'type="{"pc" if all_punct else "w"}"']
    if not unit["mwt"]:
        attrs += _word_attrs(words[0], head_ids)
    if not unit["space_after"]:
        attrs.append('join="right"')
    bbox = unit.get("_bbox")
    if has_coords(bbox):
        attrs.append(
            f'bbox="{coords.fmt(bbox["left"], bbox["top"], bbox["right"], bbox["bottom"])}"'
        )
    inner = escape(unit["form"])
    if unit["mwt"]:
        for word in words:
            dattrs = [f'id="{word["_xml_id"]}"'] + _word_attrs(word, head_ids, with_form=True)
            inner += f"<dtok {' '.join(dattrs)}/>"
    return f"<tok {' '.join(attrs)}>{inner}</tok>"


def _name_open_xml(grp):
    code = grp["code"]
    label_attr = TAGSET_ATTRIBUTE[tagset(code)]
    same_as = " ".join(f"#{u['_xml_id']}" for u in grp["units"])
    return (
        f'<name id="{grp["_xml_id"]}" type="{coarse_type(code)}" '
        f'{label_attr}="{_attr(code)}" sameAs="{same_as}">'
    )


def _header_xml(
    parsed, alto_path, conllu_path, model_udpipe, model_nametag, lang, has_names, source_file=None
):
    doc_id = escape(parsed["doc_id"])
    conllu_meta = parsed["conllu_meta"]
    alto_meta = parsed["alto_meta"]
    today = datetime.date.today().isoformat()
    converted = alto_meta.get("layout_source") == "teitok"
    has_alto = bool(parsed["alto_pages"]) and not converted
    if converted:
        # the original document flexiconv converted; the TEITOK file only relayed it
        orgfile = alto_meta.get("orgfile") or Path(alto_path).name
    elif has_alto:
        orgfile = Path(alto_path).name
    else:
        # the table or text stage 1 read (the rows file names it), not the CoNLL-U
        orgfile = Path(source_file).name if source_file else Path(conllu_path).name

    h = ["  <teiHeader>", "    <fileDesc>"]
    h.append(f"      <titleStmt><title>{doc_id}</title></titleStmt>")
    h.append("      <publicationStmt><p>Unpublished</p></publicationStmt>")
    h.append(f'      <notesStmt><note n="orgfile">{escape(orgfile)}</note></notesStmt>')
    source_info = alto_meta.get("source_image", "")
    h.append(
        f"      <sourceDesc><p>Source image: {escape(source_info)}</p></sourceDesc>"
        if source_info
        else "      <sourceDesc><p>Unknown source</p></sourceDesc>"
    )
    h.append("    </fileDesc>")

    h.append("    <encodingDesc>")
    h.append("      <appInfo>")
    h.append(
        f'        <application ident="atrium-nlp-enrich" version="{WRITER_FORMAT}">'
        f"<label>atrium-nlp-enrich TEITOK writer</label>"
        f"<desc>bbox origin: {escape(parsed['bbox_origin'])}</desc></application>"
    )
    udpipe_model = conllu_meta.get("udpipe_model") or model_udpipe or ""
    generator = conllu_meta.get("generator", "")
    if udpipe_model or generator:
        h.append(
            f'        <application ident="udpipe" version="2">'
            f"<label>{escape(generator or 'UDPipe')}</label>"
            f"<desc>Model: {escape(udpipe_model)}</desc></application>"
        )
    if model_nametag:
        h.append(
            f'        <application ident="nametag"><label>NameTag NER</label>'
            f"<desc>Model: {escape(model_nametag)}</desc></application>"
        )
    if converted and alto_meta.get("converter"):
        version = alto_meta.get("converter_version")
        version_attr = f' version="{escape(version)}"' if version else ""
        h.append(
            f'        <application ident="{escape(alto_meta["converter"])}"{version_attr}>'
            f"<label>{escape(alto_meta['converter'])}</label>"
            f"<desc>text and layout from {escape(Path(alto_path).name)}</desc></application>"
        )
    if alto_meta.get("ocr_software"):
        h.append(
            f'        <application ident="ocr">'
            f"<label>{escape(alto_meta['ocr_software'])} "
            f"{escape(alto_meta.get('ocr_version', ''))}</label></application>"
        )
    h.append("      </appInfo>")
    h.append("    </encodingDesc>")

    if lang:
        h.append(
            f'    <profileDesc><langUsage><language ident="{lang}"/></langUsage></profileDesc>'
        )

    # revisionDesc: @type/@subtype name the workflow phase the way TEITOK/flexicorp detect
    # it (converted, tagged/parsed, ner); the text wording matches their fallback patterns.
    h.append("    <revisionDesc>")
    if converted:
        who = escape(alto_meta.get("converter") or "flexiconv")
        h.append(
            f'      <change when="{today}" who="{who}" type="converted">'
            f"Converted from {escape(orgfile)} by {who}</change>"
        )
    elif has_alto:
        h.append(
            f'      <change when="{today}" who="altoconvert" type="converted">'
            f"Converted from ALTO file {escape(orgfile)}</change>"
        )
    elif source_file:
        h.append(
            f'      <change when="{today}" who="atrium-nlp-enrich" type="converted">'
            f"Converted from text file {escape(orgfile)} (annotated as CoNLL-U)</change>"
        )
    else:
        h.append(
            f'      <change when="{today}" who="atrium-nlp-enrich" type="converted">'
            f"Converted from CoNLL-U file {escape(orgfile)}</change>"
        )
    if alto_meta.get("ocr_date") and alto_meta.get("ocr_software"):
        h.append(
            f'      <change when="{escape(alto_meta["ocr_date"])}" '
            f'who="{escape(alto_meta["ocr_software"])}">OCR processing</change>'
        )
    if udpipe_model or generator:
        model_text = f" model {escape(udpipe_model)}" if udpipe_model else ""
        via = f" ({escape(generator)})" if generator else ""
        h.append(
            f'      <change when="{today}" who="udpipe" type="tagged" subtype="parsed">'
            f"tokenized, lemmatized and dependency parsed with UDPipe{model_text}{via}</change>"
        )
    if model_nametag or has_names:
        model_text = f" model {escape(model_nametag)}" if model_nametag else ""
        h.append(
            f'      <change when="{today}" who="nametag" type="ner">'
            f"named entity recognition with NameTag{model_text}</change>"
        )
    h.append("    </revisionDesc>")
    h.append("  </teiHeader>")
    return h


def _sentence_xml(sent, prefix_for, coords):
    """``<s>`` with inline, text-faithful token spacing (see the module docstring).

    ``prefix_for(unit)`` is called right before a token is rendered and returns the markup
    that precedes it: the ``<pb/>`` of a page the sentence runs onto and the ``<lb/>`` of a
    new line. It also switches ``coords`` to the page, so the token's box is scaled for the
    page it is on. When an entity's first token starts a line or page, that markup goes
    before ``<name>``; later in the entity it stays inside it."""
    head_ids = {w["id"]: w["_xml_id"] for w in sent["tokens"]}
    parts = []
    gap = None  # position in `parts` of the whitespace after the previous token

    def place_gap(breaks):
        nonlocal gap
        if gap is not None:
            parts[gap] = "\n          " if breaks else " "
        gap = None

    def render(unit, prefix):
        nonlocal gap
        place_gap(bool(prefix))
        parts.extend(prefix)
        parts.append(_tok_xml(unit, head_ids, coords))
        if unit["space_after"]:
            parts.append(" ")
            gap = len(parts) - 1

    for grp in sent["names"]:
        units = grp["units"]
        if grp["kind"] == "name":
            prefix = prefix_for(units[0])
            place_gap(bool(prefix))
            parts.extend(prefix)
            parts.append(_name_open_xml(grp))
            render(units[0], [])
            for unit in units[1:]:
                render(unit, prefix_for(unit))
            parts.append("</name>")
        else:
            for unit in units:
                render(unit, prefix_for(unit))
    if gap is not None:
        parts[gap] = "\n        "

    text_attr = f' text="{_attr(sent["text"])}"' if sent.get("text") else ""
    return f'        <s id="{sent["_xml_id"]}"{text_attr}>\n          {"".join(parts)}</s>\n'


def write_teitok_merged(
    conllu_path,
    teitok_path,
    alto_path=None,
    doc_id=None,
    model_udpipe=None,
    model_nametag=None,
    image_dir=None,
    dpi=None,
    alto_dpi=None,
    bbox_origin="page",
    rows=None,
    source_file=None,
):
    """Write TEITOK format 2 for one document (see the module docstring).

    Pages are *layout-first* (issue #38, A): a token is on the page of the layout string it
    aligned to, else on the page of its line in ``rows`` (stage 1's rows file), else on the
    page of the token before it. ``<pb/>`` comes where the page changes -- between sentences,
    or inside an ``<s>`` (and ``<name>``) that runs over a page break, as xmltokenizer and
    flexiconv allow. Pages only move forward, every page of the layout gets its ``<pb/>``,
    and ``pb@facs``/``@corresp``/``@bbox`` are written only for pages that have a
    ``<surface>``. ``source_file`` (the table or text the rows came from) is the ``orgfile``
    of a document without a layout source."""
    bbox_origin = (bbox_origin or "page").strip().lower()
    if bbox_origin not in BBOX_ORIGINS:
        raise ValueError(f"bbox_origin must be one of {BBOX_ORIGINS}, got {bbox_origin!r}")

    parsed = parse_and_align_conllu(
        conllu_path,
        alto_path,
        doc_id=doc_id,
        image_dir=image_dir,
        dpi=dpi,
        alto_dpi=alto_dpi,
        bbox_origin=bbox_origin,
        rows=rows,
    )
    if parsed is None:
        return False

    doc_id_safe = escape(parsed["doc_id"])
    sentences = parsed["sentences"]
    alto_pages = parsed["alto_pages"]
    alto_graphics = parsed["alto_graphics"]
    alto_blocks = parsed["alto_blocks"]
    scale_map = parsed["scale_map"]
    page_order = parsed["page_order"]
    page_labels = parsed["page_labels"]
    lang = parsed["lang"] or _norm_lang(model_udpipe)
    has_names = any(g["kind"] == "name" for s in sentences for g in s["names"])
    default_scale = (1.0, 1.0, None, None, 0, 0, ".png")
    coords = _Coords()
    block_langs = collections.defaultdict(collections.Counter)
    for string in parsed["alto_strings"]:
        if string.get("lang"):
            block_langs[string["block_id"]][string["lang"]] += 1

    lines = ['<?xml version="1.0" encoding="utf-8"?>']
    lang_attr = f' lang="{lang}"' if lang else ""
    lines.append(f'<TEI xmlnsoff="http://www.tei-c.org/ns/1.0"{lang_attr}>')
    lines += _header_xml(
        parsed, alto_path, conllu_path, model_udpipe, model_nametag, lang, has_names, source_file
    )

    # Page image names: {doc_id}-{N}.<ext> for ALTO; a converted layout source keeps the
    # name it gives (<pb facs>).
    page_facs = {
        pg["idx"]: escape(pg["facs"], {'"': "&quot;"}) for pg in alto_pages if pg.get("facs")
    }
    surfaces = {pg["idx"] for pg in alto_pages}

    def facs_url(page, ext):
        return page_facs.get(page) or f"{doc_id_safe}-{page}{ext}"

    if alto_pages:
        lines.append("  <facsimile>")
        for pg in alto_pages:
            idx = pg["idx"]
            _, _, img_w, img_h, _, _, img_ext = scale_map.get(idx, default_scale)
            lrx = f' lrx="{img_w}"' if img_w is not None else ""
            lry = f' lry="{img_h}"' if img_h is not None else ""
            lines.append(f'    <surface id="facs-{idx}"{lrx}{lry}>')
            lines.append(f'      <graphic url="{facs_url(idx, img_ext)}"/>')
            lines.append("    </surface>")
        lines.append("  </facsimile>")

    lines.append("  <text>")
    lines.append("    <body>")
    body = []
    state = {"page": 0, "block": None, "block_page": None, "line": None}
    blocks_on_page = collections.Counter()
    lines_on_page = collections.Counter()
    queued_figures = []

    def pb_xml(page):
        scale = scale_map.get(page, default_scale)
        attrs = [f'n="{_attr(page_labels.get(page) or str(page))}"', f'id="pb-{page}"']
        if page in surfaces:  # P4: no invented page image for a page without a surface
            attrs.append(f'facs="{facs_url(page, scale[6])}"')
            attrs.append(f'corresp="#facs-{page}"')
            if scale[2] is not None and scale[3] is not None:
                attrs.append(f'bbox="0 0 {scale[2]} {scale[3]}"')  # U2: the page's extent
        return f"<pb {' '.join(attrs)}/>"

    def open_pages(upto):
        """Markup of every page after the current one up to ``upto`` -- pages of the layout
        without text included, so every ``<surface>`` has its ``<pb/>`` -- as ``(pbs,
        figures)``; the coordinate scale ends on page ``upto``."""
        pages = [p for p in page_order if state["page"] < p <= upto]
        if not pages or pages[-1] != upto:
            pages.append(upto)
        pbs, figures = [], []
        for page in pages:
            coords.set_page(scale_map.get(page, default_scale))
            pbs.append(pb_xml(page))
            for k, g in enumerate((g for g in alto_graphics if g["page_idx"] == page), 1):
                figures.append(
                    f'<figure type="{escape(g["type"])}" id="fig-{page}.{k}" '
                    f'bbox="{coords.fmt(*g["bbox"])}"/>'
                )
        state["page"] = upto
        state["line"] = None
        return pbs, figures

    def close_block():
        if state["block"] is not None:
            body.append("      </div>\n")
            state["block"] = state["block_page"] = None

    def flush_figures():
        # <div> holds only <s>: figures of a page opened inside a sentence wait for the body
        close_block()
        body.extend(f"      {fig}\n" for fig in queued_figures)
        queued_figures.clear()

    def prefix_for(unit):
        """``<pb/>`` of pages the sentence runs onto, then ``<lb/>`` of a new line."""
        out = []
        if unit["_page"] > state["page"]:
            pbs, figures = open_pages(unit["_page"])
            out += pbs
            queued_figures.extend(figures)
        b = unit.get("_bbox")
        if b and b.get("line_id") and b["line_id"] != state["line"]:
            state["line"] = b["line_id"]
            page = state["page"]
            lines_on_page[page] += 1
            lb_bbox = coords.fmt_str(b.get("line_bbox", ""))
            bbox_attr = f' bbox="{lb_bbox}"' if lb_bbox else ""
            out.append(f'<lb id="lb-{page}.{lines_on_page[page]}"{bbox_attr}/>')
        return out

    for sent in sentences:
        if not sent["surface"]:
            continue
        if queued_figures:
            flush_figures()
        first_page = sent["surface"][0]["_page"]
        if first_page > state["page"]:
            close_block()
            pbs, figures = open_pages(first_page)
            body.extend(f"      {m}\n" for m in pbs + figures)

        page = state["page"]
        first_bbox = next(
            (u["_bbox"] for u in sent["surface"] if u.get("_bbox") and u["_page"] == page),
            None,
        )
        block_key = first_bbox.get("block_id") if first_bbox else None
        if block_key is None:
            # no block of its own: stay in the current block while it is on this page
            block_key = state["block"] if state["block_page"] == page else f"__text{page}"
        if block_key != state["block"]:
            close_block()
            state["block"], state["block_page"] = block_key, page
            blocks_on_page[page] += 1
            block = alto_blocks.get(block_key)
            attrs = [f'type="{"TextBlock" if block else "text"}"']
            if block and block.get("subtype"):
                attrs.append(f'subtype="{_attr(block["subtype"])}"')
            attrs.append(f'id="b-{page}.{blocks_on_page[page]}"')
            if block:
                counts = block_langs.get(block_key)
                block_lang = counts.most_common(1)[0][0] if counts else None
                if block_lang and block_lang != lang:
                    attrs.append(f'lang="{block_lang}"')
                block_bbox = coords.fmt_str(block.get("bbox", ""))
                if block_bbox:
                    attrs.append(f'bbox="{block_bbox}"')
            body.append(f"      <div {' '.join(attrs)}>\n")

        body.append(_sentence_xml(sent, prefix_for, coords))

    flush_figures()
    if page_order and page_order[-1] > state["page"]:  # pages after the last text
        pbs, figures = open_pages(page_order[-1])
        body.extend(f"      {m}\n" for m in pbs + figures)
    try:
        with open(teitok_path, "w", encoding="utf-8") as out:
            out.write("\n".join(lines) + "\n")
            out.write("".join(body))
            out.write("    </body>\n  </text>\n</TEI>\n")
    except Exception as exc:
        print(f"  [Error] Writing TEITOK {teitok_path}: {exc}", file=sys.stderr)
        return False
    if coords.clamped:
        print(
            f"  [TEITOK] {parsed['doc_id']}: {coords.clamped} bbox coordinate(s) fell outside "
            f"the {bbox_origin} and were clamped to 0",
            file=sys.stderr,
        )
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Public re-exports for downstream consumers (api_util/document_hook.py)
# ──────────────────────────────────────────────────────────────────────────────
# Same objects as used internally above, just given non-underscored names so a
# consumer building the atrium_document ``entities``/``pages`` blocks from the
# same parsed tokens doesn't need to reach into "private" module state.
group_ner_spans = _group_ner_spans
CNEC_TO_CONLL = _CNEC_TO_CONLL
scale_bbox_tuple = _scale_bbox_tuple
