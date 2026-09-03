#!/usr/bin/env python3
"""
vocab_review.py — read-only review artifacts for issue #6's open vocabulary questions.

Three independent reports. Each is a CSV a domain reviewer reads and turns into either
a ``taxonomy_overrides.json`` entry or a ``teater_branch_map``/``heslar_map`` flip.
Nothing here writes to the vocabulary itself, and none of the three guesses a semantic
verdict — they rank and surface candidates; a human still decides.

    python3 vocab_review.py --collisions   # M8: same-label groups that might be homonyms
    python3 vocab_review.py --composites   # O1/F: "X/Y" labels vs. standalone X, Y
    python3 vocab_review.py --exclusions   # O3/O4: impact of reinstating each excluded list
    python3 vocab_review.py --all          # all three, offline from the committed flat files

Offline and pure: reads ``data_samples/vocab/*_flat.json`` + the taxonomy config, never
touches the network, never writes anywhere but the three report CSVs.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import vocab_build as vb
import vocab_sources as vs
from vocab_manager import VocabularyManager, find_composite_links

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_VOCAB_DIR = REPO_ROOT / "data_samples" / "vocab"
DEFAULT_CONFIG = REPO_ROOT / "data_samples" / "taxonomy_config.json"

# The only judgement call baked into the tooling, and it is a classification of
# EXISTING rulings, not a new one: every currently-excluded list/branch falls into
# exactly one of three buckets. Both AMCR heslar names and TEATER branch ids below
# are named directly by the guardrail's own wording ("country name, language name,
# or geographic region name") and by TEATER's own labels for 2560/2900/3076 (ethnic
# groups / historical regions / dynasties) -- this is a restatement, not an opinion.
#
#   settled       M4/M3: a technical/administrative AMCR list, already ruled on and
#                 already correctly excluded. Not part of O3/O4 at all.
#   geo_ethnic    O3 + O4 "Q1": conflicts with the standing geographic guardrail.
#                 Reinstating any of these REQUIRES relaxing the guardrail wording
#                 in the same change (see C1) -- doing one without the other makes
#                 the prompt forbid what the vocabulary offers.
#   other         O4 "Q2": excluded on an a priori P3 read with no guardrail
#                 conflict at all -- battles/wars included, since a battle or war
#                 NAME is not itself a country/language/region.
STATUS_GEO_ETHNIC = {
    "heslar:zeme",  # 249 country names -- "country name"
    "heslar:jazyk",  # 9 language names -- "language name"
    "teater:2560",  # etnika / ethnic groups
    "teater:2900",  # historické oblasti a státní útvary / historical regions
    "teater:3076",  # panovnické dynastie / ruling dynasties
}
STATUS_OTHER_OPEN = {
    "teater:1",  # Teorie a přístupy / Theory and approaches
    "teater:288",  # Hraniční obory / Cross-border and related disciplines
    "teater:2557",  # Pomocně-historická hesla (the branch root itself)
    "teater:2558",  # bitvy / battles -- a battle name is not a place/language name
    "teater:3091",  # války / wars -- same
    "teater:3094",  # Povolání a pracovní činnosti / Professions and work activities
    "teater:3549",  # Společnost / Society
}


# ── shared loading ───────────────────────────────────────────────────────────────


def _load_filtered(
    vocab_dir: Path, manager: VocabularyManager
) -> Dict[str, List[vs.VocabRecord]]:
    """The same B5 exclusion-before-dedup view vocab_build.py builds from, offline."""
    per_source = vb._load_flat(vocab_dir)
    return {
        name: vb._filter_excluded(records, manager) for name, (records, _meta) in per_source.items()
    }


def _write_csv(path: Path, rows: Sequence[Dict[str, Any]], columns: Sequence[str]) -> None:
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=list(columns), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(buf.getvalue(), encoding="utf-8")
    print(f"  [write] {path}  ({len(rows)} rows)")


# ── M8: collision review (Track 2) ───────────────────────────────────────────────


def gloss_similarity(a: str, b: str) -> float:
    """How similar two English glosses are: 0.0 (nothing shared) to 1.0 (identical).

    ``max()`` of a character-level ratio and a whitespace-token overlap — the
    character ratio alone catches plural/spelling variance ('amphora'/'amphorae');
    the token overlap catches a reordered or partially-shared multi-word gloss a
    pure character diff would score as very different. Validated against the real
    data: the one confirmed homonym in the current build (`zámek`, 'lock'/'châteaux')
    scores 0.17 and ranks 10th-lowest of 127 real collision groups.
    """
    a_n, b_n = vs.norm_label(a), vs.norm_label(b)
    if a_n == b_n:
        return 1.0
    # SequenceMatcher.ratio() is NOT symmetric in general (its autojunk heuristic and
    # matching-block search depend on which string is "a"): comparing in a canonical
    # (sorted) order is what makes this function's result independent of call order —
    # load-bearing here, since group_dissimilarity iterates a *set* of glosses, whose
    # order Python does not guarantee.
    lo, hi = sorted((a_n, b_n))
    char_ratio = SequenceMatcher(None, lo, hi).ratio()
    a_tok, b_tok = set(a_n.split()), set(b_n.split())
    tok_ratio = len(a_tok & b_tok) / len(a_tok | b_tok) if (a_tok or b_tok) else 0.0
    return max(char_ratio, tok_ratio)


def group_dissimilarity(members: Sequence[vs.VocabRecord]) -> float:
    """The worst (lowest) pairwise gloss similarity across every distinct EN gloss in
    the group. One member with a wildly different gloss is enough to flag the whole
    group, even if the rest agree with each other."""
    glosses = sorted({vs.norm_label(m.en) for m in members})
    if len(glosses) < 2:
        return 1.0
    best = 1.0
    for i in range(len(glosses)):
        for j in range(i + 1, len(glosses)):
            best = min(best, gloss_similarity(glosses[i], glosses[j]))
    return best


def collision_review_rows(
    records: Sequence[vs.VocabRecord], manager: VocabularyManager
) -> List[Dict[str, Any]]:
    """One row per (group, member) for every same-label group with more than one
    distinct English gloss, groups ordered ascending by dissimilarity — the
    candidates most likely to be a genuine M8 homonym first. A group whose members
    all share one gloss is plain dedup (B1/B2 already handle it — no review needed)
    and is not included."""
    groups = vs.group_by_label(records)
    scored: List[Tuple[float, List[vs.VocabRecord]]] = []
    for members in groups.values():
        if len({vs.norm_label(m.en) for m in members}) < 2:
            continue
        scored.append((group_dissimilarity(members), members))
    scored.sort(key=lambda t: (t[0], vs.norm_label(t[1][0].cs)))

    rows: List[Dict[str, Any]] = []
    for dissimilarity, members in scored:
        for m in sorted(members, key=vs.record_sort_key):
            facet, rule = manager.assign_theme(m.as_dict())
            rows.append(
                {
                    "dissimilarity": round(dissimilarity, 2),
                    "cs": m.cs,
                    "source": m.source,
                    "id": m.source_id,
                    "en": m.en,
                    "scheme": m.scheme or "",
                    "sub": m.sub or "",
                    "current_facet": facet,
                    "placed_by": rule,
                    "verdict": "",  # human fills in: "" = same concept (default),
                    # or a qualifier_cs string for a genuine homonym (M8/B3)
                }
            )
    return rows


COLLISION_COLUMNS = [
    "dissimilarity",
    "cs",
    "source",
    "id",
    "en",
    "scheme",
    "sub",
    "current_facet",
    "placed_by",
    "verdict",
]


# ── O1/F: composite-label overlap (Track 3) ──────────────────────────────────────


def composite_pair_rows(nested: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every offered "X/Y[/Z]" label where at least one of X, Y, Z is ALSO offered as
    its own standalone entry — both are currently selectable answers for the same
    line, and only one is "correct" under an exact-match score (O1/F).

    Detection itself lives in :func:`vocab_manager.find_composite_links`, which is
    also what :func:`vocab_manager.attach_same_as` uses to write the ``same_as``
    links into the vocabulary — so this report and the mechanism it reports on can
    never disagree about what counts as a pair. This function only decorates each
    link with the two entries' source ids for the reviewer.
    """
    rows: List[Dict[str, Any]] = []
    for facet, cs, comp_facet, comp_cs in find_composite_links(nested):
        entry = nested[facet][cs]
        comp_entry = nested[comp_facet][comp_cs]
        rows.append(
            {
                "composite_cs": cs,
                "composite_facet": facet,
                "composite_source": entry.get("source", ""),
                "composite_id": entry.get("source_id", ""),
                "component_cs": comp_cs,
                "component_facet": comp_facet,
                "component_source": comp_entry.get("source", ""),
                "component_id": comp_entry.get("source_id", ""),
                "same_facet": facet == comp_facet,
            }
        )
    return rows


