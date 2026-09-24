"""Tests for api_util/validate_teitok_xml.py (issue #28).

Run from the repo root: pytest tests/test_validate_teitok.py -v

Two layers here, and the second is the load-bearing one:

* Curated fixtures in ``tests/fixtures/teitok/`` pin the gate's behaviour
  (accept / reject / diagnostics / exit codes).
* ``TestRealWriterRoundTrip`` runs the actual generator,
  ``api_util/teitok_alto.py::write_teitok_merged``, and validates its output.
  The first version of this gate passed every fixture test while rejecting
  100% of real output, because the fixtures were hand-authored with
  ``xmlns=`` while the writer emits ``xmlnsoff=``. Only a round-trip against
  the real writer catches that class of drift, so it must stay.
"""

import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "api_util"))

pytest.importorskip("lxml", reason="lxml is required for TEITOK XSD validation")

from api_util.validate_teitok_xml import (  # noqa: E402
    DEFAULT_SCHEMA,
    validate_directory,
    validate_document,
)

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "teitok"
REAL_SAMPLES = REPO_ROOT / "data_samples" / "TEITOK"


def test_schema_file_exists():
    assert DEFAULT_SCHEMA.is_file(), f"schema not found at {DEFAULT_SCHEMA}"


def test_valid_fixture_passes(tmp_path):
    shutil.copy(FIXTURES / "CTX_valid.teitok.xml", tmp_path)
    assert validate_directory(tmp_path) is True


def test_no_alto_fallback_fixture_passes(tmp_path):
    """Documents generated without an ALTO source (no bboxes, no
    <facsimile>) must still satisfy the contract."""
    shutil.copy(FIXTURES / "CTX_no_alto.teitok.xml", tmp_path)
    assert validate_directory(tmp_path) is True


def test_invalid_fixture_fails(tmp_path):
    shutil.copy(FIXTURES / "CTX_invalid.teitok.xml", tmp_path)
    assert validate_directory(tmp_path) is False


def test_invalid_fixture_reports_filename_and_diagnostics(tmp_path, capsys):
    shutil.copy(FIXTURES / "CTX_invalid.teitok.xml", tmp_path)
    validate_directory(tmp_path)
    captured = capsys.readouterr()
    assert "CTX_invalid.teitok.xml" in captured.err
    assert "unexpectedElement" in captured.err


def test_mixed_directory_fails_and_names_only_the_bad_file(tmp_path, capsys):
    """A gate over a whole run must fail if *any* document is malformed,
    while still reporting which one(s)."""
    shutil.copy(FIXTURES / "CTX_valid.teitok.xml", tmp_path)
    shutil.copy(FIXTURES / "CTX_no_alto.teitok.xml", tmp_path)
    shutil.copy(FIXTURES / "CTX_invalid.teitok.xml", tmp_path)
    ok = validate_directory(tmp_path)
    captured = capsys.readouterr()
    assert ok is False
    assert "CTX_invalid.teitok.xml" in captured.err
    assert "2/3 documents passed" in captured.err


def test_empty_directory_fails(tmp_path):
    assert validate_directory(tmp_path) is False


def test_missing_directory_fails(tmp_path):
    assert validate_directory(tmp_path / "does_not_exist") is False


def test_nested_layout_is_found_via_rglob(tmp_path):
    """TEITOK_OUTPUT_DIR can be flat or nested per-document; rglob must
    catch both."""
    nested = tmp_path / "some_doc_subdir"
    nested.mkdir()
    shutil.copy(FIXTURES / "CTX_valid.teitok.xml", nested)
    assert validate_directory(tmp_path) is True


# ═════════════════════════════════════════════════════════════════════════════
# Empty runs — the gate must not pre-empt the runner's FAIL_ON_EMPTY decision
# ═════════════════════════════════════════════════════════════════════════════
class TestAllowEmpty:
    def test_missing_directory_is_ok_with_allow_empty(self, tmp_path):
        assert validate_directory(tmp_path / "never_created", allow_empty=True) is True

    def test_empty_directory_is_ok_with_allow_empty(self, tmp_path):
        assert validate_directory(tmp_path, allow_empty=True) is True

    def test_allow_empty_still_rejects_a_bad_document(self, tmp_path):
        """allow_empty relaxes "nothing found", never "found something bad"."""
        shutil.copy(FIXTURES / "CTX_invalid.teitok.xml", tmp_path)
        assert validate_directory(tmp_path, allow_empty=True) is False


