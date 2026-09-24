"""
tests/test_teitok_preservation.py
=================================
Content-preservation tests for ``api_util/teitok_alto.write_teitok_merged``
(atrium-project issue #14, intermediate-data checks).

These guard the invariant that converting a NER-enriched CoNLL-U file into
TEITOK XML never drops, merges, or silently alters meaningful input text.
The conversion legitimately *reshapes* text (tokens become <tok> elements,
NER spans gain <name> wrappers, XML special characters are escaped) — the
tests are written to survive those legitimate reshapes but fail the moment a
future change loses a token, reorders tokens, or corrupts content.

When ``alto_path=None`` the function is a pure CoNLL-U -> XML transform: no
ALTO, no images, no bboxes, no network, no models. All tests run in the
default (``not slow``) lane.

CoNLL-U eligibility rule: a token row counts only when it has >= 10
tab-separated columns AND column 0 contains neither '-' (multi-word-token range)
nor '.' (empty/ellipsis node). The CoNLL-U fixtures used here have no multi-word
tokens, so every word is one <tok>; with them, the <tok> text is the surface form
of the range line and the words become <dtok> children
(tests/test_teitok_conformance.py covers that case).
"""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from teitok_alto import write_teitok_merged

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

# Add this mock ALTO string near your other constants
_ALTO_UNIT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<alto xmlns="http://www.loc.gov/standards/alto/ns-v3#">
    <Description><MeasurementUnit>{unit}</MeasurementUnit></Description>
    <Layout>
        <Page ID="Page1" PHYSICAL_IMG_NR="1" HEIGHT="3500" WIDTH="2400">
            <PrintSpace HEIGHT="3000" WIDTH="2000" HPOS="0" VPOS="0">
                <TextBlock ID="block_1" HPOS="100" VPOS="100" WIDTH="500" HEIGHT="50">
                    <TextLine ID="line_1" HPOS="100" VPOS="100" WIDTH="500" HEIGHT="50">
                        <String CONTENT="Test" HPOS="100" VPOS="100" WIDTH="500" HEIGHT="50"/>
                    </TextLine>
                </TextBlock>
            </PrintSpace>
        </Page>
    </Layout>
</alto>
"""

_ALTO_MARGIN_XML = """<?xml version="1.0" encoding="UTF-8"?>
<alto xmlns="http://www.loc.gov/standards/alto/ns-v3#">
    <Layout>
        <Page ID="Page1" PHYSICAL_IMG_NR="1" HEIGHT="3500" WIDTH="2400">
            <PrintSpace HEIGHT="3000" WIDTH="2000" HPOS="200" VPOS="100">
                <TextBlock ID="block_1" HPOS="250" VPOS="150" WIDTH="500" HEIGHT="50">
                    <TextLine ID="line_1" HPOS="250" VPOS="150" WIDTH="500" HEIGHT="50">
                        <String CONTENT="Test" HPOS="250" VPOS="150" WIDTH="500" HEIGHT="50"/>
                    </TextLine>
                </TextBlock>
            </PrintSpace>
        </Page>
    </Layout>
</alto>
"""

_PAGE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15">
    <Page imageWidth="2400" imageHeight="3500">
        <TextRegion id="r1">
            <Coords points="100,100 600,100 600,150 100,150"/>
            <TextLine id="l1">
                <Coords points="100,100 600,100 600,150 100,150"/>
                <Word id="w1">
                    <Coords points="100,100 600,100 600,150 100,150"/>
                    <TextEquiv><Unicode>Test</Unicode></TextEquiv>
                </Word>
            </TextLine>
        </TextRegion>
    </Page>
</PcGts>
"""

_HOCR_HTML = """<!DOCTYPE html>
<html>
<head><title></title></head>
<body>
    <div class="ocr_page" id="page_1" title="image 'test.png'; bbox 0 0 2400 3500; ppageno 0">
        <div class="ocr_carea" id="block_1_1" title="bbox 100 100 600 150">
            <span class="ocr_line" id="line_1_1" title="bbox 100 100 600 150">
                <span class="ocrx_word" id="word_1_1" title="bbox 100 100 600 150">Test</span>
            </span>
        </div>
    </div>
</body>
</html>
"""