COMPOSITE_COLUMNS = [
    "composite_cs",
    "composite_facet",
    "composite_source",
    "composite_id",
    "component_cs",
    "component_facet",
    "component_source",
    "component_id",
    "same_facet",
]


# ── O3/O4: exclusion impact (Track 4) ────────────────────────────────────────────


def exclusion_impact_rows(
    per_source: Dict[str, Tuple[List[vs.VocabRecord], Any]], manager: VocabularyManager
) -> List[Dict[str, Any]]:
    """Per excluded list/branch: how many terms it holds, whether it is one of the
    geographic/ethnic ones the prompt's guardrail actually conflicts with (O4's Q1),
    and a sample so a reviewer does not have to go looking. Every list here is
    already a one-line switch in ``taxonomy_config.json`` — reinstating one is
    changing its value away from ``__exclude__``, nothing more."""
    buckets: Dict[str, List[vs.VocabRecord]] = {}
    for records, _meta in per_source.values():
        for r in records:
            if not r.cs or not r.en:
                continue
            theme, rule = manager.assign_theme(r.as_dict())
            if theme != "__exclude__" or not rule.startswith(("heslar:", "teater:")):
                continue
            buckets.setdefault(rule, []).append(r)

    labels = manager.settings.get("teater_branch_labels") or {}
    reasons = manager.settings.get("_exclusions") or {}

    rows: List[Dict[str, Any]] = []
    for rule, members in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        kind, ident = rule.split(":", 1)
        label = labels.get(ident, "") if kind == "teater" else ident
        samples = sorted({m.cs for m in members})[:10]
        if rule in STATUS_GEO_ETHNIC:
            status = "open: geographic/ethnic (O3/O4 Q1)"
        elif rule in STATUS_OTHER_OPEN:
            status = "open: other (O4 Q2)"
        else:
            status = "settled (M4)"
        rows.append(
            {
                "status": status,
                "rule": rule,
                "kind": kind,
                "list_or_branch": ident,
                "label": label,
                "term_count": len(members),
                "stated_reason": reasons.get(ident, "") or reasons.get(f"TEATER {ident}", ""),
                "sample_terms": "; ".join(samples),
            }
        )
    rows.sort(key=lambda r: (r["status"], -r["term_count"]))
    return rows


