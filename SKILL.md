---
name: atrium-nlp-enrich
description: Enriches OCR/HTR text lines (CSV/XLSX/TXT or inline JSON) with Czech NLP annotations - UDPipe morphology and NameTag named entities - producing TEITOK XML, the named entities of each page, and (with a record) the record's entities block. Use this skill to linguistically enrich digitized archival documents after OCR and quality filtering, or to rescale TEITOK page coordinates to a new image size.
---

# ATRIUM NLP Enrichment Skill 📖

This skill provides agent access to the **ATRIUM NLP Enrichment** service - a
UDPipe + NameTag pipeline that turns plain text lines from digitized documents
into enriched **TEITOK XML** with morphology and named entities. Keywords are
not part of it since 1.0.0: they come from the atrium-keyword-extract skill. It
follows a **server-client** design: a
FastAPI server (in `service/`) runs the heavy pipeline, and a zero-dependency
client script (`scripts/atrium_enrich.py`) is the only thing the agent calls
directly.

## Operational Requirements ⚙️

- **Server**: a running instance is required. Default `http://localhost:8000`;
  override with `--base-url` or the `ATRIUM_NE_URL` environment variable.
- **Client dependencies**: none - `scripts/atrium_enrich.py` uses only the
  Python 3 standard library.
- **Server dependencies**: Docker (recommended, compose `api` profile) or a
  Python venv provisioned by `setup_api_service.sh` (installs repo +
  `service/requirements.txt`).
- **First launch**: nothing is downloaded; the image has no model. Every request
  calls the LINDAT UDPipe and NameTag services, so the server needs outbound
  HTTPS to them (`UDPIPE_URL`, `NAMETAG_URL`).
- **Limits**: 5 MB per upload, 30 000 words per synchronous request, 2
  concurrent pipeline runs (HTTP 429 when busy - use `--jobs` or retry later).
- **Readiness**: `GET /health` is liveness (stays 200 while draining); `GET /ready` is the
  orchestrator-facing readiness probe — 503 while warming up or shutting down.

## Pipeline 📖

Stage plan (always runs in full; LLM enrichment is excluded from the API):

| Stage      | What it does                                                   |
|------------|----------------------------------------------------------------|
| `manifest` | normalize input lines into per-document processing manifests   |
| `udp`      | UDPipe tokenization, lemmatization, morphology (LINDAT)        |
| `nt`       | NameTag named-entity recognition (LINDAT)                      |
| `stats`    | summary statistics + TEITOK XML assembly                       |

Input language is Czech-pinned (`lang=cs`) in v1.

## Workflows 🪄

### 1. Ensure the server is running

```bash
bash scripts/server.sh          # Docker Compose api profile (or local fallback)
bash scripts/server.sh --local  # force local uvicorn (no Docker)
```

Idempotent: exits immediately if `GET /ready` already answers 200; waits for
first-run warmup.

### 2. Enrich

```bash
# CSV/XLSX with a `text` column, or plain TXT lines - synchronous
python3 scripts/atrium_enrich.py small_data_samples/CTX000000001.csv

# Plain TXT lines, the entities as machine-readable CSV
python3 scripts/atrium_enrich.py small_data_samples/lines_sample.txt --format csv

# Long-running input: async jobs API (submit → poll → result; 429-safe)
python3 scripts/atrium_enrich.py lines.csv --jobs

# Full workspace ZIP (TEITOK/, UDP_NE/, paradata/)
python3 scripts/atrium_enrich.py lines.csv --zip enriched.zip

# Inline lines from stdin (no file needed)
printf 'Výzkum odhalil základy kostela.\n' | python3 scripts/atrium_enrich.py - --doc-id CTX1

# Discover capabilities and limits
python3 scripts/atrium_enrich.py --info
```

### 3. ATRIUM Document JSON accretion (optional)

Accrete this tool's `entities[]` and `pages[].teitok_surface` onto an existing baseline
record (accretion contract, `docs/document_schema.md` in the hub repo; single-file only,
not combined with `--jobs`/`--zip`):

```bash
python3 scripts/atrium_enrich.py lines.csv --document-json in.document.json \
    --document-json-out-file out.document.json

# also works from stdin
printf 'Výzkum odhalil základy kostela.\n' | python3 scripts/atrium_enrich.py - \
    --doc-id CTX1 --document-json in.document.json --document-json-out-file out.document.json
```

Every other tool's block (`page_categories`, `lines`, `translations`, `enrichment`, ...)
passes through unchanged.

### 4. Interpret output

- `table` (default): `DOC, PAGE, ENTITY, TYPE, COUNT` rows, the most frequent
  named entities of each page, plus a one-line summary (`doc_id`, `pages`,
  entity count, layout source, TEITOK validity) on stderr.
- `csv`: same rows for downstream tabular processing.
- `json`: the full envelope - `doc_id`, `pages`, `stages`, `teitok_xml`,
  `ne_summary`, `layout_source`, `teitok_schema_valid`, `paradata`, and
  `document_json` when a record was sent.
- `--zip` saves the complete pipeline workspace instead (TEITOK XML files,
  UDPipe/NameTag outputs, paradata records).

## Agent Guidelines 🤖

1. **Keywords are another skill's job.** For keywords, send the record this
   skill returns (`--document-json-out-file`) to atrium-keyword-extract; its
   `legacy` method uses the lemmas written here.
2. Prefer `--format json` when the result feeds further processing; the
   TEITOK XML is in the envelope's `teitok_xml` field, and `--zip` materializes
   the whole workspace as files.
3. For full request/response schemas, fetch `GET /openapi.json` from the
   running server (Swagger UI at `/docs`).
4. Exit code `2` (unreachable): start the server (`bash scripts/server.sh`)
   and retry once. Exit code `3` (server error): the client already retried
   a 503 or 504, and a 502 that is not final (`upstream_unavailable`: LINDAT
   did not answer), three times; a 502 with `reason: null` is final and is
   reported at once - check `GET /health?deep=true` (verifies the LINDAT
   UDPipe/NameTag upstreams) and server logs; do not loop.
5. **Busy handling**: HTTP 429 means the concurrent-run limit is reached -
   switch to `--jobs` (async submit/poll) or retry later; do not hammer the
   sync endpoint.
6. **Polling `--jobs`**: a `404` on a job id the server ACCEPTED earlier does not mean
   the id was wrong - the job record is in-memory (`service/jobs.py`), so a restart or a
   different replica behind the same URL loses it. Resubmit the input once and poll the
   new id; never loop on the old one, and never report the run as failed on that basis.
   A `404` for an id the server never returned to you IS a client error - fix the id.
7. **Size limits**: 5 MB per file, 30 000 words per sync request. Split larger
   documents into parts and tell the user you did so.
8. **Input errors**: HTTP 415 means the file type is unsupported (accepted:
   `.csv` with a `text` column, `.xlsx`, `.txt`) - convert first, do not retry.
   HTTP 422 means a supported file had unusable content (e.g. missing `text`
   column, no non-empty rows); fix the input rather than retrying.
9. Do not bypass the API by importing the pipeline code directly; server-side
   runs produce the paradata provenance records shipped in every envelope.

## Acknowledgements & Citations 🙏

Developed within the [ATRIUM](https://atrium-research.eu/) project at ÚFAL,
Charles University; UDPipe and NameTag are
[LINDAT/CLARIAH-CZ](https://lindat.cz) services. If you use this service for
research, cite the repository's `CITATION.cff`.