_ALTO_CONLLU = "# sent_id = 1\n# text = Test\n1\tTest\tTest\tNOUN\t_\t_\t0\troot\t_\t_\n\n"


# ═════════════════════════════════════════════════════════════════════════════
# Spatial Bounding Box Math (Issues #4 & #9)
# ═════════════════════════════════════════════════════════════════════════════
class TestSpatialAlignment:
    def test_page_origin_is_the_default(self, tmp_path):
        """TEITOK bboxes are page-image pixels from the page's top-left corner (the
        convention of flexiconv/teitok-tools, and of the ALTO coordinates themselves), and
        <surface> declares the page extent they live in."""
        conllu_file = _write_conllu(tmp_path, _ALTO_CONLLU, "test.conllu")
        alto_file = Path(tmp_path) / "test.alto.xml"
        alto_file.write_text(_ALTO_MARGIN_XML, encoding="utf-8")
        out = Path(tmp_path) / "test.teitok.xml"

        write_teitok_merged(str(conllu_file), str(out), alto_path=str(alto_file))
        root = ET.parse(str(out)).getroot()
        assert next(root.iter("tok")).get("bbox") == "250 150 750 200"
        surf = next(root.iter("surface"))
        assert (surf.get("lrx"), surf.get("lry")) == ("2400", "3500")

    def test_printspace_origin_is_opt_in_and_self_consistent(self, tmp_path):
        """BBOX_ORIGIN=printspace: shift by the PrintSpace origin AND declare a
        PrintSpace-sized surface. The old writer shifted the boxes but kept the full page
        size on <surface>, so the document contradicted itself."""
        conllu_file = _write_conllu(tmp_path, _ALTO_CONLLU, "test.conllu")
        alto_file = Path(tmp_path) / "test.alto.xml"
        alto_file.write_text(_ALTO_MARGIN_XML, encoding="utf-8")
        out = Path(tmp_path) / "test.teitok.xml"

        write_teitok_merged(
            str(conllu_file), str(out), alto_path=str(alto_file), bbox_origin="printspace"
        )
        root = ET.parse(str(out)).getroot()
        assert next(root.iter("tok")).get("bbox") == "50 50 550 100"
        surf = next(root.iter("surface"))
        assert (surf.get("lrx"), surf.get("lry")) == ("2000", "3000")
        assert "bbox origin: printspace" in next(root.iter("desc")).text

    def test_printspace_clamps_margin_content_to_zero(self, tmp_path, capsys):
        """Content left of / above the PrintSpace would get negative coordinates, which
        no image has; they are clamped (and counted) instead."""
        conllu_file = _write_conllu(tmp_path, _ALTO_CONLLU, "test.conllu")
        alto_file = Path(tmp_path) / "test.alto.xml"
        alto_file.write_text(
            _ALTO_MARGIN_XML.replace(
                'HPOS="250" VPOS="150" WIDTH="500"', 'HPOS="150" VPOS="150" WIDTH="500"'
            ),
            encoding="utf-8",
        )
        out = Path(tmp_path) / "test.teitok.xml"
        write_teitok_merged(
            str(conllu_file), str(out), alto_path=str(alto_file), bbox_origin="printspace"
        )
        bbox = next(ET.parse(str(out)).getroot().iter("tok")).get("bbox")
        assert bbox == "0 50 450 100"
        assert "clamped to 0" in capsys.readouterr().err

    def test_unknown_bbox_origin_is_an_error(self, tmp_path):
        conllu_file = _write_conllu(tmp_path, _ALTO_CONLLU, "test.conllu")
        with pytest.raises(ValueError, match="bbox_origin"):
            write_teitok_merged(str(conllu_file), str(tmp_path / "x.xml"), bbox_origin="margin")

    def test_tier2_mm10(self, tmp_path):
        conllu_file = _write_conllu(tmp_path, _ALTO_CONLLU, "test.conllu")
        alto_file = Path(tmp_path) / "test.alto.xml"
        alto_file.write_text(_ALTO_UNIT_XML.format(unit="mm10"), encoding="utf-8")
        out = Path(tmp_path) / "test.teitok.xml"

        write_teitok_merged(str(conllu_file), str(out), alto_path=str(alto_file), dpi=300)
        root = ET.parse(str(out)).getroot()
        tok = next(root.iter("tok"))
        surf = next(root.iter("surface"))
        assert tok.get("bbox").startswith("118 118")
        assert surf.get("lrx") == "2835"

    def test_tier2_inch1200(self, tmp_path):
        conllu_file = _write_conllu(tmp_path, _ALTO_CONLLU, "test.conllu")
        alto_file = Path(tmp_path) / "test.alto.xml"
        alto_file.write_text(_ALTO_UNIT_XML.format(unit="inch1200"), encoding="utf-8")
        out = Path(tmp_path) / "test.teitok.xml"

        write_teitok_merged(str(conllu_file), str(out), alto_path=str(alto_file), dpi=300)
        root = ET.parse(str(out)).getroot()
        tok = next(root.iter("tok"))
        assert tok.get("bbox").startswith("25 25")

    def test_tier2_pixel(self, tmp_path):
        conllu_file = _write_conllu(tmp_path, _ALTO_CONLLU, "test.conllu")
        alto_file = Path(tmp_path) / "test.alto.xml"
        alto_file.write_text(_ALTO_UNIT_XML.format(unit="pixel"), encoding="utf-8")
        out = Path(tmp_path) / "test.teitok.xml"

        write_teitok_merged(
            str(conllu_file), str(out), alto_path=str(alto_file), dpi=150, alto_dpi=300
        )
        root = ET.parse(str(out)).getroot()
        tok = next(root.iter("tok"))
        assert tok.get("bbox").startswith("50 50")

    def test_tier1_image_wins_over_dpi(self, tmp_path):
        conllu_file = _write_conllu(tmp_path, _ALTO_CONLLU, "test.conllu")
        alto_file = Path(tmp_path) / "test.alto.xml"
        alto_file.write_text(_ALTO_UNIT_XML.format(unit="mm10"), encoding="utf-8")
        out = Path(tmp_path) / "test.teitok.xml"

        import struct

        img_file = Path(tmp_path) / "test-1.png"
        png_header = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
            + struct.pack(">I", 1200)
            + struct.pack(">I", 1750)
        )
        img_file.write_bytes(png_header)

        write_teitok_merged(
            str(conllu_file),
            str(out),
            alto_path=str(alto_file),
            image_dir=str(tmp_path),
            dpi=300,
            doc_id="test",
        )
        root = ET.parse(str(out)).getroot()
        tok = next(root.iter("tok"))
        assert tok.get("bbox").startswith("50 50")


