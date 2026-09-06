# 🤝 Contributing to the NLP Enrichment Pipeline of the ATRIUM project

Thank you for your interest in contributing!
This document describes the development workflow, conventions, and rules for contributors.

## 📦 Release History

| Version     | Highlights                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | Status      |
|:------------|:-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|:------------|
| **v0.20.1** | Vocabulary -> X2, prompt -> configurable. The system prompt moves out of `llm_run.py` into `prompts/system_prompt.txt` as eleven `[[blocks]]` behind nine `PROMPT_*` flags, readable without a GPU via `prompt_template.py --preview / --full / --diff` and committed under `prompts/` behind a `--check` drift gate. Facet census added. Paradata records vocab source.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | Pre-release |
| **v0.20.0** | **The AMCR + TEATER vocabulary becomes reviewable, and every decision in it a config edit.** v0.19.0 shipped the harvest; the built vocabulary was still a flat `cs`/`en`/`sub` list nobody could audit or correct. Entries now carry `source`/`source_id`, every id dedup absorbed (`discarded_ids`, 470 terms), composite/component equivalence (`same_as`, 162 terms), and the bare label of a bracketed homonym (`bare_cs`) — so `llm_run.py` can attach `teater_category_ids` to each enrichment (`EMIT_CATEGORY_IDS`, on by default, reversible by config). The `Documentation` facet is dissolved and the technical AMCR lists excluded. **Curation surface:** facet, sub-header and per-term exclusion overrides keyed on `(source, id)`; `same_as` / `same_as_suppress`; exclusion `status`; `geo_guardrail`; `nested_keep`; `admin_stop_words`; `composite_separators`. `validate_settings()` now refuses an edit that would silently do nothing reporting every problem at once, other vocab enhancements and fixes. Tests set expanded. GHA bumps of dependencies. TEITOK-related attribute reading fixed. | Pre-release |
| **v0.19.0** | **AMCR + TEATER controlled-vocabulary harvest and build.** New `vocab_sources.py` (OAI-PMH walk on an lxml parser with entity expansion and network access disabled) and `vocab_build.py` (pure nesting; `--from-flat --check` proves the artifact is reproducible from the committed flat files alone), driven by a new monthly `vocab-refresh.yml` on a hosted runner because the machines the pipeline usually runs on cannot reach `api.aiscr.cz`; union artifacts land under `data_samples/vocab/`, covered by `test_vocab_sources.py` / `test_vocab_manager.py` over pinned fixtures. The nightly now runs the **full suite** — it previously ran `pytest -m slow` against a repo with zero slow-marked tests and explicitly tolerated exit 5, so it reported success having collected nothing. `openpyxl` declared in `requirements-test.txt`, unlocking a test that had skipped since it was written. Re-vendored `atrium_document.py`; concurrency scoped by `github.event_name`. Bumps: sentence-transformers, vllm, bitsandbytes.                                                                           | Pre-release |
| **v0.18.3** | Re-vendored `atrium_document.py`: `DocumentRecord` now **inherits `doc_id` from the baseline** instead of overwriting it with the caller's derivation. This release also closes **J3**, the gap v0.18.2's own row names: `/enrich` now accepts and returns a `document_json` part instead of shelling out to `run_pipeline.py` without either flag, so the API path finally has the coverage the CLI path had. Also in this window: TEITOK XML validated against its XSD (`api_util/validate_teitok_xml.py` plus the `teitok-schema` workflow, issue #28), `canonical_doc_id()` adopted across `build_manifest_row.py`, `summarize_nt_udp.py`, `teitok_alto.py`, `teitok_read.py` and `run_pipeline.py`, `entities[].type_cnec: null` fixed, and `tests/test_document_originators.py` -> canonical shared set.                                                                                                                                                                                                                                                                                                         | Pre-release |
| **v0.18.2** | `atrium_document` JSON input-output refined and tested against the draft schema **on the CLI path only** — `run_pipeline.py --document-json/--document-json-out`, bridged onto the `stats` stage, and exercised by the hub's end-to-end GHA pipeline. The API service was **not** covered: it shelled out to `run_pipeline.py` without passing either flag, so `/enrich` neither accepted nor returned a `document_json` part (atrium-project#10, J3 — fixed after this release).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | Pre-release |
| **v0.18.1** | Major GHA workflows update and reference to `@v1` on the hub repo. Added annotator LabelStudio imports draft.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | Pre-release |
| **v0.18.0** | `atrium_document` integration of JSON document input-output (draft). Fixed Dockerfile and paradata template refreshed.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | Pre-release |
| **v0.17.0** | OpenAPI standards realization - draft. Updated code according to LLM review. Edited GHA release workflow. `agent-skill` branch service is aligned with the `test` branch API design.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | Pre-release |
| **v0.16.2** | Updated dependency versions. Added `annotation` for the annotator-related code. Fixed config references for api_3 and api_4 scripts.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | Pre-release |
| **v0.16.1** | Updated dependency versins. Added licenses test according to the template. Fixed automatic version reading. Added new tests and fixed existing ones.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | Pre-release |
| **v0.16.0** | Update NER model with new multilingual (onto tagset).Updated template of paradata-related scripts. Added agent_dev_logs directory with issue logs, their digests and plans.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | Pre-release |
| **v0.15.0** | Integration of BBOX rescaling into the whole repo + new tests added                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | Pre-release |
| **v0.14.3** | Added new API entry point `/rescale` + Docker GH Actions alignment proceeding                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | Pre-release |
| **v0.14.2** | Ruff and pre-commit checks applied + Docker GH Actions alignment                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | Pre-release |
| **v0.14.1** | Next round LLM review edits and Docker GH Actions alignment                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | Pre-release |
| **v0.14.0** | Flexiconv-supported input formats added, and teitok xml inputs to LLM and KW parts. Test set expanded. Docker GH Actions fixed.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | Pre-release |
| **v0.13.0** | Alignment of BBOXes in TEITOK XMLs implemented to use metadata of the page image sizes instead of real page image files. Post factum fix added.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | Pre-release |
| **v0.12.0** | API service wrapper integrated to use the merged pipeline logic. Docker wrapper draft is added                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | Pre-release |
| **v0.11.0** | Merged pipeline of all 1-4 stages + keywords method of choice + optional LLM run from a single entry point. Replacement of the original data samples with synthetic similar documents. Paradata licensing implemented. Preservation tests added, and manifest composition changed.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | Pre-release |
| **v0.10.1** | Pytest unit tests added; CONTRIBUTING.md expanded with test documentation and release history section                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | Pre-release |
| **v0.9.1**  | LLM pipeline (first stage of development - all model families reported): Qwen and Gemma families identified as most promising; multi-stage prompt engineering for token-safe system prompts with thematic vocabulary grouping; critical fallback term for administrative text (headers, page numbers)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | Pre-release |
| **v0.9.0**  | LLM pipeline for vocabulary-based keywords extraction in JSONs: LLM-based processing of input texts added; prompt engineering leveraging vocabulary from TEATER API structured by defined taxonomy config                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | Pre-release |
| **v0.8.1**  | Keywords extraction by KER, YAKE, KeyBERT: new keyword extraction methods added — KeyBERT (GPU-based, semantically rich) and YAKE (CPU-based, fast)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | Pre-release |
| **v0.7.0**  | text lines -> UDP -> NER -> CSV + CoNLL-NE + beta TEITOK: ALTO XML + page image PNG + CoNLL-NE → TEITOK XML with correct layout element boundaries (upgraded from alpha); LLM-enhanced code; README updated with flexiconv and TEITOK documentation                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | Pre-release |
| **v0.5.1**  | text lines -> UDP -> NER -> CSV + CoNLLU-NE + alpha TEITOK (CSV inputs, 3 steps to get NER and UDP, Outputs per-document files: CoNLLU-NE as a combination of UDP and NT APIs application, CSV table with text line's POS and NER columns, TEITOK XML formed from ALTO XML + CoNLLU-NE (draft))                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | Pre-release |
| **v0.4.0**  | UDP from raw CSV -> KER + NER -> CoNLLU-NE (Config file format changed, Added second per-document result files - combination of UDPipe with NER tags, UDPipe called on CSV files as before, KER called on CoNLL-U files for lemma access)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | Pre-release |
| **v0.3.0**  | KER + UDP -> NER from raw CSV files with textlines (Inputs format changed to CSV for KER and UDPipe, UDPipe results moved from TEMP to OUTPUT, UDPipe outputs as NER inputs)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | Pre-release |
| **v0.2.0**  | NER + UDP + KER from raw TXT files (KER local processing added, TXT inputs in all)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | Pre-release |
| **v0.1.0**  | NER + UDP from raw TXT files (Per-page txt files extracted by alto-tools as inputs, 4-step process, Initial working version)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | Pre-release |


## 🌿 Branches & Environments

| Branch   | Environment          | Rule                                                                            |
|----------|----------------------|---------------------------------------------------------------------------------|
| `test`   | Staging              | Base for all development. Always branch from `test`.                            |
| `master` | Stable / Integration | Merged exclusively by a human reviewer. Do not open PRs directly into `master`. |

```text
test    ←  feature-<name>
test    ←  bugfix-<name>
master  ←  (humans only, after test stabilises)

```

### 🏷️ Branch Naming

| Type             | Pattern          | Example              |
|------------------|------------------|----------------------|
| New feature      | `feature-<name>` | `feature-teitok`     |
| Bug fix          | `bugfix-<name>`  | `bugfix-chunking`    |
| Hotfix on master | `hotfix-<name>`  | `hotfix-api-timeout` |

---

## 🔁 Contributor Workflow

1. **Create an issue** (or find an existing one) describing the problem or feature.
2. **Branch from `test`:**
```bash
git checkout test
git pull origin test
git checkout -b feature-<name>
```
3. **Implement your changes** observing the project's code conventions.
4. **Run the minimum tests** (see the Testing section).
5. **Open a Pull Request** targeting the `test` branch.

---

## 📋 Pull Request Format

Every PR must include:

* **Issue link:** `Closes #<number>` or `Refs #<number>`
* **Motivation:** why the change is needed
* **Description of change:** what was changed and how
* **Testing:** what was run, what passed, what could not be executed

Use a **Draft PR** if the work is not ready for review.

**Do not open PRs into `master` — merging into `master` is exclusively the
maintainers' responsibility.

> **Note on issue tracking:** Issues reference the commits and PRs that resolved
> them — not the other way around. Commit messages describe *what changed*; the issue
> is the place to record *why* and link the resulting commits together.

---

## ✏️ Commit Messages

Format:

```text
[type] concise description of what changed
```

Allowed types:

| Type       | When to use                           |
|------------|---------------------------------------|
| `add`      | Added content (general)               |
| `edit`     | Edited existing content (general)     |
| `remove`   | Removed existing content (general)    |
| `fix`      | Bug fix                               |
| `refactor` | Refactoring without behaviour change  |
| `test`     | Adding or updating tests              |
| `docs`     | Documentation only                    |
| `chore`    | Build, dependencies, CI configuration |
| `style`    | Formatting, no logic change           |
| `perf`     | Performance optimisation              |


---

## 🧪 Code Conventions & Testing

### Code Conventions

* **Comments:** informative but short, may be LLM-generated, added when function name does
not explain its functionality in detail
* **Argument types:** set default type (e.g., `int`, `list`) for function arguments
* **Console flags:** when a new one added, provide help message for it
* **Config files:** when set of variables changes it should be reflected in repository documentation
* **Generated code:** always should be manually launched and checked for mistakes before pushing

### Minimum checks before every commit

Always run basic validation locally before pushing:

```bash
# 1. Python compilation check
python -m compileall -q .

# 2. Lint & format (Ruff — matches CI)
ruff check .
ruff format .

# 3. Shell-script lint
shellcheck -e SC1091 api_*.sh api_util/*.sh setup_api_service.sh
```

> [!NOTE]
>  If specific scripts or extraction modules are updated, please run a smoke-test
> against the `data_samples/` directory to verify extraction integrity.

---

### Running the test suite

The repository ships a `pytest` harness that requires **no ML models or GPU**. The whole
suite runs offline in well under a minute.

```bash
pip install -r requirements-test.txt
```

That file is more than pytest: it also pins `jsonschema` (the `atrium_document` schema
gate), `lxml` (the TEITOK XSD gate and the OAI-PMH parser), `openpyxl`, and the FastAPI
test stack — each with a comment saying which gate would silently skip without it.

```bash
pytest -q                                    # the whole suite — use before every commit
pytest --cov=. --cov-report=term-missing     # with coverage
```

> There is **no `slow` marker in this repository** — `grep -rc pytest.mark.slow tests/`
> returns zero. `pytest -m "not slow"` and a bare `pytest` are the same run, which is
> what made the old nightly report success having collected nothing (see the v0.19.0
> row above). Heavy deps are separated by *workflow*, not by marker: `torch` lives in
> `gpu-inference.yml`, `transformers` in `scheduled-smoke.yml`.

`tests/test_paradata.py` (`ParadataLogger`, `_sanitise`) is shared across all repos.

<details>
<summary>Test layout, per-repo targets, and fixture conventions</summary>

```text
tests/
├── __init__.py              # empty
├── conftest.py              # shared fixtures (tmp_path wrappers, sample data loaders)
├── fixtures/                # small static test-data files committed to the repo
└── test_<module>.py         # repo-specific unit tests
```

**Per-repo targets:**

| Repository                | Test file           | Primary targets                                                                                                                                    |
|---------------------------|---------------------|----------------------------------------------------------------------------------------------------------------------------------------------------|
| `atrium-nlp-enrich`       | `test_keywords.py`  | `_extract_surface_text`, `_extract_lemmas`, `_extract_legacy`, `extract_keywords`, `_sort_csv_file`                                                |
| `atrium-alto-postprocess` | `test_text_util.py` | Density/ratio helpers, detectors, `pre_filter_line`, `parse_line_splits`, `categorize_line` (ppl passed directly, no GPU), `compute_quality_score` |
| `atrium-alto-postprocess` | `test_utils.py`     | `directory_scraper`, `dataframe_results` (Top-1 and Top-N), `collect_images`                                                                       |
| `atrium-translator`       | `test_utils.py`     | `_resolve_namespaces`, `validate_xml_with_xsd`, `process_alto_xml`, `process_amcr_xml` (mock translator injected)                                  |

**Heavy tests** — a test that loads a model checkpoint, calls an external API, or needs a
GPU does not belong in the default suite. Put it behind the workflow that has the
resource (`gpu-inference.yml`, `scheduled-smoke.yml`) rather than behind a marker, and
say in the PR description what it requires.

**Fixtures** — small, self-contained files committed under `tests/fixtures/`. Add a
minimal fixture in the same commit as any test that needs new sample data.

**The one deliberate exception: drift gates read `data_samples/` on purpose.** A test
that asserts a *committed artefact* still matches what its config would produce has to
open the committed artefact — a fixture copy would only prove the fixture is
self-consistent. Eleven modules do this, and it is the point of each:
`test_vocab_build.py`, `test_vocab_manager.py`, `test_vocab_review.py`,
`test_corpus_review.py`, `test_prompt_template.py`, `test_validate_teitok.py` and
friends. Everywhere else, prefer a fixture.

</details>

---

## 📁 Repository Documentation Management

Each documentation file has one target audience and one responsibility. Rules are not repeated — cross-references are used instead.

| File                                     | Audience                | Responsibility                                                                          |
|------------------------------------------|-------------------------|-----------------------------------------------------------------------------------------|
| `README.md`                              | GitHub visitors         | Project overview, workflow stages, quick start                                          |
| `CONTRIBUTING.md`                        | Developers              | Code conventions, branches, PRs, testing, generated artefacts                           |
| `data_samples/vocab/RUNBOOK.md`          | **Vocabulary curators** | Every vocabulary script and flag, the eight review sheets, where a decision is recorded |
| `prompts/RUNBOOK.md`                     | **Prompt reviewers**    | The prompt blocks and their flags, the guardrail's two halves, the output contract      |
| `data_samples/vocab/6.*.md`              | Domain reviewers        | One open question each, framed with numbers from the sheets beside them                 |
| `annotation/README.md` · `GUIDELINES.md` | Annotators              | Label Studio / Doccano setup; the annotation label scheme                               |
| `service/README.md`                      | API consumers           | REST endpoints, environment variables, deployment                                       |
| `schemas/teitok/README.md`               | Format maintainers      | The TEITOK XSD and its conformance gate                                                 |
| `agent_dev_logs/DEVLOG.md`               | Maintainers             | Per-issue history: digests, plans, decisions                                            |

* **Do not duplicate rules:** if a rule is defined in `CONTRIBUTING.md`, other files
reference it rather than copying it.
* **When changing a rule:** update the canonical source and verify that referencing files
still point correctly.

---

## ⚙️ Generated Artefacts

Some files are modified automatically by scripts or hooks:

| Script                   | What it generates                                                                                                                 |
|--------------------------|-----------------------------------------------------------------------------------------------------------------------------------|
| `api_1_manifest.sh`      | `manifest.tsv` — ordered list of all pages to process                                                                             |
| `api_2_udp.sh`           | `UDP/*.conllu` — per-document CoNLL-U files                                                                                       |
| `api_3_nt.sh`            | `NE/*/*.tsv` — per-page NER-annotated TSV files                                                                                   |
| `api_4_stats.sh`         | `UDP_NE/`, `TEITOK/`, `summary_ne_counts.csv`                                                                                     |
| **`vocab_build.py`**     | the 14 vocabulary artefacts in `data_samples/vocab/` — harvests, nested facets, meta sidecars, placement audits, `vocabulary.csv` |
| **`vocab_review.py`**    | the 8 reviewer sheets in `data_samples/vocab/` (`--all`)                                                                          |
| **`corpus_review.py`**   | the 3 corpus-evidence sheets + `corpus_review.meta.json` (`--all`; needs the document corpus)                                     |
| **`prompt_template.py`** | the 4 committed prompt renders in `prompts/` (`--write`)                                                                          |

Rules:

1. Do not manually edit auto-generated output files.
2. After changing chunking logic, re-run `api_2_udp.sh` to verify CoNLL-U validity.
3. After changing NER merging logic or TEITOK XML composition, re-run `api_4_stats.sh`
and inspect `summary_ne_counts.csv`.
4. **Config and generated artefact move in the same commit.** Editing
`data_samples/taxonomy_*.json`, `llm_config.txt` or `prompts/system_prompt.txt` without
regenerating is the failure this repo has already shipped twice (`a5e3c8a`, `d4c46b2`):
the config said one thing and the artefact the model actually reads said another, with
nothing failing. Three gates now catch it, and all three run on every PR
(`.github/workflows/vocab-drift.yml`):

   ```bash
   python3 vocab_build.py --from-flat && python3 vocab_build.py --from-flat --check
   python3 vocab_review.py --all
   python3 prompt_template.py --write && python3 prompt_template.py --check
   ```

   Full procedure and the decision tables:
   [`data_samples/vocab/RUNBOOK.md`](data_samples/vocab/RUNBOOK.md) and
   [`prompts/RUNBOOK.md`](prompts/RUNBOOK.md).

---

## 🚩 Output Format Flags

Pipeline output is controlled by boolean flags in `config_api.txt`. When adding a new output format,
follow this pattern:

| Variable         | Description                                              | Default |
|------------------|----------------------------------------------------------|---------|
| `SAVE_CONLLU_NE` | Enriched CoNLL-U with NER in the `MISC` field            | `true`  |
| `SAVE_CSV`       | Token-level summary CSV per document                     | `true`  |
| `SAVE_TEITOK`    | TEITOK-style TEI XML with bounding boxes (requires ALTO) | `true`  |

New flags must be documented here and in `config_api.txt`.

---

## 📞 Contacts & Acknowledgements

For technical questions contact **lutsai.k@gmail.com**

**Issues:** https://github.com/ufal/atrium-nlp-enrich/issues


* **Developed by:** UFAL [^7]
* **Funded by:** ATRIUM [^4]
* **Models:**
  * NameTag 3 [^6]
  * UDPipe 2 [^5]

**©️ 2026 UFAL & ATRIUM**


[^2]: https://github.com/ufal/atrium-alto-postprocess
[^3]: https://ufal.mff.cuni.cz/~strakova/cnec2.0/ne-type-hierarchy.pdf
[^4]: https://atrium-research.eu/
[^5]: https://lindat.mff.cuni.cz/services/udpipe/api-reference.php
[^6]: https://lindat.mff.cuni.cz/services/nametag/api-reference.php
[^1]: https://github.com/ufal/atrium-nlp-enrich
[^7]: https://ufal.mff.cuni.cz/home-page
