"""Pages in the TEITOK writer, layout first (issue #38, A).

Before #38 a ``<pb/>`` came from the CoNLL-U: ``# page_break = true`` (which
``merge_conllu_chunks`` wrote at every ~900-word UDPipe chunk start) or a ``# sent_id = 1``
restart, and only between sentences. So a sentence running over a page kept its second-page
tokens under the first page's ``<pb>`` (the released CTX000000002 had page 4's first line as
``lb-3.3``), and a document without ALTO got one ``<pb facs=...>`` per chunk, with an invented
page image. Now a token is on the page of its layout string, else of its line in stage 1's
rows file; ``<pb/>`` may sit inside ``<s>`` and ``<name>``.

``tests/fixtures/pages/multichunk.*``: two UDPipe chunks, five lines, three pages; sentence 2
runs from page 1 onto page 2, sentence 3 (and the entity "Jan Novák" in it) from page 2 onto
page 3, whose label is "III".
"""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from api_util.document_hook import run_document_hook
from api_util.page_rows import read_rows, rows_source
from api_util.teitok_alto import (
    _monotone_keep,
    _resolve_pages,
    parse_and_align_conllu,
    write_teitok_merged,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
PAGES = REPO_ROOT / "tests" / "fixtures" / "pages"
SAMPLES = REPO_ROOT / "data_samples"


def _write(tmp_path, rows=True, name="multichunk"):
    out = tmp_path / f"{name}.teitok.xml"
    rows_path = PAGES / "multichunk.rows.tsv"
    assert write_teitok_merged(
        str(PAGES / "multichunk.conllu"),
        str(out),
        doc_id=name,
        rows=read_rows(rows_path) if rows else None,
        source_file=rows_source(rows_path) if rows else None,
    )
    return out


def _body_events(root):
    """(tag, id, n) of every pb/lb/tok/name/s/div start in document order."""
    return [
        (el.tag, el.get("id"), el.get("n"))
        for el in root.find("text").iter()
        if el.tag in ("pb", "lb", "tok", "name", "s", "div")
    ]


def test_rows_give_pages_across_chunks_and_inside_sentences(tmp_path):
    root = ET.parse(_write(tmp_path)).getroot()
    pbs = list(root.iter("pb"))
    assert [(pb.get("id"), pb.get("n")) for pb in pbs] == [
        ("pb-1", "1"),
        ("pb-2", "2"),
        ("pb-3", "III"),
    ]
    # no page image and no surface: no invented facs (P4), no facsimile at all
    assert all(pb.get("facs") is None and pb.get("corresp") is None for pb in pbs)
    assert root.find("facsimile") is None

    s2 = root.find(".//s[@id='s-2']")
    assert [el.get("id") for el in s2.iter() if el.tag in ("pb", "lb", "tok")] == [
        "lb-1.2",
        "w-4",
        "w-5",
        "pb-2",
        "lb-2.1",
        "w-6",
        "w-7",
    ]
    # the entity runs over the page break: the <pb/> is inside <name>, before its line
    name = root.find(".//name")
    assert [el.get("id") for el in name.iter() if el.tag in ("pb", "lb", "tok")] == [
        "w-9",
        "pb-3",
        "lb-3.1",
        "w-10",
    ]
    # the line that opens the entity's sentence part is outside it
    s3 = root.find(".//s[@id='s-3']")
    assert [el.tag for el in s3][:3] == ["lb", "tok", "name"]


def test_a_block_stays_on_the_page_it_opens_on(tmp_path):
    root = ET.parse(_write(tmp_path)).getroot()
    body = root.find("text/body")
    assert [(el.tag, el.get("id")) for el in body] == [
        ("pb", "pb-1"),
        ("div", "b-1.1"),  # s-1 and s-2 (which carries pb-2)
        ("div", "b-2.1"),  # s-3 (which carries pb-3)
    ]


def test_orgfile_is_the_table_the_rows_came_from(tmp_path):
    root = ET.parse(_write(tmp_path)).getroot()
    assert root.find(".//note[@n='orgfile']").text == "multichunk.csv"
    change = next(c for c in root.iter("change") if c.get("type") == "converted")
    assert "multichunk.csv" in change.text


def test_text_is_unchanged_by_the_page_breaks(tmp_path):
    """Whitespace around the inner <pb/> keeps the spacing TEITOK readers derive."""
    from api_util.teitok_read import read_teitok_rows

    rows = read_teitok_rows(_write(tmp_path))
    assert [(r["page_idx"], r["page_label"], r["text"]) for r in rows] == [
        (1, "1", "Alfa beta."),
        (1, "1", "Gama delta"),
        (2, "2", "epsilon."),
        (2, "2", "Zeta Jan"),
        (3, "III", "Novák iota."),
    ]


def test_without_rows_a_chunk_start_is_not_a_page(tmp_path):
    root = ET.parse(_write(tmp_path, rows=False)).getroot()
    assert [pb.get("id") for pb in root.iter("pb")] == ["pb-1"]
    assert not list(root.iter("lb"))  # no layout, no rows: no lines either


def test_output_is_valid_against_the_schema(tmp_path):
    pytest.importorskip("lxml")
    from api_util.validate_teitok_xml import validate_document

    out = _write(tmp_path)
    assert validate_document(out) == []
    assert validate_document(out, profile="core") == []


def test_released_sample_sentence_crossing_a_page(tmp_path):
    """CTX000000002 s-5 runs from page 3 ("qpqb dbqp uunn") onto page 4 ("Soubor nálezů
    ..."); the released v0.21.0 sample had page 4's first line as ``lb-3.3`` under pb-3."""
    root = ET.parse(SAMPLES / "TEITOK" / "CTX000000002.teitok.xml").getroot()
    s5 = root.find(".//s[@id='s-5']")
    marks = [(el.tag, el.get("id")) for el in s5.iter() if el.tag in ("pb", "lb")]
    assert marks == [("lb", "lb-3.2"), ("pb", "pb-4"), ("lb", "lb-4.1")]
    assert s5.find("lb[@id='lb-4.1']").get("bbox") == "220 160 1220 200"
    assert [pb.get("id") for pb in root.iter("pb")] == ["pb-1", "pb-2", "pb-3", "pb-4"]
    assert root.find(".//pb[@id='pb-4']").get("bbox") == "0 0 1654 2339"  # U2


def test_one_page_alto_with_a_chunk_start_has_one_page(tmp_path):
    conllu = (SAMPLES / "UDP_NE" / "CTX000000003" / "CTX000000003.conllu").read_text(
        encoding="utf-8"
    )
    parts = conllu.split("# sent_id = 2", 1)
    assert len(parts) == 2
    injected = tmp_path / "CTX000000003.conllu"
    injected.write_text(parts[0] + "# chunk_start = 2\n# sent_id = 2" + parts[1], "utf-8")
    out = tmp_path / "CTX000000003.teitok.xml"
    assert write_teitok_merged(
        str(injected), str(out), str(SAMPLES / "ALTO" / "CTX000000003.alto.xml")
    )
    assert [pb.get("id") for pb in ET.parse(out).getroot().iter("pb")] == ["pb-1"]


def test_split_punctuation_has_no_box_of_its_own():
    """U1: "č." is one ALTO string; UDPipe splits the "." off. The word keeps the string's
    box, the punctuation gets none (flexiconv's alto.py/hocr.py do the same)."""
    root = ET.parse(SAMPLES / "TEITOK" / "CTX000000001.teitok.xml").getroot()
    toks = {t.get("id"): t for t in root.iter("tok")}
    assert (toks["w-3"].text, toks["w-4"].text) == ("č", ".")
    assert toks["w-3"].get("bbox") and toks["w-4"].get("bbox") is None
    dash = next(t for t in toks.values() if t.text == "—")  # its own string: keeps its box
    assert dash.get("bbox")


def test_aligned_pages_out_of_order_are_outliers():
    assert _monotone_keep([1, 1, 3, 1, 2, 2]) == {0, 1, 3, 4, 5}
    units = [{"words": [{}]} for _ in range(6)]
    boxes = [
        {"page_idx": p, "left": 1, "top": 1, "right": 2, "bottom": 2, "line_id": f"l{i}"}
        for i, p in enumerate([1, 1, 3, 1, 2, 2])
    ]
    outliers = _resolve_pages([], units, boxes, {1, 2, 3}, True, None, "doc")
    assert outliers == 1
    assert [u["_page"] for u in units] == [1, 1, 1, 1, 2, 2]
    assert units[2]["_bbox"] is None and units[2]["words"][0]["_page_idx"] == 1


def test_parse_reports_page_order_and_labels():
    rows = read_rows(PAGES / "multichunk.rows.tsv")
    parsed = parse_and_align_conllu(str(PAGES / "multichunk.conllu"), rows=rows)
    assert parsed["page_order"] == [1, 2, 3]
    assert parsed["page_labels"] == {3: "III"}
    assert [s["chunk_start"] for s in parsed["sentences"]] == [False, False, True]


def test_document_record_entities_are_on_their_pages(tmp_path):
    """The hook and the writer resolve pages the same way: "Jan Novák" starts on page 2."""
    out_json = tmp_path / "multichunk.document.json"
    run_document_hook(
        doc_id="multichunk",
        teitok_path="TEITOK/multichunk.teitok.xml",
        conllu_path=str(PAGES / "multichunk.conllu"),
        baseline_json=None,
        out_json=str(out_json),
        run_id="260924-120000",
        paradata_ref="",
        license_detail={},
        rows=read_rows(PAGES / "multichunk.rows.tsv"),
    )
    entities = json.loads(out_json.read_text(encoding="utf-8"))["entities"]
    assert [(e["surface"], e["page"], e["line"]) for e in entities] == [("Jan Novák", "2", 2)]


def test_flexiconv_reads_a_page_break_inside_a_sentence(tmp_path):
    """The pinned flexiconv (v0.3.10) reads the inner <pb/> as an anchor: the tokens, their
    spacing and the sentences come back as written."""
    pytest.importorskip("flexiconv")
    from flexiconv.io.teitok_xml import load_teitok

    doc = load_teitok(str(_write(tmp_path)))
    tokens = [n.features for n in doc.layers["tokens"].nodes.values()]
    assert [t["form"] for t in tokens] == (
        "Alfa beta . Gama delta epsilon . Zeta Jan Novák iota .".split()
    )
    assert [t["space_after"] for t in tokens[:-1]] == [
        True, False, True, True, True, False, True, True, True, True, False,
    ]  # fmt: skip
    sentences = [n.features["text"] for n in doc.layers["sentences"].nodes.values()]
    assert sentences == ["Alfa beta.", "Gama delta epsilon.", "Zeta Jan Novák iota."]