EXCLUSION_COLUMNS = [
    "status",
    "rule",
    "kind",
    "list_or_branch",
    "label",
    "term_count",
    "stated_reason",
    "sample_terms",
]


# ── CLI ───────────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vocab_review.py",
        description="Read-only review artifacts for issue #6's open vocabulary questions.",
    )
    p.add_argument("--collisions", action="store_true", help="M8 homonym-review sheet")
    p.add_argument("--composites", action="store_true", help="O1/F composite-label overlap")
    p.add_argument("--exclusions", action="store_true", help="O3/O4 exclusion impact")
    p.add_argument("--all", action="store_true", help="all three reports")
    p.add_argument("--vocab-dir", type=Path, default=DEFAULT_VOCAB_DIR)
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--overrides", type=Path, default=None)
    return p


def main(argv: Any = None) -> int:
    args = build_parser().parse_args(argv)
    if not (args.collisions or args.composites or args.exclusions or args.all):
        print("Nothing to do — pass --collisions, --composites, --exclusions, or --all.")
        return 2

    manager = VocabularyManager(
        config_path=str(args.config),
        overrides_path=str(args.overrides) if args.overrides else None,
    )
    manager.validate_settings()

    if not (args.vocab_dir / "amcr_flat.json").exists() or not (
        args.vocab_dir / "teater_flat.json"
    ).exists():
        print(f"[error] no *_flat.json artifacts found in {args.vocab_dir}")
        return 1

    per_source = vb._load_flat(args.vocab_dir)
    filtered = _load_filtered(args.vocab_dir, manager)

    if args.collisions or args.all:
        records = filtered.get("amcr", []) + filtered.get("teater", [])
        rows = collision_review_rows(records, manager)
        _write_csv(args.vocab_dir / "collision_review.csv", rows, COLLISION_COLUMNS)

    if args.composites or args.all:
        qualifiers = manager.qualifier_overrides()
        records = filtered.get("amcr", []) + filtered.get("teater", [])
        nested, _audit, _collisions = vb._nest(manager, records, qualifiers=qualifiers)
        rows = composite_pair_rows(nested)
        _write_csv(args.vocab_dir / "composite_pairs.csv", rows, COMPOSITE_COLUMNS)

    if args.exclusions or args.all:
        rows = exclusion_impact_rows(per_source, manager)
        _write_csv(args.vocab_dir / "exclusion_impact.csv", rows, EXCLUSION_COLUMNS)

    return 0


if __name__ == "__main__":
    sys.exit(main())
