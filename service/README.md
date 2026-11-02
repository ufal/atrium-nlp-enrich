# NLP enrichment API service

Single-file entry point for the ATRIUM NLP enrichment pipeline: upload ordered text
lines — a table, a `.txt`, or a TEITOK file converted by flexiconv — and get back enriched
**TEITOK XML, named entities and paradata** (the run's provenance log). The four core
stages (`manifest → udp → nt → stats`) always run. Keyword extraction is not part of this
service: it is [atrium-keyword-extract](https://github.com/ufal/atrium-keyword-extract)'s
`POST /extract_keywords`.

## Start

**At a glance:**

| Image                                          | CPU / GPU                            | Memory       | Volumes                                                                                                                   | Calls out to                                                                                     | Ready after                                                                       |
|------------------------------------------------|--------------------------------------|--------------|---------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------|
| `ghcr.io/ufal/atrium-nlp-enrich-api:<version>` | CPU only; no model runs in the image | not measured | none needed; the compose file mounts `./data` at `/data`, and each request works under `TEMP/api_jobs/` (`API_JOBS_ROOT`) | LINDAT's UDPipe 2 and NameTag 3 (`UDPIPE_URL`, `NAMETAG_URL`) on every request; nothing at start | as soon as the process serves, since no model is loaded; the time is not measured |

The published image first: it is what a deployment runs, and it needs no checkout.

```bash
docker run --rm -p 8000:8000 ghcr.io/ufal/atrium-nlp-enrich-api:<version>   # e.g. 1.3.1-beta
curl -s http://localhost:8000/ready                                           # 200 once ready
# from a checkout:
docker compose --profile api up -d
# or in a virtual environment (development):
./setup_api_service.sh                 # venv + deps + serve
pip install -r requirements.txt -r service/requirements.txt
python -m service.api                  # honours PORT/HOST; default 0.0.0.0:8000
```

Run from a virtual environment, the service needs no activation: the pipeline puts the
environment's `bin` first for its stage scripts, and refuses with exit 3 (HTTP 500) when their
`python3` lacks a package (see [Errors](#errors)).

Smoke test, with the service running in another terminal:

```bash
python service/test_api.py -f data_samples/DOC_LINE_CATEG/CTX000000001.csv
```

## Models and caches

Nothing is downloaded or loaded at start: the image has no model. Every request calls two remote
LINDAT services, so the service needs outbound HTTPS to them.

| What                                    | From where                        | Revision                            | Into | Without egress                                                              |
|-----------------------------------------|-----------------------------------|-------------------------------------|------|-----------------------------------------------------------------------------|
| UDPipe 2 (tokens, lemmas, tags, syntax) | `UDPIPE_URL` (LINDAT by default)  | the model named in `config_api.txt` | —    | 502 `upstream_unavailable` after the retries; 504 when every call timed out |
| NameTag 3 (named entities)              | `NAMETAG_URL` (LINDAT by default) | the model named in `config_api.txt` | —    | the same                                                                    |

## Endpoints

| Method | Path                | Purpose                                                                                                                                                                      |
|--------|---------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| GET    | `/`                 | redirects to the demo form at `/frontend` (`/docs` is the OpenAPI UI)                                                                                                        |
| GET    | `/info`             | service id, endpoints, stage plan, pinned models, `limits` (every [limit](#limits), current value) and `limits_meta` (the variable behind each)                              |
| GET    | `/health`           | liveness — 200 always, even mid-shutdown. `?deep=true` adds config validity via `run_pipeline.py --dry-run` + UDPipe/NameTag reachability (503 on failure or while draining) |
| GET    | `/ready`            | readiness — 503 until warmup finishes, 200 while serving, 503 the instant `SIGTERM` arrives. The Kubernetes `readinessProbe`/`startupProbe` target                           |
| POST   | `/enrich`           | **single-file entry point** — upload CSV/XLSX/TXT, or a converted TEITOK `.xml`; optionally the ALTO of a table's pages                                                      |
| POST   | `/enrich_text`      | same pipeline for inline JSON                                                                                                                                                |
| POST   | `/jobs`             | the `/enrich` form as a background job: returns `{"job_id", "status": "queued"}` at once; 429 `busy` when `MAX_QUEUED_JOBS` jobs already wait                                |
| GET    | `/jobs/{id}`        | the job's `status` (`queued` until it holds a slot, `running`, `done`, `failed`), `error` and `reason` (`limit_exceeded` when `API_JOB_TIMEOUT` stopped it)                  |
| GET    | `/jobs/{id}/result` | the `/enrich` JSON envelope of a finished job (409 while it runs)                                                                                                            |
| DELETE | `/jobs/{id}`        | forget a job (finished jobs are also forgotten `JOB_TTL_S`, an hour, after they end); job ids are local to the replica                                                       |
| POST   | `/rescale`          | rescale a TEITOK's bboxes to page images of another size, page by page                                                                                                       |
| POST   | `/project_record`   | project a finished record's page categories, its TEATER/AMČR categories and controlled keywords, and its statistical keywords onto its TEITOK header (opt-in)                |

### `POST /enrich` (multipart form)

| Field                      | Default                 | Notes                                                                                                                                                                                                                                                                                                                                                                                                                 |
|----------------------------|-------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `file`                     | *required*, or a record | `.csv` (needs a `text` column; optional `page_num` or `page`, `line_num` or `line`, `page_label`, `categ`), `.xlsx`, `.txt` (a form feed starts a new page), or a TEITOK `.xml` (`*.teitok.xml`, or any `.xml` starting with `<TEI`) — see [Layout inputs](#layout-inputs). Read as stage 1 reads the same file (`api_util/line_inputs.py`). Optional when `document_json` is a record whose `lines[]` carry the text |
| `alto`                     | *optional*              | ALTO XML of the pages a `.csv`/`.xlsx` lists the lines of — see [Layout inputs](#layout-inputs)                                                                                                                                                                                                                                                                                                                       |
| `lang`                     | `cs`                    | `cs` only, as the command line's `--lang`: the UDPipe and NameTag models of `config_api.txt` decide the language; any other value → 422                                                                                                                                                                                                                                                                               |
| `format`                   | `json`                  | `json` envelope, or `zip` of the workspace `OUTPUT_DIR`; any other value → 422                                                                                                                                                                                                                                                                                                                                        |
| `document_json`            | *optional*              | baseline ATRIUM Document JSON (or an AMČR seed) to accrete onto — see below; not a JSON object → 422 `invalid_record`. A born-digital record is also a layout — see [Layout inputs](#layout-inputs)                                                                                                                                                                                                                   |
| `teitok_enrichment`        | `false`                 | opt-in: the returned TEITOK also carries, in its header, the record's page categories (`pb/@ana`), its controlled keywords and its statistical keywords — see [`POST /project_record`](#post-project_record-multipart-form). `/jobs` takes it too                                                                                                                                                                     |
| `skip_untrustworthy_lines` | `false`                 | opt-in: a table's rows whose `categ` is `Trash`, `Garbage` or `Inverted` are left out, as the command line's `SKIP_UNTRUSTWORTHY_LINES`. A record sent as the text is filtered always. `/jobs` and `/enrich_text` take it too                                                                                                                                                                                         |
| `include_record`           | `false`                 | opt-in: `document_json` comes back even when none was sent, a new record with nlp-enrich's blocks, as `run_pipeline.py --document-json-out` alone writes. `/jobs` and `/enrich_text` take it too                                                                                                                                                                                                                      |

### Layout inputs

The TEITOK the service returns has the layout of what it was given; `layout_source` in the envelope says which:

| Upload                                                          | `layout_source` | The TEITOK                                                                                                                                                   |
|-----------------------------------------------------------------|-----------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `.csv`/`.xlsx`/`.txt`                                           | `rows`          | one `<pb>` per page and one `<lb>` per line of the input; no boxes, no facsimile, no page images                                                             |
| `.csv`/`.xlsx` + `alto`                                         | `alto`          | as the CLI with `INPUT_ALTO_DIR`: word, line and block boxes, `<facsimile>`, `<figure>`s                                                                     |
| a TEITOK `.xml` converted by flexiconv                          | `teitok`        | as the CLI with `FLEXICONV_ANNOTATE=true`: its pages, lines and word boxes, its page images' names                                                           |
| a born-digital record as `document_json`, alone or with a table | `record`        | a `<surface>` per page sized by `pages[].canvas`, the `lines[].bbox` boxes on `<lb>`, token boxes shared out from them, page images named `<doc_id>-<N>.png` |

* A **TEITOK upload** is text and layout at once: its rows (`teitok_read`) go through the
  pipeline as the document's table, and the file itself becomes that document's layout — the
  same claim the CLI's stage 1 makes. Convert PDF, DOCX, PAGE XML, hOCR, … to TEITOK with
  `api_flexiconv.sh` (CLI) first: flexiconv is **not** in the service image. A file
  that is not well-formed, or breaks TEITOK-core rules (duplicate ids, references that point
  nowhere), is refused with 422 and the diagnostics.
* An **`alto` part** goes with a `.csv`/`.xlsx` (e.g. ocr-postprocess's `DOC_LINE_CATEG` table and
  the ALTO it was made from); with a `.txt` or a TEITOK file it is refused (422). A PAGE XML or
  hOCR file in its place is refused with the hint to convert it with `api_flexiconv.sh`.
* A **born-digital record** (digital-convert's `POST /reformat` of a PDF) sent as `document_json` (also to
  `/enrich_text`) is a layout when its pages have a `canvas` and its lines a `bbox`; an `alto` or
  TEITOK upload wins over it.
  Sent **without `file`**, the record is the text as well: its `lines[]` (less `Garbage`,
  `Inverted` and `Trash` lines) are the table, so text and boxes come from the same lines. A
  table sent with the record is aligned to it character by character: it should list the
  record's lines as they are, because lines left out (running footers, say) shift the alignment,
  and on a long document the boxes then stop matching. A record with no text in `lines[]` (a
  scanned PDF) and no `file` is refused with 422, as is an `alto` part without a table.
* The record's boxes are in its canvas unit, PDF **points**, and the service answers in them
  (`<surface lrx="612" lry="792">` for a Letter page). For pixels, `POST /rescale` with `scale` =
  the page images' DPI / 72; the CLI scales them itself with `IMAGE_DPI` or `INPUT_PAGES_DIR`. The
  record has line boxes only, so a token's box is its share of the line box by character offset
  — approximate, and the header says so. A DOCX record has no geometry: `layout_source` is `rows`.
* The `doc_id` is the file name without `.teitok.xml`, `.alto.xml` or the table extension, as the
  command line derives it from the same file: `zpráva 1.csv` is `zpráva 1`. Only control characters and path
  separators are replaced. For a record sent
  alone, the record's `doc_id`.

### `POST /enrich_text` (JSON)

```json
{ "doc_id": "CTX1", "lines": ["Výzkum odhalil základy kostela.", "..."],
  "format": "json",
  "document_json": { "...optional baseline record, inline..." },
  "teitok_enrichment": false, "skip_untrustworthy_lines": false, "include_record": false }
```

A line may also be an object: `text`, and optional `page_num` (or `page`), `line_num` (or `line`),
`page_label` and `categ`.

### The `document_json` accretion part

The hub's [document contract](https://ufal.github.io/atrium-project/ecosystem/document-contract/)
(`docs/document_schema.md`) asks a service to **accept and return an optional `document_json` part**.
`/enrich` and `/jobs` take it as an upload part; `/enrich_text` takes it as an embedded object.

When supplied, the response's `document_json` carries the record back with only
nlp-enrich's contribution merged in — its `entities[]` rows, whose `teitok_ref` is the
entity's `<name id>` (`n-1`, …) in the returned TEITOK — while every other tool's block
(`page_categories`, `lines`, `translations`, `enrichment`, …) passes through **untouched**.
`pages[].teitok_surface`, the `<surface id>` `facs-P` of a page, is written for pages that
have a surface: with an `alto` part, or a TEITOK upload whose pages name an image or a size.
This is the same accretion the CLI performs via `run_pipeline.py --document-json/--document-json-out`.
The service threads the flags through to it, so there is one implementation, not two.

* Omit the part and the key is **absent** from the envelope — not `null`. Existing clients
  see no change at all.
* Supply it and get `null` back, and the pipeline produced no record (no CoNLL-U reached the
  document hook, or the hook failed and the run went on without it). `run_pipeline.py` prints
  `[document-json] NOT WRITTEN` on stdout in that case; the service's `stages` and the
  pipeline log say why.
* A baseline that does not validate against `atrium_document.schema.json` is still accepted:
  the pipeline warns, names the schema error, and accretes onto it anyway rather
  than turning one bad upstream record into a stalled pipeline.
* A baseline that cannot be opened at all — not UTF-8 JSON, not a JSON object, or a
  `schema_version` with a newer major — is refused before the pipeline runs, with 422
  `reason: invalid_record`.

### JSON envelope

```json
{
  "doc_id": "...", "pages": 2,
  "stages": [ {"script": "api_4_stats", "successfully_processed": 1, ...} ],
  "teitok_xml": "<?xml ...>",
  "ne_summary": [ {"file": "...", "page": "1", "entities": [...] } ],
  "paradata": { "@id": "urn:uuid:...", "@type": "CreateAction", "...": "..." },
  "limits_applied": [ {"limit": "ne_summary_top_n", "value": 20, "effect": "trimmed",
                       "count": 1, "detail": "...", "program": "nlp-enrich"} ],
  "layout_source": "rows",
  "teitok_schema_valid": true, "teitok_schema_errors": [],
  "document_json": { "...only when a baseline was supplied..." }
}
```

`limits_applied` lists every [limit](#limits) that shaped the result without refusing it
— pages whose entity summary kept its top N. The stages record them in their paradata;
this is the merged record's list (`[]` when no limit applied).

**`paradata`** is the call's provenance: one Process Run Crate `CreateAction`,
built by `atrium_rocrate.create_action()` from the run's merged pipeline-run record (its
`paradataRecord`, with the components of every stage). Its `@id` is the `run_uuid` the stats
stage stamped on the blocks it wrote into `document_json`, or, without a record, the merged run's
own. `object` is what the call was sent (the upload or `lines.json`, a separate `alto` part, the
record), and `result` is the blocks written and the TEITOK. `agent` is `ATRIUM_RUN_AGENT` when set. The
field is `null` only for a run that left no paradata. An error response carries no action. Hub
[`docs/rocrate_export.md`](https://github.com/ufal/atrium-project/blob/main/docs/rocrate_export.md) §5
describes it.

`layout_source` is `rows`, `alto`, `teitok` or `record` ([Layout inputs](#layout-inputs)).
`teitok_schema_valid`/`teitok_schema_errors` are the output-contract verdict on `teitok_xml`
(`validate_teitok_xml.py`'s default `contract` profile); a run whose TEITOK fails the contract
never gets here — stage 4 stops with exit code 5, answered as 500.

`format=zip` instead streams the full workspace `OUTPUT_DIR`
(`TEITOK/`, `UDP_NE/`, summary CSVs, `paradata/`, and
`<doc_id>.document.json` when a baseline was supplied).

### `POST /rescale` (multipart form)

A standalone coordinate transform — **not** part of the NLP pipeline (no
subprocess, no models, no workspace). Given a TEITOK document and the size of its page
images, it rescales every facsimile coordinate from the document's own coordinate space, page by page. The
coordinates are the `bbox="x1 y1 x2 y2"` pixel boxes, `pb@bbox` and the `<surface>` `lrx`/`lry` extents. Annotations
then line up exactly on top of images of that size. Each box is
scaled by the `<surface>` of the page it is on (the one its `<pb corresp>` names, or the k-th
surface for the k-th `<pb>`) and clamped to that page; `clamped` counts the coordinates that
had to move. A `<change type="rescaled">` in `<revisionDesc>` records the transform. This works for both
coordinate origins the writer offers (`BBOX_ORIGIN=page`, the default, and `printspace`): in both, `<surface>`
declares the extent the boxes are measured in.

| Field       | Default    | Notes                                                                                                                             |
|-------------|------------|-----------------------------------------------------------------------------------------------------------------------------------|
| `file`      | *required* | a `.teitok.xml` (or `.xml`)                                                                                                       |
| `width`     | —          | target image width in pixels (1–`MAX_RESCALE_DIM`), with `height`                                                                 |
| `height`    | —          | target image height in pixels (1–`MAX_RESCALE_DIM`), with `width`                                                                 |
| `scale`     | —          | instead of `width`/`height`: every page image is this fraction of its `<surface>` (0–100); required when the pages differ in size |
| `format`    | `json`     | `json` envelope, or `xml` to download the rescaled `.teitok.xml`                                                                  |
| `fix_names` | `true`     | repair malformed `<name>…</n>` closings to `</name>`                                                                              |

The **source** coordinate space is read from the document itself: each page's
`<surface>` `lrx`/`lry` (the authoritative page extent); `width`/`height` are refused (422)
for a document whose surfaces differ in size — they would distort some pages — so give
`scale` there. Without any sized `<surface>` it falls back to the maximum extent of all `bbox`
boxes (`source_kind: "bbox-extent"`, approximate). The transform is a surgical,
text-level rewrite that only touches the numeric values, so it is robust to the
non-well-formed quirk of older TEITOK exports (named entities open `<name>` but close
`</n>`; the current writer closes `</name>`) that makes a strict XML parse fail.

Because that `</n>` quirk produces invalid XML, the endpoint also **repairs it by
default** — rewriting stray `</n>` closings to `</name>` so the returned document
parses cleanly (`name_tags_fixed` reports how many were fixed). This is a no-op
on already-valid TEITOK. Pass `fix_names=false` to leave the markup byte-for-byte
as-is and only rescale coordinates.

```bash
curl -s -F "file=@CTX000000001.teitok.xml" -F "width=827" -F "height=1170" \
     http://localhost:8000/rescale            # JSON envelope
curl -s -F "file=@CTX000000001.teitok.xml" -F "width=827" -F "height=1170" \
     -F "format=xml" -OJ http://localhost:8000/rescale   # download rescaled XML
curl -s -F "file=@mixed_pages.teitok.xml" -F "scale=0.5" \
     http://localhost:8000/rescale            # pages of different sizes
```

`format=json` response:

```json
{
  "teitok_xml": "<?xml ...>",
  "source": { "width": 1654, "height": 2339 },
  "source_kind": "surface",
  "target": { "width": 827, "height": 1170 },
  "scale": { "sx": 0.5, "sy": 0.500214 },
  "pages": [
    { "surface": "facs-1", "source": { "width": 1654, "height": 2339 }, "target": { "width": 827, "height": 1170 } },
    { "surface": "facs-2", "source": { "width": 1654, "height": 2339 }, "target": { "width": 827, "height": 1170 } }
  ],
  "boxes_rescaled": 38,
  "clamped": 0,
  "name_tags_fixed": 0,
  "schema_valid": true, "schema_errors": []
}
```

`source`, `target` and `scale` describe the first page; `pages` lists every page with a sized
`<surface>`.

### `POST /project_record` (multipart form)

A standalone header transform (no pipeline) for a record that is complete only after this
service ran: after page-classification and keyword-extract have written their blocks.
Opt-in by being called; AMČR's stored TEITOK keeps linguistics and layout only.

| Field           | Default    | Notes                                                                                   |
|-----------------|------------|-----------------------------------------------------------------------------------------|
| `file`          | *required* | the document's `.teitok.xml` as nlp-enrich wrote it (format `teitok-2`)                 |
| `document_json` | *required* | the document's finished record                                                          |
| `format`        | `json`     | `json` envelope, or `xml` to download the projected `.teitok.xml`                       |

What is written — `pb/@ana` and a `classDecl` taxonomy for the page categories,
`profileDesc/textClass/keywords` for the TEATER/AMČR categories and controlled
keywords and for the `keywords` block's statistical keywords, each pointing at its pages — is
the table in the TEITOK reference's
[Record projection onto TEITOK](../docs/reference/teitok.md#record-projection-onto-teitok-opt-in). Nothing
below the header changes but `pb/@ana`; projecting again replaces an earlier projection. 422
when the TEITOK is not the record's document (its `<title>` is neither `doc_id` nor the id of
`source.filename`), is not this writer's `teitok-2` output, or does not validate.

```bash
curl -F file=@TEITOK/CTX000000001.teitok.xml -F document_json=@CTX000000001.document.json \
     http://localhost:8000/project_record                  # JSON envelope
curl -F file=@TEITOK/CTX000000001.teitok.xml -F document_json=@CTX000000001.document.json \
     -F format=xml -OJ http://localhost:8000/project_record  # download the projected XML
```

```json
{ "doc_id": "CTX000000001", "teitok_xml": "<?xml ...",
  "report": { "page_categories": 2, "teater_categories": 1,
              "controlled_keywords": { "cs": 2, "en": 2 },
              "statistical_keywords": { "document": 0, "pages": 0 },
              "unresolved_pages": [], "notes": [], "changed": true },
  "schema_valid": true, "schema_errors": [] }
```

## Errors

Every error has one JSON body (hub `docs/agent_skill_strategy.md` §4.4): `{"status": <int>, "reason": <code or null>,
"detail": "<text>"}`. `detail` is always
a string. A limit refusal adds `limit` (`{key, env, value, observed, unit}`); a request
validation error adds FastAPI's list of problems as `errors`.

| Status | `reason`                 | Meaning                                                                                                                                                                | What to do                                                                           |
|--------|--------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------|
| 404    | `null`                   | `/jobs/{id}` or its `/result` names a job this replica does not hold: deleted, forgotten `JOB_TTL_S` after it ended, lost in a restart, or accepted by another replica | submit it again with `POST /jobs`; route a client's job calls to one replica         |
| 409    | `null`                   | `/jobs/{id}/result` of a job that is not `done`                                                                                                                        | poll `GET /jobs/{id}` until `done`                                                   |
| 413    | `limit_exceeded`         | over `MAX_UPLOAD_MB` or `MAX_WORDS`                                                                                                                                    | split the input, or raise the setting `limit.env` names                              |
| 415    | `unsupported_media_type` | the upload is not `.csv`, `.xlsx`, `.txt` or a TEITOK `.xml`; `accepted` lists them                                                                                    | send one of the types in `accepted`                                                  |
| 422    | `invalid_record`         | the `document_json` sent cannot be opened (not UTF-8 JSON, not an object, a newer `schema_version` major), or its `entities` or `pages` is not a list of objects       | send the record the previous stage wrote; update this service if the record is newer |
| 422    | `limit_exceeded`         | `/rescale` over `MAX_RESCALE_DIM`                                                                                                                                      | lower `scale`, or raise `MAX_RESCALE_DIM`                                            |
| 422    | `null`                   | an unusable upload, a bad parameter (a value outside the spec's enums or bounds), or request validation (`errors`)                                                     | fix the field `errors` or `detail` names                                             |
| 429    | `busy`                   | every processing slot taken (synchronous endpoints), or the `/jobs` queue full; retry after `Retry-After` seconds                                                      | retry after `Retry-After`; add replicas if it persists                               |
| 500    | `null`                   | the TEITOK failed its output contract (exit 5) — a writer defect, please report it; LINDAT refused the request (exit 8, a 4xx)                                         | report it with `detail`; for a LINDAT 4xx, check the model names in `config_api.txt` |
| 500    | `null`                   | a dependency the stages need is missing (exit 3, a deployment defect); `detail` says what and how to install it                                                        | install what `detail` names into the service's Python, or run the image              |
| 502    | `upstream_unavailable`   | UDPipe or NameTag did not answer after their retries (exit 6); `detail` starts `LINDAT UDPipe …` or `LINDAT NameTag …`                                                 | retry later; check that `UDPIPE_URL` and `NAMETAG_URL` are reachable                 |
| 502    | `null`                   | a stage failed: an empty run, a missing stage                                                                                                                          | fix the input `detail` names; do not retry it unchanged                              |
| 503    | `null`                   | the replica is shutting down                                                                                                                                           | retry on another replica                                                             |
| 504    | `limit_exceeded`         | the run took longer than `API_JOB_TIMEOUT` and was stopped; or every LINDAT attempt timed out (exit 7, `limit.key` `lindat_timeout_s`)                                 | send a smaller input, or raise the setting `limit.env` names                         |

## Limits

Every limit is an environment setting, declared in
`tool_limits.py` and reported with its current value by `GET /info` (`limits`; `limits_meta`
says which variable sets it and whether the value came from the environment, `config_api.txt`
or the default). A malformed value stops the service at startup, naming the variable. An input
over a limit is refused with the [harmonised error](#errors); a limit that shapes a result
without refusing it is named in `limits_applied`. The three stage limits are also keys of
`config_api.txt` (named in the table): for an API job the variable wins over the template,
which wins over the default, and the service writes the effective value into the job's
config. `tests/test_limits_contract.py` checks this table against `tool_limits.py` and
`.env.example`.

| Key (`/info`)         | Variable              | Default | Unit     | Over the limit                                                                                                                                      |
|-----------------------|-----------------------|---------|----------|-----------------------------------------------------------------------------------------------------------------------------------------------------|
| `max_upload_mb`       | `MAX_UPLOAD_MB`       | 5       | MB       | 413 `limit_exceeded` — per part (the file, `document_json`, `alto`) and for the whole `/enrich_text` body                                           |
| `max_words`           | `MAX_WORDS`           | 30000   | words    | 413 `limit_exceeded` — `/enrich`, `/enrich_text` and `/jobs` alike                                                                                  |
| `max_concurrent_jobs` | `MAX_CONCURRENT_JOBS` | 2       | jobs     | a synchronous request: 429 `busy` with `Retry-After: 30`; a `/jobs` job stays `queued`                                                              |
| `max_queued_jobs`     | `MAX_QUEUED_JOBS`     | 8       | jobs     | `/jobs`: 429 `busy` with `Retry-After: 30` (0: a job only when a slot is free)                                                                      |
| `api_job_timeout`     | `API_JOB_TIMEOUT`     | 600     | s        | the run and every process it started are stopped, the workspace removed: 504 `limit_exceeded`; a `/jobs` job ends `failed`, reason `limit_exceeded` |
| `job_ttl_s`           | `JOB_TTL_S`           | 3600    | s        | a finished job is forgotten: `/jobs/{id}` answers 404                                                                                               |
| `max_rescale_dim`     | `MAX_RESCALE_DIM`     | 100000  | px       | 422 `limit_exceeded` — `width`/`height` over it, or a page that `scale` takes past it                                                               |
| `word_chunk_limit`    | `WORD_CHUNK_LIMIT`    | 900     | words    | UDPipe gets the text in pieces cut at a line end, annotated in full (`config_api.txt` `WORD_CHUNK_LIMIT`)                                           |
| `lindat_timeout_s`    | `LINDAT_TIMEOUT_S`    | 60      | s        | the UDPipe or NameTag call is retried; when every attempt timed out the stage fails → 504 `limit_exceeded` (`config_api.txt` `TIMEOUT`)             |
| `lindat_max_retries`  | `LINDAT_MAX_RETRIES`  | 5       | retries  | the stage fails → 502 `upstream_unavailable` (`config_api.txt` `MAX_RETRIES`)                                                                       |
| `ne_summary_top_n`    | `NE_SUMMARY_TOP_N`    | 20      | entities | a page keeps its N most frequent entities in `ne_summary` — `trimmed` note (the TEITOK and `document_json` carry every entity)                      |

Not settings: Starlette's multipart parser keeps its own defaults.

## Partial results

A 200 can carry less than was asked for. Read these before using the result:

- `limits_applied` lists each [limit](#limits) that shaped the result without refusing it, for
  example pages whose entity summary kept its top N.
- `document_json` is `null` although a `document_json` was sent: the record could not be updated.
  The other outputs are complete; the record you sent is unchanged, and the service log names the
  cause on its `[document-json] NOT WRITTEN` line.
- `layout_source` `rows` means the TEITOK has pages and lines but no boxes: no layout input had
  geometry ([Layout inputs](#layout-inputs)).

## Known limits

- UDPipe and NameTag run at LINDAT under the [LINDAT Terms of Use](https://lindat.mff.cuni.cz/en/terms-of-use);
  their models are CC BY-NC-SA 4.0. The paradata lists them with these licences, which are not the licence
  of the output: the rights in an output depend on the source document and are stated by whoever holds them
  ([Licences and paradata](https://ufal.github.io/atrium-project/ecosystem/licences/)).
- Every request needs LINDAT: there is no local fallback for UDPipe or NameTag.
- A born-digital record has line boxes only. Word boxes are shared out from them by character
  offset, are approximate, and the TEITOK header says so.
- A record's boxes are in PDF points; `/rescale` with `scale` = DPI/72 turns them into the pixels
  of a page image rendered at that DPI.
- Named entities come from NameTag's general model (OntoNotes types), not an archaeological one.
- `/jobs` are not persistent. A job lives in the memory of the replica that accepted it: a restart, a redeploy
  or a call that reaches another replica answers 404, and the client submits the job again. Accepted for the
  [S2 pilot](https://ufal.github.io/atrium-project/pilot/); `/enrich` is the synchronous alternative.

## Configuration (environment)

| Variable              | Default   | Meaning                                                                          |
|-----------------------|-----------|----------------------------------------------------------------------------------|
| `PORT`                | `8000`    | port the service **binds**, and the one `service/healthcheck.py` probes          |
| `HOST`                | `0.0.0.0` | bind address; see the note below                                                 |
| `GRACEFUL_SHUTDOWN_S` | `20`      | seconds uvicorn waits for in-flight requests                                     |
| `RELOAD`              | `false`   | filesystem auto-reload — development only                                        |
| `LOG_LEVEL`           | `INFO`    | root logger level for the `python -m service.api` start path                     |
| `ALLOWED_ORIGINS`     | `*`       | CORS origins                                                                     |
| `UDPIPE_URL`          | LINDAT    | UDPipe 2 endpoint, attachable; the same variable name as atrium-translator       |
| `NAMETAG_URL`         | LINDAT    | NameTag 3 endpoint, attachable                                                   |
| `API_JOBS_ROOT`       | see below | where per-job workspaces are created; computed from the repo root, not a literal |
| `API_KEEP_WORKSPACES` | unset     | keep per-request workspaces for debugging -- survives only as long as the pod    |

Every limit — `MAX_UPLOAD_MB`, `MAX_WORDS`, `MAX_CONCURRENT_JOBS`, `API_JOB_TIMEOUT` and the
rest — is listed under [Limits](#limits).

`PORT` and `HOST` are read by `service/api.py`'s `__main__` block, which is what the `api`
image's `ENTRYPOINT` (`python -m service.api`) runs. The start command lives there, not in an
exec-form `ENTRYPOINT` array, because an exec-form array runs no shell and `$PORT` could not
expand in it. `service/healthcheck.py` reads the same `PORT`, so the listener and the health
probe move together.

> **Note:** `HOST=127.0.0.1` yields a container that reports **healthy** and serves nobody:
> `service/healthcheck.py` always probes loopback by design and never reads `HOST`, so a
> loopback bind passes every probe while being unreachable from outside the container.

## How it works

`PipelineManager` treats `run_pipeline.py` as the **only** execution interface —
it never calls the stage scripts directly. Each request gets a fresh workspace
under `TEMP/api_jobs/<job_id>/` with every pipeline directory relocated inside
it, so resume / paradata-collision / `FAIL_ON_EMPTY` semantics behave as a clean
first run and concurrent requests can't collide. A `.csv`, `.xlsx` or `.txt` upload goes to
stage 1 as sent (`in/<doc_id>.<ext>`), as the command line hands it the user's file, so the
TEITOK names the file that was sent. A TEITOK upload, a record sent as the
text and `/enrich_text`'s lines are written as the canonical table (`text`, `page_num`,
`line_num`, `page_label`, `categ`). Every input goes through stage 1; none bypasses it.

The runner's exit code decides the HTTP answer:

| Exit code | Meaning                                                                                               | Answer                                                   |
|-----------|-------------------------------------------------------------------------------------------------------|----------------------------------------------------------|
| `0`       | the run completed                                                                                     | 200                                                      |
| `1`       | an empty run                                                                                          | 502                                                      |
| `2`       | a stage script is missing                                                                             | 502                                                      |
| `3`       | a dependency of the stages is missing, e.g. their `python3` cannot import `lxml`: a deployment defect | 500; `detail` says what is missing and how to install it |
| `5`       | the TEITOK failed its output contract: a writer defect, "please report it"                            | 500                                                      |
| `6`       | UDPipe or NameTag did not answer after the retries                                                    | 502 `upstream_unavailable`                               |
| `7`       | every attempt at a LINDAT call timed out                                                              | 504 `limit_exceeded`, naming `lindat_timeout_s`          |
| `8`       | LINDAT refused the request (a 4xx)                                                                    | 500                                                      |
| other     | a stage failed in another way                                                                         | 502                                                      |

Codes 6 to 8 come from the LINDAT clients (`api_util/lindat_errors.py`) and travel through their stage
scripts unchanged; each `detail` starts with the client's `LINDAT …` line. An input over a limit gives 413
or 422 `limit_exceeded`, a run over `API_JOB_TIMEOUT` gives 504 `limit_exceeded`, and every slot or the
queue taken gives 429 `busy` ([Limits](#limits), [Errors](#errors)). An unusable upload gives 422.

UDPipe/NameTag models stay operator-pinned in `config_api.txt` and are surfaced
read-only via `/info`. The layout comes with the upload ([Layout inputs](#layout-inputs)):
an uploaded TEITOK file is written to `<workspace>/layout/flexiconv/<doc_id>.teitok.xml`
(`TEITOK_FLEXICONV_DIR`, `FLEXICONV_ANNOTATE=true`), an `alto` part to
`<workspace>/layout/alto/<doc_id>.alto.xml` (`INPUT_ALTO_DIR`); both are outside `in/`, which
stage 1 reads as tables. Page images are never uploaded, so a surface keeps the size its
layout declares.

## Shutdown behaviour

The `api` image declares `HEALTHCHECK` (shallow `GET /health`, via the vendored
`service/healthcheck.py`) and `STOPSIGNAL SIGTERM`, and sets `ENV GRACEFUL_SHUTDOWN_S=20`,
which `service/api.py`'s `__main__` block passes to uvicorn as
`timeout_graceful_shutdown`.

On `SIGTERM` the service:

1. flips `GET /ready` to **503** immediately, so an orchestrator stops routing new
   requests here (`GET /health` deliberately stays 200 — a liveness probe failing
   mid-shutdown would get the container killed before it finished draining);
2. lets uvicorn drain in-flight HTTP requests (up to 20s);
3. **then waits up to a further 25s for any background `/jobs` run to finish.** This
   step is what a plain in-flight-request count cannot do: `POST /jobs` returns
   `{"status": "queued"}` straight away, so the request is long gone while the job is
   still running. Jobs are registered with `ServiceState.track()`
   (`service/atrium_service.py`) specifically so shutdown waits for them.

A job that needs longer than that drain budget is still cut short, and the job
**record** is in-memory (`service/jobs.py`) — so a client polling `/jobs/{id}` across a
restart gets 404 rather than a result. Durable job storage is out of scope. See `docs/k8s_deployment.md` in the hub
for the full
grace-period budget and the Kubernetes probe contract.

The container exits **143** (128 + SIGTERM) after a clean shutdown, not 0 — uvicorn
re-raises the captured signal on purpose so a supervisor sees the real cause. That is a
normal stop, not a crash.

## Frontend(s)

`GET /` redirects to `/frontend`, a form that sends a table, a `.txt` or a flexiconv TEITOK file, with an
optional ALTO file, to `POST /enrich`. It shows the JSON envelope, or downloads the workspace as a ZIP.
`/frontend-lindat` is the same form in LINDAT's page frame: it loads LINDAT's header and footer script from
`lindat.mff.cuni.cz`. Both pages load the Milligram style sheet from `cdnjs.cloudflare.com`, so the viewer's
browser needs to reach those hosts.

## OpenAPI (the typed contract)

The service's OpenAPI document is committed as [`service/openapi.json`](openapi.json) and
attached to every release as `openapi.json` with its `openapi.json.sha256`. It is what a client is generated from.
Every request and response field is typed (the envelope as `EnrichResponse`, the jobs API, `/rescale`), and every
error response is the body above. The registered `reason` codes are listed in `x-atrium-reason-codes`. A returned
record is typed by the vendored record schema (`AtriumDocument`), and `paradata` by its `CreateAction`.
`GET /info` reports `openapi_sha256`, the digest of the spec the running image serves. It equals the release's
`openapi.json.sha256` for an image built from that tag.

- **After an API change**, regenerate and commit it:
  `python atrium_openapi.py export --app service.api:app --out service/openapi.json`.
  `tests/test_openapi_contract.py` fails while it is stale, and when any setting
  (every limit) changes it.
- **Compatibility.** Each release compares its spec with the previous release's
  (`release.yml`, `atrium_openapi.py compare` with oasdiff): a breaking change fails the
  release unless the major version went up (for 0.x, that means 1.0), and a removed reason
  code always fails. New fields, endpoints and reason codes are additive.
- **fastapi and pydantic are pinned** exactly (`service/requirements.txt`,
  `requirements-test.txt`): the spec is generated by them. Bump both by hand and regenerate.

## Tests

`tests/test_api_contract.py` drives every endpoint with the pipeline stood in and holds each
response — 200s and refusals — to the published schema; `tests/test_openapi_contract.py`
(vendored from the hub) checks the committed spec itself.
`tests/test_api_service.py` is fully hermetic (no LINDAT, no models): it
monkeypatches the pipeline subprocess to drop fixture outputs into the
workspace, then exercises the full HTTP contract via FastAPI `TestClient`,
plus input normalization, the `doc_id` of an upload, and exit-code→HTTP mapping.
`tests/test_rescale.py` covers the `/rescale` transform and endpoint (including
the non-well-formed `<name>…</n>` TEITOK quirk and documents whose pages differ in size).
`tests/test_teitok_project.py` covers the record projection, `/project_record` and the
`teitok_enrichment` switch.
`tests/test_service_layout_inputs.py` runs the real stage-1 and stage-4 scripts in the
service's workspace (UDPipe/NameTag stood in for) with a TEITOK upload, a table with and
without its ALTO, and the refused combinations.

```bash
pytest -m "not slow" tests/test_api_service.py tests/test_rescale.py tests/test_service_layout_inputs.py tests/test_teitok_project.py
```
