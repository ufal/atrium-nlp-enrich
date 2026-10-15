"""Shared data of the record-layout tests (issue #42): the born-digital fixtures and a stand-in
for LINDAT on their text.

The records in ``tests/fixtures/record_layout/`` were made by atrium-digital-convert
(``8358f90``) from its own synthetic fixtures, with the light engine::

    python tests/fixtures/digital/make_fixtures.py --outdir OUT
    python api_util/digital_to_json.py OUT/two_column.pdf --out-dir RECORDS

``two_column`` (two pages labelled ``i``/``ii``, running header and footer, two columns),
``image_only`` (a text page, then a scanned plate and a blank page with a canvas and no
lines) and ``minimal_docx`` (``minimal.docx``: pages and lines, no geometry). No real AMČR
text (atrium-project#16).

``conllu_for()`` and ``ne_tsv_for()`` stand in for UDPipe and NameTag: one sentence per line,
words and punctuation split apart, ``SpaceAfter=No`` where the text has no space and
``SpacesAfter=\\n`` at each line end, as UDPipe writes them.
"""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "record_layout"
_TOKEN = re.compile(r"\w+|[^\w\s]")


def record_path(name: str) -> Path:
    return FIXTURES / f"{name}.document.json"


def record(name: str) -> dict:
    return json.loads(record_path(name).read_text(encoding="utf-8"))


def _tokens(text):
    """``(form, space_after)`` per token of one line."""
    matches = list(_TOKEN.finditer(text))
    return [
        (m.group(), i + 1 < len(matches) and matches[i + 1].start() > m.end())
        for i, m in enumerate(matches)
    ]


def _tags(forms, entities):
    """BIO tags of one line: ``entities`` is ``[(("Horni", "Mezi"), "gu"), ...]``."""
    tags = ["O"] * len(forms)
    for words, code in entities:
        for i in range(len(forms) - len(words) + 1):
            if tuple(forms[i : i + len(words)]) == tuple(words):
                tags[i] = f"B-{code}"
                for j in range(i + 1, i + len(words)):
                    tags[j] = f"I-{code}"
    return tags


def conllu_for(lines, entities=(), ner=True) -> str:
    """CoNLL-U of ``lines`` (strings): with ``ner``, NameTag's tags merged in (``NER=``), as
    stage 4 reads it; without, UDPipe's output, as stage 3 reads it."""
    out = []
    for n, text in enumerate(lines, start=1):
        tokens = _tokens(text)
        tags = _tags([f for f, _ in tokens], entities)
        out.append(f"# sent_id = {n}\n# text = {text}\n")
        for i, ((form, space_after), tag) in enumerate(zip(tokens, tags, strict=True), start=1):
            upos = "PUNCT" if not form[0].isalnum() else ("NUM" if form.isdigit() else "NOUN")
            head, deprel = ("0", "root") if i == 1 else ("1", "dep")
            misc = []
            if i == len(tokens):
                misc.append("SpacesAfter=\\n")
            elif not space_after:
                misc.append("SpaceAfter=No")
            if ner:
                misc.append(f"NER={tag}")
            cols = [str(i), form, form.lower(), upos, "_", "_", head, deprel, "_"]
            out.append("\t".join(cols + ["|".join(misc) or "_"]) + "\n")
        out.append("\n")
    return "".join(out)


def ne_tsv_for(lines, entities=()) -> str:
    """NameTag's per-document TSV for ``lines`` (``Word``, ``Tag``, ``NE``)."""
    rows = ["Word\tTag\tNE\n"]
    for text in lines:
        forms = [f for f, _ in _tokens(text)]
        rows += [f"{f}\t{t}\t\n" for f, t in zip(forms, _tags(forms, entities), strict=True)]
    return "".join(rows)


def record_lines(name: str):
    """The text of a fixture record's lines, as the TEITOK is made of them."""
    from api_util.record_layout import text_lines

    return [line.text for line in text_lines(record_path(name))]