# ═════════════════════════════════════════════════════════════════════════════
# Namespace normalization — both TEITOK conventions must validate
# ═════════════════════════════════════════════════════════════════════════════
class TestNamespaceConventions:
    """``teitok_alto.py`` writes ``xmlnsoff=``/``lang=`` (no namespace) -- the curated
    fixtures are real writer output, so they have that shape; older exports and
    ``service/rescale.py`` output carry the real TEI namespace with ``xml:lang``.
    One schema, both accepted."""

    WRITER_ROOT = '<TEI xmlnsoff="http://www.tei-c.org/ns/1.0" lang="cs">'
    TEI_NS_ROOT = '<TEI xmlns="http://www.tei-c.org/ns/1.0" xml:lang="cs">'

    def _as_tei_namespaced(self, src: Path, dest_dir: Path) -> Path:
        text = src.read_text(encoding="utf-8")
        assert self.WRITER_ROOT in text, "fixture root is not the writer's xmlnsoff form"
        out = dest_dir / src.name
        out.write_text(text.replace(self.WRITER_ROOT, self.TEI_NS_ROOT), encoding="utf-8")
        return out

    def test_namespaced_document_passes(self, tmp_path):
        self._as_tei_namespaced(FIXTURES / "CTX_valid.teitok.xml", tmp_path)
        assert validate_directory(tmp_path) is True

    def test_writer_shaped_no_namespace_document_passes(self, tmp_path):
        shutil.copy(FIXTURES / "CTX_valid.teitok.xml", tmp_path)
        assert validate_directory(tmp_path) is True

    def test_namespaced_invalid_document_still_fails(self, tmp_path):
        """Namespace tolerance must not become blanket tolerance."""
        self._as_tei_namespaced(FIXTURES / "CTX_invalid.teitok.xml", tmp_path)
        assert validate_directory(tmp_path) is False

    def test_format1_document_still_validates(self, tmp_path):
        """Backward compatibility: a TEITOK file the pre-2026-09 writer produced (TEI
        namespace, ``CTX.s1.w1`` ids, ``MarginTextZone-P``, one ``<tok>`` per line) must
        not fail a resumed run's gate -- REGENERATE_TEITOK is the migration, not the gate."""
        shutil.copy(FIXTURES / "legacy" / "CTX_format1.teitok.xml", tmp_path)
        assert validate_directory(tmp_path) is True

    def test_foreign_root_element_is_rejected(self, tmp_path):
        (tmp_path / "bogus.teitok.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n<alto><Layout/></alto>\n',
            encoding="utf-8",
        )
        assert validate_directory(tmp_path) is False


# ═════════════════════════════════════════════════════════════════════════════
# Well-formedness-only mode (the flexiconv tier) and the </n> quirk
# ═════════════════════════════════════════════════════════════════════════════
class TestWellformedOnlyMode:
    def test_schema_invalid_but_well_formed_passes_in_wellformed_mode(self, tmp_path):
        """CTX_invalid is well-formed XML that violates the XSD: rejected by
        the full gate, accepted by the well-formedness tier."""
        shutil.copy(FIXTURES / "CTX_invalid.teitok.xml", tmp_path)
        assert validate_directory(tmp_path) is False
        assert validate_directory(tmp_path, wellformed_only=True) is True

    def test_broken_xml_fails_even_in_wellformed_mode(self, tmp_path):
        (tmp_path / "broken.teitok.xml").write_text(
            '<?xml version="1.0"?>\n<TEI><text><body></TEI>\n', encoding="utf-8"
        )
        assert validate_directory(tmp_path, wellformed_only=True) is False

    def test_name_close_quirk_is_reported_with_a_repair_hint(self, tmp_path, capsys):
        """The `<name>...</n>` quirk must fail loudly and point at the fix —
        the gate diagnoses, it never silently repairs."""
        text = (FIXTURES / "CTX_valid.teitok.xml").read_text(encoding="utf-8")
        assert "</name>" in text
        (tmp_path / "quirk.teitok.xml").write_text(
            text.replace("</name>", "</n>"), encoding="utf-8"
        )
        assert validate_directory(tmp_path) is False
        captured = capsys.readouterr()
        assert "not well-formed XML" in captured.err
        assert "fix_teitok_bboxes.py" in captured.err