def _eligible_tokens(conllu_path):
    tokens = []
    with open(conllu_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) < 10 or "-" in cols[0] or "." in cols[0]:
                continue
            misc = cols[9]
            tokens.append(
                {
                    "form": cols[1],
                    "ner": _ner_from_misc(misc),
                    "space_after": "SpaceAfter=No" not in misc,
                }
            )
    return tokens


def _ner_from_misc(misc):
    if misc in ("_", ""):
        return ""
    for item in misc.split("|"):
        if item.startswith("NER="):
            return item[len("NER=") :]
    return ""


def _convert(conllu_path, tmp_path, name="out.teitok.xml"):
    out = Path(tmp_path) / name
    ok = write_teitok_merged(str(conllu_path), str(out), alto_path=None)
    assert ok is True, "write_teitok_merged returned False"
    assert out.exists(), "no TEITOK output produced"
    return out


def _tok_texts(root):
    return [el.text or "" for el in root.iter("tok")]


def _nonspace(chars_iterable):
    return "".join("".join(s.split()) for s in chars_iterable)


def _write_conllu(tmp_path, body, name="crafted.conllu"):
    p = Path(tmp_path) / name
    p.write_text(body, encoding="utf-8")
    return str(p)


_NER_CONLLU = (
    "# sent_id = 1\n"
    "# text = Jan Novotný v Praze .\n"
    "1\tJan\tJan\tPROPN\t_\t_\t0\troot\t_\tNER=B-P\n"
    "2\tNovotný\tNovotný\tPROPN\t_\t_\t1\tflat\t_\tNER=I-P\n"
    "3\tv\tv\tADP\t_\t_\t4\tcase\t_\tNER=O\n"
    "4\tPraze\tPraha\tPROPN\t_\t_\t1\tobl\t_\tNER=B-gu\n"
    "5\t.\t.\tPUNCT\t_\t_\t1\tpunct\t_\tNER=O\n"
    "\n"
)

