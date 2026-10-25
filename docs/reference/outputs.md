# Output files

For users of the command-line pipeline who need to find a file or free disk space: what each stage writes, where,
and what can be deleted afterwards. The service returns the same files in its JSON envelope or as a ZIP of the
workspace ([service/README.md, JSON envelope](../../service/README.md#json-envelope)); the TEITOK file itself is
described in the [TEITOK reference](teitok.md).

On this page: [stage 4 inputs and outputs](#stage-4-inputs-and-outputs) · [output structure](#output-structure) ·
[TEMP/, the intermediate files](#temp-intermediate-working-files)

## Stage 4: inputs and outputs

* **Input 1:** `OUTPUT_DIR/UDP/*.conllu`: per-document CoNLL-U files containing morphology and syntax.
* **Input 2:** `OUTPUT_DIR/NE/*/*.tsv`: per-page TSV files containing named-entity annotations.
* **Input 2b:** `OUTPUT_DIR/UDP/<doc_id>.rows.tsv` (else `TEMP_TXT_DIR/<doc_id>.rows.tsv`): the page and line of
  every token; `page_id` in the CSVs, the summary's pages, entity pages and the TEITOK pages come from it (or from
  the layout, where there is one).
* **Input 3 (optional):** `INPUT_ALTO_DIR/*.alto.xml`: source ALTO XML files used during TEITOK conversion to
  provide spatial bounding box coordinates for each token.
* **Input 4 (optional):** `INPUT_PAGES_DIR/<doc_id>-N.png`: per-page facsimile images. When specified, the pipeline
  reads their pixel size from the file headers to compute the scale factors (sx, sy). If omitted, the ALTO
  coordinates are written as they are (scale 1.0), or scaled by `IMAGE_DPI`.
* **Output 1:** `OUTPUT_DIR/summary_ne_counts.csv`: global table of aggregated named-entity statistics across all
  documents.
* **Output 2:** `OUTPUT_DIR/UDP_NE/<doc_id>/<doc_id>.csv`: per-document CSV tables with tokens, lemmas, and
  human-readable NE explanations.
* **Output 3 (optional):** `OUTPUT_DIR/UDP_NE/<doc_id>/<doc_id>.conllu`: final CoNLL-U files with NER tags in the
  `MISC` column.
* **Output 4 (optional):** `OUTPUT_DIR/TEITOK/<doc_id>.teitok.xml`: TEITOK XML files for a TEITOK project
  (`xmlfiles/<doc_id>.xml`), flexiconv/flexipipe and facsimile viewing ([how it works](../how-it-works.md#teitok-xml-the-output-format)).

The optional outputs and the coordinates are switched by flags in `config_api.txt`:
[Stage 4 output flags](../configuration.md#stage-4-output-flags). With `--document-json`, stage 4 also adds its
entities to the ATRIUM document record ([paradata and the record](paradata.md#document-record-schema)).

## Output structure

After the pipeline has run, the output directory (`OUTPUT_DIR`, `./data_samples` by default) holds the inputs it
was given beside what the stages wrote:

```
<OUTPUT_DIR>
├── DOC_LINE_CATEG/            # input: the line tables (INPUT_TABLES_DIR)
│   └── <doc_id>.csv
├── ALTO/                      # input, optional: the layout (INPUT_ALTO_DIR)
│   └── <doc_id>.alto.xml
├── pages/                     # input, optional: page images, when INPUT_PAGES_DIR points here
│   ├── <doc_id>-1.png
│   └── ...
├── manifest.tsv               # stage 1
├── UDP/                       # stage 2
│   ├── <doc_id>.conllu
│   ├── <doc_id>.rows.tsv
│   └── ...
├── NE/                        # stage 3
│   ├── <doc_id>
│   │   ├── <doc_id>-<page_num>.tsv
│   │   └── ...
│   └── ...
├── UDP_NE/                    # stage 4
│   ├── <doc_id>
│   │   ├── <doc_id>.csv
│   │   └── <doc_id>.conllu
│   └── ...
├── TEITOK/                    # stage 4 (flexiconv's conversions go to TEITOK/flexiconv/)
│   ├── <doc_id>.teitok.xml
│   └── ...
├── summary_ne_counts.csv      # stage 4
├── paradata/                  # every stage: YYMMDD-HHmmss_nlp-enrich.json
└── processing.log
```

The combined output `summary_ne_counts.csv` contains aggregated named-entity statistics across all processed pages.
It is written by stage 4 (`api_4_stats.sh`). This repository's `data_samples/` only ships the three synthetic demo
documents (`CTX00000000{1,2,3}`), so no `summary_ne_counts.csv` is committed: the file is the output of a real run,
not a sample bundled here.

Example output directories:

* [UDP](../../data_samples/UDP): per-document CoNLL-U files, with their rows files.
* [NE](../../data_samples/NE): per-page TSV files with NE annotations.
* [UDP_NE](../../data_samples/UDP_NE): per-document CSV tables with NE tags and UDPipe feature columns, plus CoNLL-U
  files with NE annotations, per document.
* [TEITOK](../../data_samples/TEITOK): per-document TEITOK XML files combining UD linguistic annotations and NER
  spans with bounding boxes aligned from the source ALTO XML.
* [manifest.tsv](../../data_samples/manifest.tsv), with **file**, **page** (count) and **path** columns.

The committed `NE/` files carry OntoNotes labels, while `UDP_NE/` and `TEITOK/` were produced with the Czech CNEC
model before the default changed; a sample refresh on LINDAT aligns them.

You can delete `UDP/` from `<OUTPUT_DIR>/` if you no longer need the raw CoNLL-U files: the final CoNLL-U files with
NER features are in `<OUTPUT_DIR>/UDP_NE/`. Keep it, with its rows files, while a stage may still be re-run: stages
3 and 4 read it.

## TEMP/: intermediate working files

`TEMP/` (set by `WORK_DIR` in [config_api.txt](../../config_api.txt)) holds transient artefacts that are only
needed during processing and can be deleted once the full pipeline has completed successfully:

```
TEMP/
├── TXT_EXTRACT/                 # stage 1 (TEMP_TXT_DIR)
│   ├── <doc_id>.txt             # the document's text, one line per table row
│   └── <doc_id>.rows.tsv        # page, line, page label and text of every line
├── CHUNKS/                      # stage 2 (CHUNK_DIR)
│   ├── <doc_id>/
│   │   ├── chunk_0.txt          # OCR-line-preserving text fragment sent to UDPipe
│   │   ├── chunk_1.txt
│   │   └── …
│   └── …
└── api_jobs/                    # the service: one workspace per request, removed after it
```

`CHUNKS/` is produced by [api_util/chunk.py](../../api_util/chunk.py), which splits documents that exceed
`WORD_CHUNK_LIMIT` (900 words by default) into sentence-boundary-aware fragments before each UDPipe API call. Each
chunk file preserves the original OCR line structure (one line per row) so that UDPipe receives correct
sentence-boundary signals between text lines. The per-chunk plain-text files carry no provenance value after the
CoNLL-U files have been merged and validated; they are not tracked by the paradata logger. Stage 2 copies each
rows file next to its CoNLL-U in `UDP/`, so `TXT_EXTRACT/` is not needed once stage 2 has finished. Stage 3 keeps
no raw NameTag responses: it writes the per-page TSV files directly.

If disk space is a concern you can safely delete `TEMP/` once `<OUTPUT_DIR>/UDP/` and `<OUTPUT_DIR>/NE/` have been
fully populated and stage 4 has completed without errors. The paradata JSONs in `<OUTPUT_DIR>/paradata/` and the
`processing.log` are the only runtime records worth keeping long-term ([paradata](paradata.md)). If you do not
plan to rerun any part of the pipeline, you can also delete [manifest.tsv](../../data_samples/manifest.tsv).
