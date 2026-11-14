import json

from api_util import summarize_nt_udp
from api_util.summarize_nt_udp import get_ne_explanation
from atrium_paradata import ParadataLogger


class TestNameTagExplanationMapping:
    def test_native_onto_tags(self):
        """Test that native ONTO tags are correctly resolved to their descriptions."""
        assert get_ne_explanation("B-PERSON") == "People, including fictional"
        assert get_ne_explanation("I-ORG") == "Companies, agencies, institutions, etc."
        assert get_ne_explanation("B-GPE") == "Countries, cities, states"

    def test_legacy_cnec_mapped_to_onto(self):
        """Test that legacy CNEC tags are correctly bridged to ONTO descriptions."""
        # 'p' -> 'PERSON'
        assert get_ne_explanation("B-p") == "People, including fictional"
        # 'i' -> 'ORG'
        assert get_ne_explanation("I-i") == "Companies, agencies, institutions, etc."
        # 'g' -> 'GPE'
        assert get_ne_explanation("B-g") == "Countries, cities, states"

    def test_complex_tag_strings(self):
        """Test that compound tags separated by pipes correctly read the primary tag."""
        assert get_ne_explanation("B-PERSON|I-p") == "People, including fictional"
        assert get_ne_explanation("I-g|B-GPE") == "Countries, cities, states"

    def test_empty_and_o_tags(self):
        """Test that 'O', empty strings, and None return an empty string."""
        assert get_ne_explanation("O") == ""
        assert get_ne_explanation("_") == ""
        assert get_ne_explanation("") == ""
        assert get_ne_explanation(None) == ""

    def test_unknown_tags(self):
        """Test that completely unknown tags fall back gracefully."""
        explanation = get_ne_explanation("B-unknown_xyz")
        assert "Unknown Code" in explanation
        assert "unknown_xyz" in explanation


def _stage_state(tmp_path):
    para_dir = tmp_path / "paradata"
    para_dir.mkdir()
    stage = ParadataLogger("nlp-enrich", {}, paradata_dir=str(para_dir))
    state = para_dir / ".state_1_nlp-enrich.json"
    state.write_text(json.dumps(stage._to_state_dict()), encoding="utf-8")
    return state


def _one_document(tmp_path, monkeypatch, hook):
    """process_single_document over a merged CoNLL-U already there, with the record hook stubbed."""
    import api_util.document_hook as document_hook

    out = tmp_path / "out"
    out.mkdir()
    (out / "CTX.conllu").write_text("# sent_id = 1\n1\tPraha\tPraha\tPROPN\n\n", "utf-8")
    records = tmp_path / "records"
    records.mkdir()
    (records / "CTX.document.json").write_text('{"doc_id": "CTX"}', encoding="utf-8")
    monkeypatch.setattr(document_hook, "run_document_hook", hook)
    state = _stage_state(tmp_path)
    ok = summarize_nt_udp.process_single_document(
        conllu_file=str(tmp_path / "CTX.conllu"),
        ne_dir=str(tmp_path / "ne"),
        output_dir=str(out),
        save_csv=False,
        document_json_dir=str(records),
        para_state=str(state),
    )
    return ok, json.loads(state.read_text(encoding="utf-8"))


def test_the_record_read_and_written_go_into_the_stages_paradata(tmp_path, monkeypatch):
    """Paradata 3.0 (atrium-project#84): the record carries no run data; the stage's state file
    (--para-state) gets the record version read and the record written, each by SHA-512, the
    output with the blocks and fields the hook wrote. No local path is recorded."""
    import hashlib

    read = {}

    def hook(**kw):
        read["bytes"] = open(kw["baseline_json"], "rb").read()
        with open(kw["out_json"], "w", encoding="utf-8") as fh:
            fh.write('{"doc_id": "CTX", "entities": []}')
        return {"entities": ["surface", "page", "line"]}

    ok, state = _one_document(tmp_path, monkeypatch, hook)
    assert ok
    (record_in,) = state["inputs"]
    (record_out,) = state["outputs"]
    assert record_in["name"] == record_out["name"] == "atrium/document-json"
    assert record_in["sha512"] == hashlib.sha512(read["bytes"]).hexdigest()
    written = b'{"doc_id": "CTX", "entities": []}'
    assert record_out["sha512"] == hashlib.sha512(written).hexdigest()
    assert record_out["record_fields"] == {"entities": ["surface", "page", "line"]}
    assert str(tmp_path) not in json.dumps(state["inputs"] + state["outputs"])


def test_a_record_write_that_fails_fails_the_document(tmp_path, monkeypatch):
    """D13 (atrium-project#84): the hook raising is no warning any more; the document fails, so
    api_4_stats.sh halts the run and nothing reaches AMČR. Nothing is recorded as written."""

    def hook(**kw):
        raise RuntimeError("schema says no")

    ok, state = _one_document(tmp_path, monkeypatch, hook)
    assert ok is False
    assert state["outputs"] == []