# ═════════════════════════════════════════════════════════════════════════════
# Single-document entry point (used by the service layer)
# ═════════════════════════════════════════════════════════════════════════════
class TestValidateDocument:
    def test_valid_document_returns_no_diagnostics(self):
        assert validate_document(FIXTURES / "CTX_valid.teitok.xml") == []

    def test_invalid_document_returns_diagnostics(self):
        errors = validate_document(FIXTURES / "CTX_invalid.teitok.xml")
        assert errors
        assert any("unexpectedElement" in e for e in errors)


# ═════════════════════════════════════════════════════════════════════════════
# The published example outputs must satisfy the contract they illustrate
# ═════════════════════════════════════════════════════════════════════════════
#: The samples git tracks, whose inputs are committed too (data_samples/ALTO, UDP_NE).
#: data_samples/ is also the default OUTPUT_DIR of config_api.txt, so a local pipeline run
#: puts its own documents -- possibly written by an older writer -- next to these. Only
#: these three are held to "exactly what today's writer produces".
COMMITTED_SAMPLES = ("CTX000000001", "CTX000000002", "CTX000000003")


def _committed_sample(doc):
    path = REAL_SAMPLES / f"{doc}.teitok.xml"
    assert path.is_file(), f"committed sample data_samples/TEITOK/{path.name} is missing"
    return path


def test_committed_data_samples_are_conformant():
    """README.md advertises data_samples/TEITOK/ as the example output
    directory. Three of those files were once not even well-formed XML
    (`<name>` closed with `</n>`); this keeps them honest.

    The XSD covers the whole directory (format-1 documents from local runs pass it, which
    is the backward compatibility a resumed run relies on); the TEITOK-core rules, which
    format 1 breaks (whitespace after join="right"), apply to the committed samples."""
    assert list(REAL_SAMPLES.glob("*.teitok.xml")), "no committed TEITOK samples found"
    assert validate_directory(REAL_SAMPLES) is True
    for doc in COMMITTED_SAMPLES:
        assert validate_document(_committed_sample(doc), profile="core") == [], doc


def _sample_nametag_model():
    """The NameTag model the committed samples were produced with, as their newest paradata
    record states it (CNEC 2.0 today -- the samples predate the OntoNotes default of #11; a
    sample refresh adds a newer api_3_nt record, which then wins). The UDPipe model needs no
    lookup: the CoNLL-U carries it (``# udpipe_model``)."""
    import json

    for path in sorted((REPO_ROOT / "data_samples" / "paradata").glob("*.json"), reverse=True):
        model = json.loads(path.read_text(encoding="utf-8")).get("config", {}).get("model_nametag")
        if model:
            return model
    return None


