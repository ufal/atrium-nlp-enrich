"""doc_identity.py -- which document a flexiconv-converted TEITOK file is, and where a document's
page layout comes from (issue #38, B).

A converted file keeps *file identity*: ``report.v2.teitok.xml`` is the document
``report.v2`` (the name minus ``.teitok.xml``), exactly as stage 1 has always called it, so
no existing run is renamed. A table document can also *claim* a converted file as its
layout source -- the case of alto-postprocess's ``--method text-lines`` reading the same
originals into ``DOC_LINE_CATEG/<doc>.csv`` -- through ``find_converted()``:

1. the file ``{doc_id}.teitok.xml`` if it exists;
2. else the single file whose name maps to ``doc_id`` under ``canonical_doc_id()``
   (``report.v2.teitok.xml`` serves ``report``: flexiconv names its output after the file
   stem, the manifest and alto-postprocess after ``canonical_doc_id``);
3. else nothing. Two files that both map to the id (``report.txt.teitok.xml`` and
   ``report.md.teitok.xml``, flexiconv's names for same-stem siblings) are *ambiguous*: no
   layout is attached and a warning says so. Before, the first one in sort order was used
   silently.

Stage 1 (``build_manifest_row.py --doc-id-only --table-ids ... --flexiconv-dir ...``) and
stage 4 (``summarize_nt_udp.layout_source``) both use these functions, so a converted file
is either annotated as its own document or used as a table document's layout -- never both.
``atrium_document.canonical_doc_id`` itself (hub-canonical, vendored byte-identically) is
not changed.
"""

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from atrium_document import canonical_doc_id  # noqa: E402

CONVERTED_SUFFIX = ".teitok.xml"


def converted_doc_id(path) -> str:
    """The document id of a converted file: its name minus ``.teitok.xml``."""
    name = Path(path).name
    if name.lower().endswith(CONVERTED_SUFFIX):
        return name[: -len(CONVERTED_SUFFIX)]
    return canonical_doc_id(name)


def source_doc_id(path) -> str:
    """The id a table of the same original would carry (``report.v2`` -> ``report``)."""
    return canonical_doc_id(converted_doc_id(path))


def _candidates(doc_id: str, flexiconv_dir: Path):
    # A file serving `doc_id` by rule 2 is named `<doc_id>.<more>.teitok.xml`; listing only
    # those keeps this cheap on large directories.
    return sorted(
        p
        for p in flexiconv_dir.glob(f"{doc_id}.*{CONVERTED_SUFFIX}")
        if p.is_file() and source_doc_id(p) == doc_id
    )


def find_converted(doc_id: str, flexiconv_dir, warn: bool = True):
    """The converted file that serves ``doc_id`` (rules 1-3 of the module docstring), or None."""
    if not doc_id or not flexiconv_dir:
        return None
    flexiconv_dir = Path(flexiconv_dir)
    if not flexiconv_dir.is_dir():
        return None
    exact = flexiconv_dir / f"{doc_id}{CONVERTED_SUFFIX}"
    if exact.is_file():
        return exact
    candidates = _candidates(doc_id, flexiconv_dir)
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1 and warn:
        names = ", ".join(p.name for p in candidates)
        print(
            f"  [Warn] {doc_id}: ambiguous converted layout ({names}); none is used. "
            f"Rename one, or name the table after the file it belongs to.",
            file=sys.stderr,
        )
    return None


def claimed_by(converted_path, table_ids) -> str:
    """The table document that uses ``converted_path`` as its layout, or ``""``.

    Stage 1 skips a claimed converted file: its text comes from the table."""
    converted_path = Path(converted_path)
    for table_id in table_ids:
        if find_converted(table_id, converted_path.parent, warn=False) == converted_path:
            return table_id
    return ""


def layout_source(doc_name, alto_dir=None, flexiconv_dir=None):
    """The file stage 4 takes a document's page layout from, or None: the document's
    ``{alto_dir}/{doc}.alto.xml`` first, else (``FLEXICONV_ANNOTATE=true``) its converted
    flexiconv file by ``find_converted()``. The same file then serves the writer
    (``teitok_layout.py``) and the document hook."""
    if alto_dir:
        alto = Path(alto_dir) / f"{doc_name}.alto.xml"
        if alto.exists():
            return alto
    return find_converted(doc_name, flexiconv_dir)
