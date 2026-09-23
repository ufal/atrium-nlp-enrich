"""tests/test_teitok_conformance.py -- the writer's TEITOK, read the way TEITOK tools read it.

``schemas/teitok/teitok.xsd`` checks the *shape* of our output and was written from the
writer itself, so it cannot tell whether the files mean the same thing to the TEITOK
tools (flexipipe, flexiconv, teitok-tools, xmltokenizer). No upstream schema exists, so
conformance is checked here by reading the output back the way those tools do and
comparing it with the CoNLL-U it came from:

* **Spacing is text-faithful.** Whitespace between ``</tok>`` and the next token is a
  space and no whitespace is ``SpaceAfter=No``. flexiconv's ``load_teitok`` is the
  strictest reader: it looks for a literal space character in ``tok.tail``.
* **Multi-word tokens.** The ``<tok>`` text is the surface form and ``<dtok>`` holds the
  syntactic words.
* **Ids.** ``w-N``, ``s-N`` and the rest are unique, and ``@head`` names the head's id.
* **Entities.** ``<name type>`` is coarse, the raw label sits in the tagset attribute and
  ``@sameAs`` lists the tokens.

Lane (a) is stdlib-only and always runs. Lane (b) repeats the round trip through the
pinned flexiconv (``requirements_flexiconv.txt``) when it is installed.

Before 2026-09 every one of these failed: each ``<tok>`` sat on its own line, so upstream
readers saw a space after every token ("č . 1 / 2024"), and "abych" was written as two
tokens, "aby" and "bych".
"""

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "api_util"))

from api_util.teitok_alto import write_teitok_merged  # noqa: E402

CONLLU = (
    "# generator = UDPipe 2, https://lindat.mff.cuni.cz/services/udpipe\n"
    "# udpipe_model = czech-pdt-ud-2.15-241121\n"
    "# sent_id = 1\n"
    "# text = Karel Novák přijel do Prahy, abych viděl hrad.\n"
    "1\tKarel\tKarel\tPROPN\t_\t_\t3\tnsubj\t_\tNER=B-PERSON\n"
    "2\tNovák\tNovák\tPROPN\t_\t_\t1\tflat\t_\tNER=I-PERSON\n"
    "3\tpřijel\tpřijet\tVERB\t_\t_\t0\troot\t_\tNER=O\n"
    "4\tdo\tdo\tADP\t_\t_\t5\tcase\t_\tNER=O\n"
    "5\tPrahy\tPraha\tPROPN\t_\t_\t3\tobl\t_\tSpaceAfter=No|NER=B-GPE\n"
    "6\t,\t,\tPUNCT\t_\t_\t9\tpunct\t_\tNER=O\n"
    "7-8\tabych\t_\t_\t_\t_\t_\t_\t_\t_\n"
    "7\taby\taby\tSCONJ\t_\t_\t9\tmark\t_\tNER=O\n"
    "8\tbych\tbýt\tAUX\t_\tMood=Cnd\t9\taux\t_\tNER=O\n"
    "9\tviděl\tvidět\tVERB\t_\t_\t3\tadvcl\t_\tNER=O\n"
    "10\thrad\thrad\tNOUN\t_\t_\t9\tobj\t_\tSpaceAfter=No|NER=O\n"
    "11\t.\t.\tPUNCT\t_\t_\t3\tpunct\t_\tNER=O\n"
    "\n"
    "# sent_id = 2\n"
    "# text = Hrad stál v roce 1998.\n"
    "1\tHrad\thrad\tNOUN\t_\t_\t2\tnsubj\t_\tNER=O\n"
    "2\tstál\tstát\tVERB\t_\t_\t0\troot\t_\tNER=O\n"
    "3\tv\tv\tADP\t_\t_\t4\tcase\t_\tNER=O\n"
    "4\troce\trok\tNOUN\t_\t_\t2\tobl\t_\tNER=B-DATE\n"
    "5\t1998\t1998\tNUM\t_\t_\t4\tnmod\t_\tSpaceAfter=No|NER=I-DATE\n"
    "6\t.\t.\tPUNCT\t_\t_\t2\tpunct\t_\tSpaceAfter=No|NER=O\n"
    "\n"
)


def _strings(y, words):
    x = 100
    out = []
    for w in words:
        width = 20 * len(w)
        out.append(
            f'<String CONTENT="{w}" HPOS="{x}" VPOS="{y}" WIDTH="{width}" HEIGHT="40"/><SP/>'
        )
        x += width + 20
    return "".join(out)


