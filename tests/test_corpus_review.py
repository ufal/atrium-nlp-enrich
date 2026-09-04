"""
tests/test_corpus_review.py — unit and end-to-end tests for corpus_review.py.

The end-to-end tests run against the real committed synthetic corpus
(data_samples/{UDP,DOC_LINE_CATEG}/CTX00000000{1,2,3}) precisely BECAUSE it is
synthetic and tiny: this pins the honest 4-hit ceiling the module docstring
describes, so nobody mistakes a later change to the matcher for more "evidence"
than three placeholder documents can actually provide.
"""

from pathlib import Path

import pytest

import corpus_review as cr
import vocab_build as vb
import vocab_review as vr
from vocab_manager import VocabularyManager

REPO_ROOT = Path(__file__).resolve().parent.parent
VOCAB_DIR = REPO_ROOT / "data_samples" / "vocab"
CONFIG = REPO_ROOT / "data_samples" / "taxonomy_config.json"
UDP_DIR = REPO_ROOT / "data_samples" / "UDP"
LINES_DIR = REPO_ROOT / "data_samples" / "DOC_LINE_CATEG"


def _shipped_manager():
    return VocabularyManager(config_path=str(CONFIG))


def _require_flat():
    if not (VOCAB_DIR / "amcr_flat.json").exists() or not (VOCAB_DIR / "teater_flat.json").exists():
        pytest.skip("flat artifacts not present in this checkout")


def _require_corpus():
    if not UDP_DIR.exists() or not LINES_DIR.exists():
        pytest.skip("synthetic corpus (data_samples/UDP, DOC_LINE_CATEG) not present")


# ── read_conllu_tokens ────────────────────────────────────────────────────────────


def test_read_conllu_tokens_skips_multiword_and_empty_nodes(tmp_path):
    """UD convention: an id containing '-' regroups already-listed single tokens
    (e.g. Czech "na+dně" contractions never occur, but the convention is universal),
    and an id containing '.' is an empty node. Both must be skipped or a word count
    would double."""
    conllu = (
        "# text = test\n"
        "1-2\tdo\t_\t_\t_\t_\t_\t_\t_\t_\n"
        "1\tdo\tdo\tADP\t_\t_\t_\t_\t_\t_\n"
        "2\tokna\tokno\tNOUN\t_\t_\t_\t_\t_\t_\n"
        "2.1\telided\telidet\tVERB\t_\t_\t_\t_\t_\t_\n"
    )
    p = tmp_path / "x.conllu"
    p.write_text(conllu, encoding="utf-8")
    tokens = cr.read_conllu_tokens(p)
    assert [t.form for t in tokens] == ["do", "okna"]
    assert [t.lemma for t in tokens] == ["do", "okno"]


def test_read_conllu_tokens_skips_comments_and_blank_lines(tmp_path):
    p = tmp_path / "x.conllu"
    p.write_text("# generator = x\n\n1\tx\ty\tNOUN\t_\t_\t_\t_\t_\t_\n", encoding="utf-8")
    tokens = cr.read_conllu_tokens(p)
    assert len(tokens) == 1


# ── _form_lemma_map / _line_lemmas ────────────────────────────────────────────────


def test_form_lemma_map_is_casefolded_and_picks_most_common():
    tokens = [
        cr.ConlluToken(form="Keramika", lemma="keramika", upos="NOUN"),
        cr.ConlluToken(form="keramiky", lemma="keramika", upos="NOUN"),
        cr.ConlluToken(form="X", lemma="a", upos="NOUN"),
        cr.ConlluToken(form="X", lemma="a", upos="NOUN"),
        cr.ConlluToken(form="X", lemma="b", upos="NOUN"),
    ]
    m = cr._form_lemma_map(tokens)
    assert m["keramika"] == "keramika"
    assert m["keramiky"] == "keramika"
    assert m["x"] == "a"  # 2 votes for "a" vs 1 for "b"


def test_form_lemma_map_skips_underscore_lemmas():
    tokens = [cr.ConlluToken(form="x", lemma="_", upos="X")]
    assert cr._form_lemma_map(tokens) == {}


def test_line_lemmas_matches_inflected_forms_via_the_document_map():
    """The concrete case the module exists for: 'středověku' (genitive) never equals
    the vocabulary's dictionary-form label 'středověk' as a substring."""
    form_lemma = {"středověku": "středověk", "raného": "raný"}
    lemmas = cr._line_lemmas("z raného středověku.", form_lemma)
    assert "středověk" in lemmas
    assert "raný" in lemmas


