# Prompt and output runbook

What the model is told, where each sentence lives, which knobs change it, and what the
run writes back. Companion to
[`data_samples/vocab/RUNBOOK.md`](../data_samples/vocab/RUNBOOK.md), which covers the
term list this prompt wraps around. Issue
[#6](https://github.com/ufal/atrium-nlp-enrich/issues/6).

Nothing here needs a GPU. Every command below is stdlib-only and offline —
`prompt_template.py` deliberately imports nothing outside the standard library, which is
what lets `vocab_build.py` check the *rendered* prompt without paying for torch.

---

## The one-minute version

```bash
python3 prompt_template.py --blocks     # which instruction blocks are on, and what each costs
python3 prompt_template.py --preview    # the instructions, with a placeholder where terms go
python3 prompt_template.py --full       # the whole thing: instructions + all 4 718 terms
python3 prompt_template.py --check      # exit 0 = the committed renders are current
python3 prompt_template.py --write      # regenerate them after a change
```

Or read the committed renders directly — same bytes, no Python required:
[`prompt_blocks.txt`](prompt_blocks.txt) · [`prompt_preview.txt`](prompt_preview.txt) ·
[`prompt_full.txt`](prompt_full.txt) (5 000 lines, 125 `--- Facet / Sub ---` headers) ·
[`prompt_guardrail_diff.txt`](prompt_guardrail_diff.txt).

---

## 1. Where each sentence lives

| File                                                                                         | Role                                                                                    | Hand-edited?                                                                 |
|----------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| [`system_prompt.txt`](system_prompt.txt)                                                     | **Source of truth.** Every instruction sentence, as `[[named blocks]]` in render order. | **Yes** — this is the file a domain reviewer changes                         |
| [`output_template.json`](output_template.json)                                               | **Source of truth.** The committed shape of one `<doc_id>_enriched.json`.               | **Yes**, but pinned by test against the schema and the prompt's own examples |
| `prompt_blocks.txt` · `prompt_preview.txt` · `prompt_full.txt` · `prompt_guardrail_diff.txt` | Committed renders — documentation, for reading and diffing                              | **No.** Generated; `--check` fails if you edit one by hand                   |
| [`../llm_config.txt`](../llm_config.txt)                                                     | Which blocks render, the guardrail mode, the term layout                                | **Yes** — 9 `PROMPT_*` keys                                                  |
| [`../prompt_template.py`](../prompt_template.py)                                             | The renderer, the CLI, and the drift gate                                               | code                                                                         |

`llm_run.py` holds **no prompt text at all**. It calls `prompt_template.render(config)`,
injects the vocabulary through `prompt_template.vocabulary_block`, and appends the
footer. The one thing that stayed in Python is truncation, because that needs a real
tokenizer.

### The template format

A block header is `[[name]]` alone on a line; everything to the next header is that
block's body; **file order is render order**. To move a rule, move it in the file.

Two whitespace rules, both deliberate:

- Trailing blank lines are normalised to exactly one newline — an editor that strips
  trailing whitespace cannot silently change the prompt.
- A **leading** blank line is kept, because that is how a block asks for a blank line
  ahead of itself (`vocabulary.header` and `examples` both rely on this).

Lines starting with `#` **before the first block** are file comments. Inside a block,
everything is prompt text — including a `#`.

---

## 2. The eleven blocks, and the nine flags

```
  prompt blocks (geo guardrail: preference, vocabulary grouping: facet_sub) — ~502 tokens of instructions
    [on ] role                             ~  47 tok
    [on ] task.extract                     ~  53 tok
    [on ] task.select                      ~  25 tok
    [on ] rule.metatext                    ~  79 tok
    [off] guardrail.geographic.strict      ~  72 tok
    [on ] guardrail.geographic.preference  ~  41 tok
    [on ] rule.ocr_normalisation           ~  62 tok
    [on ] rule.exact_term                  ~  19 tok
    [on ] rule.json_only                   ~  23 tok
    [on ] vocabulary.header                ~   7 tok
    [on ] examples                         ~ 146 tok
```

| Block                             | Flag in `llm_config.txt`          | Notes                                                 |
|-----------------------------------|-----------------------------------|-------------------------------------------------------|
| `role`                            | —                                 | **always renders**                                    |
| `task.extract`                    | `PROMPT_TASK_EXTRACT`             |                                                       |
| `task.select`                     | `PROMPT_TASK_SELECT`              |                                                       |
| `rule.metatext`                   | `PROMPT_METATEXT_RULE`            | the `Nerelevantní (meta-text)` fallback               |
| `guardrail.geographic.strict`     | `PROMPT_GEO_GUARDRAIL=strict`     | the pre-M11 absolute ban                              |
| `guardrail.geographic.preference` | `PROMPT_GEO_GUARDRAIL=preference` | **in force** — M12's wording                          |
| `rule.ocr_normalisation`          | `PROMPT_OCR_NORMALISATION`        |                                                       |
| `rule.exact_term`                 | `PROMPT_EXACT_TERM`               |                                                       |
| `rule.json_only`                  | —                                 | **always renders**                                    |
| `vocabulary.header`               | —                                 | **always renders**; terms are injected right after it |
| `examples`                        | `PROMPT_EXAMPLES`                 | the most expensive rule at ~146 tokens                |

Two keys are not block switches: `PROMPT_TEMPLATE` points at the template file (so a
variant prompt is a config edit, not a file swap), and `PROMPT_VOCAB_GROUPING` chooses
the term layout — §5.

**Safe to flip on your own:** the six booleans, `PROMPT_VOCAB_GROUPING`, and
`EMIT_CATEGORY_IDS` (whether `teater_category_ids` is attached after inference — M7 was
granted as reversible). Every one is echoed in the run banner and in `--blocks`.

**Not safe alone: `PROMPT_GEO_GUARDRAIL`.** See §3.

Adding a block to the template means adding its flag to `BLOCK_FLAGS` in
`prompt_template.py`. A block with no flag and not in `REQUIRED_BLOCKS` is an **error**,
not a silent no-op — an unreachable block is exactly the thing that reads as "the rule is
there" while the model never sees it.

---

## 3. ⚠ The geographic guardrail is one decision in two files

The clause the model reads lives in `prompts/system_prompt.txt` and is selected by
`PROMPT_GEO_GUARDRAIL`. Whether the vocabulary *offers* geographic, ethnic and dynastic
terms lives in `data_samples/taxonomy_config.json` (`geo_guardrail` plus the
`heslar_map` / `teater_branch_map` values). Change one half alone and the run measures
the contradiction rather than the model.

Current state, post-M11/M12 — the two halves agree:

```
llm_config.txt          PROMPT_GEO_GUARDRAIL=preference
taxonomy_config.json    geo_guardrail: { active: false, covers: [] }
                        heslar_map.zeme -> "Cultural & Geographic Context"   (offered)
```

`vocab_build.py` enforces the pairing: it renders the block the config selects and
checks *that text* against `taxonomy_config.json`. It does not grep Python for a
sentence — which is the whole reason the prompt became a template.

```bash
python3 vocab_build.py --from-flat --check   # exits non-zero on a one-sided change
python3 prompt_template.py --diff PROMPT_GEO_GUARDRAIL=strict PROMPT_GEO_GUARDRAIL=preference
```

The diff is two lines, and it is what M11/M12 actually changed. Both halves move in the
same commit; the build gate does not permit otherwise.

One trap worth knowing: `geo_guardrail.prompt_markers` is how the gate *recognises* the
strict clause. Reword the strict block without updating the markers and the gate stops
detecting it — silently. A test pins that
(`test_the_strict_wording_carries_every_marker_the_config_looks_for`).

---

## 4. What the run writes — the output contract

[`output_template.json`](output_template.json) is the committed shape of one
`<OUTPUT_DIR>/<doc_id>_enriched.json`: a JSON **array** of records, written by
`llm_run.py`.

Six carried-through fields (`file_id`, `page`, `line`, `categ`, `quality_score`,
`original_text`) plus `enrichment`:

| Field                   | Meaning                                                                                                                                                                                                      |
|-------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `extracted_keywords_cs` | Czech terms found **in the line**; `[]` for meta-text                                                                                                                                                        |
| `extracted_keywords_en` | English translations, same length and order                                                                                                                                                                  |
| `teater_category`       | one label from the controlled vocabulary, or `Nerelevantní (meta-text)`. A bracketed homonym qualifier is **stripped back off here** — `zámek (sídlo elity)` is offered to the model but reported as `zámek` |
| `confidence_score`      | float in `[0,1]`, for filtering                                                                                                                                                                              |
| `teater_category_ids`   | every `{source, id}` the chosen label stands for — its own plus everything M7 dedup absorbed onto it. Gated by `EMIT_CATEGORY_IDS`                                                                           |

Only the first four come from the model; `teater_category_ids` is attached after
inference by `_attach_category_ids`.

An abandoned document leaves `<doc_id>_enriched.abort.json` beside the output, carrying
`aborted`, `abort_reason`, `processed_before_abort`, `errors_before_abort` and
`timestamp_utc`. A missing main file next to a present sidecar is a *deliberate* abort,
not a crash.

Three tests hold this file honest so it cannot drift from what the code does:
`test_output_template_matches_the_schema_the_model_is_given` (against `build_schema` in
`llm_run.py`), `test_the_prompt_examples_agree_with_the_output_template`, and
`test_the_metatext_example_shows_empty_keyword_arrays`.

**Not in the output: the facet.** M2 settled that facets are internal prompt
organisation, not semantic output — they group the term list and set truncation order,
and they never reach a record.

**A naming wart, documented rather than fixed:** the field is called `teater_category`
but the vocabulary is the AMCR + TEATER union, so an AMCR-only term is reported under a
`teater_*` name. Renaming it is an output-schema break for downstream consumers, so it
stays.

---

## 5. The term layout — `PROMPT_VOCAB_GROUPING`

@motyc's second question under M2: *"check empirically how much facet placement affects
the results at all."* It was unanswerable while the grouping was welded into the prompt
builder. It is now a flag.

| Value       | Renders                                                                  | Term order                                                     |
|-------------|--------------------------------------------------------------------------|----------------------------------------------------------------|
| `facet_sub` | `--- Facet / Subgroup ---`, both curated levels — **the shipped prompt** | a permutation *within* each facet (sub-groups made contiguous) |
| `facet`     | `--- Facet ---` only                                                     | unchanged                                                      |
| `flat`      | no headers at all                                                        | unchanged                                                      |

All three offer the same terms and truncate identically. That gives two clean contrasts
rather than one muddled scale:

- **`facet` vs `flat`** isolates the ~125 header lines alone, term order identical.
- **`facet_sub` vs `facet`** measures the source's own second level — headers and
  adjacency together, which is what a real grouping is.

An unrecognised value **raises** rather than falling back, so an ablation cannot report
a difference that was never applied.

The cost is already known even though the benefit is not — headers are **~1 536 tokens**
on top of 44 781 tokens of terms, which at a 32k window is real terms dropped:

| Window   | `facet_sub` | `facet` | `flat` |
|----------|------------:|--------:|-------:|
| 8 192    |         419 |     442 |    445 |
| 32 768   |       3 106 |   3 223 |  3 232 |
| 128 000+ |       4 718 |   4 718 |  4 718 |

So the shipped layout costs **126 terms at 32k** against `flat` (117 of them the
sub-level, 9 the facet headers) and **nothing at 128k**. What nobody has measured is
whether the structure helps the model at all — that is **A2-grouping**, and it needs the
evaluation corpus and the D1 rubric, not more code.

---

## 6. Cost, and where truncation cuts

`--blocks` prices each rule, because at a tight context window **a rule kept is terms
dropped**. Instructions are ~502 tokens; the vocabulary is ~46 317 (44 781 of terms plus
1 536 of group headers under the shipped layout).

`data_samples/vocab/context_budget.csv` and `facet_census.csv` charge the *configured*
prompt's overhead against each model's window, so turning `PROMPT_EXAMPLES` off shows up
there as room for ~146 tokens of terms. Both are regenerated by
`python3 vocab_review.py --all`, and both go stale on a `PROMPT_*` flip — which is why
both are covered by the review-sheet drift test.

At today's build:

| Window   | Terms surviving | What is cut                          |
|----------|----------------:|--------------------------------------|
| 8 192    |     419 / 4 718 | everything from `Activity Area` down |
| 32 768   |   3 106 / 4 718 | only `Related Disciplines & Society` |
| 128 000+ |   4 718 / 4 718 | nothing                              |

Truncation keeps the largest fitting **prefix** in facet-priority order, so a facet is
not dropped for being unimportant — it is dropped for sitting late in the order, and
everything after the cut goes with it. That is the concrete form of M11's *evaluate later
if problems arise*: the reinstated terms sit last by design.

---

## 7. After any prompt change

```bash
$EDITOR prompts/system_prompt.txt           # or flip a PROMPT_* flag in llm_config.txt
python3 prompt_template.py --write          # 1. refresh the four committed renders
python3 prompt_template.py --check          # 2. must exit 0
python3 vocab_build.py --from-flat --check  # 3. guardrail halves must still agree
python3 vocab_review.py --budget --census   # 4. the overhead moved; refresh both sheets
python3 -m pytest tests/test_prompt_template.py tests/test_vocab_review.py -q
git add prompts data_samples/vocab llm_config.txt && git commit
```

**Config and renders move in the same commit.** Same rule as the vocabulary, for the same
reason: commit `a5e3c8a` shipped a config that dissolved a facet while the built artifact
still offered all 107 of its terms, and nothing failed. Until `--check` existed, flipping
`PROMPT_GEO_GUARDRAIL` left all four committed renders advertising the old wording with
zero CI failures.

`.github/workflows/vocab-drift.yml` runs steps 2 and 3 on every push and PR touching
`prompts/**`, `llm_config.txt`, `prompt_template.py` or the taxonomy, with a negative step
that flips a flag and asserts the gate still fails.

---

## 8. Where a prompt decision gets recorded

| Decision                                                             | Goes in                                                                                                                                       |
|----------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------|
| The wording of a rule                                                | `prompts/system_prompt.txt`, in its block                                                                                                     |
| Whether a rule is sent at all                                        | `llm_config.txt`, the block's `PROMPT_*` flag                                                                                                 |
| Geographic/ethnic terms: banned, preferred-against, or unconstrained | `PROMPT_GEO_GUARDRAIL` **and** `taxonomy_config.json`'s `geo_guardrail`, together                                                             |
| How the term list is laid out                                        | `PROMPT_VOCAB_GROUPING`                                                                                                                       |
| A new rule the prompt does not have                                  | a new `[[block]]` **and** its entry in `BLOCK_FLAGS`                                                                                          |
| Whether ids ride along with each answer                              | `EMIT_CATEGORY_IDS` in `llm_config.txt`                                                                                                       |
| What a record contains                                               | `prompts/output_template.json` **and** `build_schema` in `llm_run.py`, held in step by test                                                   |
| Which facets reach the prompt at all                                 | `in_prompt` per facet in `taxonomy_config.json`                                                                                               |
| Nothing                                                              | any `prompts/prompt_*.txt`. All four are regenerated by `--write`; a hand edit is discarded on the next run, and fails `--check` before that. |
