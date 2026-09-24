"""api_util/teitok_layout.py -- flexiconv TEITOK read as a layout source (issue #10, stage 6).

The fixtures are real flexiconv v0.3.10 output (tests/fixtures/teitok/flexiconv/). The
result must have the shape teitok_alto._parse_alto() gives for ALTO, and its character
stream must be the text teitok_read hands stage 1 -- that is what lets every UDPipe token
align back to a place on the page.
"""

import re
from pathlib import Path

import pytest

from api_util import teitok_alto
from api_util.teitok_layout import is_teitok, parse_teitok_layout, source_name
from api_util.teitok_read import parse_teitok, read_teitok_rows

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "teitok" / "flexiconv"
KINDS = ("alto", "hocr", "md", "page", "txt")


def _layout(kind):
    return parse_teitok_layout(FIXTURES / f"{kind}.teitok.xml")


@pytest.mark.parametrize("kind", KINDS)
def test_character_stream_is_the_stage_1_text(kind):
    strings, *_ = _layout(kind)
    rows = read_teitok_rows(FIXTURES / f"{kind}.teitok.xml")

    def chars(text):
        return re.sub(r"\s", "", text)

    assert chars("".join(s["content"] for s in strings)) == chars("".join(r["text"] for r in rows))


@pytest.mark.parametrize("kind", KINDS)
def test_shape_matches_the_alto_parser(kind):
    strings, pages, graphics, blocks, meta = _layout(kind)
    alto_keys = {"content", "left", "top", "right", "bottom", "page_idx", "block_id", "line_id"}
    assert all(alto_keys | {"line_bbox", "lang"} <= set(s) for s in strings)
    assert all(s["block_id"] in blocks for s in strings)
    for page in pages:
        assert {"id", "width", "height", "idx", "ps_hpos", "ps_vpos", "facs"} <= set(page)
    assert meta["layout_source"] == "teitok" and meta["measurement_unit"] == "pixel"
    assert isinstance(graphics, list)


def test_page_xml_keeps_word_and_line_boxes():
    strings, pages, _, blocks, meta = _layout("page")
    assert [s["content"] for s in strings[:5]] == ["Výzkum", "proběhl", "v", "Praze", "."]
    first = strings[0]
    assert (first["left"], first["top"], first["right"], first["bottom"]) == (100, 100, 300, 150)
    assert first["line_bbox"] == "100 100 1100 150"
    assert strings[4]["left"] is None  # flexiconv did not box the full stop
    assert strings[5]["line_id"] != first["line_id"]  # second <lb/>
    assert pages == [
        {
            "id": "e-1",
            "width": "",
            "height": "",
            "idx": 1,
            "ps_hpos": 0,
            "ps_vpos": 0,
            "ps_width": 0,
            "ps_height": 0,
            "facs": "sample_page/page1.png",
        }
    ]
    assert list(blocks.values()) == [{"bbox": "100 100 1100 300", "subtype": None, "page_idx": 1}]
    # no appInfo in flexiconv's PAGE XML output: the converter comes from the change record
    assert (meta["converter"], meta["orgfile"]) == ("flexiconv", "sample_page.xml")
    assert meta["source_image"] == "sample_page/page1.png"


def test_hocr_page_size_language_and_paragraph_blocks():
    strings, pages, _, blocks, meta = _layout("hocr")
    assert (pages[0]["width"], pages[0]["height"], pages[0]["facs"]) == (
        "2162",
        "3340",
        "output_page_1.png",
    )
    assert {b["subtype"] for b in blocks.values()} == {"p"}
    assert len(blocks) == 2
    assert {s["lang"] for s in strings} == {"en"}
    assert (meta["converter"], meta["converter_version"]) == ("flexiconv", "1.0")


def test_untokenized_documents_give_words_without_coordinates_and_no_facsimile():
    strings, pages, _, blocks, meta = _layout("txt")
    assert pages == []  # no <pb>: nothing to show a facsimile for
    assert [s["content"] for s in strings][:3] == ["Výzkum", "proběhl", "v"]
    assert all(s["left"] is None and s["line_id"] is None for s in strings)
    assert [b["subtype"] for b in blocks.values()] == ["p", "p"]
    assert meta["orgfile"] == "sample_txt.txt"


