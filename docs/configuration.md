# Configuration

For anyone running the command-line pipeline or pointing it at other services: every key of `config_api.txt`,
what it does and its default, and how the LINDAT endpoints are chosen.

On this page: [config_api.txt](#config_apitxt) · [stage 4 output flags](#stage-4-output-flags) ·
[backing service endpoints](#backing-service-endpoints)

[config_api.txt](../config_api.txt) is the one file: every stage script
starts with `source config_api.txt`, and `run_pipeline.py` reads the same file, so Python and Bash always agree on
the paths. The service's own settings (port, CORS, the limits) are environment variables, listed in
[service/README.md, Configuration (environment)](../service/README.md#configuration-environment) and
[Limits](../service/README.md#limits); [`.env.example`](../.env.example) is the complete ledger.

## `config_api.txt`

The file as shipped, grouped, with its comments shortened:

```bash
# Paths
OUTPUT_DIR="./data_samples"                       # destination for results (the samples, by default)
INPUT_TABLES_DIR="$OUTPUT_DIR/DOC_LINE_CATEG"     # input tables (.csv, .xlsx) and .txt: ocr-postprocess's DOC_LINE_CATEG/
SKIP_UNTRUSTWORTHY_LINES="${SKIP_UNTRUSTWORTHY_LINES:-false}"  # true: leave out rows whose categ is Trash, Garbage or Inverted (#72)

WORK_DIR="./TEMP"                                 # working directory for intermediate files

LOG_FILE="$OUTPUT_DIR/processing.log"
CONLLU_INPUT_DIR="$OUTPUT_DIR/UDP"
TEMP_TXT_DIR="./TEMP/TXT_EXTRACT"                 # stage 1: <doc>.txt and <doc>.rows.tsv (#38)
CHUNK_DIR="./TEMP/CHUNKS"

TSV_INPUT_DIR="$OUTPUT_DIR/NE"
SUMMARY_OUTPUT_DIR="$OUTPUT_DIR/UDP_NE"

TEITOK_OUTPUT_DIR="$OUTPUT_DIR/TEITOK"
INPUT_ALTO_DIR="$OUTPUT_DIR/ALTO"                 # source ALTO XML files, for TEITOK coordinates

PARADATA_DIR="$OUTPUT_DIR/paradata"

# Backing services (atrium-project#63). Environment wins, this file is the default:
# see "Backing service endpoints" below for why the ${VAR:-...} form is required.
UDPIPE_URL="${UDPIPE_URL:-https://lindat.mff.cuni.cz/services/udpipe/api/process}"
NAMETAG_URL="${NAMETAG_URL:-https://lindat.mff.cuni.cz/services/nametag/api/recognize}"

MODEL_UDPIPE="czech-pdt-ud-2.15-241121"
MODEL_NAMETAG="nametag3-multilingual-onto-260521"

TIMEOUT=60                     # API call timeout in seconds
MAX_RETRIES=5                  # number of retries for failed API calls
BACKOFF_FACTOR=1.5
WORD_CHUNK_LIMIT=900           # word limit per UDPipe call

SAVE_CSV=true                  # write the token-level summary CSV
SAVE_CONLLU_NE=true            # keep the merged CoNLL-U with NER in MISC
SAVE_TEITOK=true               # write TEITOK XML

# Image options (TEITOK coordinates)
INPUT_PAGES_DIR=""             # page images <doc_id>-<N>.<png|jpg|tif>: scale bboxes to them
IMAGE_DPI=""                   # no images: scale from the ALTO MeasurementUnit (or a record's pt) to this DPI
ALTO_DPI=""                    # ... and for pixel-unit ALTO, the DPI the ALTO was made at
BBOX_ORIGIN="${BBOX_ORIGIN:-page}"                # page (TEITOK norm) | printspace (images cropped to PrintSpace)
REGENERATE_TEITOK="${REGENERATE_TEITOK:-false}"   # true: rewrite existing .teitok.xml instead of resuming

# flexiconv (api_flexiconv.sh)
INPUT_DOCS_DIR="$OUTPUT_DIR/DOCS"                 # documents to convert
TEITOK_FLEXICONV_DIR="$TEITOK_OUTPUT_DIR/flexiconv"  # its TEITOK profile, outside stage 4's gate
FLEXICONV_FORCE=false                             # re-convert documents whose output exists
FLEXICONV_ANNOTATE="${FLEXICONV_ANNOTATE:-false}" # annotate the converted documents too
FLEXICONV_FORMATS="pdf docx odt rtf html htm md txt epub tei conllu vert folia srt xml hocr"

# run_pipeline.py
FAIL_ON_EMPTY=true                                # a stage that processed nothing fails the run
TEITOK_ENRICHMENT="${TEITOK_ENRICHMENT:-false}"   # opt-in record projection (atrium-project#70)
```

The keys written as `${VAR:-default}` can be set for one run from the environment without editing the file
(`BBOX_ORIGIN=printspace bash api_4_stats.sh`, `REGENERATE_TEITOK=true bash api_4_stats.sh`); a bare assignment
would overwrite the environment's value when the stage sources the file.

`run_pipeline.py` also reads `SKIP_<STAGE>=true` keys (`SKIP_MANIFEST`, `SKIP_UDP`, `SKIP_NT`, `SKIP_STATS`,
`SKIP_PROJECT`, and `SKIP_FLEXICONV` under `--with-flexiconv`), which are not in the shipped file: the equivalents
of its `--skip-<stage>` flags
([Resume / checkpoint recovery](usage.md#resume--checkpoint-recovery)). `TEITOK_ENRICHMENT=true` adds a `project`
stage after `stats` ([record projection](reference/teitok.md#record-projection-onto-teitok-opt-in)).

`TIMEOUT`, `MAX_RETRIES` and `WORD_CHUNK_LIMIT` are limits (atrium-project#53). For an API job each is also an
environment setting (`LINDAT_TIMEOUT_S`, `LINDAT_MAX_RETRIES` and `WORD_CHUNK_LIMIT`), which wins over this file, and
`GET /info` reports the value in force; see [service/README.md, Limits](../service/README.md#limits) for every limit
of the service.

## Stage 4 output flags

The behaviour of stage 4 is controlled by these keys of `config_api.txt`:

| Variable            | Description                                                                                                                                                                                                                                                                        | Default   |
|---------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------|
| `SAVE_CONLLU_NE`    | Keep the enriched CoNLL-U with NER in the `MISC` field.                                                                                                                                                                                                                            | `true`    |
| `SAVE_CSV`          | Write the token-level summary CSV per document.                                                                                                                                                                                                                                    | `true`    |
| `SAVE_TEITOK`       | Write TEITOK-style TEI XML with bounding boxes and NER spans. Without a layout (`INPUT_ALTO_DIR` unset, no converted file) TEITOK XML is still produced, with the table's pages and lines but no bboxes. A file that fails the output contract stops the stage with exit code `5`. | `true`    |
| `INPUT_PAGES_DIR`   | Directory of per-page images (`<doc_id>-N.png`). When set, bbox coordinates are scaled to match the actual image resolution. Leave empty to write raw ALTO pixel values.                                                                                                           | *(empty)* |
| `IMAGE_DPI`         | Without page images: scale from the ALTO `MeasurementUnit` (`inch1200`, `mm10`), or from a born-digital record's points, to this DPI. Empty: no scaling.                                                                                                                           | *(empty)* |
| `ALTO_DPI`          | With `IMAGE_DPI` and pixel-unit ALTO: the DPI the ALTO was made at.                                                                                                                                                                                                                | *(empty)* |
| `BBOX_ORIGIN`       | `page`: bboxes measured from the page's top-left corner (the TEITOK norm). `printspace`: measured from the ALTO PrintSpace, with a PrintSpace-sized `<surface>`; only for page images cropped to the print area.                                                                   | `page`    |
| `REGENERATE_TEITOK` | `true`: delete and rewrite each document's `.teitok.xml` instead of skipping it on a resumed run (use once after a TEITOK format change).                                                                                                                                          | `false`   |

How the scale and the origin are applied:
[ALTO-to-TEITOK XML generation and coordinate alignment](how-it-works.md#alto-to-teitok-xml-generation-and-coordinate-alignment).

## Backing service endpoints

`UDPIPE_URL` and `NAMETAG_URL` are **attachable** (12-factor IV): point them at a self-hosted UDPipe 2 / NameTag 3
instance, or a local stub, without touching code. Precedence, highest first:

1. **`--url`** on `call_udpipe.py` / `call_nametag.py`.
2. **The environment**: `UDPIPE_URL` / `NAMETAG_URL` exported by docker compose `environment:`, a k8s `env:` block,
   or the shell.
3. **[config_api.txt](../config_api.txt)**, which supplies the LINDAT defaults.

Both keys must be written in the `${UDPIPE_URL:-https://…}` form shown above. A bare assignment breaks the first two
tiers: every stage script begins with `source config_api.txt`, and bash preserves the export attribute of an
already-exported variable, so a plain `UDPIPE_URL="https://…"` silently overwrites *and re-exports* the value the
deployment set; the helper scripts would then read this file's endpoint rather than the operator's.

The `/info` endpoint and the `?deep=true` health probe resolve the same precedence, so they always report and probe
the endpoint the pipeline uses. For the service, the two variables are listed with the rest of its environment in
[service/README.md, Configuration (environment)](../service/README.md#configuration-environment).
