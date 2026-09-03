"""
tests/test_vocab_review.py — unit and end-to-end tests for vocab_review.py.

Like test_vocab_build.py, the end-to-end tests run against the real committed flat
harvests: a synthetic fixture could not have caught the geographic_or_ethnic /
"settled vs. still-open" categorisation bug this file's own history includes (see
test_exclusion_impact_settled_and_open_totals_reconcile) -- that bug was invisible on
made-up data and only showed up once the real term counts stopped adding up to 2930.
"""

from pathlib import Path

import pytest

import vocab_build as vb
import vocab_review as vr
import vocab_sources as vs
from vocab_manager import VocabularyManager

REPO_ROOT = Path(__file__).resolve().parent.parent
VOCAB_DIR = REPO_ROOT / "data_samples" / "vocab"
CONFIG = REPO_ROOT / "data_samples" / "taxonomy_config.json"


def _shipped_manager():
    return VocabularyManager(config_path=str(CONFIG))


def _require_flat():
    if not (VOCAB_DIR / "amcr_flat.json").exists() or not (VOCAB_DIR / "teater_flat.json").exists():
        pytest.skip("flat artifacts not present in this checkout")


# ── gloss_similarity / group_dissimilarity (pure functions) ─────────────────────


@pytest.mark.parametrize(
    "a,b,expected_low",
    [
        ("amphora", "amphorae", False),  # near-identical, plural variance
        ("armour and weapons", "weapons and armour", False),  # same tokens, reordered
        ("lock", "châteaux", True),  # genuinely different
        ("colourant", "dye", True),  # genuinely different
    ],
)
def test_gloss_similarity_separates_variance_from_real_difference(a, b, expected_low):
    score = vr.gloss_similarity(a, b)
    assert 0.0 <= score <= 1.0
    assert (score < 0.5) == expected_low


def test_gloss_similarity_is_symmetric_and_identical_is_one():
    assert vr.gloss_similarity("hearth", "hearth") == 1.0
    assert vr.gloss_similarity("a", "b") == vr.gloss_similarity("b", "a")


def test_group_dissimilarity_is_the_worst_pair_not_the_average():
    a = vs.VocabRecord(cs="x", en="fireplace", source="amcr", source_id="1")
    b = vs.VocabRecord(cs="x", en="hearth", source="teater", source_id="2", broader=("1",))
    c = vs.VocabRecord(cs="x", en="fire place", source="teater", source_id="3", broader=("1",))
    # Three distinct glosses, three pairwise scores — the group score must be the
    # lowest of the three (the worst pair), not their average or the first computed.
    pairwise = [
        vr.gloss_similarity("fireplace", "hearth"),
        vr.gloss_similarity("fireplace", "fire place"),
        vr.gloss_similarity("hearth", "fire place"),
    ]
    assert vr.group_dissimilarity([a, b, c]) == min(pairwise)
    assert min(pairwise) < sum(pairwise) / len(pairwise)  # genuinely below the average


def test_gloss_similarity_matches_regardless_of_which_side_a_set_iterates_first():
    """SequenceMatcher.ratio() alone is not symmetric (autojunk + matching-block
    search depend on argument order); group_dissimilarity iterates a *set* of
    glosses, whose iteration order Python does not guarantee, so gloss_similarity
    itself must not depend on which argument comes first."""
    assert vr.gloss_similarity("hearth", "fire place") == vr.gloss_similarity("fire place", "hearth")


def test_group_dissimilarity_single_gloss_group_is_not_flagged():
    a = vs.VocabRecord(cs="x", en="church", source="amcr", source_id="1")
    b = vs.VocabRecord(cs="x", en="church", source="teater", source_id="2", broader=("1",))
    assert vr.group_dissimilarity([a, b]) == 1.0


# ── collision_review_rows (M8 / Track 2) ─────────────────────────────────────────


def test_collision_review_zamek_ranks_near_the_top_of_real_collisions():
    """Validates the ranking heuristic against the one collision already confirmed
    as a genuine homonym (M8, motyc 5439363875) — it must not be buried among the
    ~470 real collision groups, most of which are plain translation variance."""
    _require_flat()
    manager = _shipped_manager()
    per_source = vb._load_flat(VOCAB_DIR)
    filtered = [
        r for name, (recs, _m) in per_source.items() for r in vb._filter_excluded(recs, manager)
    ]
    rows = vr.collision_review_rows(filtered, manager)

    ordered_groups = list(dict.fromkeys(r["cs"] for r in rows))
    assert "zámek" in ordered_groups
    rank = ordered_groups.index("zámek") + 1
    assert rank <= 20, f"zámek ranked {rank} of {len(ordered_groups)} — heuristic regressed"


def test_collision_review_excludes_single_gloss_groups():
    """A group where every record shares one EN gloss is plain dedup (B1/B2 already
    carry every id) and must not appear — it needs no human review."""
    _require_flat()
    manager = _shipped_manager()
    per_source = vb._load_flat(VOCAB_DIR)
    filtered = [
        r for name, (recs, _m) in per_source.items() for r in vb._filter_excluded(recs, manager)
    ]
    rows = vr.collision_review_rows(filtered, manager)
    assert "kostel" not in {r["cs"] for r in rows}  # both AMCR records say "church"


