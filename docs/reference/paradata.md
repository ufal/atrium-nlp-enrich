# Paradata, provenance and the record schema

For anyone auditing a run or integrating the document record: what a run records about itself, where to look when
a document was skipped, how a container run is tied to its image, and which schema the record follows. The
licences the paradata lists are in [licences.md](licences.md).

On this page: [paradata logs](#paradata-logs) (the [run logs](#the-run-logs-in-output_dirparadata),
[processing.log](#the-runtime-log-output_dirprocessinglog),
[provenance for containers](#provenance-for-containers), [the service's provenance](#the-services-provenance)) ·
[document record schema](#document-record-schema)

## Paradata logs

Every pipeline script records structured provenance metadata through [atrium_paradata.py](../../atrium_paradata.py).
Two complementary log surfaces are produced after a run.

### The run logs in `OUTPUT_DIR/paradata/`

Each of the four pipeline scripts produces one JSON file here, named with the pattern:

```
YYMMDD-HHmmss_nlp-enrich.json
```

where the timestamp prefix is the UTC wall-clock time at which the script started. Because every script is an
independent invocation, a complete four-step run creates four separate files, so individual stages can be audited
in isolation. `run_pipeline.py` merges them into one record per run
([What the runner does](../usage.md#what-the-runner-does)).

The paradata logs (samples in [data_samples/paradata](../../data_samples/paradata)) capture key details about each
pipeline stage, including the program name, run ID, execution duration, configuration parameters, input and output
statistics, and performance metrics. They also document skipped files with reasons and provide a breakdown of
output types and processing rates for benchmarking. This structured metadata makes the pipeline's execution
traceable and auditable.

The declared output types per stage are:

| Script              | Types recorded                                                                   |
|---------------------|----------------------------------------------------------------------------------|
| `api_1_manifest.sh` | `tsv` (one entry per input CSV/XLSX processed into the manifest)                 |
| `api_2_udp.sh`      | `conllu` (one per document)                                                      |
| `api_3_nt.sh`       | `tsv` (one per page; the count reflects individual page TSV files)               |
| `api_4_stats.sh`    | `csv` always; `conllu` when `SAVE_CONLLU_NE=true`; `xml` when `SAVE_TEITOK=true` |

**Resumed runs.** When resuming an interrupted run (stages 2–4 skip already-finished documents via
`[ -f "$out" ] && continue`), the resumed documents are not re-counted in the paradata JSON. The
`input_files_total` field still reflects the full manifest, so `skipped_files + successfully_processed` is less
than `input_files_total` for partial runs. This is expected behaviour; the difference represents the documents
carried over from a previous invocation.

**Paradata state files.** While a pipeline script is running, [atrium_paradata.py](../../atrium_paradata.py) stores
intermediate state in a plain-text JSON file inside `<OUTPUT_DIR>/paradata/` (named `.state_<runid>_<program>.json`).
This file is removed when the script completes. Because it is plain JSON it can be inspected with any text editor if
a run is interrupted unexpectedly; `run_pipeline.py --clean-state` sweeps stale ones.

**Components and licences.** Each record lists the components the run used, each with its licence, as declared in
[para_config.txt](../../para_config.txt), and a computed label, the most restrictive of them. The label is not the
licence of the output: [licences.md](licences.md).

### The runtime log, `OUTPUT_DIR/processing.log`

[api_common.sh](../../api_util/api_common.sh) exposes a `log()` helper that timestamps and `tee`-appends warnings
and errors to this flat file. The four main pipeline scripts (`api_1_manifest.sh` … `api_4_stats.sh`) write to
`processing.log` indirectly through the Python helpers, which print timestamped messages to stderr; any script that
sources `api_common.sh` can also write here via the `log()` function directly.

```
[2026-01-15 09:42:11] [WARN] UDPipe failed (HTTP 503). Retrying in 2s…
[2026-01-15 09:42:14] [ERR]  UDPipe failed permanently after 5 attempts.
```

This file accumulates across reruns; it is the first place to check when a document appears in
`skipped_files_detail` but the reason is terse.

### Provenance for containers

When the runner (or its Docker entrypoint) is started with the `ATRIUM_RUNNER_IMAGE`, `ATRIUM_RUNNER_REPO`, and
`ATRIUM_RUNNER_REF` environment variables set, those values are forwarded to every stage subprocess and end up in
each stage's paradata record (and therefore the merged record). This ties a run back to the exact image and commit
that produced it.

```bash
ATRIUM_RUNNER_IMAGE="ghcr.io/ufal/atrium-nlp-enrich:1.2.0-beta" \
ATRIUM_RUNNER_REF="v1.2.0-beta" \
python3 run_pipeline.py
```

`ATRIUM_RUNNER_IMAGE` names the image with its tag, the release without its leading `v`; `ATRIUM_RUNNER_REF` is the
git ref and keeps the `v` (or a commit: `"$(git rev-parse --short HEAD)"`). `docker-compose.yaml` sets all three for
its services. The published images: [usage, Docker](../usage.md#docker).

### The service's provenance

Over HTTP, every `/enrich` response carries `paradata`: the call's Process Run Crate `CreateAction`, built from the
run's merged pipeline-run record ([service/README.md, JSON envelope](../../service/README.md#json-envelope)).

## Document record schema

The per-document record this tool reads and writes, `<doc_id>.document.json`, the pair of the paradata above,
follows [atrium_document.schema.json](../../atrium_document.schema.json), schema version **`1.0`**. That version is
frozen as the hub tag [`doc-schema-v1`](https://github.com/ufal/atrium-project/releases/tag/doc-schema-v1)
(ufal/atrium-project@`544298b`), and it is the baseline this tool implements:

* [tests/test_schema_freeze.py](../../tests/test_schema_freeze.py) checks this repository's schema against the frozen
  copy beside it, [atrium_document.schema.doc-schema-v1.json](../../atrium_document.schema.doc-schema-v1.json): the
  copy is exactly the tagged file, nothing declared at the freeze has been removed or renamed, and every change made
  since is registered;
* all three files, like `atrium_document.py`, are vendored from the hub and kept byte-identical to its `v1` tag by
  the `para-drift` CI check, so they are never edited in this repository. The hub additionally checks that every
  record shape the tools write validates under both the frozen and the current schema.

In the record, nlp-enrich owns the `entities` block: each entity points at its `<name>` in the TEITOK file
(`teitok_ref`), and each page with a surface at its `<surface>` (`pages[].teitok_surface`). How the service accretes
onto a record it is sent: [service/README.md, The document_json accretion part](../../service/README.md#the-document_json-accretion-part).

What may change after the freeze, and what a new major version takes, is in the hub's
[Freeze & conformance](https://github.com/ufal/atrium-project/blob/main/docs/document_schema.md#freeze--conformance).
[CITATION.cff](../../CITATION.cff) carries the same reference under `references`.