@pytest.mark.parametrize("doc", COMMITTED_SAMPLES)
def test_committed_samples_are_what_the_writer_produces_today(doc, tmp_path):
    """The samples used to be artefacts of an older writer (TEI namespace, other bboxes),
    so "the samples validate" said nothing about the code. They must be byte-identical to
    a fresh run of the writer on the committed inputs (ALTO + NER-merged CoNLL-U + the
    models their paradata records), apart from the run dates."""
    import re

    from teitok_alto import write_teitok_merged

    sample = _committed_sample(doc).name
    out = tmp_path / sample
    assert write_teitok_merged(
        str(REPO_ROOT / "data_samples" / "UDP_NE" / doc / f"{doc}.conllu"),
        str(out),
        str(REPO_ROOT / "data_samples" / "ALTO" / f"{doc}.alto.xml"),
        doc_id=doc,
        model_nametag=_sample_nametag_model(),
    )

    def undated(text):
        return re.sub(
            r'(<change when=")\d{4}-\d{2}-\d{2}(" who="(?:altoconvert|udpipe|nametag)")',
            r"\1DATE\2",
            text,
        )

    committed = (REAL_SAMPLES / sample).read_text(encoding="utf-8")
    assert undated(out.read_text(encoding="utf-8")) == undated(committed), (
        f"data_samples/TEITOK/{sample} is stale -- regenerate it (see data_samples/TEITOK "
        "in README.md)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# Round-trip against the real generator — the test that catches writer drift
# ═════════════════════════════════════════════════════════════════════════════
_CONLLU = (
    "# sent_id = 1\n"
    "# text = Jan Novotný v Praze .\n"
    "1\tJan\tJan\tPROPN\t_\t_\t0\troot\t_\tNER=B-P\n"
    "2\tNovotný\tNovotný\tPROPN\t_\t_\t1\tflat\t_\tNER=I-P\n"
    "3\tv\tv\tADP\t_\t_\t4\tcase\t_\tNER=O\n"
    "4\tPraze\tPraha\tPROPN\t_\t_\t1\tobl\t_\tNER=B-gu\n"
    "5\t.\t.\tPUNCT\t_\t_\t1\tpunct\t_\tNER=O\n"
    "\n"
)

_ALTO = """<?xml version="1.0" encoding="UTF-8"?>
<alto xmlns="http://www.loc.gov/standards/alto/ns-v3#">
    <Description><MeasurementUnit>pixel</MeasurementUnit></Description>
    <Layout>
        <Page ID="Page1" PHYSICAL_IMG_NR="1" HEIGHT="3500" WIDTH="2400">
            <PrintSpace HEIGHT="3000" WIDTH="2000" HPOS="0" VPOS="0">
                <TextBlock ID="block_1" HPOS="100" VPOS="100" WIDTH="500" HEIGHT="50">
                    <TextLine ID="line_1" HPOS="100" VPOS="100" WIDTH="500" HEIGHT="50">
                        <String ID="s1" CONTENT="Jan" HPOS="100" VPOS="100" WIDTH="80" HEIGHT="40"/>
                        <String ID="s2" CONTENT="Novotný" HPOS="200" VPOS="100" WIDTH="180" HEIGHT="40"/>
                        <String ID="s3" CONTENT="v" HPOS="400" VPOS="100" WIDTH="20" HEIGHT="40"/>
                        <String ID="s4" CONTENT="Praze" HPOS="440" VPOS="100" WIDTH="140" HEIGHT="40"/>
                        <String ID="s5" CONTENT="." HPOS="590" VPOS="100" WIDTH="10" HEIGHT="40"/>
                    </TextLine>
                </TextBlock>
            </PrintSpace>
        </Page>
    </Layout>
</alto>
"""


class TestRealWriterRoundTrip:
    """Generate TEITOK with the production writer, then validate it against
    the pinned schema. If ``teitok_alto.py``'s output shape drifts — a new
    element, a renamed attribute, a changed root — these fail, which is the
    whole point of calling the schema an output *contract*."""

    def _generate(self, tmp_path, *, with_alto: bool) -> Path:
        from teitok_alto import write_teitok_merged

        conllu = tmp_path / "doc.conllu"
        conllu.write_text(_CONLLU, encoding="utf-8")
        out = tmp_path / "doc.teitok.xml"

        alto_arg = None
        if with_alto:
            alto = tmp_path / "doc.alto.xml"
            alto.write_text(_ALTO, encoding="utf-8")
            alto_arg = str(alto)

        assert write_teitok_merged(str(conllu), str(out), alto_path=alto_arg) is True
        assert out.is_file(), "writer reported success but produced no file"
        return out

    def test_generated_output_with_alto_is_conformant(self, tmp_path):
        out = self._generate(tmp_path, with_alto=True)
        errors = validate_document(out)
        assert errors == [], "real writer output (ALTO/bbox path) violates the XSD:\n" + "\n".join(
            errors
        )

    def test_generated_output_without_alto_is_conformant(self, tmp_path):
        """The text-only fallback branch (no <facsimile>, no bboxes)."""
        out = self._generate(tmp_path, with_alto=False)
        errors = validate_document(out)
        assert errors == [], "real writer output (no-ALTO path) violates the XSD:\n" + "\n".join(
            errors
        )

    def test_generated_output_passes_the_directory_gate(self, tmp_path):
        """End-to-end shape of what api_4_stats.sh actually runs."""
        self._generate(tmp_path, with_alto=True)
        assert validate_directory(tmp_path) is True

    def test_writer_still_emits_the_xmlnsoff_convention(self, tmp_path):
        """Documents the coupling explicitly: the schema has no
        targetNamespace *because* the writer emits `xmlnsoff`. If this
        assertion ever fails, teitok.xsd and _strip_tei_namespace need
        revisiting together — not a one-line schema patch."""
        out = self._generate(tmp_path, with_alto=True)
        head = out.read_text(encoding="utf-8").splitlines()[1]
        assert 'xmlnsoff="http://www.tei-c.org/ns/1.0"' in head
        assert "xmlns=" not in head

    def test_lang_is_not_invented(self, tmp_path):
        """No ALTO LANG, no UDPipe model: no @lang (it used to be a hard-coded "cs")."""
        out = self._generate(tmp_path, with_alto=True)
        head = out.read_text(encoding="utf-8").splitlines()[1]
        assert "lang=" not in head
        assert validate_document(out) == []

    def test_lang_comes_from_alto_then_from_the_udpipe_model(self, tmp_path):
        import xml.etree.ElementTree as ET

        from teitok_alto import write_teitok_merged

        conllu = tmp_path / "doc.conllu"
        conllu.write_text(_CONLLU, encoding="utf-8")
        alto = tmp_path / "doc.alto.xml"
        alto.write_text(_ALTO.replace('ID="block_1"', 'ID="block_1" LANG="sk"'), encoding="utf-8")
        out = tmp_path / "a.teitok.xml"
        assert write_teitok_merged(
            str(conllu), str(out), alto_path=str(alto), model_udpipe="czech-pdt"
        )
        root = ET.parse(str(out)).getroot()
        assert root.get("lang") == "sk"
        assert next(root.iter("language")).get("ident") == "sk"

        out2 = tmp_path / "b.teitok.xml"
        assert write_teitok_merged(str(conllu), str(out2), model_udpipe="czech-pdt-ud-2.15-241121")
        assert ET.parse(str(out2)).getroot().get("lang") == "cs"
        assert validate_document(out) == [] and validate_document(out2) == []

    def test_named_entities_survive_into_conformant_name_elements(self, tmp_path):
        """The NER spans in _CONLLU must become schema-valid <name> wrappers
        (a PER span of two tokens and a LOC span of one)."""
        import xml.etree.ElementTree as ET

        out = self._generate(tmp_path, with_alto=True)
        assert validate_document(out) == []
        names = list(ET.parse(str(out)).getroot().iter("name"))
        assert [n.get("type") for n in names] == ["PER", "LOC"]
        assert [len(list(n.iter("tok"))) for n in names] == [2, 1]


# ═════════════════════════════════════════════════════════════════════════════
# TEITOK-core profile (the flexiconv gate) and --exclude
# ═════════════════════════════════════════════════════════════════════════════
FLEXICONV_FIXTURES = FIXTURES / "flexiconv"


class TestCoreProfile:
    """``--profile core`` checks what every TEITOK tool relies on, for documents our XSD
    does not describe (flexiconv output) -- and still catches real defects."""

    def _doc(self, tmp_path, body, name="doc.teitok.xml"):
        (tmp_path / name).write_text(
            f'<?xml version="1.0" encoding="utf-8"?>\n<TEI><text>{body}</text></TEI>\n',
            encoding="utf-8",
        )
        return tmp_path / name

    def test_real_flexiconv_output_passes_core(self):
        for path in sorted(FLEXICONV_FIXTURES.glob("*.teitok.xml")):
            assert validate_document(path, profile="core") == [], path.name

    def test_real_flexiconv_output_is_not_our_xsd_profile(self):
        """Why flexiconv output needs its own gate: it is valid TEITOK, not our writer's."""
        assert validate_document(FLEXICONV_FIXTURES / "txt.teitok.xml") != []

    def test_duplicate_token_id_fails(self, tmp_path):
        path = self._doc(tmp_path, '<s id="s-1"><tok id="w-1">a</tok> <tok id="w-1">b</tok></s>')
        errors = validate_document(path, profile="core")
        assert any("duplicate @id 'w-1'" in e for e in errors)

    def test_tokens_without_ids_are_allowed(self, tmp_path):
        """flexiconv leaves split-off punctuation without @id; TEITOK numbers it later."""
        path = self._doc(tmp_path, '<p><tok id="w-1">konec</tok><tok>.</tok></p>')
        assert validate_document(path, profile="core") == []

    def test_unresolved_head_fails(self, tmp_path):
        path = self._doc(tmp_path, '<s id="s-1"><tok id="w-1" head="w-9">a</tok></s>')
        assert any("does not resolve" in e for e in validate_document(path, profile="core"))

    def test_resolvable_and_numeric_heads_pass(self, tmp_path):
        path = self._doc(
            tmp_path,
            '<s id="s-1"><tok id="w-1" head="w-2">a</tok> <tok id="w-2" head="0">b</tok></s>',
        )
        assert validate_document(path, profile="core") == []

    def test_join_right_followed_by_whitespace_fails(self, tmp_path):
        """The contradiction the old writer produced on every SpaceAfter=No token: upstream
        TEITOK readers see the whitespace and re-insert the space."""
        path = self._doc(
            tmp_path,
            '<s id="s-1"><tok id="w-1" join="right">Praze</tok>\n<tok id="w-2">.</tok></s>',
        )
        errors = validate_document(path, profile="core")
        assert any("followed by whitespace" in e for e in errors)

    def test_join_right_with_no_gap_passes(self, tmp_path):
        path = self._doc(
            tmp_path, '<s id="s-1"><tok id="w-1" join="right">Praze</tok><tok id="w-2">.</tok></s>'
        )
        assert validate_document(path, profile="core") == []

    def test_negative_bbox_fails(self, tmp_path):
        path = self._doc(tmp_path, '<p><tok id="w-1" bbox="-20 10 30 40">a</tok></p>')
        assert any("non-negative" in e for e in validate_document(path, profile="core"))

    def test_missing_text_element_fails(self, tmp_path):
        (tmp_path / "x.teitok.xml").write_text("<TEI><teiHeader/></TEI>", encoding="utf-8")
        assert "no <text> element" in validate_document(tmp_path / "x.teitok.xml", profile="core")

    def test_core_directory_gate_cli(self, tmp_path):
        from api_util.validate_teitok_xml import main

        for path in FLEXICONV_FIXTURES.glob("*.teitok.xml"):
            shutil.copy(path, tmp_path)
        assert main([str(tmp_path), "--profile", "core", "--quiet"]) == 0
        assert main([str(tmp_path), "--quiet"]) == 1


class TestExclude:
    def test_excluded_subdirectory_is_not_validated(self, tmp_path):
        """api_4_stats.sh validates TEITOK_OUTPUT_DIR with the writer XSD but must leave
        flexiconv's subdirectory (another TEITOK profile, gated by api_flexiconv.sh) out."""
        shutil.copy(FIXTURES / "CTX_valid.teitok.xml", tmp_path)
        flex = tmp_path / "flexiconv"
        flex.mkdir()
        shutil.copy(FLEXICONV_FIXTURES / "txt.teitok.xml", flex)
        assert validate_directory(tmp_path) is False
        assert validate_directory(tmp_path, exclude=[flex]) is True

    def test_exclude_on_cli_is_repeatable(self, tmp_path):
        from api_util.validate_teitok_xml import main

        shutil.copy(FIXTURES / "CTX_valid.teitok.xml", tmp_path)
        for sub in ("a", "b"):
            (tmp_path / sub).mkdir()
            shutil.copy(FIXTURES / "CTX_invalid.teitok.xml", tmp_path / sub)
        argv = [str(tmp_path), "--quiet", "--exclude", str(tmp_path / "a")]
        assert main(argv) == 1
        assert main(argv + ["--exclude", str(tmp_path / "b")]) == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