_SPECIAL_CONLLU = (
    "# sent_id = 1\n"
    '# text = a < b & c " d\n'
    "1\ta<b\ta\tNOUN\t_\t_\t0\troot\t_\t_\n"
    "2\tc&d\tc\tNOUN\t_\t_\t1\tnmod\t_\t_\n"
    '3\te"f\te\tNOUN\t_\t_\t1\tnmod\t_\t_\n'
    "\n"
)


class TestWellFormed:
    def test_output_is_well_formed_tei(self, sample_conllu, tmp_path):
        out = _convert(sample_conllu, tmp_path)
        root = ET.parse(str(out)).getroot()
        assert root.tag == "TEI"

    def test_ner_document_is_well_formed(self, tmp_path):
        cp = _write_conllu(tmp_path, _NER_CONLLU)
        out = _convert(cp, tmp_path, "ner.teitok.xml")
        root = ET.parse(str(out)).getroot()
        assert root.tag == "TEI"


class TestTokenPreservation:
    def test_every_form_present_as_tok(self, sample_conllu, tmp_path):
        out = _convert(sample_conllu, tmp_path)
        root = ET.parse(str(out)).getroot()
        emitted = _tok_texts(root)
        expected = [t["form"] for t in _eligible_tokens(sample_conllu)]
        assert emitted == expected

    def test_tok_count_matches_eligible_tokens(self, sample_conllu, tmp_path):
        out = _convert(sample_conllu, tmp_path)
        root = ET.parse(str(out)).getroot()
        assert len(_tok_texts(root)) == len(_eligible_tokens(sample_conllu))

    def test_no_meaningful_text_dropped(self, sample_conllu, tmp_path):
        out = _convert(sample_conllu, tmp_path)
        root = ET.parse(str(out)).getroot()
        got = _nonspace(_tok_texts(root))
        exp = _nonspace(t["form"] for t in _eligible_tokens(sample_conllu))
        assert got == exp

    def test_sentence_text_reconstructs_from_tokens(self, sample_conllu, tmp_path):
        out = _convert(sample_conllu, tmp_path)
        root = ET.parse(str(out)).getroot()
        sentences = list(root.iter("s"))
        assert sentences, "no <s> elements emitted"
        checked = 0
        for s in sentences:
            text_attr = s.get("text")
            if not text_attr:
                continue
            rebuilt = ""
            for tok in s.iter("tok"):
                rebuilt += tok.text or ""
                rebuilt += "" if tok.get("join") == "right" else " "
            assert "".join(rebuilt.split()) == "".join(text_attr.split())
            checked += 1
        assert checked > 0


class TestSpecialChars:
    def test_special_chars_escaped_and_preserved(self, tmp_path):
        cp = _write_conllu(tmp_path, _SPECIAL_CONLLU, "special.conllu")
        out = _convert(cp, tmp_path, "special.teitok.xml")
        root = ET.parse(str(out)).getroot()
        emitted = _tok_texts(root)
        assert emitted == ["a<b", "c&d", 'e"f']


class TestNerSpans:
    def test_ner_span_tokens_all_preserved(self, tmp_path):
        cp = _write_conllu(tmp_path, _NER_CONLLU)
        out = _convert(cp, tmp_path, "ner.teitok.xml")
        root = ET.parse(str(out)).getroot()

        assert _tok_texts(root) == ["Jan", "Novotný", "v", "Praze", "."]

        name_tok_texts = []
        for name in root.iter("name"):
            name_tok_texts.extend(t.text for t in name.iter("tok"))
        assert "Jan" in name_tok_texts
        assert "Novotný" in name_tok_texts
        assert "Praze" in name_tok_texts
        assert "v" not in name_tok_texts
        assert "." not in name_tok_texts

    def test_name_wrapper_types_mapped(self, tmp_path):
        cp = _write_conllu(tmp_path, _NER_CONLLU)
        out = _convert(cp, tmp_path, "ner.teitok.xml")
        root = ET.parse(str(out)).getroot()
        types = {n.get("type") for n in root.iter("name")}
        assert "PER" in types
        assert "LOC" in types


