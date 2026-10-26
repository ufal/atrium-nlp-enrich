# Using nlp-enrich

For users and integrators who want to run it: how to set it up, call the service, run the pipeline from the
command line, read its exit codes, put the result into a TEITOK project, convert other input formats, and fix boxes
that do not line up. What each stage does: [how it works](how-it-works.md).

On this page:

- [Setup](#setup) and [the service](#the-service)
- [The command line, stage by stage](#the-command-line-stage-by-stage)
- [One-command pipeline run](#one-command-pipeline-run-run_pipelinepy): [what the runner does](#what-the-runner-does),
  [resume](#resume--checkpoint-recovery), [exit codes](#exit-codes)
- [Docker](#docker)
- [Importing into a TEITOK project](#importing-into-a-teitok-project)
- [Other input formats: flexiconv](#other-input-formats-flexiconv)
- [Troubleshooting](#troubleshooting): [fixing bounding box alignments](#fixing-bounding-box-alignments),
  [files from an older format](#files-from-an-older-format), [when a run stops](#when-a-run-stops)

## Setup

Python 3.11, the version the images and CI use.

1. Create and activate a new virtual environment in the project directory.
2. Install the required Python packages:

   ```bash
   pip install -r requirements.txt
   ```

   To run the REST API service, install its requirements too:

   ```bash
   pip install -r service/requirements.txt
   ```

3. Review and update [config_api.txt](../config_api.txt) with your paths and API settings
   ([configuration](configuration.md)).

Every run sends the text to LINDAT's UDPipe 2 and NameTag 3 services over HTTPS, or to the instances `UDPIPE_URL`
and `NAMETAG_URL` name ([backing service endpoints](configuration.md#backing-service-endpoints)). Without them a run
stops with exit code 6 or 7 ([Exit codes](#exit-codes)).

## The service

[service/README.md](../service/README.md) is the reference: the endpoints, the layout inputs, the response, the
limits, the errors and the OpenAPI contract. In short:

```bash
python -m service.api                  # PORT / HOST; default 0.0.0.0:8000
curl -s -X POST localhost:8000/enrich -F "file=@data_samples/DOC_LINE_CATEG/CTX000000001.csv" \
     -F "alto=@data_samples/ALTO/CTX000000001.alto.xml"           # the JSON envelope, TEITOK with boxes
curl -s -X POST localhost:8000/rescale -F "file=@data_samples/TEITOK/CTX000000001.teitok.xml" \
     -F width=827 -F height=1170                                  # no LINDAT needed
```

`/enrich` takes a table, a `.txt` or a converted TEITOK file, optionally with the ALTO of a table's pages or an
ATRIUM record; `/jobs` runs the same as a background job; `/rescale` and `/project_record` transform a finished
TEITOK file without running the pipeline.

## The command line, stage by stage

The process is divided into sequential steps, each responsible for one part of the enrichment. Step 1 happens in
[atrium-ocr-postprocess](https://github.com/ufal/atrium-ocr-postprocess); step 2 is this repository's four stage
scripts. [run_pipeline.py](#one-command-pipeline-run-run_pipelinepy) runs them all with one command.

### Step 1: prepare tables with the text of page-specific ALTOs

If you already have a directory of CSV (XLSX) tables with a `text` column holding the text extracted from ALTO XML
files, skip step 1 and go to step 2.

The input tables are the result of the ALTO XML postprocessing pipeline of
[atrium-ocr-postprocess](https://github.com/ufal/atrium-ocr-postprocess) (text and bounding boxes ordered by
LayoutReader, recorded as a `text` column): its `DOC_LINE_CATEG/` directory, which `INPUT_TABLES_DIR` points at by
default. Each CSV (XLSX) file corresponds to a document and has a row for each line, with page and line number
columns for the proper ordering (`page_num` and `line_num`):

```
DOC_LINE_CATEG/
├── document1.csv
├── document2.csv
└── ...
```

with each file structured like the synthetic sample
[data_samples/DOC_LINE_CATEG/CTX000000001.csv](../data_samples/DOC_LINE_CATEG/CTX000000001.csv) (columns abridged
here):

```
file,page_num,line_num,text,split_ws,split_we,lang,lang_score,perplex,…,categ,…
CTX000000001,1,1,Výzkumná zpráva č. 1/2024 — Hradiště u Horní Mezí,,,ces,1.0,58.0,…,Clear,…
CTX000000001,1,2,Terénní výzkum provedl Jan Novotný v červnu 2024.,,,ces,1.0,42.5,…,Clear,…
CTX000000001,2,1,Nalezená keramika pochází z raného středověku.,,,ces,1.0,51.0,…,Clear,…
...
```

where `split_ws` and `split_we` are the start and end character offsets of the words split in the original ALTO
XML. The `lang` and `lang_score` columns give the detected language and its confidence score, while `perplex`,
`categ` and the other quality columns add metadata about the text classification. Only `text` is required; a
`page_label` column, when present, becomes `<pb n>` in TEITOK. `page` and `line` are read as `page_num` and
`line_num`, and a byte-order mark at the start of a CSV is fine.

Every row with text is enriched, whatever its `categ`. With `SKIP_UNTRUSTWORTHY_LINES=true` in
[config_api.txt](../config_api.txt), or `run_pipeline.py --skip-untrustworthy-lines`, the rows whose `categ` is
`Trash` (or digital-convert's `Garbage` and `Inverted`) are left out; the service's `skip_untrustworthy_lines` does
the same. A record sent as the text is filtered always.

### Step 2: extract named entities and CoNLL-U

This step performs the NLP analysis with the external LINDAT/CLARIAH-CZ APIs, producing Universal Dependencies
(CoNLL-U) and named-entity recognition (NER) data. It is split into modular shell scripts to handle large-scale
processing, text chunking and API rate limiting. Run them in sequence; each sources
[config_api.txt](../config_api.txt) for its configuration.

#### 1. Generate manifest

```bash
./api_1_manifest.sh
```

* **Input:** the tables and plain-text files in `INPUT_TABLES_DIR` (`*.csv`, `*.xlsx`, `*.txt`; in a text file a
  form feed starts a page), read by [api_util/line_inputs.py](../api_util/line_inputs.py) as the service reads an
  upload. Any other file there is named on stderr and in the paradata as skipped; a TEITOK file is read from
  `TEITOK_FLEXICONV_DIR` with `FLEXICONV_ANNOTATE=true` ([below](#annotating-converted-documents-flexiconv_annotate)).
* **Output:** `<OUTPUT_DIR>/manifest.tsv`, and per document `TEMP_TXT_DIR/<doc_id>.txt` (one line per table row)
  with `TEMP_TXT_DIR/<doc_id>.rows.tsv` next to it: the page, line, page label and text of every line.

The example output file [manifest.tsv](../data_samples/manifest.tsv) has **file**, **page** (the page count) and
**path** columns. It lists all text files to be processed in the next steps. To see how many documents will be
processed (the rows of the manifest, without its header line):

```bash
tail -n +2 <OUTPUT_DIR>/manifest.tsv | wc -l
```

#### 2. UDPipe processing (morphology and syntax)

```bash
./api_2_udp.sh
```

* **Input:** `<OUTPUT_DIR>/manifest.tsv` and the text files it lists (`TEMP_TXT_DIR/<doc_id>.txt`).
* **Output:** `<OUTPUT_DIR>/UDP/*.conllu` (intermediate per-document CoNLL-U files), each with its
  `<doc_id>.rows.tsv` copied next to it.

To see how many documents have been processed into CoNLL-U files (each file corresponds to a document):

```bash
ls -l <OUTPUT_DIR>/UDP/*.conllu | wc -l
```

The example output directory [UDP](../data_samples/UDP) contains per-document CoNLL-U files.

You can launch the next step when a portion of the CoNLL-U files is ready, without waiting for the entire input
collection to finish. Relaunch it after all CoNLL-U files are ready, to process the files created after the
previous run began.

#### 3. NameTag processing (NER tags)

```bash
./api_3_nt.sh
```

* **Input:** `<OUTPUT_DIR>/UDP/*.conllu` and their `.rows.tsv`.
* **Output:** `<OUTPUT_DIR>/NE/*/*.tsv`, NE-annotated per-page files: `<doc_id>-P.tsv` holds the tokens of page P;
  a sentence that runs over a page is split between two files, in order.

To see how many documents have been processed into TSV files (each subdirectory corresponds to a document):

```bash
ls -l <OUTPUT_DIR>/NE | wc -l
```

The example output directory [NE](../data_samples/NE) contains per-page TSV files with NE annotations. The tags are
the labels of the configured NameTag model (`MODEL_NAMETAG`): OntoNotes 5 for the default multilingual model,
[CNEC 2.0](https://ufal.mff.cuni.cz/~strakova/cnec2.0/ne-type-hierarchy.pdf) for the Czech one.

#### 4. Generate statistics

```bash
./api_4_stats.sh
```

What it reads and writes: [stage 4 inputs and outputs](reference/outputs.md#stage-4-inputs-and-outputs); its flags:
[Stage 4 output flags](configuration.md#stage-4-output-flags). To check the result:

```bash
ls <OUTPUT_DIR>/UDP_NE | wc -l            # documents with a .csv and a .conllu
ls <OUTPUT_DIR>/UDP_NE/*/*.csv | wc -l    # documents processed into tables
ls <OUTPUT_DIR>/TEITOK/*.xml | wc -l      # .teitok.xml documents written
```

The example output directories [UDP_NE](../data_samples/UDP_NE) and [TEITOK](../data_samples/TEITOK) hold the
results for the three sample documents; the whole tree is in [output structure](reference/outputs.md#output-structure).

## One-command pipeline run (`run_pipeline.py`)

While each stage can be launched by hand, [run_pipeline.py](../run_pipeline.py) chains them end to end and merges
every per-stage paradata JSON produced during the run into a single `pipeline-run-merged` record.

The stage scripts run `python3` from `PATH`. Started from a virtual environment (`venv/bin/python run_pipeline.py`,
no activation needed), the runner puts that environment's `bin` first for them. Before the first stage it checks
that this `python3` can import what the stages need (`requests` for UDPipe and NameTag, `lxml` for the TEITOK gate).
If it cannot, the runner stops with exit code `3`, names the interpreter and the missing package, and gives the
`pip install` that fixes it (atrium-nlp-enrich#42).

```bash
# Full core run: api_1 → api_2 → api_3 → api_4
python3 run_pipeline.py

# Run only a subset of the core stages (canonical order is always enforced)
python3 run_pipeline.py --stages udp nt

# Resume after an interruption: start from a chosen stage, skip every earlier one
python3 run_pipeline.py --start-from nt

# Skip individual stages (re-run only NER + stats, leave manifest/UDPipe as-is)
python3 run_pipeline.py --skip-manifest --skip-udp

# Clear stale .state_* checkpoint sidecars from PARADATA_DIR before running
python3 run_pipeline.py --clean-state

# Force execution: bypass missing dependency checks and ignore individual stage failures
python3 run_pipeline.py --force

# Validate configuration and resolve the plan without running anything
python3 run_pipeline.py --dry-run

# Print the resolved config + stage plan as JSON (for wrappers / healthchecks)
python3 run_pipeline.py --print-config json

# Add this run's entities to an ATRIUM document record
python3 run_pipeline.py --document-json CTX.document.json --document-json-out CTX.document.json

# Enrich the record's own lines (a born-digital record from digital-convert): written as <doc_id>.csv into
# INPUT_TABLES_DIR first, and left there; an existing file of that name is never replaced
python3 run_pipeline.py --document-json C-1.document.json --document-json-out C-1.document.json --text-from-record

# Leave out the rows ocr-postprocess categorised Trash (and Garbage, Inverted)
python3 run_pipeline.py --skip-untrustworthy-lines
```

The runner reads the **same** [config_api.txt](../config_api.txt) that the shell stages source, so Python and Bash
always agree on `OUTPUT_DIR`, `PARADATA_DIR`, and the input/output paths. `python3 run_pipeline.py --help` lists
every option. The runner never re-implements stage logic: it shells out to the exact same
[api_1_manifest.sh](../api_1_manifest.sh) … [api_4_stats.sh](../api_4_stats.sh) and [config_api.txt](../config_api.txt)
you can run by hand, so anything documented for those stages (resume behaviour, output flags, …) applies unchanged
under the runner.

### What the runner does

1. **Resolves config** from [config_api.txt](../config_api.txt) (with `$VAR` / `${VAR}` expansion).
2. **Runs each stage in order**, spacing stage starts by ≥ 1.1 s so the 1-second-resolution paradata filenames
   (`YYMMDD-HHmmss_nlp-enrich.json`) never collide.
3. **Collects** the paradata JSON each stage writes, scoped to **this run only** (paradata files that already
   existed before the run are never merged).
4. **Merges** all per-stage records into one `<PARADATA_DIR>/<runid>_nlp-enrich_pipeline-run.json` via
   `atrium_paradata.merge_run_paradata`. The merged record tracks document-level statistics across the sequential
   pipeline (recording true throughput without inflating input counts). Its computed licence label is re-derived
   from the **union** of every component used across the stages, so the most-restrictive rule holds end to end (a
   core run's label is CC BY-NC-SA 4.0, from the NameTag 3 and UDPipe 2 models; converting with flexiconv adds its
   GPL-3.0-or-later). The label describes the components, not the rights in the output:
   [licences](reference/licences.md).

### Resume / checkpoint recovery

Long batches on constrained hardware are expensive to restart from scratch, so the runner lets you re-enter the
pipeline at any stage instead of redoing completed work. Recovery operates at two complementary levels.

**Document-level (automatic).** Every stage already skips inputs whose output exists (stages 2–4 via
`[ -f "$out" ] && continue`), so simply re-running the same command picks up where the previous run stopped.

**Pipeline-level starting points.** To skip whole stages, not just completed documents, the runner accepts explicit
entry points over the full stage order:

| Flag                   | Effect                                                                   |
|------------------------|--------------------------------------------------------------------------|
| `--start-from <stage>` | Run from `<stage>` onward; every earlier stage is skipped.               |
| `--skip-<stage>`       | Skip one named stage, run the rest.                                      |
| `--clean-state`        | Sweep stale `.state_*.json` sidecars from `PARADATA_DIR` before running. |

`<stage>` is one of `manifest`, `udp`, `nt`, `stats`, `project` (the canonical order; `project` needs
`--teitok-enrichment` to be part of the run). Each skip flag also has an equivalent `SKIP_<STAGE>=true` key that can
live in [config_api.txt](../config_api.txt) (e.g. `SKIP_MANIFEST=true`), so a habitual resume profile can be
persisted without retyping flags.

```bash
# UDPipe + NameTag already finished: resume at statistics
python3 run_pipeline.py --start-from stats

# Re-run only NER and statistics; keep the existing manifest and CoNLL-U
python3 run_pipeline.py --skip-manifest --skip-udp
```

Skipped stages are recorded under `skipped_stages` in the merged `<runid>_nlp-enrich_pipeline-run.json` record, so a
resumed run remains fully auditable. An all-skipped run is treated as a **successful resume**, not an empty failure
(see [Exit codes](#exit-codes) below).

### Exit codes

The exit code is the runner's contract; the service maps it to an HTTP status
([service/README.md, How it works](../service/README.md#how-it-works)).

| Code | Meaning                                                                                                                                                                     |
|------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `0`  | All requested stages completed; nothing flagged.                                                                                                                            |
| `1`  | A stage processed **nothing** despite having input and no resume, and `FAIL_ON_EMPTY=true` (the default). Also: `--with-flexiconv` could not convert at least one document. |
| `2`  | A required stage script was not found.                                                                                                                                      |
| `3`  | A dependency preflight failed: `--with-flexiconv` without flexiconv, or the stages' `python3` cannot import `requests` or `lxml` (the message names it and the fix).        |
| `5`  | The TEITOK output failed its output contract (`api_4_stats.sh`'s gate: the XSD, unique ids, resolvable references, the page rules). A writer defect: please report it.      |
| `6`  | LINDAT UDPipe or NameTag did not answer after `MAX_RETRIES` retries (HTTP 5xx or 429, a refused or dropped connection); the first line on stderr names the service (#41).   |
| `7`  | Every attempt at a LINDAT call timed out (`TIMEOUT` seconds each).                                                                                                          |
| `8`  | LINDAT refused the request (HTTP 4xx, e.g. an unknown model): a configuration or request defect, not the input.                                                             |
| `≠0` | A stage script itself exited non-zero (its code is propagated).                                                                                                             |

**Using `--force` (`-f`)** overrides exit codes `1`, `3`, and `≠0`. It bypasses preflight dependency crashes and
forces `FAIL_ON_EMPTY=False`, so the pipeline keeps attempting the following stages even if one stage crashes or
processes zero files.

The empty-run guard is governed by `FAIL_ON_EMPTY` in [config_api.txt](../config_api.txt). A **resumed** run, where
every document was already complete and thus *skipped*, or where a stage was skipped outright via `--start-from` /
`--skip-<stage>` (see [Resume / checkpoint recovery](#resume--checkpoint-recovery)), is treated as success, not an
empty failure. Set `FAIL_ON_EMPTY=false` to permit genuinely empty stages.

## The command line and the service

Stage 1 and the service read every input through [api_util/line_inputs.py](../api_util/line_inputs.py), and the
service runs the same four stages on what it read (its upload becomes a table in a workspace of its own), so the same
input gives the same rows, CoNLL-U, entities, TEITOK and record (atrium-project#72;
[tests/test_cli_service_parity.py](../tests/test_cli_service_parity.py)). Where they differ:

| What                        | Command line                                                   | Service                                                  | Why they differ                                            |
|-----------------------------|----------------------------------------------------------------|----------------------------------------------------------|------------------------------------------------------------|
| How much per run            | every document in `INPUT_TABLES_DIR`                           | one document per request                                 | the service is stateless                                   |
| Table, `.txt`               | files in `INPUT_TABLES_DIR`                                    | the `file` part                                          |                                                            |
| Lines as JSON               | none; write them to a `.txt`                                   | `POST /enrich_text`                                      | an HTTP convenience                                        |
| TEITOK (flexiconv's)        | files in `TEITOK_FLEXICONV_DIR` with `FLEXICONV_ANNOTATE=true` | the `file` part                                          | on the command line, flexiconv writes them there           |
| PDF, office files, PAGE XML | converted by flexiconv (`--with-flexiconv`)                    | not read; send flexiconv's TEITOK                        | flexiconv is GPL-3.0-or-later and stays out of the service |
| ALTO layout                 | `INPUT_ALTO_DIR`                                               | the `alto` part                                          |                                                            |
| Page images                 | `INPUT_PAGES_DIR`, scaled into the TEITOK file                 | not taken; `POST /rescale` scales a finished TEITOK file | the images are large; the service keeps uploads small      |
| The record                  | `--document-json`, `--document-json-out`                       | `document_json`                                          |                                                            |
| The record as the text      | `--text-from-record`                                           | `document_json` without `file`                           |                                                            |
| Untrustworthy rows          | `SKIP_UNTRUSTWORTHY_LINES` / `--skip-untrustworthy-lines`      | `skip_untrustworthy_lines`                               | both off by default                                        |
| Language                    | `--lang`                                                       | `lang`, `cs` only                                        | the service's models are pinned per deployment             |
| Outputs                     | files under `OUTPUT_DIR`                                       | the JSON envelope, or `format=zip` of the same files     |                                                            |
| Paradata                    | a file per stage and a merged one in `PARADATA_DIR`            | the envelope's `paradata`, a `CreateAction`              | atrium-project#71                                          |

## Docker

The published images are `ghcr.io/ufal/atrium-nlp-enrich:<version>` (the batch runner, `run_pipeline.py`) and
`ghcr.io/ufal/atrium-nlp-enrich-api:<version>` (the service). `<version>` is the release **without** its leading
`v`: `1.2.0-beta` for the release `v1.2.0-beta`. The target is part of the image name, not the tag.
`atrium-nlp-enrich-llm` was published up to 0.23.0 only; it is not built any more (the keyword and LLM code left,
see [the repository split](decisions/2026-10-01-repository-split.md)).

```bash
docker run --rm -p 8000:8000 ghcr.io/ufal/atrium-nlp-enrich-api:<version>   # the service
docker compose --profile api up -d                                          # the service, from a checkout
```

To tie a container run to its image and commit, set `ATRIUM_RUNNER_IMAGE`, `ATRIUM_RUNNER_REPO` and
`ATRIUM_RUNNER_REF` ([provenance for containers](reference/paradata.md#provenance-for-containers)).

**Docker on Linux: run as yourself.** `./data` is part of the clone and belongs to you, while the images run as uid
10001 by default. `docker-compose.yaml` runs every service as `user: "${ATRIUM_UID:-10001}:0"`, so put your uid in
`.env` once (`echo "ATRIUM_UID=$(id -u)" >> .env`) and the container writes `./data` as you. With `docker run`,
pass `--user "$(id -u):0"`. Docker Desktop (macOS, Windows) needs neither. (atrium-project#69)

## Importing into a TEITOK project

The files follow TEITOK's conventions, but a TEITOK project has a few of its own (`xmlfiles/`, `Originals/`,
`settings.xml`), and the upstream readers differ in what they keep:

- **File name.** A project keeps each document as `xmlfiles/<name>.xml`: copy `TEITOK/<doc_id>.teitok.xml` to
  `xmlfiles/<doc_id>.xml` (the `.teitok.xml` suffix is this pipeline's, not TEITOK's).
- **Original.** `note[@n="orgfile"]` names the file the document came from (the ALTO file, the input table, or the
  original a converted document was made from), without a directory. Put that file in the project's `Originals/`.
- **Attributes.** Tokens carry `lemma`, `upos`, `xpos`, `feats`, `head`, `deprel` and `ord`. teitok-tools' default
  tag attribute is `pos`: declare `xpos` (and the others you want to query or show) in the project's `settings.xml`.
- **Page images.** `pb@facs` and `<graphic url>` name the images (`<doc_id>-N.png` for ALTO documents, the converted
  file's own names otherwise); place them where the project's facsimile settings look.

What the TEITOK readers keep (flexiconv v0.3.10, the pinned version, is tested in
`tests/test_teitok_conformance.py` and `tests/test_teitok_pages.py`; flexipipe `73188c5` was checked by hand on the
committed samples, 2026-09-24):

| Reader                                  | Spacing (`SpaceAfter`) | Sentences, `<pb/>` inside `<s>` | Multi-word tokens (`<dtok>`)               | Dependency heads                                                                    |
|-----------------------------------------|------------------------|---------------------------------|--------------------------------------------|-------------------------------------------------------------------------------------|
| flexiconv `load_teitok`                 | kept                   | kept                            | **lost**: the surface token only, no words | kept as the raw `@head` id                                                          |
| flexipipe `load_teitok` (Python loader) | kept                   | kept                            | kept                                       | **wrong**: `head="w-N"` becomes token N of the *document*, wrong from sentence 2 on |
| this repo's `teitok_read.py`            | kept                   | kept, one row per page part     | kept, the surface form                     | not read                                                                            |

The two defects are upstream, recorded in issue #38 for an upstream report; `@ord` gives each word's
sentence-local number for a reader that needs it.

## Other input formats: flexiconv

This section matters when your documents come from an OCR or digitisation pipeline that does **not** produce ALTO
XML (PAGE XML, hOCR, plain-text exports, or office and PDF documents) and ocr-postprocess's line table is not
enough. If you have ALTO XML, the pipeline generates TEITOK XML natively in stage 4.

### What flexiconv is

[flexiconv](https://github.com/ufal/flexiconv) is a format converter by the TEITOK author (ÚFAL) that translates
OCR, layout and document formats into **TEITOK XML**. Its output can be loaded straight into a TEITOK project, and
the TEITOK readers of this repository (e.g. [api_util/teitok_read.py](../api_util/teitok_read.py), which
atrium-keyword-extract vendors) accept it.

In this pipeline flexiconv only **converts** inputs that are not line tables or ALTO; it is not what writes the
annotated TEITOK. Every annotated file, a converted document's included, is written by this repository's own writer
([api_util/teitok_alto.py](../api_util/teitok_alto.py), format 2). flexiconv runs from the command line only, and is
optional.

```
  Your input format           flexiconv                     Output
  ─────────────────    ──────────────────────   ──────────────────────────────────
  PAGE XML, hOCR    ─┐                           .teitok.xml   ──► TEITOK platform
  txt, md, html     ─┤──► api_flexiconv.sh ────► (flexiconv    ──► the TEITOK readers
  docx, odt, pdf    ─┘                            profile)
```

By default flexiconv output is used as it is, without UDPipe/NameTag
([annotating it](#annotating-converted-documents-flexiconv_annotate) is opt-in). It contains what the source
contains:

| Source                                 | flexiconv TEITOK                                                        | Rows seen by `teitok_read.py`      |
|----------------------------------------|-------------------------------------------------------------------------|------------------------------------|
| PAGE XML, hOCR, ALTO (`.xml`, `.hocr`) | `<tok bbox>` words with `<lb/>` lines and `<facsimile>` zones, no `<s>` | one row per line                   |
| txt, md, html, docx, odt, rtf, pdf, …  | `<p>`, `<head>`, `<item>` text, not tokenized                           | one row per paragraph/heading/item |

So the downstream readers (keyword extraction in atrium-keyword-extract, LLM enrichment in atrium-digital-convert)
can work on it; a lemma-based method cannot, because there are no lemmas.

A PDF converted with flexiconv's default reader (`pdf=smart`) has no word boxes and no page images, so its TEITOK
has no facsimile; flexiconv's `pdf=bbox` reader gives word boxes but needs Poppler's `pdftotext` (not wired into
`api_flexiconv.sh`). See also [Pitfalls](reference/teitok.md#pitfalls) 6–8.

### How to use it in this pipeline

1. **Install** the pinned flexiconv and the format extras:

   ```bash
   pip install -r requirements_flexiconv.txt   # flexiconv v0.3.10 + docx/odt/md/pdf/rtf extras
   ```

   flexiconv is **GPL-3.0-or-later** (declared in its `pyproject.toml`) and optional: nothing else in the pipeline
   imports it, and `para_config.txt` records it as a conditional component.

2. **Put the documents** in `INPUT_DOCS_DIR` (`config_api.txt`, default `$OUTPUT_DIR/DOCS`) and list the extensions
   to convert in `FLEXICONV_FORMATS`. `xml` covers PAGE XML, ALTO and TEI: flexiconv detects them by content.

3. **Convert:**

   ```bash
   bash api_flexiconv.sh
   ```

   Each file becomes `<stem>.teitok.xml` in `TEITOK_FLEXICONV_DIR` (default `$TEITOK_OUTPUT_DIR/flexiconv`). Two
   inputs with the same stem (`report.txt` + `report.md`) become `report.txt.teitok.xml` and
   `report.md.teitok.xml`. Existing outputs are kept unless `FLEXICONV_FORCE=true`. The script calls flexiconv's
   library (`flexiconv.api.run_convert`), or its CLI (`flexiconv --no-auto-install -t teitok IN OUT`) when only the
   CLI is installed. Either way it never `pip install`s missing extras in the middle of a run. Without flexiconv
   installed the stage stops at once with exit code `3`. A file that cannot be converted is reported in one line
   and recorded, with its reason, in the paradata record of the run (`--program nlp-enrich`, component
   `flexiconv`); the stage converts the rest and then exits `1`, so `run_pipeline.py --with-flexiconv` does not end
   green with documents missing. The output directory is then checked with `validate_teitok_xml.py --profile core`,
   the rules any TEITOK document must meet. This is not this writer's XSD, and `api_4_stats.sh` leaves this
   directory out of its own gate.

4. **Use the result** with the readers of the stages that follow (atrium-keyword-extract reads a `.teitok.xml`
   directly), or annotate it here with `FLEXICONV_ANNOTATE`.

For a single file, the CLI directly: `flexiconv -t teitok input.page.xml output.teitok.xml`
(`flexiconv --list-formats` lists every input format).

`run_pipeline.py --with-flexiconv` runs `api_flexiconv.sh` as its first stage (`--start-from` any later stage skips
it). The REST service never runs flexiconv (no GPL code in its image), but it takes flexiconv's output: upload a
converted `.teitok.xml` to `/enrich` and it is annotated with its own layout
([service/README.md, Layout inputs](../service/README.md#layout-inputs)).

Before relying on the flexiconv path for a collection, convert a few real documents of each kind and look at the
result: [checking a real collection](evaluation/flexiconv-collection-check.md) has the procedure and a reference run.

### Annotating converted documents (`FLEXICONV_ANNOTATE`)

With `FLEXICONV_ANNOTATE=true` a converted document goes through the same linguistic stages as a table input. It
comes out as TEITOK format 2 in `TEITOK_OUTPUT_DIR`: sentences, lemmas, UPOS/XPOS/features, dependencies, `<name>`
entities and TEITOK ids. It also keeps what flexiconv found on the page:

```bash
python3 run_pipeline.py --with-flexiconv   # api_flexiconv.sh, then manifest → udp → nt → stats
```

`--with-flexiconv` sets the flag for every stage. To run stage by stage, set `FLEXICONV_ANNOTATE=true` in
`config_api.txt` and run `bash api_flexiconv.sh` before `api_1_manifest.sh`.

| Stage               | With `FLEXICONV_ANNOTATE=true`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
|---------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 1 manifest          | Each `TEITOK_FLEXICONV_DIR/*.teitok.xml` is a document (`report.txt.teitok.xml` is `report.txt`) whose text is the rows `teitok_read` gives (one per line or text block). When a table document uses the file as its layout (next row), the table wins and the converted file is recorded as skipped.                                                                                                                                                                                                                                                                                                                                                                                           |
| 2–3 UDPipe, NameTag | Unchanged.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| 4 stats             | A document without `<doc_id>.alto.xml` takes its layout from its converted file ([api_util/teitok_layout.py](../api_util/teitok_layout.py)): pages from `<pb>` (label `pb@n`, image and size from `pb@facs`/`@bbox` or its `<surface>`), lines from `<lb bbox>`, word boxes from `<tok bbox>`, and text blocks with their element name as `subtype` (`head`, `p`, `item`, …). The file is `<doc_id>.teitok.xml`, else the one file whose `canonical_doc_id` is the document's (`report.v2.teitok.xml` serves `report`); two such files (`report.txt` and `report.md` conversions) are ambiguous: none is used, and a warning says so ([api_util/doc_identity.py](../api_util/doc_identity.py)). |
| document record     | `entities[].bbox`, `teitok_ref` and `pages[].teitok_surface` are filled as for ALTO documents.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |

| Source                             | Layout in the annotated TEITOK                                                                                                                                                                                                                                               |
|------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| PAGE XML, hOCR, ALTO via flexiconv | Word and line boxes, and the page image under its own name (`<graphic url>` = flexiconv's `facs`). The page size is set when the source has one (hOCR). Punctuation that flexiconv did not box gets no bbox. flexiconv's `<zone>`s are not carried over (format 2 has none). |
| txt, md, docx, odt, pdf, …         | `<div type="TextBlock" subtype="p\|head\|item\|…">`, with no boxes and no facsimile.                                                                                                                                                                                         |

Inline markup such as `<hi>` is flattened into its block. The converted file stays in `TEITOK_FLEXICONV_DIR` as the
record of the conversion.

The header names flexiconv (`<change who="flexiconv" type="converted">`) and the original document (`orgfile`). A
page image the converted file names is looked up in `INPUT_PAGES_DIR` under that name. When found, it sets the
surface size; the coordinates are already image pixels and stay as they are.

**In the full ATRIUM pipeline**, ocr-postprocess's `--method text-lines` reads the same documents into
`DOC_LINE_CATEG/`, which is this repo's `INPUT_TABLES_DIR`. With `INPUT_DOCS_DIR` pointing at the originals, the
text comes from ocr-postprocess, where its lines are categorised, and the layout comes from flexiconv.

Upstream, flexiconv can also annotate its own output (`flexiconv --flexipipe`, or xmltokenizer); this pipeline uses
its own UDPipe/NameTag stages instead, so that every document gets the same writer and ids. If your format is not
supported by flexiconv, please open an issue on the [flexiconv GitHub repository](https://github.com/ufal/flexiconv).

## Troubleshooting

### Fixing bounding box alignments

If you have just digitised a batch of archival documents, your first goal may be making sure the annotations line
up with your page images in a web viewer.

Say your original document was processed at a high archival resolution, but the image you serve to your web
frontend is exactly 1200 pixels wide and 1800 pixels high. The TEITOK bounding boxes then do not line up with it.
There are two ways to fix that without re-running the pipeline.

**Method 1: the API (single files or web integrations).** Send the misaligned XML to the service's `/rescale`
endpoint, with the exact dimensions of your target image, and ask for the output as an XML file instead of the
default JSON envelope:

```bash
curl -X POST "http://localhost:8000/rescale" \
     -F "file=@CTX000000001.teitok.xml" \
     -F "width=1200" \
     -F "height=1800" \
     -F "format=xml" \
     -o CTX000000001.rescaled.teitok.xml
```

The service reads each page's coordinate space from its `<surface>` tag and scales the bounding boxes (`bbox`) of
that page to the new 1200×1800 size; boxes are clamped to the page, and a `<change type="rescaled">` in the header
records what was done. It also repairs malformed named-entity tags (like `<name>...</n>`) in the document. When the
pages of a document differ in size, width and height would distort some of them: give a factor instead
(`-F "scale=0.5"`), and every page image is taken to be that fraction of its surface. Every field and the response:
[service/README.md](../service/README.md#post-rescale-multipart-form).

**Method 2: the command line (whole directories).** With hundreds of XML files in a folder and a known scale ratio
or DPI conversion, use `fix_teitok_bboxes.py`. If your web images are exactly 50 % the size of your original scans
(a scale factor of 0.5), process the entire directory at once:

```bash
python3 fix_teitok_bboxes.py -i /path/to/my/teitok_folder/ --sx 0.5 --sy 0.5
```

If your original ALTO OCR data was in tenths of a millimetre (`mm10`) and you need a 72 DPI screen resolution, the
script does that arithmetic:

```bash
python3 fix_teitok_bboxes.py -i my_document.teitok.xml --unit mm10 --dpi 72
```

If the original scans included a scanner bed margin (e.g. 50 pixels on the left and 20 on the top) that was cropped
out of the final web image, shift everything left and up:

```bash
python3 fix_teitok_bboxes.py -i my_document.teitok.xml --dx -50 --dy -20
```

A shift moves content near the edge off the page; such coordinates are clamped to the page (0, or the page's
width/height) and counted, rather than written as negative values the stage-4 gate would reject. Each `<surface>`
is rescaled by its own size, and a `<change type="rescaled">` records the rewrite.

Both methods let you overlay the annotations on the page images without re-running the pipeline. Why boxes can be
off in the first place (image names, ALTO units, the origin, two readers):
[Pitfalls](reference/teitok.md#pitfalls).

### Files from an older format

A resumed run keeps existing `.teitok.xml` files, also those written by an older writer. After a format change,
rewrite them once with `REGENERATE_TEITOK=true bash api_4_stats.sh`; to correct the pages of a collection run up to
v0.21.0, follow [Format changes](reference/teitok.md#format-changes).

### When a run stops

The exit code says why ([Exit codes](#exit-codes)); the first line on stderr names a LINDAT service that failed.
`<OUTPUT_DIR>/processing.log` and the paradata's `skipped_files_detail` name the documents and the reasons
([paradata](reference/paradata.md)).