ALTO = f"""<?xml version="1.0" encoding="UTF-8"?>
<alto xmlns="http://www.loc.gov/standards/alto/ns-v3#">
<Description><MeasurementUnit>pixel</MeasurementUnit></Description>
<Layout><Page ID="P1" WIDTH="2000" HEIGHT="3000"><PrintSpace HPOS="80" VPOS="90" WIDTH="1800" HEIGHT="2800">
<TextBlock ID="TB1" HPOS="100" VPOS="100" WIDTH="1400" HEIGHT="200" LANG="cs">
<TextLine ID="L1" HPOS="100" VPOS="100" WIDTH="1400" HEIGHT="40">{_strings(100, ["Karel", "Novák", "přijel", "do", "Prahy,"])}</TextLine>
<TextLine ID="L2" HPOS="100" VPOS="160" WIDTH="1400" HEIGHT="40">{_strings(160, ["abych", "viděl", "hrad."])}</TextLine>
<TextLine ID="L3" HPOS="100" VPOS="220" WIDTH="1400" HEIGHT="40">{_strings(220, ["Hrad", "stál", "v", "roce", "1998."])}</TextLine>
</TextBlock></PrintSpace></Page></Layout></alto>
"""


def _conllu_sentences(text):
    """Surface units per sentence: ``{"form", "space_after", "words": [(ord, form, head)]}``."""
    sentences, units, sent_text, mwt_end = [], [], None, None
    for line in text.splitlines():
        if line.startswith("# text ="):
            sent_text = line.split("=", 1)[1].strip()
        elif not line.strip():
            if units:
                sentences.append({"text": sent_text, "units": units})
            units, mwt_end = [], None
        elif not line.startswith("#"):
            c = line.split("\t")
            space_after = "SpaceAfter=No" not in c[9]
            if "-" in c[0]:
                mwt_end = int(c[0].split("-")[1])
                units.append({"form": c[1], "space_after": space_after, "words": []})
            elif mwt_end is not None and int(c[0]) <= mwt_end:
                units[-1]["words"].append((c[0], c[1], c[6]))
                if int(c[0]) == mwt_end:
                    mwt_end = None
            else:
                units.append(
                    {"form": c[1], "space_after": space_after, "words": [(c[0], c[1], c[6])]}
                )
    if units:
        sentences.append({"text": sent_text, "units": units})
    return sentences


def _upstream_read(path):
    """Read TEITOK the way flexiconv's ``load_teitok`` / flexipipe do: tokens in document
    order, form = ``tok.text``, space after = a space in ``tok.tail``, ``<dtok>`` = words,
    and ``@head`` resolved through ``@id``."""
    root = ET.parse(str(path)).getroot()
    ids = {}
    for el in root.iter():
        if el.tag in ("tok", "dtok") and el.get("id"):
            ids[el.get("id")] = el
    sentences = []
    for s in root.iter("s"):
        units = []
        for tok in s.iter("tok"):
            dtoks = tok.findall("dtok")
            words = [(d.get("ord"), d.get("form"), d.get("head")) for d in dtoks] or [
                (tok.get("ord"), (tok.text or "").strip(), tok.get("head"))
            ]
            units.append(
                {
                    "form": (tok.text or "").strip(),
                    "space_after": " " in (tok.tail or ""),
                    "words": words,
                    "el": tok,
                }
            )
        text = "".join(u["form"] + (" " if u["space_after"] else "") for u in units).rstrip()
        sentences.append({"text": text, "units": units, "el": s})
    return root, ids, sentences


@pytest.fixture
def written(tmp_path):
    conllu = tmp_path / "CTX.conllu"
    conllu.write_text(CONLLU, encoding="utf-8")
    alto = tmp_path / "CTX.alto.xml"
    alto.write_text(ALTO, encoding="utf-8")
    out = tmp_path / "CTX.teitok.xml"
    assert write_teitok_merged(
        str(conllu), str(out), str(alto), doc_id="CTX", model_nametag="nametag3-multilingual-onto"
    )
    return out


# ── (a) stdlib upstream-style reader ────────────────────────────────────────────────────


def test_sentence_text_is_reconstructed_from_token_spacing(written):
    _, _, sentences = _upstream_read(written)
    expected = _conllu_sentences(CONLLU)
    assert [s["text"] for s in sentences] == [s["text"] for s in expected]


def test_every_space_after_value_survives(written):
    _, _, sentences = _upstream_read(written)
    got = [(u["form"], u["space_after"]) for s in sentences for u in s["units"]]
    exp = [(u["form"], u["space_after"]) for s in _conllu_sentences(CONLLU) for u in s["units"]]
    assert got == exp
    assert sum(1 for _, sa in exp if not sa) == 4


def test_multiword_token_is_one_surface_token_with_dtok_words(written):
    root, _, sentences = _upstream_read(written)
    abych = next(u for u in sentences[0]["units"] if u["form"] == "abych")
    assert [w[:2] for w in abych["words"]] == [("7", "aby"), ("8", "bych")]
    dtoks = abych["el"].findall("dtok")
    assert re.fullmatch(r"w-\d+", abych["el"].get("id"))
    assert [d.get("id") for d in dtoks] == [
        f"{abych['el'].get('id')}.1",
        f"{abych['el'].get('id')}.2",
    ]
    assert dtoks[1].get("lemma") == "být" and dtoks[1].get("feats") == "Mood=Cnd"
    # The surface token, not a word, carries the line position on the page image.
    assert abych["el"].get("bbox") is not None and all(d.get("bbox") is None for d in dtoks)


