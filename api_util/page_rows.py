"""page_rows.py -- page and line provenance of every token (issue #38, A).

Stage 1 turns a table (or a converted TEITOK file) into ``<doc>.txt``, one row per line, and
now also writes ``<doc>.rows.tsv``: the ``page``, ``line``, page ``label`` and ``text`` of
each of those lines, in the same order. Stage 2 copies it next to the CoNLL-U it annotated
(``UDP/<doc>.rows.tsv``), so the pair stays together across resumed runs and containers.

UDPipe keeps the line ends of its input: the last token of every line carries
``SpacesAfter=\\n`` in MISC. Counting those marks -- plus the start of every chunk after the
first, since ``chunk.py`` splits on line boundaries and a chunk's last token has no mark --
places each token on its row, hence on its page. That is exact and cheap; it is checked
(row count, and the text of every row) before it is trusted. When the check fails, a
character cursor aligns the tokens with the rows instead; without a rows file at all, the
old per-page convention (``# sent_id = 1`` restarting in a later sentence) is the last
resort.

Before this module, ``call_udpipe.merge_conllu_chunks`` wrote ``# page_break = true`` at every
UDPipe chunk start and NameTag, the summary and the TEITOK writer read it as a page break:
"pages" were ~900-word chunks. The marker is now ``# chunk_start = K``; both forms are read
as chunk starts, never as pages.

Stdlib only; not vendored into atrium-llm-enrich (it reads TEITOK, not CoNLL-U).
"""

import argparse
import csv
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

ROWS_SUFFIX = ".rows.tsv"
ROWS_HEADER = ["page", "line", "label", "text"]
# Optional first line of a rows file: the table or text stage 1 read (the TEITOK orgfile of a
# document without a layout source).
SOURCE_PREFIX = "# source = "
CHUNK_MARKERS = ("# chunk_start", "# page_break = true")

# Everything str.splitlines() splits on: a table cell with one of these would become two
# lines in <doc>.txt (and in chunk.py) but stay one row here, and the counting would drift.
LINE_BREAKS = re.compile("[\r\n\x0b\x0c\x1c\x1d\x1e\x85  ]+")
_WS = re.compile(r"\s+")


def normalize_row_text(text) -> str:
    """One row = one line: line and paragraph separators become spaces."""
    return LINE_BREAKS.sub(" ", str(text or "")).strip()


@dataclass(frozen=True)
class Row:
    page: int
    line: int
    label: str
    text: str


@dataclass(frozen=True)
class Place:
    page: int
    line: int
    row: int


# ── the rows file ─────────────────────────────────────────────────────────────


def rows_path_for(text_path) -> Path:
    """``TEMP/TXT_EXTRACT/<doc>.txt`` -> ``TEMP/TXT_EXTRACT/<doc>.rows.tsv``."""
    p = Path(text_path)
    name = p.name[: -len(".txt")] if p.name.endswith(".txt") else p.name
    return p.with_name(name + ROWS_SUFFIX)


def write_rows(path, rows, source="") -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        if source:
            fh.write(f"{SOURCE_PREFIX}{normalize_row_text(Path(source).name)}\n")
        writer = csv.writer(fh, delimiter="\t", lineterminator="\n")
        writer.writerow(ROWS_HEADER)
        for r in rows:
            writer.writerow([r.page, r.line, r.label, r.text])


def read_rows(path):
    """The rows of a ``.rows.tsv`` file, or None when it is missing or unreadable."""
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            first = fh.readline()
            if not first.startswith(SOURCE_PREFIX):
                fh.seek(0)
            reader = csv.DictReader(fh, delimiter="\t")
            rows = []
            for rec in reader:
                rows.append(
                    Row(
                        page=int(rec.get("page") or 1) or 1,
                        line=int(rec.get("line") or 0),
                        label=rec.get("label") or "",
                        text=rec.get("text") or "",
                    )
                )
            return rows
    except (OSError, ValueError, csv.Error):
        return None


def rows_source(path) -> str:
    """The source file a rows file names on its first line, or ``""``."""
    try:
        with open(path, encoding="utf-8") as fh:
            first = fh.readline().rstrip("\n")
    except OSError:
        return ""
    return first[len(SOURCE_PREFIX) :].strip() if first.startswith(SOURCE_PREFIX) else ""


def find_rows(conllu_path, text_dir=None):
    """The rows file of a document: next to its CoNLL-U (``UDP/<doc>.rows.tsv``, written by
    stage 2), else in ``text_dir`` (stage 1's ``TEMP_TXT_DIR``). None when there is none."""
    conllu_path = Path(conllu_path)
    doc = conllu_path.name
    for suffix in (".conllu",):
        if doc.endswith(suffix):
            doc = doc[: -len(suffix)]
    candidates = [conllu_path.with_name(doc + ROWS_SUFFIX)]
    if text_dir:
        candidates.append(Path(text_dir) / f"{doc}{ROWS_SUFFIX}")
    for c in candidates:
        if c.is_file():
            return c
    return None


