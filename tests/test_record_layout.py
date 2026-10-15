"""tests/test_record_layout.py -- TEITOK from a born-digital record (issue #42).

A born-digital PDF has no ALTO; its ATRIUM record (digital-convert ``/reformat``) has
``pages[].canvas`` and ``lines[].bbox``. ``api_util/record_layout.py`` reads the record into
the structures ``teitok_alto._parse_alto()`` returns, so the writer gives it a ``<surface>``
per page and boxed ``<lb>``s and ``<tok>``s. The fixtures are synthetic records made by
digital-convert (``tests/record_layout_data.py``).
"""

import collections
import json
import shutil
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from api_util import doc_identity  # noqa: E402
from api_util.document_hook import run_document_hook  # noqa: E402
from api_util.record_layout import (  # noqa: E402
    parse_record_layout,
    record_has_geometry,
    record_rows,
    text_lines,
    word_boxes,
)
from api_util.teitok_alto import write_teitok_merged  # noqa: E402
from atrium_document import validate_document as validate_record  # noqa: E402
from tests.record_layout_data import conllu_for, record, record_lines, record_path  # noqa: E402

ENTITIES = [(("Horni", "Mezi"), "gu")]


def _write_record(tmp_path, data, name="doc"):
    path = tmp_path / f"{name}.document.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ── the adapter ─────────────────────────────────────────────────────────────────────────


def test_pages_come_from_the_canvases_and_keep_their_labels():
    strings, pages, graphics, _, meta = parse_record_layout(record_path("two_column"))
    assert [(p["idx"], p["width"], p["height"], p["unit"]) for p in pages] == [
        (1, 612.0, 792.0, "pt"),
        (2, 612.0, 792.0, "pt"),
    ]
    assert not any(p.get("facs") for p in pages)  # the record has no page images
    assert meta["page_labels"] == {1: "i", 2: "ii"} and meta["page_count"] == 2
    assert meta["layout_source"] == "record" and meta["measurement_unit"] == "pt"
    assert (meta["orgfile"], meta["record_file"]) == ("two_column.pdf", "two_column.document.json")
    assert meta["converter"] == "digital-convert"
    assert graphics == []
    assert {s["page_idx"] for s in strings} == {1, 2}


def test_word_boxes_share_out_their_line_box():
    strings, *_ = parse_record_layout(record_path("two_column"))
    lines = collections.defaultdict(list)
    for s in strings:
        lines[s["line_id"]].append(s)
    assert len(lines) == 17
    for words in lines.values():
        x1, y1, x2, y2 = map(float, words[0]["line_bbox"].split())
        assert words[0]["left"] == pytest.approx(x1) and words[-1]["right"] == pytest.approx(x2)
        for w in words:
            assert x1 - 1e-3 <= w["left"] < w["right"] <= x2 + 1e-3
            assert (w["top"], w["bottom"]) == pytest.approx((y1, y2))
        assert [w["left"] for w in words] == sorted(w["left"] for w in words)
    first = strings[0]
    assert (first["content"], first["left"], first["right"]) == ("Zprava", 72.0, 99.006)


def test_a_vertical_line_box_is_shared_out_downwards():
    assert word_boxes("ab cd", (10.0, 0.0, 20.0, 50.0)) == [
        ("ab", (10.0, 0.0, 20.0, 20.0)),
        ("cd", (10.0, 30.0, 20.0, 50.0)),
    ]
    # one word keeps the whole box, whatever its shape (a page number)
    assert word_boxes("1", (300.0, 744.0, 305.0, 753.0)) == [("1", (300.0, 744.0, 305.0, 753.0))]
    assert word_boxes("a b", None) == [("a", None), ("b", None)]


def test_blocks_are_the_line_groups_with_their_region():
    _, _, _, blocks, _ = parse_record_layout(record_path("two_column"))
    by_page = collections.defaultdict(list)
    for block in blocks.values():
        by_page[block["page_idx"]].append(block)
    assert [b["subtype"] for b in by_page[1]] == [
        "page_header",
        None,
        None,
        None,
        None,
        "page_footer",
    ]
    assert by_page[1][2]["bbox"] == "72 102.484 203.388 142.484"  # three lines of a column


def test_lines_without_a_box_are_placed_without_coordinates(tmp_path):
    """A hybrid record (atrium-digital-convert#4 W3): OCR re-read page ii, its lines have no
    box. They still give strings, so their tokens keep page and line."""
    data = record("two_column")
    for line in data["lines"]:
        if line["page"] == "ii":
            del line["bbox"]
    strings, pages, *_ = parse_record_layout(_write_record(tmp_path, data))
    on_ii = [s for s in strings if s["page_idx"] == 2]
    assert on_ii and all(s["left"] is None and s["line_bbox"] == "" for s in on_ii)
    assert len({s["line_id"] for s in on_ii}) == 6
    assert [p["idx"] for p in pages] == [1, 2]  # page ii keeps its canvas


