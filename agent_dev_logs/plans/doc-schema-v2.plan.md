# Strategy — [atrium-project#84](https://github.com/ufal/atrium-project/issues/84) (doc-schema-v2): nlp-enrich's part

> _**Refreshed 2026-11-14 (afternoon)**: "Status — round 6 (11-14)": the hub merged, the pins moved, round 6._
> _**Refreshed 2026-11-14**: "Status — PR (11-14)": the PR's checks and round 5's fixes._
> _**Refreshed 2026-11-13**: "Status — round 2" (the code, not pushed yet) and round 4's notes. The file keeps
> the name `doc-schema-v2.plan.md` (it was `84.plan.md` on 11-12 and 11-13)._
> _**Written 2026-11-12** on ARÚP's output contract of 12 November and atrium-project#84 (motyc, 11-12), at this
> checkout's head `40c68c9` (= `test`). The hub carries the whole change:
> [plan](https://github.com/ufal/atrium-project/blob/test/agent_dev_logs/plans/doc-schema-v2.plan.md) ·
> [digest](https://github.com/ufal/atrium-project/blob/test/agent_dev_logs/digests/doc-schema-v2.digest.md) ·
> [contract digest](https://github.com/ufal/atrium-project/blob/test/agent_dev_logs/digests/project_state_1211.md).
> This file is the repository's slice only. It replaces the 11-11 slice of the same
> name; its points that still hold are carried here._

**Status (2026-11-14, afternoon)**: 🟡 **The hub's PR is merged and this repository is pinned to it: drift is green.
Round 6 completes this repository's part where no answer is pending; see "Status — round 6". The release (v2.0.0-beta)
is cut at K4TEL's cadence.**

**Status (2026-11-14)**: 🟡 **[atrium-nlp-enrich#45](https://github.com/ufal/atrium-nlp-enrich/pull/45) is open
(`doc-schema-v2` into `test`); see "Status — PR". Drift clears once the hub's PR merges and the pins move; the
record-major check clears at this tool's next release, which raises its major version.** _(superseded 11-14 afternoon)_

**Status (2026-11-13)**: 🟡 **Implemented, not pushed yet; see "Status — round 2". Deferred items are listed there.** _(superseded 11-14: the PR is open)_

**Status (2026-11-12)**: 📋 **Planned, plans only. No ALTO is produced or stored (D24): nlp-enrich takes its layout
from the record (or docproc), not ALTO, and TEITOK stays the standard linguistic output with its limits stated
(#84 §1; atrium-project#24's three-format decision revised). Until atrium-project#78 is settled, what it produces
through UDPipe and NameTag — the linguistic layer, entities, TEITOK — is not published (D35). Code follows Kate's
answer on #84 (16 November) and the hub's shared modules.**

## Its fields

| Record node / output                           | In v2                                                                                                           |
|------------------------------------------------|-----------------------------------------------------------------------------------------------------------------|
| `lines[].lemma`, `upos`, `feats`, `teitok_ref` | written, for the first time: the `include_lines` branch is `pass` today (`api_util/document_hook.py:238, 407`)  |
| `pages[].teitok_surface`                       | written                                                                                                         |
| `entities[]`                                   | written; `page` = the record's page key, `line` = the record's `line`, `bbox` in the one coordinate space (D28) |
| `atr/teitok-xml`                               | written; layout from the record (`pages[].canvas`, `lines[].bbox`, `bbox_precision`, `block`) or docproc        |
| `derived_from.teitok`                          | stops (D1): `document_hook.py:368`                                                                              |
| reads `lines[]`                                | by `categ` only: `Trash`, `Empty` left out; never the producer's confidence or the decode flag                  |

## Tasks (next rounds)

1. **Layout from the record, not ALTO** (D24). `api_util/teitok_alto.py` builds TEITOK from CoNLL-U plus a layout
   source: ALTO, a flexiconv TEITOK (`teitok_layout.py`), or the record (`record_layout.py`, issue #42). In the
   pipeline only the record path remains: `record_layout.text_lines()` / `record_rows()` / `parse_record_layout()`
   (130, 163, 250) read `pages[].canvas` and `lines[].bbox`; they gain `bbox_precision` (a `derived` box is a
   block's; `absent` gives a line without coordinates) and `block` (the TEITOK `<lb>` may carry it). ALTO input stays
   for batch and research use, outside the pipeline. If the record proves too thin (block boxes only for ATR text),
   docproc is the second source; the contract allows either (#84 §1).
2. **TEITOK's limits, stated** (#84 §1). In the TEITOK header and the docs: ATR text has block-level boxes unless
   the ATR keeps line breaks (Ronald's ask 7); token boxes are interpolated within a line (`word_boxes()`,
   `record_layout.py:197`) and marked so; born-digital lines are measured.
3. **Entities in the record's keys** (D28, H2). `entities[].bbox` is in the raw ALTO unit today
   (`teitok_alto.py`, `_build_page_scale_map()` 122, `dpi_scale`); with the record as the source it is already in
   the record's space. `entities[].page`/`line` use the record's page key and `line`, not a per-page count of layout
   lines.
4. **The `lines[]` linguistic fields** (`document_hook.py:407`): lemma, UPOS, features and the TEITOK reference per
   record line.
5. **No run data** (D1). `record_layout._converter()` (218) and the service (`service/api.py:678`) read
   `provenance.contributors` to name the converter in the TEITOK header; the record no longer has it. The producer
   comes from the docproc's paradata, passed with the job, or the header names the record version read.
6. **Paradata** (#84 §4). One action, written to both `paradata/atrium/document-json` and
   `paradata/atr/teitok-xml`: object = the record version read (SHA-512) and, if docproc is read,
   `atr/docproc-json`; result = the record's `lines` (`lemma`, `upos`, `feats`, `teitok_ref`), `pages`
   (`teitok_surface`), `entities`, and `atr/teitok-xml` (SHA-512). Components with their terms: UDPipe 2 and
   NameTag 3 (LINDAT services; the models CC BY-NC-SA 4.0), flexiconv (MIT); never merged.
7. **Limits refuse** (D13): `note_summary_trimmed()` (`api_util/summarize_nt_udp.py:490`) records `trimmed` for a
   summary that is not a stored output — it leaves the paradata or the cap goes; `split` (chunking for the services)
   stays recorded.
8. **D35 in the docs:** the README and `docs/` say that outputs produced through LINDAT are not published by AMČR
   until atrium-project#78 is settled; no code change.

## Status — round 2 (11-13)

Local branch from `test`, on the re-vendored shared modules (record 2.0, paradata 3.0,
`ContentLimitError`); delivered as an archive with the commands to run; pushed 11-13 (below). Nothing posted.

- **Tasks 1, 3:** `record_layout.py` reads blocks from `lines[].block` and keeps the record's `line`, keyed through
  `page_index`. A `derived` box is its block's; `absent` gives a line without coordinates. It skips `Trash` and
  `Empty` lines. Entities name the record's page and line.
- **Task 2:** the TEITOK header states where the line text and boxes come from (`sourceDesc`, a note on derived
  boxes); `docs/reference/teitok.md` says the same.
- **Task 4:** `include_lines` is built for the record layout: per record line, the head token's `lemma`, `upos`,
  `feats`, and `teitok_ref` (its `<s>` id).
- **Task 5:** the header names the record version read; no contributors are read.
- **Task 6, paradata:** one action. `object`: the record read (and the upload as `original`); `result`: the
  record's fields and `atr/teitok-xml`, by SHA-512. `api_4_stats.sh` records them through the CLI.
- **Task 7:** `note_summary_trimmed` is gone; `NE_SUMMARY_TOP_N` is a parameter; word chunking records `split`.
- **Task 8:** D35 stated in the README and docs.
- **Not built:** docproc as a second layout source. The record was enough in the local chain check (a born-digital
  PDF: 18 of 18 TEITOK references resolve).
- **Tests:** 1085 passed.
- **Not pushed yet:** the round-3 archive goes on a `doc-schema-v2` branch. Round 4 checked that tree with the
  addendum: 1085 pass.
- **[atrium-project#78](https://github.com/ufal/atrium-project/issues/78#issuecomment-6827422711)** (11-12): LINDAT's
  Terms of Use set aside for the pilot; whether D35 holds in the pilot is the hub's Q14. The docs keep D35 until it is
  answered.

## Status — PR (11-14)

[atrium-nlp-enrich#45](https://github.com/ufal/atrium-nlp-enrich/pull/45), head `d0df625`. Failing checks: check-drift
(canonical), because the callers read the hub at `v1` (`4435ffb`) while the copies are v2; api-contract, because the
record schema went from 1.0 to 2.0 without a major version. The causes across all seven PRs:
[hub plan of #84](https://github.com/ufal/atrium-project/blob/test/agent_dev_logs/plans/doc-schema-v2.plan.md),
"Status — PRs".

Round 5 (not pushed):

- `atrium_rocrate.py` and `tests/test_atrium_rocrate.py` re-vendored: a crate root that asserts no licence names
  `#no-licence-asserted` again (RO-Crate 1.2 requires a root licence; atrium-project#6, motyc 11-12). The hub's PR
  failed its RO-Crate check without it.
- `api_2_udp.sh` gets its exec bit back (the push stored it as 100644).

The suite passes: 1087. After the hub's PR merges, `v1` moves to its merge commit and
`scripts/pin_hub_reusables.py --sha` pins this repository's callers to it: drift clears. The record-major check stays
red until the release, which raises the major version in `para_config.txt` (`v1.3.4-beta` now), `CITATION.cff` and
`service/openapi.json`'s `info.version`.

## Status — round 6 (11-14)

The hub's PR (atrium-project#86) merged; `v1` moved to it and K4TEL pinned this repository's callers: drift green. Round
6 (local, delivered as an archive):

- `atrium_document.py`, its schema and `tests/test_document_originators.py` re-vendored: rows may carry
  `lines[].unit: "block"` (rule 5, written by ocr-postprocess only), and `quality_summary.lines` counts them as
  `block_units`. `v2.0.0-beta` as the unreleased version: `para_config.txt`, `CITATION.cff`, `service/openapi.json`
  (re-exported) and a CONTRIBUTING.md row marked Unreleased; api-contract passes with it.
- `api_2_udp.sh` is 100755 again (`git update-index --chmod=+x`): the push of 11-14 had stored it as 100644 once more.
- The hub's scanned E2E lane now runs this image with `--text-from-record` and no ALTO (atrium-project task 7).

The suite passes: 1088. Next: the hub's second PR for #84 (the E2E lanes, rule 5's mark), then `v1` and the pins again;
then this PR. Hub:
[plan of #84](https://github.com/ufal/atrium-project/blob/test/agent_dev_logs/plans/doc-schema-v2.plan.md),
"Status — round 6".

## Depends on

- Kate's answer on #84 (16 November): D24 and the two-level contract.
- ocr-postprocess's slice: the record builder writes `bbox`, `bbox_precision`, `block` and `canvas` in the one
  coordinate space.
- Hub tasks 1 (grants: the `lines[]` linguistic fields), 3 (`file_entity`), 4 (`atrium_limits`); re-vendoring.
- atrium-project#78 (LINDAT terms; D35) for publication, not for the code.

## Superseded in this repository's logs

- `plans/teitok_conformance_plan.md`: a dated note of 11-12 at its top (ALTO input superseded by D24; the record is
  the layout source).
- Closed #42's files (listed, not edited): the record as one of three layout sources → the only one in the
  pipeline.

## Not in scope

- #7 (the domain NameTag model) and #18 (annotation tool): deferred past the pilot phase.
- The LINDAT terms (atrium-project#78); the daily probe's schedule (atrium-project#81).
- Producing ALTO; an ALTO export (D24: only if a consumer needs it, from docproc).