def test_collision_review_rows_are_ranked_ascending():
    _require_flat()
    manager = _shipped_manager()
    per_source = vb._load_flat(VOCAB_DIR)
    filtered = [
        r for name, (recs, _m) in per_source.items() for r in vb._filter_excluded(recs, manager)
    ]
    rows = vr.collision_review_rows(filtered, manager)
    scores = [r["dissimilarity"] for r in rows]
    assert scores == sorted(scores)


# ── composite_pair_rows (O1/F / Track 3) ─────────────────────────────────────────


def _built_union():
    manager = _shipped_manager()
    per_source = vb._load_flat(VOCAB_DIR)
    filtered = {name: vb._filter_excluded(recs, manager) for name, (recs, _m) in per_source.items()}
    qualifiers = manager.qualifier_overrides()
    records = filtered.get("amcr", []) + filtered.get("teater", [])
    nested, _audit, _collisions = vb._nest(manager, records, qualifiers=qualifiers)
    return nested


@pytest.mark.parametrize(
    "composite,component",
    [
        ("most/brod", "most"),
        ("muzeum/skanzen", "muzeum"),
        ("budova/stavba", "budova"),
        ("zámek/zámeček/vila", "vila"),
    ],
)
def test_composite_pairs_finds_the_flagship_examples(composite, component):
    """The four pairs named throughout the issue thread (finding 2, comment
    5427831261) must all be detected on the real, currently-adopted vocabulary."""
    _require_flat()
    nested = _built_union()
    rows = vr.composite_pair_rows(nested)
    hits = [r for r in rows if r["composite_cs"] == composite and r["component_cs"] == component]
    assert hits, f"{composite!r} <-> {component!r} not found in composite_pair_rows"


def test_composite_pairs_never_matches_a_label_against_itself():
    _require_flat()
    nested = _built_union()
    rows = vr.composite_pair_rows(nested)
    for r in rows:
        assert r["composite_cs"] != r["component_cs"]


# ── exclusion_impact_rows (O3/O4 / Track 4) ──────────────────────────────────────


def test_exclusion_impact_settled_and_open_totals_reconcile():
    """The three status buckets must partition every excluded term with no overlap
    and no gap — this is the check that would have caught the geographic_or_ethnic
    vs. settled-M4 conflation this tool's own history had (240 already-settled AMCR
    technical terms were briefly folded into an 'open' total)."""
    _require_flat()
    manager = _shipped_manager()
    per_source = vb._load_flat(VOCAB_DIR)
    rows = vr.exclusion_impact_rows(per_source, manager)

    by_status = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + r["term_count"]
    assert set(by_status) == {
        "settled (M4)",
        "open: geographic/ethnic (O3/O4 Q1)",
        "open: other (O4 Q2)",
    }
    assert sum(by_status.values()) == sum(r["term_count"] for r in rows)


@pytest.mark.parametrize(
    "rule",
    ["heslar:zeme", "heslar:jazyk", "teater:2560", "teater:2900", "teater:3076"],
)
def test_exclusion_impact_flags_exactly_the_guardrail_conflicting_lists(rule):
    """O3/O4: only the lists the guardrail's own wording names (country, language,
    geographic region) or TEATER's own ethnic/historical/dynastic labels are Q1 —
    everything else excluded is Q2 or already settled, not a guardrail question."""
    _require_flat()
    manager = _shipped_manager()
    per_source = vb._load_flat(VOCAB_DIR)
    rows = vr.exclusion_impact_rows(per_source, manager)
    row = next(r for r in rows if r["rule"] == rule)
    assert row["status"] == "open: geographic/ethnic (O3/O4 Q1)"


def test_exclusion_impact_technical_amcr_lists_are_settled_not_open():
    """dokument_material etc. were ruled on under M4 — they are not part of O4 and
    must not appear alongside the still-open questions."""
    _require_flat()
    manager = _shipped_manager()
    per_source = vb._load_flat(VOCAB_DIR)
    rows = vr.exclusion_impact_rows(per_source, manager)
    row = next(r for r in rows if r["rule"] == "heslar:dokument_material")
    assert row["status"] == "settled (M4)"


# ── CLI smoke test ────────────────────────────────────────────────────────────────


def test_main_all_writes_three_csvs(tmp_path, monkeypatch):
    """The CLI writes into --vocab-dir, never the real data_samples/vocab/ during a
    test — this test passes a tmp_path copy so it never touches the committed tree."""
    _require_flat()
    import shutil

    dest = tmp_path / "vocab"
    dest.mkdir()
    for name in ("amcr_flat.json", "teater_flat.json"):
        shutil.copy(VOCAB_DIR / name, dest / name)

    rc = vr.main(["--all", "--vocab-dir", str(dest), "--config", str(CONFIG)])
    assert rc == 0
    assert (dest / "collision_review.csv").exists()
    assert (dest / "composite_pairs.csv").exists()
    assert (dest / "exclusion_impact.csv").exists()


def test_main_with_no_flags_is_a_usage_error(capsys):
    assert vr.main([]) == 2