class TestPageBoundaries:
    def test_all_tokens_present_across_two_page_reset(self, two_page_conllu, tmp_path):
        out = _convert(two_page_conllu, tmp_path, "twopage.teitok.xml")
        root = ET.parse(str(out)).getroot()
        assert _tok_texts(root) == [t["form"] for t in _eligible_tokens(two_page_conllu)]
        assert len(list(root.iter("pb"))) == 2

    def test_a_chunk_marker_is_not_a_page_break(self, page_break_conllu, tmp_path):
        """``# page_break = true`` marked a UDPipe chunk start, not a page (issue #38, A)."""
        out = _convert(page_break_conllu, tmp_path, "pb.teitok.xml")
        root = ET.parse(str(out)).getroot()
        assert _tok_texts(root) == [t["form"] for t in _eligible_tokens(page_break_conllu)]
        assert len(list(root.iter("pb"))) == 1
        assert next(root.iter("pb")).get("facs") is None  # no page image: no invented facs


# ═════════════════════════════════════════════════════════════════════════════
# Non-ALTO layout formats (Issue #10)
# ═════════════════════════════════════════════════════════════════════════════
# PAGE XML and hOCR never reach this writer: they enter through flexiconv
# (api_flexiconv.sh), which writes its own TEITOK. What must hold is (a) that the writer
# does not pretend to read them, and (b) that flexiconv's TEITOK uses the same coordinate
# convention as this writer's default, so both kinds of file overlay the same page image.
_FLEXICONV_FIXTURES = Path(__file__).parent / "fixtures" / "teitok" / "flexiconv"


class TestNonAltoLayoutFormats:
    def test_page_xml_is_not_read_as_alto(self, tmp_path):
        conllu_file = _write_conllu(tmp_path, _ALTO_CONLLU, "test.conllu")
        page_file = Path(tmp_path) / "test.page.xml"
        page_file.write_text(_PAGE_XML, encoding="utf-8")
        out = Path(tmp_path) / "test.teitok.xml"

        assert write_teitok_merged(str(conllu_file), str(out), alto_path=str(page_file))
        root = ET.parse(str(out)).getroot()
        assert _tok_texts(root) == ["Test"]
        assert next(root.iter("tok")).get("bbox") is None
        assert root.find("facsimile") is None

    def test_hocr_is_not_read_as_alto(self, tmp_path):
        conllu_file = _write_conllu(tmp_path, _ALTO_CONLLU, "test.conllu")
        hocr_file = Path(tmp_path) / "test.hocr"
        hocr_file.write_text(_HOCR_HTML, encoding="utf-8")
        out = Path(tmp_path) / "test.teitok.xml"

        assert write_teitok_merged(str(conllu_file), str(out), alto_path=str(hocr_file))
        assert next(ET.parse(str(out)).getroot().iter("tok")).get("bbox") is None

    def test_flexiconv_page_xml_bboxes_are_page_origin_pixels(self):
        """flexiconv's PAGE XML import keeps the PAGE Coords as they are: word 1 of the
        fixture is Coords "100,100 300,100 300,150 100,150"."""
        root = ET.parse(str(_FLEXICONV_FIXTURES / "page.teitok.xml")).getroot()
        assert next(root.iter("tok")).get("bbox") == "100 100 300 150"

    def test_flexiconv_hocr_bboxes_are_page_origin_pixels(self):
        root = ET.parse(str(_FLEXICONV_FIXTURES / "hocr.teitok.xml")).getroot()
        assert next(root.iter("pb")).get("bbox") == "0 0 2162 3340"
        assert next(root.iter("tok")).get("bbox") == "802 1263 1327 1337"