def test_untrustworthy_lines_are_left_out_of_text_and_layout(tmp_path):
    data = record("two_column")
    data["lines"][2]["categ"] = "Garbage"
    path = _write_record(tmp_path, data)
    assert "Sonda II odkryla val." not in [line.text for line in text_lines(path)]
    assert "Sonda" not in [s["content"] for s in parse_record_layout(path)[0]]
    assert "Sonda II odkryla val." not in [r["text"] for r in record_rows(path)]


@pytest.mark.parametrize("name", ["two_column", "image_only", "minimal_docx"])
def test_the_table_and_the_layout_are_one_selection(name):
    """A record sent alone: its table (record_rows) and its layout strings carry the same words
    on the same pages, so nothing shifts the character alignment."""
    strings, *_ = parse_record_layout(record_path(name))
    rows = record_rows(record_path(name))
    assert [(r["page_num"], w) for r in rows for w in r["text"].split()] == [
        (s["page_idx"], s["content"]) for s in strings
    ]


def test_rows_number_pages_by_index_and_lines_per_page():
    rows = record_rows(record_path("two_column"))
    assert rows[0] == {"text": "Zprava o vyzkumu Horni Mez", "page_num": 1, "line_num": 1}
    assert [(r["page_num"], r["line_num"]) for r in rows][10:12] == [(1, 11), (2, 1)]


def test_geometry_is_a_canvas_with_a_boxed_line_on_it():
    assert record_has_geometry(record_path("two_column"))
    assert record_has_geometry(record_path("image_only"))
    assert not record_has_geometry(record_path("minimal_docx"))  # DOCX: no canvas, no boxes
    assert not record_has_geometry(b"not json")
    assert not record_has_geometry(
        {  # the box is on a page without a canvas
            "pages": [{"page": "1", "canvas": {"width": 612, "height": 792, "unit": "pt"}}],
            "lines": [{"page": "2", "line": 0, "text": "x", "bbox": [0, 0, 1, 1]}],
        }
    )


# ── the writer ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def two_column(tmp_path):
    conllu = tmp_path / "two_column.conllu"
    conllu.write_text(conllu_for(record_lines("two_column"), ENTITIES), encoding="utf-8")

    def write(**kwargs):
        out = tmp_path / "two_column.teitok.xml"
        assert write_teitok_merged(
            str(conllu), str(out), str(record_path("two_column")), doc_id="two_column", **kwargs
        )
        return ET.parse(out).getroot(), out

    return write


def _toks_inside_their_lb(root):
    """Every token box lies inside the box of the ``<lb>`` before it (rounding aside)."""
    line = None
    for el in root.iter():
        if el.tag == "lb":
            line = [int(v) for v in el.get("bbox").split()]
        elif el.tag == "tok" and el.get("bbox"):
            x1, y1, x2, y2 = (int(v) for v in el.get("bbox").split())
            assert line[0] - 1 <= x1 < x2 <= line[2] + 1 and (y1, y2) == (line[1], line[3])


def test_a_record_gives_a_surface_per_page_and_boxed_lines(two_column, capsys):
    root, path = two_column()
    assert [
        (s.get("id"), s.get("lrx"), s.get("lry"), s.find("graphic").get("url"))
        for s in root.iter("surface")
    ] == [
        ("facs-1", "612", "792", "two_column-1.png"),
        ("facs-2", "612", "792", "two_column-2.png"),
    ]
    assert [(pb.get("n"), pb.get("corresp"), pb.get("bbox")) for pb in root.iter("pb")] == [
        ("i", "#facs-1", "0 0 612 792"),
        ("ii", "#facs-2", "0 0 612 792"),
    ]
    lbs = list(root.iter("lb"))
    assert len(lbs) == 17 and all(lb.get("bbox") for lb in lbs)
    assert lbs[0].get("bbox") == "72 20 189 29"
    assert all(t.get("bbox") for t in root.iter("tok") if t.get("type") == "w")
    _toks_inside_their_lb(root)
    subtypes = [d.get("subtype") for d in root.iter("div")]
    assert subtypes.count("page_header") == 2 and subtypes.count("page_footer") == 2
    assert "page canvases are in pt" in capsys.readouterr().err


def test_the_output_passes_the_xsd_and_the_core_lint(two_column):
    pytest.importorskip("lxml")
    from api_util.validate_teitok_xml import validate_document

    _, path = two_column()
    assert validate_document(path) == []
    assert validate_document(path, profile="core") == []