def test_markdown_structure_becomes_block_subtypes():
    strings, _, _, blocks, _ = _layout("md")
    assert [b["subtype"] for b in blocks.values()] == ["head", "p", "item"]
    assert "důležitý." in [s["content"] for s in strings]  # <hi> text inside the paragraph


def test_pages_are_numbered_like_teitok_read_rows(tmp_path):
    """The first <pb> opens page 1 (converters put it first); a <pb> inside an untokenized
    block starts the next page after that block -- exactly the pages teitok_read gives the
    rows stage 1 sends to UDPipe."""
    doc = tmp_path / "d.teitok.xml"
    doc.write_text(
        "<TEI><text><body><pb/><p>a b</p><p>c <pb facs='p2.png'/>d</p><p>e</p></body></text></TEI>",
        encoding="utf-8",
    )
    strings, pages, *_ = parse_teitok_layout(doc)
    assert [(s["content"], s["page_idx"]) for s in strings] == [
        ("a", 1),
        ("b", 1),
        ("c", 1),
        ("d", 1),
        ("e", 2),
    ]
    assert [r["page_num"] for r in read_teitok_rows(doc)] == [1, 1, 2]
    assert [p["idx"] for p in pages] == [2]  # only the page that names an image


def test_surfaces_images_sizes_and_labels(tmp_path):
    """P5 (issue #38, C): a <pb> without @corresp takes the k-th <surface>; the image may
    only be in its <graphic url>, the size in @lrx/@lry or graphic@width/@height; pb@n is
    kept as the page's label."""
    doc = tmp_path / "d.teitok.xml"
    doc.write_text(
        "<TEI><facsimile>"
        "<surface id='s1' lrx='800' lry='1200'><graphic url='one.jpg'/></surface>"
        "<surface id='s2'><graphic url='two.jpg' width='640px' height='960'/></surface>"
        "</facsimile><text><body>"
        "<pb n='I'/><p>a</p><pb n='2'/><p>b</p><pb n='7a' corresp='#s1'/><p>c</p>"
        "</body></text></TEI>",
        encoding="utf-8",
    )
    _, pages, _, _, meta = parse_teitok_layout(doc)
    assert [(p["idx"], p["facs"], p["width"], p["height"]) for p in pages] == [
        (1, "one.jpg", "800", "1200"),
        (2, "two.jpg", "640", "960"),
        (3, "one.jpg", "800", "1200"),
    ]
    assert meta["page_labels"] == {1: "I", 3: "7a"}
    assert meta["page_count"] == 3


def test_text_before_the_first_page_break_is_page_one(tmp_path):
    """Same page ordinals as teitok_read's ``page_idx`` (the pages stage 1 records)."""
    doc = tmp_path / "d.teitok.xml"
    doc.write_text(
        "<TEI><text><body><p>title</p><pb n='1'/><p>body</p></body></text></TEI>",
        encoding="utf-8",
    )
    strings, _, _, _, meta = parse_teitok_layout(doc)
    assert [(s["content"], s["page_idx"]) for s in strings] == [("title", 1), ("body", 2)]
    assert [r["page_idx"] for r in read_teitok_rows(doc)] == [1, 2]
    assert meta["page_labels"] == {2: "1"}


def test_writer_dispatches_tei_roots_to_the_layout_reader():
    path = FIXTURES / "page.teitok.xml"
    assert teitok_alto._parse_alto(str(path)) == parse_teitok_layout(path)


def test_unreadable_file_gives_an_empty_layout(tmp_path, capsys):
    bad = tmp_path / "bad.teitok.xml"
    bad.write_text("<TEI><text>", encoding="utf-8")
    strings, pages, graphics, blocks, meta = parse_teitok_layout(bad)
    assert (strings, pages, graphics, blocks) == ([], [], [], {})
    assert "Failed to parse TEITOK layout" in capsys.readouterr().err


def test_helpers(tmp_path):
    assert is_teitok(FIXTURES / "txt.teitok.xml")
    alto = tmp_path / "x.alto.xml"
    alto.write_text("<alto/>", encoding="utf-8")
    assert not is_teitok(alto)
    assert not is_teitok(tmp_path / "missing.xml")
    assert source_name(parse_teitok(FIXTURES / "alto.teitok.xml")) == "sample_alto.xml"
