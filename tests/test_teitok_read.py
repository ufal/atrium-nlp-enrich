# Adjust import path assuming pytest runs from the repository root
import sys
from pathlib import Path

import pytest

_api_util_path = str(Path(__file__).parent.parent / "api_util")
if _api_util_path not in sys.path:
    sys.path.insert(0, _api_util_path)

from api_util.teitok_read import (  # noqa: E402
    doc_id_from_path,
    read_teitok_rows,
    read_teitok_text,
    read_teitok_tokens,
)

TEITOK_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<teiCorpus>
    <text>
        <pb n="1"/>
        <s text="První věta na stránce.">
            <tok id="w-1" type="w" lemma="první" upos="ADJ" join="right">První</tok>
            <tok id="w-2" type="w" lemma="věta" upos="NOUN">věta</tok>
            <tok id="w-3" type="w" lemma="na" upos="ADP">na</tok>
            <tok id="w-4" type="w" lemma="stránka" upos="NOUN" spaceAfter="No">stránce</tok>
            <tok id="w-5" type="pc" lemma="." upos="PUNCT">.</tok>
        </s>
        <lb/>
        <s>
            <tok id="w-6" type="w" lemma="druhý" upos="ADJ">Druhá</tok>
            <tok id="w-7" type="w" lemma="chybí" upos="VERB">chybí</tok>
            <tok id="w-8" type="w" lemma="text" upos="NOUN">text</tok>
        </s>
        <pb n="2"/>
        <s text="Věta na druhé straně.">
            <tok id="w-9" type="w" lemma="věta" upos="NOUN">Věta</tok>
        </s>
    </text>
</teiCorpus>
"""


@pytest.fixture
def sample_teitok(tmp_path):
    p = tmp_path / "doc.teitok.xml"
    p.write_text(TEITOK_SAMPLE, encoding="utf-8")
    return p


def test_doc_id_from_path():
    assert doc_id_from_path("CTX001.conllu") == "CTX001"
    assert doc_id_from_path("CTX001.teitok.xml") == "CTX001"
    assert doc_id_from_path("/path/to/CTX001.txt") == "CTX001"


def test_read_teitok_rows(sample_teitok):
    rows = read_teitok_rows(sample_teitok)
    assert len(rows) == 3

    # Check page and line tracking
    assert rows[0] == {"page_num": 1, "line_num": 1, "text": "První věta na stránce."}

    # Check fallback text reconstruction from <tok> elements if @text is missing
    assert rows[1] == {"page_num": 1, "line_num": 2, "text": "Druhá chybí text"}

    assert rows[2] == {"page_num": 2, "line_num": 2, "text": "Věta na druhé straně."}


def test_read_teitok_text(sample_teitok):
    text = read_teitok_text(sample_teitok)
    assert text == "První věta na stránce.\nDruhá chybí text\nVěta na druhé straně."


def test_read_teitok_tokens(sample_teitok):
    tokens = read_teitok_tokens(sample_teitok)
    assert len(tokens) == 9

    # Check standard token attributes
    assert tokens[0] == {"form": "První", "lemma": "první", "upos": "ADJ", "space_after": False}
    assert tokens[1] == {"form": "věta", "lemma": "věta", "upos": "NOUN", "space_after": True}

    # Check spaceAfter="No" mapped properly
    assert tokens[3]["space_after"] is False

    # upos comes from the `upos` attribute alone -- `type` ("w"/"pc") is a separate
    # word/punctuation flag, not a fallback source for UPOS (see the real fixture below).
    assert tokens[7] == {"form": "text", "lemma": "text", "upos": "NOUN", "space_after": True}


def test_read_teitok_tokens_upos_comes_from_the_upos_attribute_not_type():
    """Regression: `type=` on a real <tok> is "w"/"pc" (word vs. punctuation), never a
    UPOS tag -- `tok.get("pos", tok.get("type", ""))` used to fall through to `type`
    for every token (since real TEITOK output has no `pos=` attribute at all), so
    every token got upos "w" or "pc" and keywords.py's NOUN/PROPN/ADJ filter matched
    nothing on any .teitok.xml input."""
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<teiCorpus><text><s text="x">'
        '<tok id="w-1" type="w" lemma="kostel" upos="NOUN">kostel</tok>'
        "</s></text></teiCorpus>"
    )
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".teitok.xml", delete=False) as f:
        f.write(xml)
        path = f.name
    tokens = read_teitok_tokens(path)
    assert tokens[0]["upos"] == "NOUN"


def test_real_shipped_teitok_fixture_has_genuine_upos_values():
    """Integration check against the real committed sample
    (data_samples/TEITOK/CTX000000001.teitok.xml), not just a hand-written fixture --
    this is the file the defect was found on. Before the fix every token's upos was
    "w" or "pc"; a real UPOS tagset must appear, and NOUN/PROPN/ADJ specifically, since
    those are what keywords.py filters on."""
    from pathlib import Path

    fixture = Path(__file__).parent.parent / "data_samples" / "TEITOK" / "CTX000000001.teitok.xml"
    if not fixture.exists():
        pytest.skip("data_samples/TEITOK/CTX000000001.teitok.xml not present in this checkout")
    tokens = read_teitok_tokens(fixture)
    upos_values = {t["upos"] for t in tokens}
    assert upos_values - {"w", "pc"}, f"upos values are still just type flags: {upos_values}"
    assert {"NOUN", "ADJ"} & upos_values


def test_keywords_extract_lemmas_nonempty_on_real_teitok_fixture():
    """The end-to-end regression the fix is actually for: keywords._extract_lemmas()
    must return real content-word lemmas for a .teitok.xml input, not an empty list."""
    from pathlib import Path

    fixture = Path(__file__).parent.parent / "data_samples" / "TEITOK" / "CTX000000001.teitok.xml"
    if not fixture.exists():
        pytest.skip("data_samples/TEITOK/CTX000000001.teitok.xml not present in this checkout")

    import keywords

    lemmas = keywords._extract_lemmas(str(fixture))
    assert lemmas, "lemma extraction returned nothing for a real TEITOK file"