def test_the_header_names_the_record_and_the_approximate_token_boxes(two_column):
    root, _ = two_column()
    assert root.find(".//note[@n='orgfile']").text == "two_column.pdf"
    assert "two_column.document.json" in root.find(".//sourceDesc/p").text
    writer = root.find(".//application[@ident='atrium-nlp-enrich']/desc").text
    assert "apportioned from line boxes" in writer
    assert root.find(".//application[@ident='digital-convert']") is not None
    changes = {(c.get("who"), c.get("type")) for c in root.iter("change")}
    assert ("digital-convert", "converted") in changes
    assert ("altoconvert", "converted") not in changes


def test_image_dpi_turns_points_into_pixels(two_column, capsys):
    root, _ = two_column(dpi=144)
    assert {(s.get("lrx"), s.get("lry")) for s in root.iter("surface")} == {("1224", "1584")}
    assert next(root.iter("lb")).get("bbox") == "144 40 378 58"
    assert "page canvases are in pt" not in capsys.readouterr().err


def _png(path, width, height):
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x02\0\0\0"
    )


def test_a_page_image_scales_its_page_exactly(two_column, tmp_path):
    pages = tmp_path / "pages"
    pages.mkdir()
    _png(pages / "two_column-1.png", 1836, 2376)  # page i rendered at 216 DPI
    root, _ = two_column(image_dir=str(pages))
    surfaces = {s.get("id"): (s.get("lrx"), s.get("lry")) for s in root.iter("surface")}
    assert surfaces == {"facs-1": ("1836", "2376"), "facs-2": ("612", "792")}
    assert next(root.iter("lb")).get("bbox") == "216 60 567 87"


def test_pages_without_text_keep_their_surface(tmp_path):
    """image_only: a text page, a scanned plate and a blank page (needs_ocr, no lines)."""
    conllu = tmp_path / "image_only.conllu"
    conllu.write_text(conllu_for(record_lines("image_only")), encoding="utf-8")
    out = tmp_path / "image_only.teitok.xml"
    assert write_teitok_merged(
        str(conllu), str(out), str(record_path("image_only")), doc_id="image_only"
    )
    root = ET.parse(out).getroot()
    assert [s.get("id") for s in root.iter("surface")] == ["facs-1", "facs-2", "facs-3"]
    assert [pb.get("corresp") for pb in root.iter("pb")] == ["#facs-1", "#facs-2", "#facs-3"]
    assert [lb.get("id") for lb in root.iter("lb")] == ["lb-1.1"]


# ── which layout stage 4 takes ──────────────────────────────────────────────────────────


def test_the_record_is_the_third_layout_source(tmp_path):
    records, alto_dir = tmp_path / "records", tmp_path / "alto"
    records.mkdir()
    alto_dir.mkdir()
    shutil.copy(record_path("two_column"), records / "X.document.json")
    shutil.copy(record_path("minimal_docx"), records / "D.document.json")
    assert doc_identity.layout_source("X", record_dir=records) == records / "X.document.json"
    assert doc_identity.layout_source("X") is None  # no document-json directory
    assert doc_identity.layout_source("D", record_dir=records) is None  # DOCX: rows
    (alto_dir / "X.alto.xml").write_text("<alto/>", encoding="utf-8")
    assert doc_identity.layout_source("X", alto_dir, record_dir=records) == alto_dir / "X.alto.xml"


# ── the record nlp-enrich hands on ──────────────────────────────────────────────────────


def test_the_hook_keys_pages_by_label_and_boxes_entities_in_points(tmp_path):
    rec = tmp_path / "two_column.document.json"
    shutil.copy(record_path("two_column"), rec)
    conllu = tmp_path / "two_column.conllu"
    conllu.write_text(conllu_for(record_lines("two_column"), ENTITIES), encoding="utf-8")
    teitok = tmp_path / "two_column.teitok.xml"
    assert write_teitok_merged(str(conllu), str(teitok), str(rec), doc_id="two_column")
    run_document_hook(
        doc_id="two_column",
        teitok_path=str(teitok),
        conllu_path=str(conllu),
        baseline_json=str(rec),
        out_json=str(rec),
        run_id="261015-120000",
        paradata_ref="261015-120000_nlp-enrich.json",
        license_detail={},
        alto_path=str(rec),
    )
    out = json.loads(rec.read_text(encoding="utf-8"))
    # the record's own page rows, labelled "i"/"ii" -- not new rows "1"/"2"
    assert [(p["page"], p.get("teitok_surface")) for p in out["pages"]] == [
        ("i", "facs-1"),
        ("ii", "facs-2"),
    ]
    (entity,) = out["entities"]
    assert (entity["surface"], entity["page"], entity["teitok_ref"]) == ("Horni Mezi", "i", "n-1")
    assert entity["bbox"] == pytest.approx([161.024, 64.312, 250.049, 80.312], abs=1e-3)
    assert [(line.get("bbox")) for line in out["lines"]] == [
        line.get("bbox") for line in record("two_column")["lines"]
    ]  # digital-convert's boxes, untouched
    validate_record(out)