def test_heads_resolve_through_ids_back_to_the_conllu_heads(written):
    _, ids, sentences = _upstream_read(written)
    for sent, exp in zip(sentences, _conllu_sentences(CONLLU), strict=True):
        got_words = [w for u in sent["units"] for w in u["words"]]
        exp_words = [w for u in exp["units"] for w in u["words"]]
        for (ord_, form, head), (e_ord, e_form, e_head) in zip(got_words, exp_words, strict=True):
            assert (ord_, form) == (e_ord, e_form)
            if e_head == "0":
                assert head is None
            else:
                assert head in ids, f"head {head!r} of {form!r} does not resolve"
                assert ids[head].get("ord") == e_head


def test_ids_are_teitok_native_unique_and_document_global(written):
    root = ET.parse(str(written)).getroot()
    patterns = {
        "tok": r"w-\d+",
        "dtok": r"w-\d+\.\d+",
        "s": r"s-\d+",
        "name": r"n-\d+",
        "surface": r"facs-\d+",
        "pb": r"pb-\d+",
        "lb": r"lb-\d+\.\d+",
        "div": r"b-\d+\.\d+",
    }
    seen = set()
    for el in root.iter():
        if el.tag in patterns:
            assert re.fullmatch(patterns[el.tag], el.get("id")), (el.tag, el.get("id"))
            assert el.get("id") not in seen
            seen.add(el.get("id"))
    tok_ids = [t.get("id") for t in root.iter("tok")]
    assert tok_ids == [f"w-{i}" for i in range(1, len(tok_ids) + 1)]
    assert [s.get("id") for s in root.iter("s")] == ["s-1", "s-2"]
    assert [lb.get("id") for lb in root.iter("lb")] == ["lb-1.1", "lb-1.2", "lb-1.3"]


def test_entities_carry_coarse_type_raw_label_and_sameas(written):
    root = ET.parse(str(written)).getroot()
    names = [
        (n.get("id"), n.get("type"), n.get("onto"), n.get("sameAs")) for n in root.iter("name")
    ]
    assert names == [
        ("n-1", "PER", "PERSON", "#w-1 #w-2"),
        ("n-2", "LOC", "GPE", "#w-5"),
        ("n-3", "MISC", "DATE", "#w-14 #w-15"),
    ]
    assert all(n.get("cnec") is None for n in root.iter("name"))


def test_entity_trailing_space_sits_inside_the_name(written):
    """flexipipe writes it this way, and it is the only placement a tail-based reader
    attributes to the entity's last token."""
    text = written.read_text(encoding="utf-8")
    assert re.search(r">Novák</tok> </name><tok", text)
    assert re.search(r">Prahy</tok></name><tok", text)


def test_line_break_after_a_space_keeps_the_space(written):
    """The space between "Prahy," and "abych" is whitespace before the <lb/>."""
    text = written.read_text(encoding="utf-8")
    assert re.search(r">,</tok>\s+<lb id=\"lb-1\.2\"", text)


def test_header_names_the_workflow_phases(written):
    root = ET.parse(str(written)).getroot()
    changes = {(c.get("who"), c.get("type"), c.get("subtype")) for c in root.iter("change")}
    assert ("altoconvert", "converted", None) in changes
    assert ("udpipe", "tagged", "parsed") in changes
    assert ("nametag", "ner", None) in changes
    assert root.find(".//notesStmt/note[@n='orgfile']").text == "CTX.alto.xml"
    app = root.find(".//application[@ident='atrium-nlp-enrich']")
    assert app is not None and app.get("version") == "teitok-2"
    assert root.get("lang") == "cs"


def test_output_passes_the_xsd_and_the_core_lint(written):
    pytest.importorskip("lxml")
    from api_util.validate_teitok_xml import validate_document

    assert validate_document(written) == []
    assert validate_document(written, profile="core") == []


def test_atrium_readers_agree_with_the_upstream_reading(written):
    """teitok_read (keywords.py, llm_run.py) and an upstream reader see the same text."""
    from api_util.teitok_read import read_teitok_rows, read_teitok_tokens

    rows = read_teitok_rows(written)
    assert [r["text"] for r in rows] == [s["text"] for s in _conllu_sentences(CONLLU)]
    tokens = read_teitok_tokens(written)
    _, _, sentences = _upstream_read(written)
    assert [(t["form"], t["space_after"]) for t in tokens] == [
        (u["form"], u["space_after"]) for s in sentences for u in s["units"]
    ]


# ── (b) pinned flexiconv ────────────────────────────────────────────────────────────────


def test_flexiconv_round_trip(written):
    pytest.importorskip("flexiconv")
    from flexiconv.io.teitok_xml import load_teitok

    doc = load_teitok(str(written))
    tokens = [n.features for n in doc.layers["tokens"].nodes.values()]
    exp = [u for s in _conllu_sentences(CONLLU) for u in s["units"]]
    assert [t["form"] for t in tokens] == [u["form"] for u in exp]
    assert [t["space_after"] for t in tokens[:-1]] == [u["space_after"] for u in exp[:-1]]
    sentences = [n.features["text"] for n in doc.layers["sentences"].nodes.values()]
    assert sentences == [s["text"] for s in _conllu_sentences(CONLLU)]