def test_line_lemmas_falls_back_to_surface_word_when_unseen():
    lemmas = cr._line_lemmas("neznámé slovo", {})
    assert lemmas == ["neznámé", "slovo"]


def test_line_lemmas_ignores_digits_and_punctuation():
    lemmas = cr._line_lemmas("A123/2024!", {})
    assert lemmas == ["a"]


# ── _single_word_terms ────────────────────────────────────────────────────────────


def test_single_word_terms_excludes_multi_word_labels():
    nested = {
        "Feature": {
            "kostel": {"en": "church", "source": "amcr", "source_id": "1"},
            "zlomek keramiky": {"en": "ceramic sherd", "source": "amcr", "source_id": "2"},
        }
    }
    idx = cr._single_word_terms(nested)
    assert "kostel" in idx
    assert "zlomek keramiky" not in idx
    assert not any(len(k.split()) > 1 for k in idx)


def test_single_word_terms_uses_bare_cs_for_a_qualified_entry():
    """A bracketed homonym split (B3) is single-word once its bare label is used --
    'zámek (sídlo elity)' itself is not, but its bare_cs 'zámek' is."""
    nested = {
        "Activity Area": {
            "zámek (sídlo elity)": {
                "en": "châteaux",
                "source": "teater",
                "source_id": "1439",
                "bare_cs": "zámek",
            }
        }
    }
    idx = cr._single_word_terms(nested)
    assert "zámek" in idx  # norm_label casefolds but does not strip diacritics
    entry = idx["zámek"][0]
    assert entry["cs"] == "zámek (sídlo elity)"  # the enum key stays as offered


# ── end-to-end against the real committed synthetic corpus ──────────────────────


def test_corpus_term_evidence_finds_exactly_the_known_four_hits():
    """Pins the exact ceiling the module docstring states. If this test's expected
    set ever needs to grow, it means real documents landed -- update the test as
    part of that change, not as a silent drift."""
    _require_flat()
    _require_corpus()
    manager = _shipped_manager()
    nested = cr.shipped_nested(VOCAB_DIR, manager)
    rows, stats = cr.corpus_term_evidence_rows(nested, UDP_DIR, LINES_DIR)

    hits = {r["cs"]: r for r in rows if r["occurrences"] > 0}
    assert set(hits) == {"hradiště", "sonda", "keramika", "středověk"}
    assert hits["hradiště"]["doc_count"] == 2
    assert hits["sonda"]["doc_count"] == 2
    assert hits["keramika"]["doc_count"] == 1
    assert hits["středověk"]["doc_count"] == 1
    assert stats["documents"] == 3
    assert stats["terms_with_hits"] == 4


def test_corpus_term_evidence_example_lines_cite_the_real_line():
    _require_flat()
    _require_corpus()
    manager = _shipped_manager()
    nested = cr.shipped_nested(VOCAB_DIR, manager)
    rows, _stats = cr.corpus_term_evidence_rows(nested, UDP_DIR, LINES_DIR)
    keramika = next(r for r in rows if r["cs"] == "keramika")
    assert "Nalezená keramika" in keramika["example_lines"]


def test_corpus_branch_evidence_covers_the_same_rules_as_exclusion_impact():
    """The corpus roll-up must never disagree with the other O3/O4 sheets about
    which rules exist -- all built from the same _excluded_buckets()."""
    _require_flat()
    manager = _shipped_manager()
    per_source = vb._load_flat(VOCAB_DIR)
    exclusion_rules = {r["rule"] for r in vr.exclusion_impact_rows(per_source, manager)}
    branch_rules = {r["rule"] for r in cr.corpus_branch_evidence_rows(per_source, manager, UDP_DIR)}
    assert exclusion_rules == branch_rules


def test_corpus_branch_evidence_finds_stredovek_under_vyskovy_bod_typ():
    """vyskovy_bod_typ (an AMCR 'elevation reference point' list, excluded under M4)
    happens to also carry a record labelled 'středověk' -- the same label the OFFERED
    Chronology term uses. This is a real, if surprising, cross-list label collision
    the corpus can surface: 'středověk' occurring in text says nothing about which of
    the two records a model meant, only that the LABEL is attested in real usage."""
    _require_flat()
    _require_corpus()
    manager = _shipped_manager()
    per_source = vb._load_flat(VOCAB_DIR)
    rows = cr.corpus_branch_evidence_rows(per_source, manager, UDP_DIR)
    row = next(r for r in rows if r["rule"] == "heslar:vyskovy_bod_typ")
    assert row["occurrences"] == 1
    assert row["doc_count"] == 1
    assert "středověk" in row["sample_hit_terms"]


