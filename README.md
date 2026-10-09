<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.8+-blue.svg" title="Python Version"></a>
  <a href="https://lindat.mff.cuni.cz/services/udpipe/api-reference.php"><img src="https://img.shields.io/badge/API-UDPipe%202-0055A4.svg" title="UDPipe 2 API (Lindat)"></a>
  <a href="https://lindat.mff.cuni.cz/services/nametag/api-reference.php"><img src="https://img.shields.io/badge/API-NameTag%203-0055A4.svg" title="NameTag 3 API (Lindat)"></a>
  <a href="https://opensource.org/license/mit/"><img src="https://img.shields.io/github/license/ufal/atrium-nlp-enrich" title="MIT License"></a>
  <a href="https://atrium-research.eu/"><img src="https://img.shields.io/badge/funded%20by-ATRIUM-8A2BE2.svg" title="ATRIUM Project"></a>
</p>

---

# 📦 NLP Enrichment of text: UDPipe, NameTag and TEITOK

This project provides a workflow for processing text stored in CSV (XLSX) with NLP services. It takes ordered text
and extracts high-level linguistic features like Named Entities (NER) with tags and CONLL-U files with
lemmas & part-of-speech tags, and writes them, with the page layout, as one TEITOK XML file per document.

---

> [!CAUTION]
> This repository is a follow-up to the OCR-postprocessing [GitHub repository](https://github.com/ufal/atrium-ocr-postprocess),
> a part of ATRIUM project dedicated to the ALTO-2-TXT workflow and the collection of statistics from the text content
> of the documents (text and bounding boxes ordered by LayoutReader) recorded in CSV (XLSX) tables as a `text` column [^2].
>
> **Keyword extraction is no longer part of this repository** (since v1.0.0). It moved to
> [atrium-keyword-extract](https://github.com/ufal/atrium-keyword-extract) (statistical keywords, `POST /extract_keywords`).
> The LLM semantic-enrichment code left with the `atrium-llm-enrich` split (see [Where things went](#where-things-went)).

## Table of contents

- [TEITOK XML — Unified Output Format](#teitok-xml--unified-output-format)
  - [The format and the standards it builds on](#the-format-and-the-standards-it-builds-on)
  - [How a TEITOK document is composed](#how-a-teitok-document-is-composed)
  - [Importing into a TEITOK project](#importing-into-a-teitok-project)
  - [Tools that generate or read TEITOK](#tools-that-generate-or-read-teitok) · [Pitfalls](#pitfalls)
- [ ⚙️ Setup](#-setup)
- [Workflow Stages](#workflow-stages)
  - [Step 1: Prepare CSVs with texts from Page-Specific ALTOs](#-step-1-prepare-csvs-with-texts-from-page-specific-altos)
  - [Step 2: Extract NER and CONLL-U](#-step-2-extract-ner-and-conll-u)
    - [Configuration ⚙️](#configuration-)
    - [Execution Pipeline](#execution-pipeline)
      - [I. Generate Manifest](#1-generate-manifest)
      - [II. UDPipe Processing (Morphology & Syntax)](#2-udpipe-processing-morphology--syntax)
      - [III. NameTag Processing (NER tags)](#3-nametag-processing-ner-tags)
      - [IV. Generate Statistics](#4-generate-statistics)
- [Output Structure](#output-structure)
- [EXTRA: Converting Other Input Formats with flexiconv](#extra-converting-other-input-formats-with-flexiconv)
- [EXTRA: REST API Service](#extra-rest-api-service)
- [Paradata Logs](#paradata-logs)
  - [`<OUTPUT_DIR>/paradata/` — structured run logs 📂](#output_dirparadata--structured-run-logs-)
  - [`<OUTPUT_DIR>/processing.log` — human-readable runtime log 📄](#output_dirprocessinglog--human-readable-runtime-log-)
  - [`TEMP/` — intermediate working files 📂](#temp--intermediate-working-files-)
  - [Document record schema 📑](#document-record-schema-)
  - [One-command pipeline run (`run_pipeline.py`)](#one-command-pipeline-run-run_pipelinepy)
- [Where things went](#where-things-went)
- [Acknowledgements](#acknowledgements-)

## TEITOK XML — Unified Output Format

**TEITOK XML** (`.teitok.xml`) is the primary enriched output format of this pipeline. It is the
[TEI](https://tei-c.org/)-based XML format of the [TEITOK](https://www.teitok.org/) corpus
platform, carrying spatially-grounded linguistic and NER annotations produced by UDPipe and
NameTag. The files follow the conventions the TEITOK tools themselves read and write
([flexiconv](https://github.com/ufal/flexiconv), [flexipipe](https://github.com/ufal/flexipipe),
teitok-tools), so they can go straight into a TEITOK project (see
[Importing into a TEITOK project](#importing-into-a-teitok-project)) and be read by flexiconv
and flexipipe. What each tool keeps on a round trip is listed there: spacing survives all of
them; two upstream readers still lose something (multi-word tokens in flexiconv, dependency
heads in flexipipe).

Each document in the collection is serialised as a single `.teitok.xml` file that integrates four
layers of information in a consistent, machine-readable structure:

| Layer                   | Content                                                                                                                                                                                                                     |
|-------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Layout**              | Page, text-block, and line boundaries with pixel bounding boxes from the source ALTO XML (page origin), scaled to the stored page images when those are available; without a layout, the pages and lines of the input table |
| **Morphology & Syntax** | Per-token lemma, UPOS/XPOS tags, morphological features, and dependency relations produced by UDPipe 2; multi-word tokens ("abych" = aby + bych) as one surface `<tok>` with `<dtok>` words                                 |
| **Named Entities**      | Entity spans with a coarse category (`PER`, `ORG`, `LOC`, `MISC`) and the raw NameTag label in `@onto` (OntoNotes, the default model), `@cnec` (CNEC 2.0) or `@archaeo` (the archaeological model)                          |
| **Facsimile links**     | `<surface>` elements in `<facsimile>` that tie each page to its companion image, enabling TEITOK's side-by-side text/image view                                                                                             |

### Why TEITOK XML?

Storing all enrichment layers in a single interoperable format offers several practical advantages
over keeping CoNLL-U, TSV, and image files in separate silos:

- 🔍 **Full-text and attribute search** — TEITOK's built-in CQL/XPATH query engine lets users
  search across lemmas, NER types, POS tags, and raw text simultaneously.
- 🏷 **Named entity access** — entity spans (`<name type="PER" onto="PERSON">`) are first-class XML
  elements: queryable, stylable, and exportable independently of the surrounding tokens.
- 🖱 **Mouseover information** — hovering over any token in the TEITOK GUI surfaces its lemma,
  morphological features, and dependency relation without leaving the page view.
- 🖼 **Page visualisation with spatial overlays** — bounding box coordinates on every `<tok>`,
  `<lb>`, and `<div>` are used by TEITOK's facsimile viewer to overlay text highlights directly
  onto the scanned page image, making OCR quality immediately visible.
- 📐 **Layout-aware structure** — text blocks (`<div type="TextBlock">`), lines (`<lb>`),
  and graphical elements (`<figure>`) preserve the physical layout of the original document.
- 🔗 **Interoperability** — TEI/XML is a widely adopted standard in digital humanities; the files
  can be ingested by other TEI-aware tools (e.g. eXist-db, Oxygen XML Editor) without conversion.

### The format and the standards it builds on

TEITOK XML is not a schema of its own; it layers three sets of conventions, and this repository
pins one profile of them:

- **TEI P5** ([Guidelines](https://tei-c.org/guidelines/p5/)) gives the document skeleton:
  `teiHeader` (file, encoding and revision description), `facsimile`/`surface`/`graphic` for the
  page images, `text`/`body`/`div` for text blocks, `pb`/`lb` for page and line beginnings, `s`
  for sentences, `name` for named entities and `figure` for graphical regions.
- **TEITOK** (the corpus platform, [teitok.org](https://www.teitok.org/)) adds the tokenized
  layer it searches and displays: every token is a `<tok>` element inline in the running text, a
  multi-word token keeps its surface form with one `<dtok>` per syntactic word, the annotation
  lives in token attributes, and any element can carry `@bbox="x1 y1 x2 y2"` in the pixels of its
  page image. TEITOK files carry no TEI namespace (`xmlnsoff` keeps the URI without declaring it)
  and use plain `@id`s.
- **Annotation vocabularies** are those of the tools that produced them: Universal Dependencies
  (CoNLL-U) for `upos`, `feats`, `deprel` and `head`; the UDPipe model's own tag set for `xpos`;
  the NameTag model's entity labels (OntoNotes 5 by default, CNEC 2.0, or the archaeological types
  of #7) in `@onto`/`@cnec`/`@archaeo`, mapped to four coarse types in `@type` (`PER`, `ORG`,
  `LOC`, `MISC`) by [api_util/ner_types.py](api_util/ner_types.py) 📎; a label no table knows
  becomes `type="MISC"` with the raw label in `@label`.
- **Format 2** is this repository's profile: [schemas/teitok/teitok.xsd](schemas/teitok/teitok.xsd) 📎
  plus the contract checks below, stamped `version="teitok-2"` in `appInfo`. The hub's document
  record ([atrium_document.schema.json](atrium_document.schema.json) 📎) points into it by id.

### TEITOK XML structure at a glance

An excerpt of [data_samples/TEITOK/CTX000000001.teitok.xml](data_samples/TEITOK/CTX000000001.teitok.xml) 📎
(attributes shortened; the header is described below):

```xml
<TEI xmlnsoff="http://www.tei-c.org/ns/1.0" lang="cs">
  <teiHeader> ... </teiHeader>
  <facsimile>
    <surface id="facs-1" lrx="1654" lry="2339">
      <graphic url="CTX000000001-1.png"/>
    </surface>
  </facsimile>
  <text><body>
    <pb n="1" id="pb-1" facs="CTX000000001-1.png" corresp="#facs-1" bbox="0 0 1654 2339"/>
    <div type="TextBlock" id="b-1.1" bbox="220 160 1420 280">
      <s id="s-1" text="Výzkumná zpráva č. 1/2024 — Hradiště u Horní Mezí ...">
        <lb id="lb-1.1" bbox="220 160 1320 200"/><tok id="w-1" type="w" ord="1" lemma="výzkumný" upos="ADJ" head="w-2" deprel="amod" bbox="220 160 420 194">Výzkumná</tok> <tok id="w-2" ...>zpráva</tok> <tok id="w-3" ... join="right" bbox="...">č</tok><tok id="w-4" type="pc" ...>.</tok> ...
        <name id="n-3" type="LOC" cnec="gu" sameAs="#w-9 #w-10 #w-11 #w-12"><tok id="w-9" ...>Hradiště</tok> ... <tok id="w-12" ...>Mezí</tok>
          </name><lb id="lb-1.2" bbox="220 210 1220 250"/><tok id="w-13" ...>Terénní</tok> ...
      </s>
    </div>
  </body></text>
</TEI>
```

The conventions, which are the same as the TEITOK tools' (full list:
[schemas/teitok/README.md](schemas/teitok/README.md) 📎):

- **Namespace-off root** (`xmlnsoff`, plain `@id`). `lang` comes from the ALTO `LANG`
  attributes, else from the UDPipe model name; it is omitted when neither says.
- **Spacing is text-faithful**: tokens sit inline, a space between `</tok>` and the next `<tok>`
  is a space in the text, and no whitespace means `SpaceAfter=No` ("č." above).
  `join="right"` marks the same thing for TEI-P5 tools.
- **Ids** are local to the document: `w-N` tokens (`w-N.K` for the `<dtok>` words of a
  multi-word token), `s-N`, `n-N` entities, `facs-P` surfaces, `pb-P`, `lb-P.L`, `b-P.K`. `@head`
  points at the head word's id. The document record (`--document-json`) uses the same ids:
  `entities[].teitok_ref` = `n-N` and `pages[].teitok_surface` = `facs-P`.
- **Bounding boxes** are `x1 y1 x2 y2` pixels measured from the page's top-left corner, and
  `<surface lrx lry>` (and `pb@bbox="0 0 W H"`, as flexiconv writes it) gives the extent they
  are measured in (see
  [ALTO-to-TEITOK XML Generation and Coordinate Alignment](#alto-to-teitok-xml-generation-and-coordinate-alignment)).
  Punctuation that UDPipe splits off an OCR word ("č." → "č" + ".") has no box of its own;
  the word keeps the OCR string's box, as in flexiconv's ALTO and hOCR import.
- **Pages come from the layout** (ALTO, a converted file, or the table's `page_num`), never
  from UDPipe's chunks. A sentence (or an entity) that runs over a page break keeps its
  tokens together and gets the `<pb/>` inside it, before the first token of the new page —
  the anchor xmltokenizer and flexiconv allow there. `pb@n` is the page label (`"I"`, `"7a"`);
  `pb@facs`/`@corresp` appear only for a page that has an image (a `<surface>`).
- **Header**: `notesStmt/note[@n="orgfile"]` names the source ALTO file, `appInfo` names the
  writer (`atrium-nlp-enrich`, format `teitok-2`) and the UDPipe/NameTag models, and
  `revisionDesc/change@type` records the phases (`converted`, `tagged`/`parsed`, `ner`).

Every file is checked before the stage finishes: against
[schemas/teitok/teitok.xsd](schemas/teitok/teitok.xsd) 📎, and — for files in the current format —
for unique ids, resolvable `sameAs`/`corresp`/`head` references and the page rules (`pb-K`
increasing, `lb-P.L` on page P). A file that fails stops the stage with exit code `5`.
`tests/test_teitok_conformance.py` reads the writer's output the way flexiconv does to keep it
TEITOK-conformant.

> [!NOTE]
> TEITOK XML is generated by Step 4 of this pipeline (`api_4_stats.sh`) when
> `SAVE_TEITOK=true`. The source ALTO XML files must be present in `INPUT_ALTO_DIR`
> for spatial coordinates to be included. Without a layout, TEITOK XML is still produced:
> its pages and lines are those of the input table (`<pb>` per page, `<lb>` per line), without
> bounding boxes and without a facsimile. If your documents are not in
> ALTO format, see [EXTRA: Converting Other Input Formats with flexiconv](#extra-converting-other-input-formats-with-flexiconv).

> [!IMPORTANT]
> The format changed in 2026-09 ("format 2": inline spacing, `<dtok>`, `w-N` ids, page-origin
> bboxes). A resumed run keeps existing `.teitok.xml` files. Rewrite them once, so that old and new
> files do not mix: `REGENERATE_TEITOK=true bash api_4_stats.sh`, or set it in `config_api.txt`.
>
> **Pages changed after v0.21.0** (issue #38): runs up to v0.21.0 counted UDPipe's ~900-word chunks
> as pages in `NE/<doc>-N.tsv`, `summary_ne_counts.csv`, `UDP_NE/<doc>.csv` and the document record,
> and left a sentence that runs over a page on its first page in the TEITOK. To correct a collection:
> re-run it from stage 1 (which writes the rows files pages now come from); or, keeping the
> CoNLL-U and NE files, rebuild the rows files with stage 1, copy each `TEMP_TXT_DIR/<doc>.rows.tsv`
> to `UDP/`, re-split the NE files by page without calling NameTag
> (`python3 api_util/page_rows.py resplit --conllu-dir <OUTPUT_DIR>/UDP --ne-dir <OUTPUT_DIR>/NE`),
> delete `UDP_NE/<doc>/<doc>.csv` and run stage 4 with `REGENERATE_TEITOK=true`. In-place document
> records keep entities under their old pages: re-seed them from the record before nlp-enrich.

### How a TEITOK document is composed

Nothing in the default pipeline edits TEITOK in place. Stage 4 builds each file in one pass from
the formats the earlier stages leave on disk, so every element can be traced to one of them (the
opt-in [record projection](#record-projection-onto-teitok-opt-in) is the one later writer, and
it touches only the header and `pb/@ana`):

| Source (stage)                                                                                                                                                      | Format on disk                                                                                                                           | Becomes in the TEITOK file                                                                                                                                                                                                                                        |
|---------------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Line table: ocr-postprocess `DOC_LINE_CATEG/<doc>.csv`, or any CSV/XLSX with the same columns, or the rows of a flexiconv conversion (stage 1, `api_1_manifest.sh`) | `file`, `page_num`, `line_num`, `text` → `TEMP_TXT_DIR/<doc>.txt` (one line per row) and `<doc>.rows.tsv` (page, line, page label, text) | the text itself; the pages (`<pb n>` = the table's `page_label`, when it has that column) and lines of every token; without a layout, also the `<pb>`/`<lb>` structure                                                                                            |
| UDPipe 2 (stage 2, `api_2_udp.sh`)                                                                                                                                  | `UDP/<doc>.conllu` (+ the rows file kept beside it; `# chunk_start` marks UDPipe's ~900-word request chunks, which are not pages)        | `<s id text>` per sentence; `<tok>` per token with `lemma`, `upos`, `xpos`, `feats`, `head`, `deprel`, `ord`; `<dtok>` for the words of a multi-word token; `SpaceAfter=No` as no whitespace (and `join="right"`)                                                 |
| NameTag 3 (stage 3, `api_3_nt.sh`)                                                                                                                                  | IOB TSV per page, `NE/<doc>/<doc>-P.tsv`, merged by stage 4 into `UDP_NE/<doc>/<doc>.conllu`                                             | `<name id type sameAs>` around the entity's tokens, the raw label in `@onto`/`@cnec`/`@archaeo`                                                                                                                                                                   |
| Layout (stage 4, `api_4_stats.sh`): the ALTO file in `INPUT_ALTO_DIR`; else a flexiconv conversion in `TEITOK_FLEXICONV_DIR` (`FLEXICONV_ANNOTATE=true`); else none | ALTO `Page`/`PrintSpace`/`TextBlock`/`TextLine`/`String` (+ `Illustration`, `GraphicalElement`); or TEITOK `pb`/`lb`/`tok@bbox`          | `<facsimile>` with one `<surface lrx lry>` and `<graphic url>` per page; `<pb n id facs corresp bbox>`; `<div type="TextBlock" bbox>`; `<lb bbox>`; `<figure type bbox>`; `@bbox` on every token aligned to an OCR string (tokens are matched to strings by text) |
| Page images (`INPUT_PAGES_DIR`), or `IMAGE_DPI`                                                                                                                     | PNG, JPEG or TIFF named `<doc_id>-<N>.<ext>`                                                                                             | the scale from layout units to image pixels, `<surface lrx lry>` and the `graphic@url`/`pb@facs` names                                                                                                                                                            |
| Provenance                                                                                                                                                          | ALTO `Description`, the models in `config_api.txt`, the run date                                                                         | `teiHeader`: `note[@n="orgfile"]`, `appInfo` (writer + format, UDPipe/NameTag models, OCR software), `revisionDesc/change` (`converted`, `tagged`/`parsed`, `ner`)                                                                                                |
| Document record (`--document-json`)                                                                                                                                 | `atrium_document` JSON                                                                                                                   | nothing by default: the record points into the file (`entities[].teitok_ref` = `n-N`, `pages[].teitok_surface` = `facs-P`); the opt-in projection adds page categories and the record's controlled keywords to the header                                         |

The line table can come from any input ocr-postprocess reads: ALTO, the other OCR formats (PAGE
XML, hOCR, ABBYY FineReader XML, DjVuXML, Tesseract TSV, OCR JSON), PDF, office and text files (its
[input formats reference](https://github.com/ufal/atrium-ocr-postprocess/blob/master/docs/text_inputs.md#formats-and-their-standards)).
For every input but ALTO the table carries text and pages only. The boxes then come from a flexiconv
conversion of the same document (PAGE XML, hOCR), or there are none.

The writer is [api_util/teitok_alto.py](api_util/teitok_alto.py) 📎 (`write_teitok_merged`, called by
`summarize_nt_udp.py`); the gate is [api_util/validate_teitok_xml.py](api_util/validate_teitok_xml.py) 📎
(`contract` profile). Keywords, TEATER topics, page categories and line quality are not written
into TEITOK by default: they live in the document record (the three-format decision recorded on
ufal/atrium-project#24, 2026-08-01; the AMČR storage contract keeps page classification and line
quality "only in the record"). The opt-in projection below writes page categories, TEATER
categories and the controlled keywords a record already carries, never line quality, and since
v1.0.0 it no longer computes keywords of its own.

### Record projection onto TEITOK (opt-in)

For TEITOK users who want the record's page-level facts in the file itself (ufal/flexiconv#1:
the page category and keywords; the LINDAT dataset), atrium-project#70 item 2 adds a
projection, **off by default**. [api_util/teitok_project.py](api_util/teitok_project.py) 📎
writes, in the header and `pb/@ana` only:

| From                                                                                     | Into the TEITOK file                                                                                                                                                                                                                                               |
|------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| page category (`pages[].category`, else `page_categories[P]`)                            | `<pb ana="#pcat-DRAW"/>`, and `encodingDesc/classDecl/taxonomy[@id="tax-page-category"]/category[@id="pcat-DRAW"]` with `@corresp` = the `atrium_vocab` concept URI and the definition in `catDesc`                                                                |
| TEATER/AMČR category (`enrichment.items[]`, keyword-extract's controlled kind)           | `profileDesc/textClass/keywords[@scheme="#tax-amcr-teater"][@resp="#app-kw-controlled"]/term[@type="teater-category"]`: `@ref` = the concept URIs of `teater_category_ids`, `@cert` = the highest confidence, `@corresp` = its pages; the meta sentinel is skipped |
| controlled keywords, cs and en                                                           | `keywords[@resp="#app-kw-controlled"][@lang]/term[@type="extracted-keyword"][@corresp]`                                                                                                                                                                            |
| statistical keywords (`keywords`, keyword-extract's statistical kind, atrium-project#73) | `keywords[@resp="#app-kw-statistical"][@scheme="#kw-<method>"]/term[@type="statistical-keyword"][@n=rank][@score]`: the document's list, and one more per page with `@corresp="#pb-K"`, at most 20 each                                                            |
| provenance                                                                               | `appInfo/application` with `@id` `app-pc`, `app-kw-controlled` or `app-kw-statistical` after the writer's own, `@ident` the program the record's stamp names for the block, and `revisionDesc/change[@type="enriched"]`                                            |

Pages resolve through `pages[].teitok_surface`, then `page_index`, then a numeric page key (`pb-K`),
then the `<pb n>` label; an enrichment item's page (its `## Page` label) through the record's page of
that label, then `<pb n>`, then as a number. A page that resolves to nothing is reported, not fatal.
Nothing inside `<s>`, `<tok>` or `<name>` changes, so `teitok_read`, `teitok_layout`, flexiconv's
reader and ocr-postprocess read the same text, and the writer's own header lines stay as they were.
The projection is idempotent (it replaces its own earlier output), refuses another document's
TEITOK (the `<title>` must be the record's `doc_id` or the id of its `source.filename`), and
validates its output with the `contract` profile before writing. The keywords come from the record only:
keyword-extract writes the statistical ones as `keywords` and the controlled ones as `enrichment`
(atrium-project#73). (Up to v1.0.0-beta the module also took a keywords.py CSV, `--kw-method` and
`--kw-csv`, and named its applications `app-llm-enrich` and `app-kw`; a re-projection removes those.)

```bash
# in the pipeline: a `project` stage after `stats` (reachable with --start-from project)
python3 run_pipeline.py --teitok-enrichment \
    --document-json CTX.document.json --document-json-out CTX.document.json
TEITOK_ENRICHMENT=true python3 run_pipeline.py      # or switch it on in config_api.txt

# on a finished record
python3 -m api_util.teitok_project --teitok TEITOK/CTX.teitok.xml --record CTX.document.json --in-place
curl -F file=@TEITOK/CTX.teitok.xml -F document_json=@CTX.document.json http://localhost:8000/project_record
```

The service takes `teitok_enrichment=true` on `/enrich`, `/enrich_text` and `/jobs`. A TEITOK
regeneration (`REGENERATE_TEITOK`, a stage-4 re-run) writes the file anew without the projection;
project again after it. Line-level anchoring (a keyword on its `<lb>`) is not done: an enrichment
stage's line numbers and the writer's `lb` numbering are not the same count.

### Importing into a TEITOK project

The files follow TEITOK's conventions, but a TEITOK project has a few of its own
(`xmlfiles/`, `Originals/`, `settings.xml`), and the upstream readers differ in what they keep:

- **File name.** A project keeps each document as `xmlfiles/<name>.xml`: copy
  `TEITOK/<doc_id>.teitok.xml` to `xmlfiles/<doc_id>.xml` (the `.teitok.xml` suffix is this
  pipeline's, not TEITOK's).
- **Original.** `note[@n="orgfile"]` names the file the document came from (the ALTO file, the
  input table, or the original a converted document was made from), without a directory. Put
  that file in the project's `Originals/`.
- **Attributes.** Tokens carry `lemma`, `upos`, `xpos`, `feats`, `head`, `deprel` and `ord`.
  teitok-tools' default tag attribute is `pos`: declare `xpos` (and the others you want to query
  or show) in the project's `settings.xml`.
- **Page images.** `pb@facs` and `<graphic url>` name the images (`<doc_id>-N.png` for ALTO
  documents, the converted file's own names otherwise); place them where the project's
  facsimile settings look.

What the TEITOK readers keep (flexiconv v0.3.10, the pinned version, is tested in
`tests/test_teitok_conformance.py` and `tests/test_teitok_pages.py`; flexipipe `73188c5` was
checked by hand on the committed samples, 2026-09-24):

| Reader                                  | Spacing (`SpaceAfter`) | Sentences, `<pb/>` inside `<s>` | Multi-word tokens (`<dtok>`)                | Dependency heads                                                           |
|-----------------------------------------|------------------------|---------------------------------|---------------------------------------------|----------------------------------------------------------------------------|
| flexiconv `load_teitok`                 | ✅                      | ✅                               | ❌ the surface token only, without its words | kept as the raw `@head` id                                                 |
| flexipipe `load_teitok` (Python loader) | ✅                      | ✅                               | ✅                                           | ❌ `head="w-N"` becomes token N of the *document*: wrong from sentence 2 on |
| this repo's `teitok_read.py`            | ✅                      | ✅ one row per page part         | ✅ surface form                              | not read                                                                   |

The two ❌ are upstream defects, recorded in issue #38 for an upstream report; `@ord` gives each word's
sentence-local number for a reader that needs it.

### Tools that generate or read TEITOK

| Tool                                                            | Role here                                                                                                                                    | Licence                         | Notes                                                                                                                                                                                  |
|-----------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| this pipeline's writer (`api_util/teitok_alto.py`)              | **generates** format 2 from the line table, CoNLL-U, NameTag output and a layout                                                             | MIT                             | the only writer in ATRIUM                                                                                                                                                              |
| [flexiconv](https://github.com/ufal/flexiconv) (pinned v0.3.10) | **converts** PDF, DOCX, ODT, RTF, HTML, Markdown, TXT, EPUB, PAGE XML, hOCR, ALTO, TEI … into TEITOK (`api_flexiconv.sh`); reads TEITOK back | GPL-3.0-or-later                | no `<s>`, no annotation; boxes only from layout formats (PAGE XML, hOCR, ALTO; PDF only in its `pdf=bbox` mode, which needs Poppler's `pdftotext`); CLI only, never in a service image |
| [flexipipe](https://github.com/ufal/flexipipe)                  | a UD pipeline (UDPipe and other backends) that can write and read TEITOK; not used                                                           | MIT                             | its Python TEITOK loader misreads `@head` (table above)                                                                                                                                |
| [xmltokenizer](https://github.com/ufal/xmltokenizer)            | tokenizes existing TEI/XML inline, keeping every element and character; not used (our text comes from OCR lines, not from existing markup)   | MIT                             | the library flexipipe uses for TEI input                                                                                                                                               |
| [teitok-tools](https://github.com/ufal/teitok-tools)            | the TEITOK platform's scripts, e.g. `udpipe2teitok.pl` (UDPipe-parsed TEITOK from raw text); used only to check conventions                  | none declared in the repository | what a project expects is under [Importing into a TEITOK project](#importing-into-a-teitok-project)                                                                                    |
| [flexicorp](https://github.com/ufal/flexicorp)                  | corpus query interface over TEITOK XML, CQP/CWB, Manatee, BlackLab …; a possible consumer                                                    | none declared in the repository | —                                                                                                                                                                                      |
| atrium-keyword-extract `api_util/teitok_read.py`                | **reads** TEITOK as line-level input for keyword extraction                                                                                  | MIT                             | `teitok_read.py` is vendored from here, pinned by hash (atrium-digital-convert vendors the same readers)                                                                               |
| atrium-ocr-postprocess `text_formats.read_tei`                  | **reads** TEITOK (and TEI) as a text input: every `<pb/>` a page, `<lb/>` lines                                                              | MIT                             | —                                                                                                                                                                                      |
| atrium-project `tools/e2e/e2e_assert.py --teitok-dir`           | **checks** that a document record's references resolve to the right elements and pages                                                       | none declared in the repository | strict for `teitok-2` files                                                                                                                                                            |

### Pitfalls

Each of these leaves a *valid* file that is wrong for its purpose — showing the text over the
page image — so the gate cannot catch them:

1. **Page-image names.** Images must be `<doc_id>-<N>.<png|jpg|jpeg|tif|tiff>` in
   `INPUT_PAGES_DIR` (a converted file's own `pb@facs` names also work). A page without one keeps
   its boxes in layout units and gets a guessed `<doc_id>-<N>.png` name; the writer warns
   (`[Warn] <doc>: no page image …`).
2. **ALTO units.** ALTO in `mm10` or `inch1200` needs `INPUT_PAGES_DIR` or `IMAGE_DPI`; without
   either the boxes stay in ALTO units (warned: `MeasurementUnit is mm10 …`).
3. **Origin.** `BBOX_ORIGIN=printspace` is only for page images cropped to the print space.
4. **Rescaling.** `/rescale` and `fix_teitok_bboxes.py` must target the size of the image the
   viewer shows, page by page.
5. **Stale files.** A resumed run keeps existing `.teitok.xml` files (`REGENERATE_TEITOK=false`),
   and files written before `8003051` (the page fix, after v0.21.0) carry the same `teitok-2`
   stamp: tell them apart by `<change type="converted" when="…">`, or regenerate everything.
6. **Two readers.** When the text comes from one reader (e.g. ocr-postprocess's table) and the
   layout from another (flexiconv), tokens get boxes only as far as the two agree; below 90 %
   aligned tokens the writer warns, and unaligned tokens have no box.
7. **flexiconv PDFs** carry no boxes and no page images by default, so no facsimile.
8. **Licence.** flexiconv is GPL-3.0-or-later: it runs as a CLI step; the REST service accepts its
   `.teitok.xml` output but never runs it.
9. **Vendored readers.** After changing `api_util/teitok_read.py` or `api_util/flexiconv_convert.py`,
   re-vendor them into atrium-keyword-extract and atrium-digital-convert (their `tests/test_vendored_teitok_parity.py` pin them).
10. **Upstream readers** lose `<dtok>` words (flexiconv) or misplace heads (flexipipe) — see the
    table in [Importing into a TEITOK project](#importing-into-a-teitok-project).
11. **No TEI namespace.** Tools that expect `http://www.tei-c.org/ns/1.0` need it added
    (`xmlnsoff` → `xmlns`) on their copy.
12. **New NE models.** Add their labels to `api_util/ner_types.py`; otherwise every entity is
    `type="MISC"`.
13. **Record references.** `lines[].teitok_ref` is not written yet; the hub E2E checks references
    strictly only for `teitok-2` files.
14. **Page numbers.** The writer numbers pages by their order in the ALTO file (`pb-1`, `facs-1`,
    the page-image name `<doc_id>-1`, the record's `pages[].teitok_surface`), and `pb@n` is the
    table's `page_label`, else that number. ocr-postprocess's ALTO methods number pages by
    `PHYSICAL_IMG_NR`, and its `DOC_LINE_CATEG` table has no `page_label`. When an ALTO file's
    `PHYSICAL_IMG_NR`s are not 1, 2, 3 … in order, the TEITOK file shows the ordinals, and the
    record gets this repo's `pages[]` rows under the ordinals beside ocr-postprocess's rows under
    the ALTO numbers. Name page images by the ordinal.

---

## ⚙️ Setup

Before you begin, set up your environment.

1. Create and activate a new virtual environment in the project directory 🖥.
2. Install the required Python packages:
```bash
pip install -r requirements.txt
```

*(Optional) To run the REST API service, install additional requirements:*
```bash
pip install -r service/requirements.txt
```

3. Review and update the [config_api.txt](config_api.txt) 📎 file with your specific paths and API configurations.
You are now ready to start the workflow.

---

## Workflow Stages

The process is divided into sequential steps, each responsible for a specific part of the NLP enrichment pipeline.

### ▶ Step 1: Prepare CSVs with texts from Page-Specific ALTOs

> [!IMPORTANT]
> If you already have a directory of CSV (XLSX) tables with `text` column containing extracted text
> files from ALTO XMLs, you can skip Step 1 and proceed directly to Step 2.

The `../CSVS_with_TEXT/` directory mentioned later is the result of ALTO XML postprocessing pipeline described
in the separate repository [^2]. It contains document-specific CSV (XLSX) files with the `text` column containing
extracted textual content from the ALTO XML files. Each CSV (XLSX) file corresponds to a document and contains rows
for each page with a line number column for the proper ordering (`page_num` and `line_num`).

```
CSVS_with_TEXT/
├── document1.csv
├── document2.csv
└── ...
```
with the structure of each CSV (XLSX) file like:
```
file,page_num,line_num,text,split_ws,split_we,lang,lang_score,perplex,categ
CTX201504033,1,8,2012,,,N/A,0,0,Non-text
CTX201504033,2,2,1,,,N/A,0,0,Non-text
CTX201504033,3,2,2,,,N/A,0,0,Non-text
...
```
Where `split_ws` and `split_we` are the start and end character offsets of the words split in the original ALTO XML.
The `lang` and `lang_score` columns indicate the detected language and its confidence score,
while `perplex` and `categ` provide additional metadata about the text classification.

If the script detects an `.xlsx` file, it will iterate over all sheet names, verify if a `text` column exists
in each sheet, and extract the content safely for Excel tables with multiple sheets.

### ▶ Step 2: Extract NER and CONLL-U

This stage performs advanced NLP analysis using external APIs (Lindat/CLARIAH-CZ)
to generate Universal Dependencies (CoNLL-U) and Named Entity Recognition (NER) data.

Unlike previous steps, this process is split into modular shell scripts to handle large-scale
processing, text chunking, and API rate limiting.

#### Configuration ⚙️

Before running the pipeline, review the [api_config.txt](config_api.txt) 📎 file. This file controls
directory paths, API endpoints, and model selection.

```bash
# config_api.txt
OUTPUT_DIR="../../ARUB"                          # Destination for results
INPUT_TABLES_DIR="$OUTPUT_DIR/DOC_LINE_LR_CLS"  # Input tables from Step 1

WORK_DIR="./TEMP"                                # Working directory for intermediate files

LOG_FILE="$OUTPUT_DIR/processing.log"
CONLLU_INPUT_DIR="$OUTPUT_DIR/UDP"
TEMP_TXT_DIR="./TEMP/TXT_EXTRACT"
CHUNK_DIR="./TEMP/CHUNKS"

TSV_INPUT_DIR="$OUTPUT_DIR/NE"
SUMMARY_OUTPUT_DIR="$OUTPUT_DIR/UDP_NE"

TEITOK_OUTPUT_DIR="$OUTPUT_DIR/TEITOK"
INPUT_ALTO_DIR="$OUTPUT_DIR/ALTO"               # Source ALTO XML files - for TEITOK conversion

# Backing services. Environment wins, this file is the default — see
# "Backing Service Endpoints" below for why the ${VAR:-...} form is required.
UDPIPE_URL="${UDPIPE_URL:-https://lindat.mff.cuni.cz/services/udpipe/api/process}"
NAMETAG_URL="${NAMETAG_URL:-https://lindat.mff.cuni.cz/services/nametag/api/recognize}"

MODEL_UDPIPE="czech-pdt-ud-2.15-241121"
MODEL_NAMETAG="nametag3-multilingual-onto-260521"

TIMEOUT=60                     # API call timeout in seconds
MAX_RETRIES=5                  # Number of retries for failed API calls
BACKOFF_FACTOR=1.5
WORD_CHUNK_LIMIT=900           # Word limit per API call

SAVE_CSV=true                  # write token-level summary CSV
SAVE_CONLLU_NE=true            # keep merged CoNLL-U with NER in MISC
SAVE_TEITOK=true               # write TEITOK XML (see "TEITOK XML — Unified Output Format")

# ── Image Options (TEITOK coordinates) ──────────────────────────────────────────
INPUT_PAGES_DIR=""             # page images <doc_id>-<N>.<png|jpg|tif>: scale bboxes to them
IMAGE_DPI=""                   # no images: scale from the ALTO MeasurementUnit to this DPI
ALTO_DPI=""                    # ... and for pixel-unit ALTO, the DPI the ALTO was made at
BBOX_ORIGIN="page"             # page (TEITOK norm) | printspace (images cropped to PrintSpace)
REGENERATE_TEITOK="${REGENERATE_TEITOK:-false}"  # true: rewrite existing .teitok.xml instead of resuming
```

`TIMEOUT`, `MAX_RETRIES` and `WORD_CHUNK_LIMIT` are limits (atrium-project#53). For an API job
each is also an environment setting — `LINDAT_TIMEOUT_S`, `LINDAT_MAX_RETRIES` and
`WORD_CHUNK_LIMIT`, which win over this file — and `GET /info` reports the value in force; see
[service/README.md § Limits](service/README.md#limits) for every limit of the service.

#### Backing Service Endpoints

`UDPIPE_URL` and `NAMETAG_URL` are **attachable** (12-factor IV): point them at a
self-hosted UDPipe 2 / NameTag 3 instance, or a local stub, without touching code.
Precedence, highest first:

1. **`--url`** on `call_udpipe.py` / `call_nametag.py`.
2. **The environment** — `UDPIPE_URL` / `NAMETAG_URL` exported by docker compose
   `environment:`, a k8s `env:` block, or the shell.
3. **[config_api.txt](config_api.txt) 📎**, which supplies the LINDAT defaults.

Both keys must be written in the `${UDPIPE_URL:-https://…}` form shown above.
A bare assignment breaks the first two tiers: every stage script begins with
`source config_api.txt`, and bash preserves the export attribute of an
already-exported variable, so a plain `UDPIPE_URL="https://…"` silently
overwrites *and re-exports* the value the deployment set — the helper scripts
would then read this file's endpoint rather than the operator's.

The `/info` endpoint and the `?deep=true` health probe resolve the same
precedence, so they always report and probe the endpoint the pipeline uses.

#### Execution Pipeline

Run the following scripts in sequence. Each script sources [config_api.txt](config_api.txt) 📎
directly for configuration. Retry logic and per-attempt error handling are implemented inside
the Python helper scripts ([call_udpipe.py](api_util/call_udpipe.py),
[call_nametag.py](api_util/call_nametag.py)) using exponential back-off controlled by the
`MAX_RETRIES` and `BACKOFF_FACTOR` variables. [api_util/api_common.sh](api_util/api_common.sh) 📎
is a standalone utility module that exposes a `log()` helper and an `api_call_with_retry()`
shell function for any custom scripts that choose to source it; the four main pipeline scripts
(`api_1_manifest.sh` … `api_4_stats.sh`) do not source it. Additionally, [api_util/](api_util/) 📁
contains helper Python scripts for chunking and analysis

##### 1. Generate Manifest

Maps input text files to document IDs and page numbers to ensure correct processing order.

```bash
./api_1_manifest.sh
```

* **Input:** `../CSVS_with_TEXT/` (raw text files in subdirectories from Step 1).
* **Output:** `OUTPUT_DIR/manifest.tsv`, and per document `TEMP_TXT_DIR/<doc_id>.txt` (one line per
  table row) with `TEMP_TXT_DIR/<doc_id>.rows.tsv` next to it: the page, line, page label and text
  of every line. That file is where stages 3 and 4 take page numbers from
  ([api_util/page_rows.py](api_util/page_rows.py) 📎).

Example output file [manifest.tsv](data_samples/manifest.tsv) 📎 with **file**, **page**
number, and **path** columns. It lists all text files to be processed in the next steps.
Run the following command to see how many documents will be processed:

```bash
tail -n +2 OUTPUT_DIR/manifest.tsv | wc -l
```
which returns the total number of document rows in the manifest, excluding the header line.

##### 2. UDPipe Processing (Morphology & Syntax)

Sends text to the UDPipe API [^5]. Large documents are automatically split into chunks (default 900 words) using
[chunk.py](api_util/chunk.py) 📎 to respect API limits, then merged back into valid CoNLL-U files.

```bash
./api_2_udp.sh
```

* **Input 1:** `OUTPUT_DIR/manifest.tsv` (mapping of text files to document IDs and page numbers).
* **Input 2:** `../CSVS_with_TEXT/` (raw text files in subdirectories from Step 1).
* **Output:** `OUTPUT_DIR/UDP/*.conllu` (Intermediate per-document CoNLL-U files), each with its
  `<doc_id>.rows.tsv` copied next to it, so the text and its page provenance stay together on
  resumed runs and in containers (where `TEMP/` is not kept).

Run the following command to see how many documents have been processed into CoNLL-U files:

```bash
ls -l <OUTPUT_DIR>/UDP/ | wc -l
```
which returns the total number of CoNLL-U files created (each file corresponds to a document).

Example output directory [UDP](data_samples/UDP) 📁 contains per-document CoNLL-U files.

> [!NOTE]
> **Chunking and page boundaries.** [chunk.py](api_util/chunk.py)📎 splits text on OCR line boundaries (not raw whitespace),
> preserving the newline-separated structure of the source CSV so that UDPipe receives proper
> sentence-boundary hints between lines. A chunk is about `WORD_CHUNK_LIMIT` words, **not a page**:
> when a document spans several chunks, [call_udpipe.py](api_util/call_udpipe.py)📎 merges them into
> one CoNLL-U and marks where each chunk starts with `# chunk_start = K`. Pages come from the rows
> file instead: UDPipe marks every line end (`SpacesAfter=\n`), so counting those marks — checked
> against the text of every row — places each token on its line and page
> ([page_rows.py](api_util/page_rows.py)📎); if the check fails, the characters are aligned instead.
> Up to v0.21.0 the chunk marker was `# page_break = true` and every stage read it as a page;
> it is now read as a chunk start. Without a rows file, only an old per-page CoNLL-U (whose
> `# sent_id` restarts at 1) has more than one page.

> [!TIP]
> You can launch the next step when a portion of CoNLL-U files are ready,
> without waiting for the entire input collection to finish. You will have to relaunch
> the next step after all CoNLL-U files are ready to process the files created after the previous
> run began.

##### 3. NameTag Processing (NER tags)

Takes the valid CoNLL-U files and passes them through the NameTag API [^6] to annotate Named Entities
(NE) directly into the syntax trees.

```bash
./api_3_nt.sh
```

* **Input:** `OUTPUT_DIR/UDP/*.conllu` (Intermediate per-document CoNLL-U files) and their `.rows.tsv`.
* **Output:** `OUTPUT_DIR/NE/*/*.tsv` (NE annotated per-page files: `<doc_id>-P.tsv` holds the tokens
  of page P; a sentence that runs over a page is split between two files, in order)

Run the following command to see how many documents have been processed into TSV files:

```bash
ls -l OUTPUT_DIR/NE | wc -l
```
which returns the total number of directories created (each subfolder corresponds to a document).

Example output directory [NE](data_samples/NE) 📁 contains per-page TSV files with NE annotations. The tags are
the labels of the configured NameTag model (`MODEL_NAMETAG`): OntoNotes 5 for the default multilingual model,
CNEC 2.0 [^3] for the Czech one. The committed `NE/` files carry OntoNotes labels, while `UDP_NE/` and `TEITOK/`
were produced with the Czech CNEC model before the default changed; a sample refresh on LINDAT aligns them.


##### 4. Generate Statistics

This stage consolidates the linguistic data from UDPipe (CoNLL-U) and the NER data from
NameTag (TSV) into final per-document formats. It also generates a master summary of
entity counts across the entire collection and can optionally produce TEITOK-compatible
XML files that merge linguistic tokens with original ALTO layout coordinates.

The process utilizes [summarize_nt_udp.py](api_util/summarize_nt_udp.py) 📎 to merge these
layers, map complex CNEC 2.0 tags (e.g., `g`, `pf`, `if`) into human-readable categories
(e.g., "Geographical name", "First name", "Company/Firm"), and write all output formats.
Optionally, TEITOK-related functionality is implemented in
[teitok_alto.py](api_util/teitok_alto.py) 📎.

```bash
./api_4_stats.sh
```

#### Inputs and Outputs

* **Input 1:** `OUTPUT_DIR/UDP/*.conllu` — Per-document CoNLL-U files containing morphology and syntax.
* **Input 2:** `OUTPUT_DIR/NE/*/*.tsv` — Per-page TSV files containing Named Entity annotations.
* **Input 2b:** `OUTPUT_DIR/UDP/<doc_id>.rows.tsv` (else `TEMP_TXT_DIR/<doc_id>.rows.tsv`) — the page and line of
every token; `page_id` in the CSVs, the summary's pages, entity pages and the TEITOK pages come from it
(or from the layout, where there is one).
* **Input 3 (Optional):** `INPUT_ALTO_DIR/*.alto.xml` — Source ALTO XML files used during TEITOK conversion to provide spatial bounding box coordinates for each token.
* **Input 4 (Optional):** `INPUT_PAGES_DIR/<doc_id>-N.png` — Per-page facsimile images. When specified, the pipeline reads
their pixel size from the file headers to compute the scale factors (sx, sy). If omitted, the ALTO coordinates are written
as they are (scale 1.0), or scaled by `IMAGE_DPI`.
* **Output 1:** `OUTPUT_DIR/summary_ne_counts.csv` — Global table of aggregated Named Entity statistics across all documents.
* **Output 2:** `OUTPUT_DIR/UDP_NE/<doc_id>/<doc_id>.csv` — Per-document CSV tables with tokens, lemmas, and human-readable NE explanations.
* **Output 3 (Optional):** `OUTPUT_DIR/UDP_NE/<doc_id>/<doc_id>.conllu` — Final CoNLL-U files with NER tags enriched in the `MISC` column.
* **Output 4 (Optional):** `OUTPUT_DIR/TEITOK/<doc_id>.teitok.xml` — TEITOK XML files for a TEITOK project (`xmlfiles/<doc_id>.xml`), flexiconv/flexipipe and facsimile viewing (see [TEITOK XML — Unified Output Format](#teitok-xml--unified-output-format)).

The behavior of this step is controlled by boolean flags in your [config_api.txt](config_api.txt):

| Variable            | Description                                                                                                                                                                                                                                                                        | Default   |
|---------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------|
| `SAVE_CONLLU_NE`    | Keep the enriched CoNLL-U with NER in the `MISC` field.                                                                                                                                                                                                                            | `true`    |
| `SAVE_CSV`          | Write the token-level summary CSV per document.                                                                                                                                                                                                                                    | `true`    |
| `SAVE_TEITOK`       | Write TEITOK-style TEI XML with bounding boxes and NER spans. Without a layout (`INPUT_ALTO_DIR` unset, no converted file) TEITOK XML is still produced, with the table's pages and lines but no bboxes. A file that fails the output contract stops the stage with exit code `5`. | `true`    |
| `INPUT_PAGES_DIR`   | Directory of per-page images (`<doc_id>-N.png`). When set, bbox coordinates are scaled to match the actual PNG resolution. Leave empty to write raw ALTO pixel values.                                                                                                             | *(empty)* |
| `BBOX_ORIGIN`       | `page`: bboxes measured from the page's top-left corner (the TEITOK norm). `printspace`: measured from the ALTO PrintSpace, with a PrintSpace-sized `<surface>` — only for page images cropped to the print area.                                                                  | `page`    |
| `REGENERATE_TEITOK` | `true`: delete and rewrite each document's `.teitok.xml` instead of skipping it on a resumed run (use once after a TEITOK format change).                                                                                                                                          | `false`   |

#### ALTO-to-TEITOK XML Generation and Coordinate Alignment

When `SAVE_TEITOK=true`, [teitok_alto.py](api_util/teitok_alto.py) 📎 reads and processes the internal spatial
hierarchy of your ALTO source specifications.

**Coordinate origin (`BBOX_ORIGIN`):**

ALTO positions (`HPOS`, `VPOS`) are measured from the top-left corner of the page image, and
TEITOK expects exactly that: every TEITOK tool (flexiconv's ALTO/PAGE/hOCR import,
teitok-tools) writes `bbox` as page-image pixels. So by default (`BBOX_ORIGIN=page`) the
coordinates are taken as they are, and `<surface lrx lry>` declares the page size.

Some collections publish page images **cropped to the print area**. For those, set
`BBOX_ORIGIN=printspace`: the page's `<PrintSpace>` origin is subtracted from every
coordinate, and `<surface>` declares the PrintSpace size instead.

```xml
<PrintSpace HEIGHT="2039" WIDTH="1254" VPOS="150" HPOS="200">
```

With the sample above, a block at `HPOS=220 VPOS=160` becomes `bbox="20 10 …"` on a
`1254 × 2039` surface instead of `bbox="220 160 …"` on a `1654 × 2339` one. Content outside
the PrintSpace (e.g. marginalia) would get negative coordinates; they are clamped to 0 and
counted in a warning.

$$\text{Written Coordinate} = \text{round}((\text{ALTO Coordinate} - \text{Origin}) \times \text{Scale Factor})$$

where Origin is 0 for `page`, and the PrintSpace `HPOS`/`VPOS` for `printspace`.

**Scale factor (three tiers, per page):**

* **Companion Image Present (Tier 1):** If `INPUT_PAGES_DIR` is set and matching images exist, the tool
reads their pixel size from the file headers (PNG, JPEG, TIFF; no imaging library needed) and scales
the reference extent to it: `sx = image width / Page WIDTH` (`/ PrintSpace WIDTH` under `printspace`).
  Worked example: [`data_samples/pages/CTX000000001-1.png`](data_samples/pages/CTX000000001-1.png) is
  827×1170, half the ALTO page. With `INPUT_PAGES_DIR=data_samples/pages`, page 1 of `CTX000000001` gets
  `<surface lrx="827" lry="1170">` and the first block moves from `220 160 1420 280` to `110 80 710 140`.
  Page 2 has no image and stays at tier 3. The image draws the ALTO boxes at half scale, so the overlay
  can be checked by eye (`tests/test_teitok_integration.py`).
* **User-set DPI (Tier 2):** If no image is available, scale is derived directly from the ALTO `<MeasurementUnit>`
(`inch1200`, `mm10`, or `pixel`) mapped against the `IMAGE_DPI` and `ALTO_DPI` settings.
* **Native Processing (Fallback):** If no image and no DPI is provided, the scale factor is `1.0`.

Two of these fall-backs are easy to miss, because the file stays valid, so the writer reports them
on stderr (once per document): a page with no `<doc_id>-<N>.<png|jpg|jpeg|tif|tiff>` in the image
folder (`[Warn] <doc>: no page image in … for page(s) …` — its boxes stay unscaled and its `facs`
name is a guess, e.g. page 2 in the worked example above), and tier 3 with an ALTO
`MeasurementUnit` other than `pixel` (`MeasurementUnit is mm10 …` — the boxes are then in
1/10 mm, not pixels; set `INPUT_PAGES_DIR` or `IMAGE_DPI`).

In every tier `<surface lrx lry>` is the extent of the space the bboxes are measured in, so
`POST /rescale` and `fix_teitok_bboxes.py` can rescale a document to any other image size.

> **Relative coordinates:** resolution-independent (0–1) bounding boxes were proposed upstream
> ([ufal/flexiconv#1](https://github.com/ufal/flexiconv/issues/1)) and have not been answered or
> adopted; TEITOK uses absolute pixels.

#### Fixing Bounding Box Alignments (Practical Guide)

If you are a new user approaching this pipeline—perhaps a researcher who just digitized a batch of archival documents—your 
primary goal might be making sure the semantic annotations actually line up with your page images in a web viewer.

Let's say your original document was processed at a massive archival resolution, but the image you are serving to your 
web frontend is exactly 1200 pixels wide and 1800 pixels high. Currently, your TEITOK XML bounding boxes are completely 
misaligned.

Here is exactly how you would use the integrated tools to solve this problem.

**Method 1: The Quick API Fix (Best for single files or web integrations)**

Since the pipeline now includes a dedicated FastAPI service, you don't even need to write a script. You can just send 
your misaligned XML to the `/rescale` endpoint.

Open your terminal and run a simple curl command, explicitly telling the API the exact dimensions of your target image 
and requesting the output as an XML file instead of the default JSON metadata:

```bash
curl -X POST "http://localhost:8000/rescale" \
     -F "file=@CTX000000001.teitok.xml" \
     -F "width=1200" \
     -F "height=1800" \
     -F "format=xml" \
     -o CTX000000001.rescaled.teitok.xml
```

*What happens behind the scenes:* The API detects each page's coordinate space from its `<surface>` tag 
in your XML and scales the bounding boxes (`bbox`) of that page to the new 1200x1800 dimensions; boxes are clamped
to the page, and a `<change type="rescaled">` in the header records what was done. As a bonus, it also repairs any
malformed named-entity tags (like `<name>...</n>`) in the document. When the pages of a document differ in size,
width and height would distort some of them: give a factor instead (`-F "scale=0.5"`), and every page image is
taken to be that fraction of its surface.

**Method 2: The Command-Line Batch Process (Best for whole directories)**

If you have hundreds of XML files in a folder and you know exactly what scale ratio or DPI conversion you need, using 
the REST API file-by-file would be tedious. Instead, use the dedicated CLI tool, `fix_teitok_bboxes.py`.

If you know your web images are exactly 50% the size of your original scans (a scale factor of 0.5), you can process 
the entire directory at once:

```bash
python3 fix_teitok_bboxes.py -i /path/to/my/teitok_folder/ --sx 0.5 --sy 0.5
```

Alternatively, if your original ALTO OCR data was in millimeters (`mm10`) and you need to target a standard 72 DPI 
screen resolution, the script can handle that math directly:

```bash
python3 fix_teitok_bboxes.py -i my_document.teitok.xml --unit mm10 --dpi 72
```

If the original scans included a scanner bed margin (e.g., 50 pixels on the left and 20 on the top) that was cropped 
out of the final web image, you can strip that out by shifting everything left and up:

```bash
python3 fix_teitok_bboxes.py -i my_document.teitok.xml --dx -50 --dy -20
```

A shift moves content near the edge off the page; such coordinates are clamped to the page (0, or the
page's width/height) and counted, rather than written as negative values the stage-4 gate would reject.
Each `<surface>` is rescaled by its own size, and a `<change type="rescaled">` records the rewrite.

Both methods directly address the historical pain point of facsimile alignment, allowing you to flawlessly overlay
the NLP enrichments onto the visual documents without needing to re-run the entire pipeline.

> [!NOTE]
> When a token's matched ALTO strings span more than one page (a rare OCR edge case near page
> boundaries), a warning is printed to stderr identifying the token and the conflicting page
> indices. The first matched page is used for the bbox assignment in that case.

The structural and spatial hierarchy from the ALTO file is strictly preserved in the generated TEITOK XML:

* **Tokens:** Matched coordinates are written to each `<tok>` element as `@bbox="x1 y1 x2 y2"` (page-image
pixels, the TEITOK convention). Each token also carries `@type="w"` (word) or `@type="pc"` (punctuation
character) derived from UDPipe's UPOS tag. Alignment runs on the *surface* tokens — for a multi-word token such
as "abych" the one `<tok>` gets the bbox, its `<dtok>` words none.
* **Lines:** ALTO `<TextLine>` elements are preserved via `<lb id="lb-P.L">` (line break) tags, which also include
their own `@bbox` spatial coordinates.
* **Blocks:** ALTO `<TextBlock>` elements become `<div type="TextBlock" id="b-P.K">` containers. Their
`@subtype` is the label of the block's ALTO `TAGREFS` tag (e.g. `paragraph`, `heading`), and their
`@lang` is set where the block's ALTO `LANG` differs from the document's. Without ALTO there is one
`<div type="text">` per page.
* **Graphics:** Non-text elements like `Illustration` and `GraphicalElement` blocks are parsed and
appended to their respective pages as `<figure id="fig-P.K">` tags with strict bounding boxes.
* **Pages:** Page boundaries are marked with `<pb n="N" id="pb-N" facs="..." corresp="#facs-N" bbox="0 0 W H"/>`
elements pointing to the page's `<surface>`. A token is on the page of the ALTO string it aligned to; a token
that did not align is on the page of its line in the rows file. Pages only move forward, so every page gets
exactly one `<pb>` (pages without text included). A sentence running over a page break gets its `<pb/>`
inside the `<s>` — inside the `<name>`, too, when an entity runs over — and the figures of that page follow
the sentence. A `<div>` stays on the page it opens on.

Named entity spans are wrapped in `<name>` elements grouping their constituent `<tok>` nodes, with
`@sameAs` listing the token ids. `@type` holds the coarse category (`PER`, `ORG`, `LOC`, or `MISC`,
from [api_util/ner_types.py](api_util/ner_types.py) 📎 — the same map the document record's
`entities[].type_teitok` uses), and the raw NameTag label goes in the attribute of its tagset:
`@onto` for the default multilingual OntoNotes model (`<name type="PER" onto="PERSON">`), `@cnec` for
the Czech CNEC 2.0 model (`<name type="PER" cnec="pf">`), `@archaeo` for the archaeological model.

> [!NOTE]
> Thanks to the sequence matching approach, the script achieves near-perfect spatial alignment between
> NLP tokens and OCR coordinates, drastically improving upon older greedy matching methods that would
> break on minor character variations. Alignment statistics (matched vs. total tokens) are printed to
> the console per document; below 90 % a warning asks whether text and layout come from the same
> document version (e.g. ocr-postprocess's text with a flexiconv layout). A token that aligned to
> a page out of reading order loses its box (the longest in-order run of aligned pages is kept).

```bash
ls OUTPUT_DIR/UDP_NE | wc -l
```

which returns the total number of created files, both `.csv` and `.conllu` corresponding
to specific documents.

```bash
ls OUTPUT_DIR/UDP_NE/*/*.csv | wc -l
```

returns number of documents processed into tables

```bash
ls OUTPUT_DIR/TEITOK/*.xml | wc -l
```

returns number of recorded `.teitok.xml` documents.

Example summary table: `summary_ne_counts.csv` (produced by a real run; not committed —
see the note below).

Example output directory [UDP_NE](data_samples/UDP_NE) 📁 contains per-document CSV
tables with NE tags and UDPipe feature columns, plus CoNLL-U files with NE annotations in
per-document manner.

Example output directory [TEITOK](data_samples/TEITOK) 📁 contains per-document TEITOK
XML files combining UD linguistic annotations and NER spans with bounding boxes aligned
from the source ALTO XML.

#### Output Structure

After completing the pipeline, your working and output directories will be organized as follows:

```
TEMP/
├── CHUNKS/
│   └── ...
├── nametag_response_docname1.conllu.json
└── ...
```

AND

```
<OUTPUT_DIR>
├── UDP_NE/
│   ├── <doc_id>
│   │   ├── <doc_id>.csv
│   │   └── <doc_id>.conllu
│   ├── <doc_id>
│   │   ├── <doc_id>.csv
│   │   └── <doc_id>.conllu
│   └── ...
├── UDP/
│   ├── <doc_id>.conllu
│   ├── <doc_id>.rows.tsv
│   └── ...
├── TEITOK/
│   ├── <doc_id>.teitok.xml
│   ├── <doc_id>.teitok.xml
│   └── ...
├── NE/
│   ├── <doc_id>
│   │   ├── <doc_id>-<page_num>.tsv
│   │   └── ...
│   ├── <doc_id>
│   │   ├── <doc_id>-<page_num>.tsv
│   │   └── ...
│   └── ...
├── altos/
│   ├── <doc_id>.alto.xml
│   └── ...
├── pages/
│   ├── <doc_id>-1.png
│   ├── <doc_id>-2.png
│   └── ...
├── processing.log
├── summary_ne_counts.csv
└── manifest.tsv
```

The combined output `summary_ne_counts.csv` contains aggregated Named Entity
statistics across all processed pages. This repository's `data_samples/` only ships the three
synthetic demo documents (`CTX00000000{1,2,3}`), so no `summary_ne_counts.csv` is
committed — the file is real output of a real `api_5_summary_ne.sh` run, not a sample bundled here.

> [!NOTE]
> Now you can delete `UDP/` from `<OUTPUT_DIR>/` if you no longer need the raw CoNLL-U files.
> The final CoNLL-U files with NER features are in `<OUTPUT_DIR>/UDP_NE/`.

If you do not plan to rerun any part of the pipeline, you can also delete
the entire `TEMP/` directory including [manifest.tsv](data_samples/manifest.tsv) 📎.

---

## EXTRA: Converting Other Input Formats with flexiconv

> [!NOTE]
> This section is relevant when your documents originate from an OCR or digitisation
> pipeline that does **not** produce ALTO XML — for example, PAGE XML, hOCR, plain-text
> exports, or office/PDF documents. If you already have ALTO XML, the pipeline generates
> TEITOK XML natively via `api_4_stats.sh` (see above).

### What is flexiconv?

**[flexiconv](https://github.com/ufal/flexiconv)** [^9](https://github.com/ufal/flexiconv) is a format converter
by the TEITOK author (UFAL) that translates OCR, layout and document formats into **TEITOK
XML**. Its output can be loaded straight into a TEITOK project, and the readers of this repository
(the TEITOK readers, e.g. [api_util/teitok_read.py](api_util/teitok_read.py) 📎, which atrium-keyword-extract vendors) accept it.

```
  Your input format           flexiconv                     Output
  ─────────────────    ──────────────────────   ──────────────────────────────────
  PAGE XML, hOCR    ─┐                           .teitok.xml   ──► TEITOK platform
  txt, md, html     ─┤──► api_flexiconv.sh ────► (flexiconv    ──► the TEITOK readers
  docx, odt, pdf    ─┘                            profile)
```

By default flexiconv output is used as it is, without UDPipe/NameTag
([annotating it](#annotating-converted-documents-flexiconv_annotate) is opt-in). It contains
what the source contains:

| Source                                 | flexiconv TEITOK                                                        | Rows seen by `teitok_read.py`      |
|----------------------------------------|-------------------------------------------------------------------------|------------------------------------|
| PAGE XML, hOCR, ALTO (`.xml`, `.hocr`) | `<tok bbox>` words with `<lb/>` lines and `<facsimile>` zones, no `<s>` | one row per line                   |
| txt, md, html, docx, odt, rtf, pdf, …  | `<p>`, `<head>`, `<item>` text, not tokenized                           | one row per paragraph/heading/item |

So the downstream readers (keyword extraction in atrium-keyword-extract, LLM enrichment in
atrium-digital-convert) can work on it; a lemma-based method cannot, because there are no lemmas.

A PDF converted with flexiconv's default reader (`pdf=smart`) has no word boxes and no page
images, so its TEITOK has no facsimile; flexiconv's `pdf=bbox` reader gives word boxes but needs
Poppler's `pdftotext` (not wired into `api_flexiconv.sh`). See also [Pitfalls](#pitfalls) 6–8.

### How to use it in this pipeline

1. **Install** the pinned flexiconv and the format extras:

```bash
pip install -r requirements_flexiconv.txt   # flexiconv v0.3.10 + docx/odt/md/pdf/rtf extras
```

flexiconv is **GPL-3.0-or-later** (declared in its `pyproject.toml`) and optional: nothing else
in the pipeline imports it, and `para_config.txt` records it as a conditional component.

2. **Put the documents** in `INPUT_DOCS_DIR` (`config_api.txt`, default `$OUTPUT_DIR/DOCS`) and
list the extensions to convert in `FLEXICONV_FORMATS`. `xml` covers PAGE XML, ALTO and TEI:
flexiconv detects them by content.

3. **Convert:**

```bash
bash api_flexiconv.sh
```

Each file becomes `<stem>.teitok.xml` in `TEITOK_FLEXICONV_DIR` (default
`$TEITOK_OUTPUT_DIR/flexiconv`). Two inputs with the same stem (`report.txt` + `report.md`)
become `report.txt.teitok.xml` and `report.md.teitok.xml`. Existing outputs are kept unless
`FLEXICONV_FORCE=true`. The script calls flexiconv's library (`flexiconv.api.run_convert`), or
its CLI (`flexiconv --no-auto-install -t teitok IN OUT`) when only the CLI is installed. Either
way it never `pip install`s missing extras in the middle of a run. Without flexiconv installed the
stage stops at once with exit code `3`. A file that cannot be converted is reported in one line and
recorded, with its reason, in the paradata record of the run (`--program nlp-enrich`, component
`flexiconv`); the stage converts the rest and then exits `1`, so `run_pipeline.py --with-flexiconv`
does not end green with documents missing. The output directory is then checked with
`validate_teitok_xml.py --profile core`, the rules any TEITOK document must meet. This is not
this writer's XSD, and `api_4_stats.sh` leaves this directory out of its own gate.

4. **Use the result** with the readers of the stages that follow (atrium-keyword-extract reads
a `.teitok.xml` directly), or annotate it here with `FLEXICONV_ANNOTATE`.

For a single file, the CLI directly: `flexiconv -t teitok input.page.xml output.teitok.xml`
(`flexiconv --list-formats` lists every input format).

`run_pipeline.py --with-flexiconv` runs `api_flexiconv.sh` as its first stage (next section;
`--start-from` any later stage skips it). The REST service never runs flexiconv (no GPL code in its
image), but it takes flexiconv's output: upload a converted `.teitok.xml` to `/enrich` and it is
annotated with its own layout ([service/README.md](service/README.md) 📎).

### Annotating converted documents (`FLEXICONV_ANNOTATE`)

With `FLEXICONV_ANNOTATE=true` a converted document goes through the same linguistic stages as
a table input. It comes out as TEITOK format 2 in `TEITOK_OUTPUT_DIR`: sentences, lemmas,
UPOS/XPOS/features, dependencies, `<name>` entities and TEITOK ids. It also keeps what flexiconv
found on the page:

```bash
python3 run_pipeline.py --with-flexiconv   # api_flexiconv.sh, then manifest → udp → nt → stats
```

`--with-flexiconv` sets the flag for every stage. To run stage by stage, set
`FLEXICONV_ANNOTATE=true` in `config_api.txt` and run `bash api_flexiconv.sh` before
`api_1_manifest.sh`.

| Stage               | With `FLEXICONV_ANNOTATE=true`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
|---------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 1 manifest          | Each `TEITOK_FLEXICONV_DIR/*.teitok.xml` is a document (`report.txt.teitok.xml` is `report.txt`) whose text is the rows `teitok_read` gives (one per line or text block). When a table document uses the file as its layout (next row), the table wins and the converted file is recorded as skipped.                                                                                                                                                                                                                                                                                                                                                                                           |
| 2–3 UDPipe, NameTag | Unchanged.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| 4 stats             | A document without `<doc_id>.alto.xml` takes its layout from its converted file ([api_util/teitok_layout.py](api_util/teitok_layout.py) 📎): pages from `<pb>` (label `pb@n`, image and size from `pb@facs`/`@bbox` or its `<surface>`), lines from `<lb bbox>`, word boxes from `<tok bbox>`, and text blocks with their element name as `subtype` (`head`, `p`, `item`, …). The file is `<doc_id>.teitok.xml`, else the one file whose `canonical_doc_id` is the document's (`report.v2.teitok.xml` serves `report`); two such files (`report.txt` and `report.md` conversions) are ambiguous: none is used, and a warning says so ([api_util/doc_identity.py](api_util/doc_identity.py) 📎). |
| document record     | `entities[].bbox`, `teitok_ref` and `pages[].teitok_surface` are filled as for ALTO documents.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |

| Source                             | Layout in the annotated TEITOK                                                                                                                                                                                                                                               |
|------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| PAGE XML, hOCR, ALTO via flexiconv | Word and line boxes, and the page image under its own name (`<graphic url>` = flexiconv's `facs`). The page size is set when the source has one (hOCR). Punctuation that flexiconv did not box gets no bbox. flexiconv's `<zone>`s are not carried over (format 2 has none). |
| txt, md, docx, odt, pdf, …         | `<div type="TextBlock" subtype="p\|head\|item\|…">`, with no boxes and no facsimile.                                                                                                                                                                                         |

Inline markup such as `<hi>` is flattened into its block. The converted file stays in
`TEITOK_FLEXICONV_DIR` as the record of the conversion.

The header names flexiconv (`<change who="flexiconv" type="converted">`) and the original
document (`orgfile`). A page image the converted file names is looked up in `INPUT_PAGES_DIR` under
that name. When found, it sets the surface size; the coordinates are already image pixels and stay
as they are.

**In the full ATRIUM pipeline**, ocr-postprocess's `--method text-lines` reads the same documents
into `DOC_LINE_CATEG/`, which is this repo's `INPUT_TABLES_DIR`. With `INPUT_DOCS_DIR` pointing at
the originals, the text comes from ocr-postprocess, where its lines are categorised, and the
layout comes from flexiconv.

### Checking a real collection (issue #10)

Before relying on the flexiconv path for a collection, convert a few real documents of each kind
and record what comes out. `api_util/flexiconv_report.py` prints the table for you, one row per
converted file, and lists the inputs that produced nothing:

```bash
bash api_flexiconv.sh
python3 api_util/flexiconv_report.py "$TEITOK_FLEXICONV_DIR" --inputs "$INPUT_DOCS_DIR"
# | Input | Pages | Rows | Tokens | Elements with bbox | `--profile core` |
# | hocr `page_1.hocr` | 1 | 3 | 13 | 15 | ✅ |   ... exit 0 only if every file passes
```

Fill in the notes by looking at a few of the files:

| Input (format, source)      | Converted? | `--profile core` | Rows | Notes (layout kept? text order? encoding?) |
|-----------------------------|------------|------------------|------|--------------------------------------------|
| PAGE XML (e.g. Transkribus) |            |                  |      |                                            |
| hOCR (e.g. Tesseract)       |            |                  |      |                                            |
| docx / odt                  |            |                  |      |                                            |
| pdf (text layer)            |            |                  |      |                                            |
| txt / md                    |            |                  |      |                                            |

Reference run (2026-09-23, flexiconv v0.3.10, its own `examples/` plus one Czech txt), all through
`api_flexiconv.sh`, all passing `--profile core`, nothing installed during the run:

| Input                                 | Rows | Tokens | Elements with bbox |
|---------------------------------------|------|--------|--------------------|
| PAGE XML `aletheiaexamplepage.xml`    | 96   | 532    | 593                |
| hOCR `output_page_1.hocr`             | 3    | 13     | 15                 |
| ALTO `sample.alto.xml`                | 1    | 5      | 8                  |
| docx `16453-1.docx`                   | 21   | 464    | —                  |
| md `FORMATS_AND_MAPPINGS.md`          | 209  | 1463   | —                  |
| txt (2 paragraphs)                    | 2    | 10     | —                  |

Before the 2026-09 reader fallback every one of them read as **0 rows**. For docx/odt/epub, flexiconv also writes the
embedded images into a `<output>_files/` directory next to the TEITOK file.

Real flexiconv v0.3.10 output for txt, md, PAGE XML, hOCR and ALTO is committed in
[tests/fixtures/teitok/flexiconv/](tests/fixtures/teitok/flexiconv) 📁 and covered by the tests.

> [!TIP]
> Upstream, flexiconv can also annotate its own output (`flexiconv --flexipipe`, or
> xmltokenizer); this pipeline uses its own UDPipe/NameTag stages instead
> ([above](#annotating-converted-documents-flexiconv_annotate)), so that every document gets
> the same writer and ids. If your format is not supported by flexiconv, please open an issue
> on the [flexiconv GitHub repository](https://github.com/ufal/flexiconv).

---

## EXTRA: REST API Service

The pipeline now includes a fully-featured **FastAPI REST service** that exposes the core NLP enrichment and rescaling functionalities over HTTP.

* **Single-file enrichment:** Upload CSV, XLSX, or plain text to the `/enrich` endpoint and receive a combined JSON envelope (or ZIP workspace) with TEITOK XML, paradata, and NER summaries.
* **Coordinate Rescaling:** Use the `/rescale` endpoint to align XML spatial coordinates to specific target image resolutions directly over the network.
* **Job Management:** Background processing for larger documents with a asynchronous `/jobs` queue.

For complete setup instructions, payload examples, and endpoint documentation, refer to the [Service README](service/README.md).

---

## Paradata Logs

Every pipeline script records structured provenance metadata through
[atrium_paradata.py](atrium_paradata.py) 📎.  Two complementary log surfaces
are produced after a run:

### `<OUTPUT_DIR>/paradata/` — structured run logs 📂

Each of the four pipeline scripts produces one JSON file here, named with the
pattern:

```
YYMMDD-HHmmss_nlp-enrich.json
```

where the timestamp prefix is the UTC wall-clock time at which the script
started.  Because every script is an independent invocation, a complete
four-step run will create four separate files, making it straightforward to
audit individual stages in isolation.

The paradata logs (samples in directory [paradata](data_samples/paradata) 📂) capture key details about each pipeline stage,
including the program name, run ID, execution duration, configuration parameters, input and output statistics,
and performance metrics. They also document skipped files with reasons and provide a breakdown of output
types and processing rates for benchmarking. This structured metadata ensures traceability and facilitates
auditing of the pipeline's execution.

The declared output types per stage are:

| Script              | Types recorded                                                                                    |
|---------------------|---------------------------------------------------------------------------------------------------|
| `api_1_manifest.sh` | `tsv` (one entry per input CSV/XLSX processed into the manifest)                                  |
| `api_2_udp.sh`      | `conllu` (one per document)                                                                       |
| `api_3_nt.sh`       | `tsv` (one per page — count reflects individual page TSV files)                                   |
| `api_4_stats.sh`    | `csv` always; `conllu` when `SAVE_CONLLU_NE=true`; `xml` when `SAVE_TEITOK=true`                  |

> [!NOTE]
> When resuming an interrupted run (steps 2–4 skip already-finished documents
> via `[ -f "$out" ] && continue`), the resumed documents are not re-counted in
> the paradata JSON.  The `input_files_total` field still reflects the full
> manifest, so `skipped_files + successfully_processed` will be less than
> `input_files_total` for partial runs.  This is expected behaviour; the
> difference represents the documents carried over from a previous invocation.

> [!NOTE]
> **Paradata state files.** While a pipeline script is running, [atrium_paradata.py](atrium_paradata.py)
> stores intermediate state in a plain-text JSON file inside `<OUTPUT_DIR>/paradata/`
> (named `.state_<runid>_<program>.json`).  This file is automatically removed when
> the script completes.  Because it is plain JSON it can be inspected with any text
> editor if a run is interrupted unexpectedly.

### `<OUTPUT_DIR>/processing.log` — human-readable runtime log 📄

[api_common.sh](api_util/api_common.sh) 📎 exposes a `log()` helper that timestamps and
`tee`-appends warnings and errors to this flat file. The four main pipeline scripts
(`api_1_manifest.sh` … `api_4_stats.sh`) write to `processing.log` indirectly through the
Python helpers, which print timestamped messages to stderr; any script that sources
`api_common.sh` can also write here via the `log()` function directly.

```
[2026-01-15 09:42:11] [WARN] UDPipe failed (HTTP 503). Retrying in 2s…
[2026-01-15 09:42:14] [ERR]  UDPipe failed permanently after 5 attempts.
```

This file accumulates across reruns;
it is the first place to check when a document appears in
`skipped_files_detail` but the reason is terse.

### `TEMP/` — intermediate working files 📂

`TEMP/` (set by `WORK_DIR` in [config_api.txt](config_api.txt) 📎) holds
transient artefacts that are only needed during processing and can be deleted
once the full pipeline has completed successfully:

```
TEMP/
├── CHUNKS/
│   ├── <doc_id>/
│   │   ├── chunk_0.txt      # OCR-line-preserving text fragment sent to UDPipe
│   │   ├── chunk_1.txt
│   │   └── …
│   └── …
└── nametag_response_<doc_id>.conllu.json   # raw JSON reply from the NameTag API
```

`CHUNKS/` is produced by [api_util/chunk.py](api_util/chunk.py) 📎 which splits
documents that exceed `WORD_CHUNK_LIMIT` (default 900 words) into
sentence-boundary-aware fragments before each UDPipe API call.  Each chunk file
preserves the original OCR line structure (one line per row) so that UDPipe
receives correct sentence-boundary signals between text lines.  The per-chunk
plain-text files and the raw NameTag JSON responses carry no provenance value
after the CoNLL-U files have been merged and validated; they are not tracked by
the paradata logger.

> [!TIP]
> If disk space is a concern you can safely delete `TEMP/` once
> `<OUTPUT_DIR>/UDP/` and `<OUTPUT_DIR>/NE/` have been fully populated and
> step 4 has completed without errors.  The paradata JSONs in
> `<OUTPUT_DIR>/paradata/` and the `processing.log` are the only runtime
> records worth keeping long-term.

### Document record schema 📑

The per-document record this tool reads and writes — `<doc_id>.document.json`, the pair of the
paradata above — follows [atrium_document.schema.json](atrium_document.schema.json) 📎, schema
version **`1.0`**. That version is frozen as the hub tag
[`doc-schema-v1`](https://github.com/ufal/atrium-project/releases/tag/doc-schema-v1)
(ufal/atrium-project@`544298b`), and it is the baseline this tool implements:

* [tests/test_schema_freeze.py](tests/test_schema_freeze.py) 📎 checks this repository's schema
  against the frozen copy beside it,
  [atrium_document.schema.doc-schema-v1.json](atrium_document.schema.doc-schema-v1.json) 📎: the
  copy is exactly the tagged file, nothing declared at the freeze has been removed or renamed, and
  every change made since is registered;
* all three files, like `atrium_document.py`, are vendored from the hub and kept byte-identical to
  its `v1` tag by the `para-drift` CI check, so they are never edited in this repository. The hub
  additionally checks that every record shape the tools write validates under both the frozen and
  the current schema.

What may change after the freeze, and what a new major version takes, is in the hub's
[Freeze & conformance](https://github.com/ufal/atrium-project/blob/main/docs/document_schema.md#freeze--conformance).
[CITATION.cff](CITATION.cff) 📎 carries the same reference under `references`.

---

### One-command pipeline run (`run_pipeline.py`)

While each stage can be launched manually (see [Workflow Stages](#workflow-stages)),
[run_pipeline.py](run_pipeline.py) 📎 chains them end-to-end and merges every per-stage paradata JSON
produced during the run into a single `pipeline-run-merged` record.

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
```

The runner reads the **same** [config_api.txt](config_api.txt) 📎 that the shell stages source, so Python and Bash always agree on `OUTPUT_DIR`, `PARADATA_DIR`, and the input/output paths.

#### What the runner does

1. **Resolves config** from [config_api.txt](config_api.txt) 📎 (with `$VAR` / `${VAR}` expansion).
2. **Runs each stage in order**, spacing stage starts by ≥ 1.1 s so the
1-second-resolution paradata filenames (`YYMMDD-HHmmss_nlp-enrich.json`)
never collide.
3. **Collects** the paradata JSON each stage writes, scoped to **this run only**
(paradata files that already existed before the run are never merged).
4. **Merges** all per-stage records into one
`<PARADATA_DIR>/<runid>_nlp-enrich_pipeline-run.json` via
`atrium_paradata.merge_run_paradata`. The merged record accurately tracks document-level statistics across the sequential pipeline (recording true throughput without inflating input counts). The effective license of the merged record is re-derived from the **union** of every component used across the stages, so the most-restrictive rule holds end-to-end (a core run is CC BY-NC-SA 4.0, from the NameTag 3 and UDPipe 2 models; converting with flexiconv adds its GPL-3.0-or-later).

#### Resume / checkpoint recovery

Long batches on constrained hardware are expensive to restart from scratch, so the
runner lets you re-enter the pipeline at any stage instead of redoing completed work.
Recovery operates at two complementary levels.

**Document-level (automatic).** Every stage already skips inputs whose output exists
(steps 2–4 via `[ -f "$out" ] && continue`), so simply re-running the same command
picks up where the previous run stopped.

**Pipeline-level starting points.** To skip whole stages — not just completed
documents — the runner accepts explicit entry points over the full stage order:

| Flag                   | Effect                                                                   |
|------------------------|--------------------------------------------------------------------------|
| `--start-from <stage>` | Run from `<stage>` onward; every earlier stage is skipped.               |
| `--skip-<stage>`       | Skip one named stage, run the rest.                                      |
| `--clean-state`        | Sweep stale `.state_*.json` sidecars from `PARADATA_DIR` before running. |

`<stage>` is one of `manifest`, `udp`, `nt`, `stats`, `project` (the canonical
order; `project` needs `--teitok-enrichment` to be part of the run).
Each skip flag also has an equivalent `SKIP_<STAGE>=true` knob that can live in
[config_api.txt](config_api.txt) 📎 (e.g. `SKIP_MANIFEST=true`), so a habitual resume
profile can be persisted without retyping flags.

```bash
# UDPipe + NameTag already finished — resume at statistics
python3 run_pipeline.py --start-from stats

# Re-run only NER and statistics; keep the existing manifest and CoNLL-U
python3 run_pipeline.py --skip-manifest --skip-udp
```

Skipped stages are recorded under `skipped_stages` in the merged
`<runid>_nlp-enrich_pipeline-run.json` record, so a resumed run remains fully
auditable. An all-skipped run is treated as a **successful resume**, not an empty
failure (see [Exit codes](#exit-codes) below).

#### Provenance for containers

When the runner (or its Docker entrypoint) is started with the
`ATRIUM_RUNNER_IMAGE`, `ATRIUM_RUNNER_REPO`, and `ATRIUM_RUNNER_REF` environment
variables set, those values are forwarded to every stage subprocess and end up
in each stage's paradata record (and therefore the merged record). This ties a
run back to the exact image/commit that produced it.

```bash
ATRIUM_RUNNER_IMAGE="ghcr.io/ufal/atrium-nlp-enrich:1.0.0" \
ATRIUM_RUNNER_REF="$(git rev-parse --short HEAD)" \
python3 run_pipeline.py
```

The published images are `ghcr.io/ufal/atrium-nlp-enrich:<version>` (the batch runner)
and `ghcr.io/ufal/atrium-nlp-enrich-api:<version>` (the service). `atrium-nlp-enrich-llm`
was published up to 0.23.0 only; it is not built any more (the keyword and LLM code left, see
[Where things went](#where-things-went)). `<version>` is the release **without** its leading
`v` (`1.0.0` for `v1.0.0`) — the
target is part of the image name, not the tag. `ATRIUM_RUNNER_REF` is the git ref and keeps the `v`.

> [!NOTE]
> **Docker on Linux: run as yourself.** `./data` is part of the clone and belongs to you, while
> the images run as uid 10001 by default. `docker-compose.yaml` runs every service as
> `user: "${ATRIUM_UID:-10001}:0"`, so put your uid in `.env` once —
> `echo "ATRIUM_UID=$(id -u)" >> .env` — and the container writes `./data` as you. With
> `docker run`, pass `--user "$(id -u):0"`. Docker Desktop (macOS, Windows) needs neither.
> (atrium-project#69)

#### Exit codes

| Code | Meaning                                                                                                                                                                     |
|------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `0`  | All requested stages completed; nothing flagged.                                                                                                                            |
| `1`  | A stage processed **nothing** despite having input and no resume, and `FAIL_ON_EMPTY=true` (the default). Also: `--with-flexiconv` could not convert at least one document. |
| `2`  | A required stage script was not found.                                                                                                                                      |
| `3`  | A dependency preflight failed (`--with-flexiconv` without flexiconv).                                                                                                       |
| `5`  | The TEITOK output failed its output contract (`api_4_stats.sh`'s gate: the XSD, unique ids, resolvable references, the page rules). A writer defect: please report it.      |
| `6`  | LINDAT UDPipe or NameTag did not answer after `MAX_RETRIES` retries (HTTP 5xx or 429, a refused or dropped connection); the first line on stderr names the service (#41).   |
| `7`  | Every attempt at a LINDAT call timed out (`TIMEOUT` seconds each).                                                                                                          |
| `8`  | LINDAT refused the request (HTTP 4xx, e.g. an unknown model): a configuration or request defect, not the input.                                                             |
| `≠0` | A stage script itself exited non-zero (its code is propagated).                                                                                                             |

> [!TIP]
> **Using `--force` (`-f`)** overrides exit codes `1`, `3`, and `≠0`. It bypasses preflight dependency crashes and forces `FAIL_ON_EMPTY=False`, allowing the pipeline to continue attempting subsequent stages even if one stage crashes or processes zero files.

The empty-run guard is governed by `FAIL_ON_EMPTY` in [config_api.txt](config_api.txt) 📎. A
**resumed** run — where every document was already complete and thus *skipped*, or
where a stage was skipped outright via `--start-from` / `--skip-<stage>` (see
[Resume / checkpoint recovery](#resume--checkpoint-recovery)) — is treated as
success, not an empty failure. Set `FAIL_ON_EMPTY=false` to permit genuinely empty
stages.

> [!NOTE]
> The runner never re-implements stage logic: it shells out to the exact same
> [api_1_manifest.sh](api_1_manifest.sh) … [api_4_stats.sh](api_4_stats.sh), and [config_api.txt](config_api.txt) you can
> run by hand. Anything documented for those stages (resume behaviour, output
> flags, …) applies unchanged under the runner.

---


## Where things went

Since v1.0.0 this repository is the morphology / named-entity / TEITOK stage only. The October 2026
split of the ATRIUM tool repositories moved the rest:

| What                                                             | Now in                                                                                                                                                                                                                       | Was                                    |
|------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------|
| Keyword extraction: KeyBERT, YAKE, KER; `POST /extract_keywords` | [atrium-keyword-extract](https://github.com/ufal/atrium-keyword-extract)                                                                                                                                                     | `keywords.py`, `--kw*`, `kw_method`    |
| The LLM controlled-vocabulary stage                              | [atrium-keyword-extract](https://github.com/ufal/atrium-keyword-extract), by way of atrium-llm-enrich and atrium-digital-convert (until atrium-keyword-extract#2 lands, the code is at atrium-digital-convert `v1.0.0-beta`) | `llm_run.py`, `vocab_*.py`, `prompts/` |
| OCR output postprocessing (ALTO and the other OCR formats)       | [atrium-ocr-postprocess](https://github.com/ufal/atrium-ocr-postprocess)                                                                                                                                                     | `atrium-alto-postprocess`              |

The API lost the `kw_method` and `num_keywords` parameters, the `keywords`, `method_requested`,
`method_used` and `llm` response fields and the `keyword_methods` block of `/info`: a breaking
change, hence the major version. Records written before it are read as before.

## Acknowledgements 🙏

**For support write to:** lutsai.k@gmail.com responsible for this GitHub repository [^8] 🔗

- **Developed by** UFAL [^7] 👥
- **Funded by** ATRIUM [^4]  💰
- **Shared by** ATRIUM [^4] & UFAL [^7] 🔗
- **Frameworks used**:
  - Lindat/CLARIAH-CZ **NameTag 3** API [^6] 🏷
  - Lindat/CLARIAH-CZ **UDPipe 2** API [^5] 🏷
  - UFAL **flexiconv** (format conversion to TEITOK XML) [^9] 🏷

**©️ 2026 UFAL & ATRIUM**

[^2]: https://github.com/ufal/atrium-ocr-postprocess
[^3]: https://ufal.mff.cuni.cz/~strakova/cnec2.0/ne-type-hierarchy.pdf
[^4]: https://atrium-research.eu/
[^5]: https://lindat.mff.cuni.cz/services/udpipe/api-reference.php
[^6]: https://lindat.mff.cuni.cz/services/nametag/api-reference.php
[^7]: https://ufal.mff.cuni.cz/
[^8]: https://github.com/ufal/atrium-nlp-enrich
[^9]: https://github.com/ufal/flexiconv

[^13]: https://huggingface.co/Qwen/Qwen2.5-7B-Instruct
[^14]: https://huggingface.co/mistralai/Mistral-Nemo-Instruct-2407
[^15]: https://huggingface.co/CohereForAI/aya-expanse-8b
[^16]: https://huggingface.co/speakleash/Bielik-11B-v3.0-Instruct
[^17]: https://huggingface.co/meta-llama/Meta-Llama-3.1-8B-Instruct
[^18]: https://huggingface.co/OpenPipe/Qwen3-14B-Instruct
[^19]: https://huggingface.co/Qwen/Qwen3-8B
[^20]: https://huggingface.co/google/gemma-3-12b-it
[^21]: https://huggingface.co/Aratako/Ministral-3-14B-Instruct-2512-BF16-TextOnly
[^22]: https://huggingface.co/google/gemma-4-31B-it
[^23]: https://huggingface.co/Qwen/Qwen3.6-35B-A3B
[^24]: https://huggingface.co/Qwen/Qwen3.6-27B
[^25]: https://huggingface.co/google/gemma-4-26B-A4B-it
[^26]: https://huggingface.co/Qwen/Qwen3.5-9B
[^27]: https://huggingface.co/Qwen/Qwen3-235B-A22B-Instruct-2507
[^28]: https://huggingface.co/deepseek-ai/DeepSeek-V3
[^29]: https://huggingface.co/meta-llama/Llama-4-Maverick-17B-128E-Instruct
[^30]: https://huggingface.co/meta-llama/Meta-Llama-3.1-70B-Instruct