def page_labels(rows) -> dict:
    """Page ordinal -> label (``pb@n``), for pages whose label differs from the ordinal."""
    labels = {}
    for r in rows or []:
        if r.label and r.label != str(r.page):
            labels.setdefault(r.page, r.label)
    return labels


# ── reading the CoNLL-U surface ───────────────────────────────────────────────


def read_surface(conllu_path):
    """Sentences of a CoNLL-U file as ``{"sent_id", "chunk_start", "surface": [units]}``.

    A unit is what ``teitok_alto.parse_and_align_conllu`` calls a surface token: a
    multi-word-token range line (with its words), or a word outside any range. Each unit
    has ``form``, ``misc`` (raw MISC column) and ``n_words``. Returns [] on a read error."""
    sentences = []
    units, chunk_start, sent_id = [], False, None
    open_range = None

    def flush():
        nonlocal units, chunk_start, sent_id, open_range
        if units:
            sentences.append({"sent_id": sent_id, "chunk_start": chunk_start, "surface": units})
            units, chunk_start, sent_id = [], False, None
        open_range = None

    try:
        with open(conllu_path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.rstrip("\n")
                if not line.strip():
                    flush()
                    continue
                if line.startswith("#"):
                    if line.strip().startswith(CHUNK_MARKERS):
                        chunk_start = True
                    elif line.startswith("# sent_id"):
                        sent_id = line.split("=", 1)[1].strip() if "=" in line else None
                    continue
                cols = line.split("\t")
                if len(cols) < 10 or "." in cols[0]:
                    continue
                if "-" in cols[0]:
                    start, _, end = cols[0].partition("-")
                    try:
                        open_range = int(end)
                    except ValueError:
                        open_range = None
                    units.append({"form": cols[1], "misc": cols[9], "n_words": 0})
                    continue
                try:
                    word_no = int(cols[0])
                except ValueError:
                    word_no = None
                if open_range is not None and word_no is not None and word_no <= open_range:
                    units[-1]["n_words"] += 1
                    if word_no == open_range:
                        open_range = None
                    continue
                open_range = None
                units.append({"form": cols[1], "misc": cols[9], "n_words": 1})
        flush()
    except OSError as exc:
        print(f"  [pages] cannot read {conllu_path}: {exc}", file=sys.stderr)
        return []
    return sentences


def _misc_value(misc, key):
    for item in (misc or "").split("|"):
        if item.startswith(key + "="):
            return item.split("=", 1)[1]
    return ""


def count_newlines(escaped) -> int:
    """Line ends in a UDPipe ``SpacesAfter``/``SpacesBefore`` value (``\\n``; ``\\\\`` is a
    literal backslash, so ``\\\\n`` is not a line end)."""
    n, i = 0, 0
    while i < len(escaped):
        if escaped[i] == "\\" and i + 1 < len(escaped):
            n += escaped[i + 1] == "n"
            i += 2
        else:
            i += 1
    return n


def _squash(text):
    return _WS.sub("", unicodedata.normalize("NFC", text or ""))


# ── placing units on rows ─────────────────────────────────────────────────────


def _place_by_newlines(sentences):
    """Row index per unit, by counting line ends; also returns the number of rows used."""
    placed, row, ended = [], 0, True
    for si, sent in enumerate(sentences):
        if si and sent.get("chunk_start") and not ended:
            row += 1  # a new chunk starts a new line; its predecessor carried no mark
            ended = True
        for unit in sent["surface"]:
            misc = unit.get("misc", "")
            before = count_newlines(_misc_value(misc, "SpacesBefore"))
            if before:
                row += before
            placed.append(row)
            after = count_newlines(_misc_value(misc, "SpacesAfter"))
            row += after
            ended = after > 0
    used = row if ended else row + 1
    return placed, used


def _verified(sentences, placed, used, rows):
    if used != len(rows):
        return False
    texts = [""] * len(rows)
    units = [u for s in sentences for u in s["surface"]]
    for unit, r in zip(units, placed, strict=True):
        if r >= len(rows):
            return False
        texts[r] += unit.get("form", "")
    return all(_squash(t) == _squash(row.text) for t, row in zip(texts, rows, strict=True))


def _place_by_characters(sentences, rows):
    """Fallback: align the unit forms with the rows' text, character by character."""
    from api_util.teitok_alto import _align_tokens_to_alto

    strings = []
    for idx, row in enumerate(rows):
        for word in row.text.split():
            strings.append(
                {
                    "content": word,
                    "left": None,
                    "top": None,
                    "right": None,
                    "bottom": None,
                    "page_idx": row.page,
                    "block_id": None,
                    "line_id": idx,
                    "line_bbox": "",
                }
            )
    units = [u for s in sentences for u in s["surface"]]
    boxes = _align_tokens_to_alto(units, strings)
    placed, last = [], 0
    for box in boxes:
        if box is not None and box.get("line_id") is not None:
            last = max(last, box["line_id"])  # rows only move forward
        placed.append(last)
    return placed


def place_units(sentences, rows, doc_id=""):
    """A ``Place`` (page, line, row) for every surface unit, in document order, and the method
    used: ``"newline"`` (verified line-end counting), ``"chars"`` (character alignment) or
    ``"none"`` (no rows; every place is None)."""
    units = [u for s in sentences for u in s["surface"]]
    if not rows:
        return [None] * len(units), "none"
    placed, used = _place_by_newlines(sentences)
    method = "newline"
    if not _verified(sentences, placed, used, rows):
        placed = _place_by_characters(sentences, rows)
        method = "chars"
        print(
            f"  [pages] {doc_id or 'document'}: line ends do not match the rows file "
            f"({used} vs {len(rows)} rows); pages come from character alignment",
            file=sys.stderr,
        )
    places = []
    for r in placed:
        r = min(max(r, 0), len(rows) - 1)
        places.append(Place(page=rows[r].page, line=rows[r].line, row=r))
    return places, method


def legacy_sentence_pages(sentences):
    """Pages without a rows file: an old per-page CoNLL-U restarts ``# sent_id = 1`` on every
    page. Chunk markers are never pages. One page for a merged, renumbered file."""
    pages, page = [], 1
    for si, sent in enumerate(sentences):
        if si and sent.get("sent_id", sent.get("id")) == "1":
            page += 1
        pages.append(page)
    return pages


def word_pages(conllu_path, rows=None, doc_id=""):
    """Per sentence, the page of every syntactic word (what NameTag tags), in order."""
    sentences = read_surface(conllu_path)
    places, method = place_units(sentences, rows, doc_id)
    out, k = [], 0
    legacy = legacy_sentence_pages(sentences) if method == "none" else None
    for si, sent in enumerate(sentences):
        pages = []
        for unit in sent["surface"]:
            page = places[k].page if places[k] is not None else legacy[si]
            pages.extend([page] * unit["n_words"])
            k += 1
        out.append(pages)
    return out


# ── migration: re-split existing NE files by page ─────────────────────────────


def resplit_ne(conllu_path, ne_doc_dir, rows, doc_id):
    """Re-partition ``NE/<doc>/<doc>-N.tsv`` (written with chunk "pages") by real page,
    without calling NameTag: the files are concatenated in order and cut at page changes.
    Returns the number of page files written, or None when the token counts disagree."""
    ne_doc_dir = Path(ne_doc_dir)
    files = sorted(
        ne_doc_dir.glob("*.tsv"),
        key=lambda p: int(m.group(1)) if (m := re.search(r"-(\d+)\.tsv$", p.name)) else 0,
    )
    header, lines = None, []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            first = fh.readline()
            header = header or first
            lines.extend(ln for ln in fh.read().splitlines() if ln.strip())
    pages = [p for sent in word_pages(conllu_path, rows, doc_id) for p in sent]
    if len(pages) != len(lines):
        return None
    by_page = {}
    for page, line in zip(pages, lines, strict=True):
        by_page.setdefault(page, []).append(line)
    for f in files:
        f.unlink()
    for page, page_lines in by_page.items():
        with open(ne_doc_dir / f"{doc_id}-{page}.tsv", "w", encoding="utf-8") as fh:
            fh.write(header or "Word\tTag\tNE\n")
            fh.write("\n".join(page_lines) + "\n")
    return len(by_page)


def _main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    rs = sub.add_parser("resplit", help="re-split existing NE TSVs by real page (no NameTag call)")
    rs.add_argument("--conllu-dir", required=True, help="UDP/ (CoNLL-U + .rows.tsv)")
    rs.add_argument("--ne-dir", required=True, help="NE/ (one directory per document)")
    rs.add_argument("--text-dir", default=None, help="TEMP_TXT_DIR, if rows are only there")
    args = parser.parse_args(argv)
    failures = 0
    for conllu in sorted(Path(args.conllu_dir).glob("*.conllu")):
        doc = conllu.name[: -len(".conllu")]
        ne_doc = Path(args.ne_dir) / doc
        rows_path = find_rows(conllu, args.text_dir)
        if not ne_doc.is_dir() or rows_path is None:
            print(f"[SKIP] {doc}: {'no NE directory' if not ne_doc.is_dir() else 'no rows file'}")
            continue
        n = resplit_ne(conllu, ne_doc, read_rows(rows_path), doc)
        if n is None:
            failures += 1
            print(f"[FAIL] {doc}: NE token count differs from the CoNLL-U; left as it was")
        else:
            print(f"[OK] {doc}: {n} page file(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_main())