# ── gold_workbook_rows ────────────────────────────────────────────────────────────


def test_gold_workbook_covers_every_committed_line():
    _require_flat()
    _require_corpus()
    manager = _shipped_manager()
    nested = cr.shipped_nested(VOCAB_DIR, manager)
    rows = cr.gold_workbook_rows(nested, LINES_DIR, UDP_DIR)
    assert len(rows) == 16  # 4 + 10 + 2 real DOC_LINE_CATEG rows


def test_gold_workbook_gold_columns_start_blank():
    _require_flat()
    _require_corpus()
    manager = _shipped_manager()
    nested = cr.shipped_nested(VOCAB_DIR, manager)
    rows = cr.gold_workbook_rows(nested, LINES_DIR, UDP_DIR)
    for row in rows:
        assert row["gold_category"] == ""
        assert row["gold_keywords_cs"] == ""
        assert row["model_category"] == ""
        assert row["model_keywords_cs"] == ""


def test_gold_workbook_candidate_terms_on_the_known_line():
    _require_flat()
    _require_corpus()
    manager = _shipped_manager()
    nested = cr.shipped_nested(VOCAB_DIR, manager)
    rows = cr.gold_workbook_rows(nested, LINES_DIR, UDP_DIR)
    row = next(
        r for r in rows if r["file_id"] == "CTX000000001" and r["page"] == "2" and r["line"] == "1"
    )
    candidates = row["candidate_terms"].split("; ")
    assert "keramika" in candidates
    assert "středověk" in candidates


def test_gold_workbook_is_sorted_by_file_then_page_then_line():
    _require_flat()
    _require_corpus()
    manager = _shipped_manager()
    nested = cr.shipped_nested(VOCAB_DIR, manager)
    rows = cr.gold_workbook_rows(nested, LINES_DIR, UDP_DIR)
    keys = [(r["file_id"], int(r["page"]), int(r["line"])) for r in rows]
    assert keys == sorted(keys)


# ── CLI smoke test ────────────────────────────────────────────────────────────────


def test_main_all_writes_three_csvs(tmp_path):
    """Writes into --vocab-dir/--udp-dir/--lines-dir copies, never the real
    data_samples/ tree, during a test."""
    _require_flat()
    _require_corpus()
    import shutil

    vocab_dest = tmp_path / "vocab"
    vocab_dest.mkdir()
    for name in ("amcr_flat.json", "teater_flat.json"):
        shutil.copy(VOCAB_DIR / name, vocab_dest / name)

    udp_dest = tmp_path / "UDP"
    shutil.copytree(UDP_DIR, udp_dest)
    lines_dest = tmp_path / "DOC_LINE_CATEG"
    shutil.copytree(LINES_DIR, lines_dest)

    rc = cr.main(
        [
            "--all",
            "--vocab-dir",
            str(vocab_dest),
            "--config",
            str(CONFIG),
            "--udp-dir",
            str(udp_dest),
            "--lines-dir",
            str(lines_dest),
        ]
    )
    assert rc == 0
    assert (vocab_dest / "corpus_term_evidence.csv").exists()
    assert (vocab_dest / "corpus_branch_evidence.csv").exists()
    assert (vocab_dest / "gold_workbook.csv").exists()


def test_main_with_no_flags_is_a_usage_error():
    assert cr.main([]) == 2


def test_main_handles_missing_corpus_directories_gracefully(tmp_path, capsys):
    """The generator must degrade to zero occurrences, not crash, when the real
    corpus is absent -- which is the state of this repository today."""
    _require_flat()
    import shutil

    vocab_dest = tmp_path / "vocab"
    vocab_dest.mkdir()
    for name in ("amcr_flat.json", "teater_flat.json"):
        shutil.copy(VOCAB_DIR / name, vocab_dest / name)

    rc = cr.main(
        [
            "--term-evidence",
            "--vocab-dir",
            str(vocab_dest),
            "--config",
            str(CONFIG),
            "--udp-dir",
            str(tmp_path / "no-such-udp-dir"),
            "--lines-dir",
            str(tmp_path / "no-such-lines-dir"),
        ]
    )
    assert rc == 0
    import csv

    rows = list(csv.DictReader(open(vocab_dest / "corpus_term_evidence.csv", encoding="utf-8")))
    assert all(int(r["occurrences"]) == 0 for r in rows)
