# TEITOK conformance & flexi* integration — ecosystem plan (umbrella for #9 · #10 · #28)

> _Written 2026-09-23 from an audit of `atrium-nlp-enrich` (`test` `ed18f40`, v0.20.3), `atrium-llm-enrich`,
> `atrium-alto-postprocess` and `atrium-project`, checked against the TEITOK author's own tooling. Per-issue detail:
> [`digests/9.digest.md`](../digests/9.digest.md) · [`plans/9.plan.md`](9.plan.md) ·
> [`digests/10.digest.md`](../digests/10.digest.md) · [`plans/10.plan.md`](10.plan.md) ·
> [`digests/28.digest.md`](../digests/28.digest.md) · [`plans/28.plan.md`](28.plan.md). Findings marked ▶ were
> reproduced by running the code (scratch environment, repos untouched)._

## 0. Progress (updated 2026-09-23)

Stages 1–5 are implemented. Stage 1 is on `test` (maintainer commits `bd62317` / `f82f922`). Stages 2–5 are on the
local branch `claude/inspiring-cerf-2gdtd1` in nlp-enrich, llm-enrich and the hub, which is not pushed and awaits review.

| Stage | State | Deviations from §5 |
|-------|-------|--------------------|
| 1 — dev logs | ✅ on `test` | the umbrella plan moved into `plans/`; its links were fixed in Stage 2 |
| 2 — P0 fixes | ✅ branch | hub `atrium_vocab.py` **not** touched: the file is byte-identical in five tool repos, so `teitok_alto._CNEC_TO_CONLL` keeps its name as the declared authority (now an alias of `ner_types.CNEC_TO_CONLL`); a drift test pins it equal to `atrium_vocab.CNEC_TO_ENTITY_TYPE`. `summarize_nt_udp.py` keeps its own CNEC→OntoNotes *explanation* map (a different purpose). `ner_types.CNEC_CODES` recognises every CNEC 2.0 code (`ty`, `n_`, `T`, …), not only the coarse-mapped ones |
| 3 — writer conformance | ✅ branch | `entities[].bbox` stays in ALTO page units (it matches `lines[].bbox`); `pages[].teitok_surface` is only written for pages that have a `<surface>` (ALTO input), so `/enrich` records have none. Also fixed on the way: non-ALTO roots (PAGE XML, hOCR) passed as `alto_path` no longer produce an empty facsimile; unnamed ALTO blocks/lines no longer collapse into one; `summarize_nt_udp.py` per-document mode forwards `--dpi/--alto-dpi`; the dead pre-merge writer call is removed; `MODEL_NAMETAG` reaches the header (`--model-nametag`) |
| 4 — flexiconv path | ✅ branch (`run_pipeline.py --with-flexiconv` deferred) | reference experiment on flexiconv's own examples recorded in the README; real ATRIUM documents still to run |
| 5 — cross-repo | ✅ branch | hub: E2E asserts TEITOK and turns `SAVE_TEITOK` on; fixture + `document_schema.md` ids. `docs_site/external-tools.md` / `pipelines.md` W11 and the `atrium_vocab.py` authority string left to their own rounds (#57 policy, 5-repo vendoring) |
| 6 — annotation of flexiconv output | ⏸ later, new issue | — |

Evidence: flexiconv v0.3.10 round-trip of the regenerated samples keeps every `SpaceAfter=No` (7/7, 16/16, 2/2;
before: 0/7). "abych" is one `<tok>` with two `<dtok>`. OntoNotes `PERSON` → `type="PER" onto="PERSON"`. Sample block
bbox is `220 160 1420 280` on `1654×2339` (page) or `20 10 1220 130` on `1254×2039` (printspace). nlp-enrich
`pytest -m "not slow"` passes 1007 tests with 7 environment-only skips.

## 1. Why this plan exists

`atrium-nlp-enrich` is the only ATRIUM tool that **writes** TEITOK XML (`api_util/teitok_alto.py`, stage 4 /
`/enrich`) and the only one that **converts** third-party formats into it (`api_flexiconv.sh` → flexiconv).
`atrium-llm-enrich` **reads** it (`api_util/teitok_read.py`, `api_util/xml_to_md.py`); the hub **documents** it
(`docs/document_schema.md`, `docs_site/pipelines.md`, `docs_site/external-tools.md`) and its shared
`atrium_vocab.py` names `teitok_alto.py _CNEC_TO_CONLL` as the authority of the 4-concept `entity-type` SKOS scheme.

Since the #9/#10/#28 logs were last refreshed, #28 landed (v0.18.3), #11 switched NER to the multilingual
**OntoNotes** model, the flexiconv pin moved to `v0.3.10`, and upstream made plain `@id` the TEITOK default
(flexipipe 0.3.27, 2026-08-05). The question behind this plan: *do the files we generate — via the CLI and via the
service — still fit current TEITOK conventions, and what in the issue plans is still undone?*

## 2. Reference: current TEITOK conventions

There is **no published TEITOK schema** (no XSD/RNG/DTD in any upstream repository) and teitok.org is not reachable
from the build environment, so the reference is the behaviour of the TEITOK author's own readers and writers:
flexiconv `v0.3.10` = `a982b88` (main `a4f0fd9`), flexipipe `73188c5`, xmltokenizer `4b05623`, flexicorp `61f6543`,
teitok-tools `2968265`.

| Aspect               | Convention                                                                                                                                                                                                                                   | Where upstream does it                                                                                               |
|----------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------|
| Namespace            | namespace-off `<TEI>`; `xmlnsoff="http://www.tei-c.org/ns/1.0"` is the TEITOK idiom                                                                                                                                                          | flexiconv `io/teitok_xml.save_teitok`; flexicorp `flexdecoder_writers.cpp`; teitok-tools `teitok2p5.pl`              |
| Ids                  | plain `@id` (not `xml:id`) on `tok`/`s`; `w-N` / `s-N`, document-global; other elements `facs-N`, `lb-P.L`, `e-N`                                                                                                                            | xmltokenizer `profiles_builtin/teitok.toml`; flexiconv `io/alto.py`, `io/page_xml.py`; `conllu2teitok.pl`            |
| Token attributes     | `lemma upos xpos feats deprel head` (+`ord` sentence index, `ohead`, `deps`, `misc`); `_` values dropped; `head` = the head token's `@id`                                                                                                    | `conllu2teitok.pl`; xmltokenizer `conllu.py`; flexipipe `teitok_name_wrap._tok_ord` (needs `ord` or `w-N`)           |
| **Spacing**          | **text-faithful**: whitespace between `</tok>` and the next `<tok>` is a space; none = `SpaceAfter=No`. `join="right"` is a TEI-P5 export marker, honoured by flexicorp only under `@space="remove"`                                         | flexipipe `_token_from_tok_elem`; flexiconv `load_teitok`; `teitok2conllu.pl`; flexicorp `flexencoder_extractor.cpp` |
| Multi-word tokens    | `<tok>surface<dtok form=… lemma=… …/><dtok …/></tok>`                                                                                                                                                                                        | `conllu2teitok.pl`; flexipipe `_dump_teitok_python`; xmltokenizer                                                    |
| Named entities       | `<name type=…>` wrapping the span, optional `sameAs="#w-1 #w-2"`                                                                                                                                                                             | `nametag.pl`; flexipipe `teitok_name_wrap.py`                                                                        |
| Header               | `titleStmt/title`; `notesStmt/note[@n="orgfile"]`; `revisionDesc/change[@who,@when]`; flexicorp reads workflow phases from `change@type/@subtype/@n` (`converted`, `tokenized`, `tagged`, `parsed`, `ner`) and falls back to the change text | flexiconv `_ensure_tei_header`; flexicorp `backends/teitokxml.py`                                                    |
| Language             | plain `@lang` on `TEI`/`text`/`div`/`s` and/or `profileDesc/langUsage/language`                                                                                                                                                              | flexiconv `io/{folia,tmx,hocr}.py`; `udpipe2teitok.pl`                                                               |
| Layout               | `bbox="x1 y1 x2 y2"` in **absolute page-image pixels, page origin** (raw ALTO HPOS/VPOS); `<pb facs>`; optional `<facsimile><surface><zone>` + `@corresp`                                                                                    | flexiconv `io/alto.py`, `io/hocr.py`; `page2teitok.pl`; `hocr2teitok.pl`                                             |
| Project layout       | a TEITOK project indexes `xmlfiles/<docid>.xml` (doc id = filename minus `.xml`)                                                                                                                                                             | flexicorp `_scan_xmlfiles`; flexiconv `--teitok-project`                                                             |
| Relative coordinates | **not adopted** — ufal/flexiconv#1 (ATRIUM alignment, incl. 0–1 bboxes) open, no reply since 2026-06-15                                                                                                                                      | —                                                                                                                    |

Upstream quirk worth reporting (user action): flexicorp's text fallbacks are written as `r"\\btagg"`, `r"\\bner\\b"`,
… — in a raw string that matches a literal backslash, so only the plain patterns (`tokeniz`, `lemmat`, `dependency`,
`named entit`, `convert`) ever fire ▶. Our header should therefore rely on `change@type`.

## 3. Findings

### Writer — `api_util/teitok_alto.py::write_teitok_merged` (CLI and `/enrich` share it)
| ID   | Sev | Finding                                                                                                                                                                                                                                                                                                                                                       |
|------|-----|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| W1 ▶ | P0  | Every `<tok>` is written on its own line; spacing only via `join="right"`. A flexiconv round-trip of the samples keeps **0 of 7** `SpaceAfter=No` ("č . 1 / 2024"); flexipipe, teitok2conllu and flexicorp read it the same way. ATRIUM's own readers are unaffected (they use `<s @text>` first) → writer-only fix.                                          |
| W2 ▶ | P0  | MWT range lines are skipped: "abych" → `<tok>aby</tok><tok>bych</tok>` — surface text changed, the range line's `SpaceAfter` lost, ALTO character alignment degraded.                                                                                                                                                                                         |
| W3 ▶ | P0  | The coarse NER map is CNEC-only while the default model is OntoNotes (#11): every entity becomes `type="MISC" cnec="PERSON"`. `document_hook.py` maps OntoNotes correctly, so TEITOK and `entities[].type_teitok` disagree; `summarize_nt_udp.py` holds a third map (with archaeo `LOCATION→LOC`) and hub `atrium_vocab.py` a fourth (`CNEC_TO_ENTITY_TYPE`). |
| W4 ▶ | P0  | Every bbox is shifted by the ALTO PrintSpace origin while `<surface lrx/lry>` is the full Page (block `220 160` → `20 10` on `1654×2339`). Upstream uses page origin; tier-1 scaling divides by Page width (so even the "cropped image" rationale is not met); `document_hook.py` writes **unshifted** boxes to `entities[].bbox`; the XSD allows negatives.  |
| W5   | P1  | `lang="cs"` hard-coded; ABBYY `TextBlock@LANG` and the model language are ignored.                                                                                                                                                                                                                                                                            |
| W6   | P1  | `<div type="MarginTextZone-P">` for every block with no ALTO source (the XSD accepts any string; the literal lives in fixtures, samples, READMEs; flagged in llm-enrich #13 / hub #13).                                                                                                                                                                       |
| W7   | P1  | Ids `CTX.s1.w3`, no `ord` — flexipipe cannot re-wrap names. Ids are a cross-repo contract (`entities[].teitok_ref`, `lines[].teitok_ref`, `pages[].teitok_surface`).                                                                                                                                                                                          |
| W8   | P2  | Header lacks `orgfile`, a NameTag `<change>` and phase attributes; `<figure id>` uses `hash() % 10000`.                                                                                                                                                                                                                                                       |
| W9 ▶ | P1  | Committed `data_samples/TEITOK/*` are stale (`xmlns=` + `xml:lang`, unshifted) — not today's writer output.                                                                                                                                                                                                                                                   |
| W10  | P1  | `schemas/teitok/teitok.xsd` is derived from the writer (circular); flexiconv output only gets `--wellformed-only`.                                                                                                                                                                                                                                            |

### Tools, adapters, readers
| ID | Sev | Finding |
|---|---|---|
| T1 ▶ | P0 | `fix_teitok_bboxes.py` crashes on every file (tuple returns of `fix_name_close_tags` / `detect_source_size` unpacked wrongly); its only test lives outside `testpaths`. |
| T2 ▶ | P0 | `flexiconv_convert.py` calls `flexiconv.convert()`, which does not exist (API: `flexiconv.api.run_convert` → `ConvertResult`) → always the CLI; no `--no-auto-install` (flexiconv `pip install`s extras mid-run); same-stem inputs collide; re-runs fail on "refusing to overwrite". |
| T3 ▶ | P0 | flexiconv output has **no `<s>`** in any format (plain formats: `<p>` text; PAGE/hOCR/ALTO: `<tok bbox>` in `<div>`/`<lb/>`) → `read_teitok_rows()` returns `[]` → keywords/LLM read nothing (PAGE example: 532 tokens, 0 rows). |
| T4 | P1 | `FLEXICONV_FORMATS` lacks `xml`/`hocr`; the pin covers the core only (docx/odt/md/pdf/rtf extras come from runtime installs); no flexiconv licence/paradata entry (it declares GPL-3.0-or-later; flexipipe, xmltokenizer: MIT). |
| T5 | P1 | The two `teitok_read.py` copies diverged both ways (llm: `</n>` repair, roman `pb`; nlp: `@upos` fix); llm-enrich keeps a stale, test-only fork of `teitok_alto.py`; no drift check covers these copies. |
| T6 | P2 | Tier-1 image fixture never committed; `tests/test_teitok_integraion.py` (sic) checks a 1×1 PNG exists. |
| T7 | P1 | `api_flexiconv.sh` is manual (not a `run_pipeline.py` stage, not in the service) and writes into `$TEITOK_OUTPUT_DIR`, which `api_4_stats.sh` validates with the full writer XSD → a converted document halts the next `stats` run. |
| T8 | P2 | `api_4_stats.sh` resume skips existing `.teitok.xml` → after any format change, directories would mix old and new files. |

### Docs & configs
| ID | Finding                                                                                                                                                                                                                                                             |
|----|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| D1 | nlp `README.md`: `xmlns=`/`xml:lang` example, `</n>` close, "`<n>` elements", "ready for the flexiconv converter", "raw ALTO pixel values", `INPUT_ALTO_DIR="$OUTPUT_DIR/altos"`, a fictional flexiconv CLI recipe, UDPipe/NameTag said to run on flexiconv output. |
| D2 | `config_api.txt` Image-Options comment, `FLEXICONV_FORMATS`; `para_config.txt` NameTag comment still "Czech CNEC 2.0".                                                                                                                                              |
| D3 | `schemas/teitok/README.md` needs an upstream-conformance section; `service/README.md` `/rescale` wording.                                                                                                                                                           |
| D4 | Hub: `e2e-pipeline-smoke.yml` runs nlp with `SAVE_TEITOK=false`; `external-tools.md` has TEITOK/flexiconv "pending"; `pipelines.md` W11 unwritten; `fixtures/atrium_document.example.json` + `document_schema.md` carry the old id forms.                           |
| D5 | llm-enrich `README.md`/`CONTRIBUTING.md`/`para_config.txt`: flexiconv licence "not yet checked", "verbatim copies" claim.                                                                                                                                           |

## 4. Decisions (user, 2026-09-23)

1. **Bbox origin: page origin by default** (upstream). `BBOX_ORIGIN=page|printspace`; under `printspace`,
   `<surface lrx/lry>` = PrintSpace size and tier-1 scales against PrintSpace. Coordinates never negative.
2. **flexiconv output: reader fallback now** (`<lb/>` lines for layout formats, block text otherwise);
   text-faithful annotation via xmltokenizer + UDPipe/NameTag later, opt-in, as a new issue.
3. **Ids: TEITOK-native** — `tok` `w-N` (document-global), `dtok` `w-N.K`, `s` `s-N`, `name` `n-N` (+`sameAs`),
   `surface` `facs-N`, `pb` `pb-N`, `lb` `lb-P.L`, `div` `b-P.K`, `figure` `fig-P.K`, plus `ord`. `teitok_ref` /
   `teitok_surface` carry these local ids (`n-5`, `s-3`, `facs-1`); the `atrium_document` schema types them as plain
   strings, so the schema itself does not change — producers, tests, the hub fixture and docs do. Minor version bump
   with a migration note; readers stay id-agnostic, so old files remain readable.
4. **Stage 1** = refresh of these dev logs (+ status notes in llm-enrich #10/#13 and hub #13).

## 5. Stages

Stages 2–5 each land as one coherent change set: writer, XSD, fixtures, regenerated samples, readers and docs move
together. Every new attribute needs the XSD in the same commit (its attribute sets are closed).

**Stage 1 — dev logs** (this batch): `digests/`+`plans/` for #9, #10, #28; `DEVLOG.md`; this file;
`atrium-llm-enrich/agent_dev_logs/{digests,plans}/{10,13}.*`; `atrium-project/agent_dev_logs/{digests,plans}/13.*`.

**Stage 2 — P0 fixes, no structural change**
- `fix_teitok_bboxes.py` + `tests/test_fix_teitok_bboxes.py`; move `api_util/test_cli_orchestration.py` → `tests/`.
- `api_util/flexiconv_convert.py` (`run_convert` + `ConvertResult`, CLI `--no-auto-install`, collisions, `FLEXICONV_FORCE`),
  `requirements_flexiconv.txt` extras, `TEITOK_FLEXICONV_DIR` in `config_api.txt`/`api_flexiconv.sh`.
- `api_util/teitok_read.py` canonical copy (fallback modes, tail/`join` spacing, `dtok`, `</n>` repair, roman `pb`,
  `@upos`) + real-output flexiconv fixtures.
- `api_util/ner_types.py::coarse_type()` — one CNEC ∪ OntoNotes ∪ archaeo → PER/ORG/LOC/MISC map used by
  `teitok_alto.py`, `document_hook.py`, `summarize_nt_udp.py`; `@cnec` for CNEC codes, new `@onto` for OntoNotes
  (XSD: `cnec` optional, `onto` added); hub `docs/templates/shared/atrium_vocab.py` updated and re-vendored.

**Stage 3 — writer conformance (the contract change set)**
- `teitok_alto.py`: text-faithful spacing (tails; no whitespace across `</name>`/`<lb/>` at a `SpaceAfter=No`;
  `join="right"` kept); MWT `<tok><dtok/></tok>`; ids per decision 3 assigned **once** in `parse_and_align_conllu()`
  and consumed by writer and hook; `ord`; `sameAs`; bbox origin per decision 1 (hook uses the same boxes);
  `lang` from `TextBlock@LANG` → model → omit, plus `langUsage`; `<div type="TextBlock">` (+`@subtype` from ALTO
  `TAGREFS` when present); header `orgfile`, `change@type` (`converted`, `tagged`+`parsed`, `ner`), writer version
  stamp in `appInfo`; deterministic `fig-P.K`.
- `schemas/teitok/teitok.xsd` + `README.md`, `tests/fixtures/teitok/*`, regenerated `data_samples/TEITOK/*`,
  `api_util/document_hook.py`, tests (`test_document_hook`, `test_api_service`, `test_rescale`, `test_teitok_preservation`,
  `test_validate_teitok`), `REGENERATE_TEITOK` knob in `api_4_stats.sh`.
- New `tests/test_teitok_conformance.py` (stdlib TEITOK-reading round-trip + `flexiconv.load_teitok` at `v0.3.10`)
  and `validate_teitok_xml.py --profile core`; both in `.github/workflows/teitok-schema.yml`.

**Stage 4 — flexiconv path (#10)**: `FLEXICONV_FORMATS += xml hocr`; per-file paradata; `--profile core` gate on
`TEITOK_FLEXICONV_DIR`; `para_config.txt` licence line (nlp + llm); optional `run_pipeline.py --with-flexiconv`;
the real-document experiment table in the README.

**Stage 5 — cross-repo**
- llm-enrich: re-vendor `api_util/{teitok_read,bbox_scale,flexiconv_convert}.py` + tests; delete the stale
  `api_util/teitok_alto.py` fork (its tests stay in nlp); `xml_to_md.py` spacing via `teitok_read`; a SHA-256 drift
  test for the vendored copies; README / CONTRIBUTING / para_config.
- hub: `e2e-pipeline-smoke.yml` `SAVE_TEITOK=true` + validator step + `tools/e2e/e2e_assert.py` TEITOK checks;
  `fixtures/atrium_document.example.json`, `docs/document_schema.md` (ids); `docs_site/external-tools.md` entries for
  TEITOK, flexiconv, flexipipe, xmltokenizer, flexicorp, teitok-tools; `docs_site/pipelines.md` W11.
- alto-postprocess: no code change (pass-through of `teitok_surface`/`teitok_ref`); re-vendor shared files only.

**Stage 6 — later, new issue**: xmltokenizer (`profile="teitok"`) + UDPipe/NameTag annotation of flexiconv TEITOK,
`FLEXICONV_ANNOTATE=true`.

**Docs & configs, all stages** — nlp: `README.md` (TEITOK section: real example, ids, spacing, MWT, bbox origin, how to
import into a TEITOK project as `xmlfiles/<id>.xml`; flexiconv section rewrite), `service/README.md`, `config_api.txt`,
`para_config.txt`, `CONTRIBUTING.md`, `schemas/teitok/README.md`, `.github/workflows/teitok-schema.yml`;
llm-enrich: `README.md`, `CONTRIBUTING.md`, `para_config.txt`; hub: Stage 5.

## 6. Verification (offline)

1. Stage 1 — `pytest tests/test_docs.py`; no foreign plan left in `plans/10.plan.md`.
2. Stage 2 — `pytest tests/test_fix_teitok_bboxes.py tests/test_flexiconv_convert.py tests/test_teitok_read.py
   tests/test_document_hook.py -q`; the fixer halves a copy of `data_samples/TEITOK`; `sample.txt` + `sample.md`
   convert to two files with ≥1 row each; nothing is pip-installed during conversion.
3. Stage 3 — `pytest -m "not slow"`; `validate_teitok_xml.py data_samples/TEITOK` and `--profile core`; flexiconv
   round-trip keeps 7/7 `SpaceAfter=No`; "abych" survives as one surface token; an OntoNotes `PERSON` becomes
   `type="PER" onto="PERSON"`; default-origin block bbox `220 160 1420 280` on `1654×2339`, `printspace` →
   `20 10 1220 130` on `1254×2039`; `entities[].bbox` = union of the entity's TEITOK token boxes.
4. Stage 4 — `api_flexiconv.sh` then `api_4_stats.sh` both pass; `keywords.py -i "$TEITOK_FLEXICONV_DIR" -m yake`
   produces keywords.
5. Stage 5 — llm-enrich `pytest -m "not slow"`; hub `pytest tests/`; E2E left to CI unless run locally.
6. `ruff check` / `pre-commit run --all-files` in every touched repo.
