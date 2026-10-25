# How nlp-enrich works

For anyone who wants the idea before the details: what the four stages do to a document, why the output is TEITOK,
and how a word gets its place on the page image. The commands are in [usage](usage.md); every element of the TEITOK
file is in the [TEITOK reference](reference/teitok.md), and every option in the [configuration](configuration.md).

On this page: [the flow](#the-flow) · [the four stages](#the-four-stages) ·
[TEITOK XML, the output format](#teitok-xml-the-output-format) ·
[where the positions on the page come from](#where-the-positions-on-the-page-come-from) ·
[ALTO-to-TEITOK generation and coordinate alignment](#alto-to-teitok-xml-generation-and-coordinate-alignment)

## The flow

```
 line table (CSV, XLSX, .txt)                     layout, optional: ALTO | flexiconv TEITOK | born-digital record
        |                                                          |      page images, optional
        v                                                          v
 1 manifest --> 2 UDPipe 2 (LINDAT) --> 3 NameTag 3 (LINDAT) --> 4 merge and write --> CSV, CoNLL-U, TEITOK XML,
   text, rows     CoNLL-U                 entities per page                              the record's entities, paradata
```

The command line runs the four stage scripts in order, `api_1_manifest.sh` … `api_4_stats.sh`, by hand or through
`run_pipeline.py`. The service runs `run_pipeline.py` in a fresh workspace for each request
([service/README.md, How it works](../service/README.md#how-it-works)). Annotation happens on LINDAT's servers;
this repository prepares the text, calls the services and assembles their answers.

## The four stages

Each stage script sources [config_api.txt](../config_api.txt) directly for its configuration. Retry logic and
per-attempt error handling are implemented inside the Python helper scripts
([call_udpipe.py](../api_util/call_udpipe.py), [call_nametag.py](../api_util/call_nametag.py)), using exponential
back-off controlled by the `MAX_RETRIES` and `BACKOFF_FACTOR` variables.
[api_util/api_common.sh](../api_util/api_common.sh) is a standalone utility module that exposes a `log()` helper
and an `api_call_with_retry()` shell function for any custom scripts that choose to source it; the four main
pipeline scripts do not source it. [api_util/](../api_util/) also contains the helper Python scripts for chunking
and analysis.

### 1. Manifest

Stage 1 maps the input tables to document ids and page counts, to ensure the correct processing order. For every
table in `INPUT_TABLES_DIR` it writes a row of `<OUTPUT_DIR>/manifest.tsv` and, per document,
`TEMP_TXT_DIR/<doc_id>.txt` (one line per table row) with `TEMP_TXT_DIR/<doc_id>.rows.tsv` next to it: the page,
line, page label and text of every line. That rows file is where stages 3 and 4 take page numbers from
([api_util/page_rows.py](../api_util/page_rows.py)).

When the script meets an `.xlsx` file, it iterates over all sheets, checks whether each has a `text` column, and
extracts the content, so Excel tables with several sheets are read safely.

### 2. UDPipe: morphology and syntax

Stage 2 sends the text to the [UDPipe 2 API](https://lindat.mff.cuni.cz/services/udpipe/api-reference.php). Large
documents are split into chunks (900 words by default) by [chunk.py](../api_util/chunk.py) to respect the API's
limits, and the answers are merged back into one valid CoNLL-U file per document. Each CoNLL-U file gets its
`<doc_id>.rows.tsv` copied next to it, so the text and its page provenance stay together on resumed runs and in
containers, where `TEMP/` is not kept.

**Chunking and page boundaries.** [chunk.py](../api_util/chunk.py) splits text on OCR line boundaries (not raw
whitespace), preserving the newline-separated structure of the source table, so that UDPipe receives proper
sentence-boundary hints between lines. A chunk is about `WORD_CHUNK_LIMIT` words, **not a page**: when a document
spans several chunks, [call_udpipe.py](../api_util/call_udpipe.py) merges them into one CoNLL-U file and marks where
each chunk starts with `# chunk_start = K`. Pages come from the rows file instead: UDPipe marks every line end
(`SpacesAfter=\n`), so counting those marks, checked against the text of every row, places each token on its line
and page ([page_rows.py](../api_util/page_rows.py)); if the check fails, the characters are aligned instead. Up to
v0.21.0 the chunk marker was `# page_break = true` and every stage read it as a page; it is now read as a chunk
start. Without a rows file, only an old per-page CoNLL-U file (whose `# sent_id` restarts at 1) has more than one
page.

### 3. NameTag: named entities

Stage 3 passes the CoNLL-U files through the [NameTag 3 API](https://lindat.mff.cuni.cz/services/nametag/api-reference.php),
which annotates named entities directly in the syntax trees. It writes them page by page, as IOB TSV files
(`NE/<doc_id>/<doc_id>-P.tsv` holds the tokens of page P); a sentence that runs over a page is split between two
files, in order. The pages come from the rows file. The tags are the labels of the configured NameTag model
(`MODEL_NAMETAG`): OntoNotes 5 for the default multilingual model,
[CNEC 2.0](https://ufal.mff.cuni.cz/~strakova/cnec2.0/ne-type-hierarchy.pdf) for the Czech one.

### 4. Merge, statistics and TEITOK

Stage 4 consolidates the linguistic data from UDPipe (CoNLL-U) and the named entities from NameTag (TSV) into the
final per-document formats. It also writes a summary of entity counts across the whole collection and, by default,
a TEITOK XML file per document that merges the tokens with the page layout.

[summarize_nt_udp.py](../api_util/summarize_nt_udp.py) merges these layers, maps the NameTag labels to
human-readable categories (CNEC 2.0 `g`, `pf`, `if` to "Geographical name", "First name", "Company/Firm";
OntoNotes `GPE`, `PERSON` to "Countries, cities, states", "People, including fictional") and writes every output
format. The TEITOK writer is [teitok_alto.py](../api_util/teitok_alto.py). Every TEITOK file is checked against its
output contract before the stage finishes; a file that fails stops the stage with exit code `5`. What stage 4 reads
and writes: [the outputs reference](reference/outputs.md#stage-4-inputs-and-outputs).

## TEITOK XML, the output format

**TEITOK XML** (`.teitok.xml`) is the primary enriched output of this pipeline. It is the [TEI](https://tei-c.org/)-based
XML format of the [TEITOK](https://www.teitok.org/) corpus platform, carrying spatially grounded linguistic and
named-entity annotations produced by UDPipe and NameTag. The files follow the conventions the TEITOK tools themselves
read and write ([flexiconv](https://github.com/ufal/flexiconv), [flexipipe](https://github.com/ufal/flexipipe),
teitok-tools), so they can go straight into a TEITOK project
([Importing into a TEITOK project](usage.md#importing-into-a-teitok-project)) and be read by flexiconv and flexipipe.
What each tool keeps on a round trip is listed there: spacing survives all of them; two upstream readers still lose
something (multi-word tokens in flexiconv, dependency heads in flexipipe).

Each document in the collection is serialised as a single `.teitok.xml` file that integrates four layers of
information in a consistent, machine-readable structure:

| Layer                 | Content                                                                                                                                                                                                                     |
|-----------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Layout**            | Page, text-block, and line boundaries with pixel bounding boxes from the source ALTO XML (page origin), scaled to the stored page images when those are available; without a layout, the pages and lines of the input table |
| **Morphology/syntax** | Per-token lemma, UPOS/XPOS tags, morphological features, and dependency relations produced by UDPipe 2; multi-word tokens ("abych" = aby + bych) as one surface `<tok>` with `<dtok>` words                                 |
| **Named entities**    | Entity spans with a coarse category (`PER`, `ORG`, `LOC`, `MISC`) and the raw NameTag label in `@onto` (OntoNotes, the default model), `@cnec` (CNEC 2.0) or `@archaeo` (the archaeological model)                          |
| **Facsimile links**   | `<surface>` elements in `<facsimile>` that tie each page to its companion image, enabling TEITOK's side-by-side text/image view                                                                                             |

The structure of a file, element by element: [TEITOK XML structure at a glance](reference/teitok.md#teitok-xml-structure-at-a-glance).

### Why TEITOK XML

Storing all enrichment layers in a single interoperable format offers several practical advantages over keeping
CoNLL-U, TSV, and image files in separate silos:

- **Full-text and attribute search.** TEITOK's built-in CQL/XPATH query engine lets users search across lemmas, NER
  types, POS tags, and raw text simultaneously.
- **Named entity access.** Entity spans (`<name type="PER" onto="PERSON">`) are first-class XML elements: queryable,
  stylable, and exportable independently of the surrounding tokens.
- **Mouseover information.** Hovering over any token in the TEITOK GUI surfaces its lemma, morphological features,
  and dependency relation without leaving the page view.
- **Page visualisation with spatial overlays.** Bounding box coordinates on every `<tok>`, `<lb>`, and `<div>` are
  used by TEITOK's facsimile viewer to overlay text highlights directly onto the scanned page image, making OCR
  quality immediately visible.
- **Layout-aware structure.** Text blocks (`<div type="TextBlock">`), lines (`<lb>`), and graphical elements
  (`<figure>`) preserve the physical layout of the original document.
- **Interoperability.** TEI/XML is a widely adopted standard in digital humanities; the files can be ingested by
  other TEI-aware tools (e.g. eXist-db, Oxygen XML Editor) without conversion.

### The format and the standards it builds on

TEITOK XML is not a schema of its own; it layers three sets of conventions, and this repository pins one profile of
them:

- **TEI P5** ([Guidelines](https://tei-c.org/guidelines/p5/)) gives the document skeleton: `teiHeader` (file,
  encoding and revision description), `facsimile`/`surface`/`graphic` for the page images, `text`/`body`/`div` for
  text blocks, `pb`/`lb` for page and line beginnings, `s` for sentences, `name` for named entities and `figure` for
  graphical regions.
- **TEITOK** (the corpus platform, [teitok.org](https://www.teitok.org/)) adds the tokenized layer it searches and
  displays: every token is a `<tok>` element inline in the running text, a multi-word token keeps its surface form
  with one `<dtok>` per syntactic word, the annotation lives in token attributes, and any element can carry
  `@bbox="x1 y1 x2 y2"` in the pixels of its page image. TEITOK files carry no TEI namespace (`xmlnsoff` keeps the
  URI without declaring it) and use plain `@id`s.
- **Annotation vocabularies** are those of the tools that produced them: Universal Dependencies (CoNLL-U) for
  `upos`, `feats`, `deprel` and `head`; the UDPipe model's own tag set for `xpos`; the NameTag model's entity labels
  (OntoNotes 5 by default, CNEC 2.0, or the archaeological types of #7) in `@onto`/`@cnec`/`@archaeo`, mapped to
  four coarse types in `@type` (`PER`, `ORG`, `LOC`, `MISC`) by [api_util/ner_types.py](../api_util/ner_types.py);
  a label no table knows becomes `type="MISC"` with the raw label in `@label`.
- **Format 2** is this repository's profile: [schemas/teitok/teitok.xsd](../schemas/teitok/teitok.xsd) plus the
  contract checks ([schemas/teitok/README.md](../schemas/teitok/README.md)), stamped `version="teitok-2"` in
  `appInfo`. The hub's document record ([atrium_document.schema.json](../atrium_document.schema.json)) points into
  it by id.

## Where the positions on the page come from

A word's box in the TEITOK file is only as precise as the layout it came from. The writer takes the layout of a
document from its ALTO file; else from a TEITOK file that flexiconv converted; else from the document's born-digital
record; else there is none ([How a TEITOK document is composed](reference/teitok.md#how-a-teitok-document-is-composed)).

| Layout                                                                    | Boxes in the TEITOK file                                                                                | How precise                                                                                      |
|---------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------|
| ALTO (`INPUT_ALTO_DIR`; the service's `alto` part)                        | every token aligned to an OCR string gets that string's box; lines, text blocks and figures keep theirs | measured: the OCR engine's word coordinates                                                      |
| a flexiconv conversion of PAGE XML, hOCR or ALTO (`FLEXICONV_ANNOTATE`)   | word and line boxes from the source; punctuation that flexiconv did not box has none                    | measured, as in the source                                                                       |
| a born-digital record (digital-convert's `POST /reformat` of a PDF, #42)  | line boxes from `lines[].bbox`; each word gets the share of its line box that its characters take       | estimated from line geometry, not measured; the TEITOK header says so; in PDF points (1/72 inch) |
| a flexiconv conversion of PDF, DOCX or text; a table alone; a DOCX record | none: the pages and lines only, without a facsimile                                                     | —                                                                                                |

The record's boxes are scaled as ALTO's are: to the page images, or by `IMAGE_DPI`. The service does neither and
answers in points; `POST /rescale` with `scale` = the images' DPI / 72 converts them
([service/README.md, Layout inputs](../service/README.md#layout-inputs)).

## ALTO-to-TEITOK XML generation and coordinate alignment

When `SAVE_TEITOK=true`, [teitok_alto.py](../api_util/teitok_alto.py) reads and processes the internal spatial
hierarchy of the ALTO source.

### Coordinate origin (`BBOX_ORIGIN`)

ALTO positions (`HPOS`, `VPOS`) are measured from the top-left corner of the page image, and TEITOK expects exactly
that: every TEITOK tool (flexiconv's ALTO/PAGE/hOCR import, teitok-tools) writes `bbox` as page-image pixels. So by
default (`BBOX_ORIGIN=page`) the coordinates are taken as they are, and `<surface lrx lry>` declares the page size.

Some collections publish page images **cropped to the print area**. For those, set `BBOX_ORIGIN=printspace`: the
page's `<PrintSpace>` origin is subtracted from every coordinate, and `<surface>` declares the PrintSpace size
instead.

```xml
<PrintSpace HEIGHT="2039" WIDTH="1254" VPOS="150" HPOS="200">
```

With the sample above, a block at `HPOS=220 VPOS=160` becomes `bbox="20 10 …"` on a `1254 × 2039` surface instead
of `bbox="220 160 …"` on a `1654 × 2339` one. Content outside the PrintSpace (e.g. marginalia) would get negative
coordinates; they are clamped to 0 and counted in a warning.

$$\text{Written Coordinate} = \text{round}((\text{ALTO Coordinate} - \text{Origin}) \times \text{Scale Factor})$$

where Origin is 0 for `page`, and the PrintSpace `HPOS`/`VPOS` for `printspace`.

### Scale factor: three tiers, per page

* **Companion image present (tier 1).** If `INPUT_PAGES_DIR` is set and matching images exist, the tool reads their
  pixel size from the file headers (PNG, JPEG, TIFF; no imaging library needed) and scales the reference extent to
  it: `sx = image width / Page WIDTH` (`/ PrintSpace WIDTH` under `printspace`). Worked example:
  [`data_samples/pages/CTX000000001-1.png`](../data_samples/pages/CTX000000001-1.png) is 827×1170, half the ALTO
  page. With `INPUT_PAGES_DIR=data_samples/pages`, page 1 of `CTX000000001` gets `<surface lrx="827" lry="1170">`
  and the first block moves from `220 160 1420 280` to `110 80 710 140`. Page 2 has no image and stays at tier 3.
  The image draws the ALTO boxes at half scale, so the overlay can be checked by eye
  (`tests/test_teitok_integration.py`).
* **User-set DPI (tier 2).** If no image is available, the scale is derived from the ALTO `<MeasurementUnit>`
  (`inch1200`, `mm10`, or `pixel`) mapped against the `IMAGE_DPI` and `ALTO_DPI` settings, or from a born-digital
  record's canvas unit (`pt`, 1/72 inch).
* **Native processing (fallback, tier 3).** If no image and no DPI is provided, the scale factor is `1.0`.

Two of these fall-backs are easy to miss, because the file stays valid, so the writer reports them on stderr (once
per document): a page with no `<doc_id>-<N>.<png|jpg|jpeg|tif|tiff>` in the image folder
(`[Warn] <doc>: no page image in … for page(s) …`: its boxes stay unscaled and its `facs` name is a guess, e.g.
page 2 in the worked example above), and tier 3 with an ALTO `MeasurementUnit` other than `pixel`
(`MeasurementUnit is mm10 …`: the boxes are then in 1/10 mm, not pixels; set `INPUT_PAGES_DIR` or `IMAGE_DPI`).

In every tier `<surface lrx lry>` is the extent of the space the bboxes are measured in, so `POST /rescale` and
`fix_teitok_bboxes.py` can rescale a document to any other image size
([Fixing bounding box alignments](usage.md#fixing-bounding-box-alignments)).

**Relative coordinates.** Resolution-independent (0–1) bounding boxes were proposed upstream
([ufal/flexiconv#1](https://github.com/ufal/flexiconv/issues/1)) and have not been answered or adopted; TEITOK uses
absolute pixels.

### What the writer keeps of the ALTO hierarchy

The structural and spatial hierarchy of the ALTO file is preserved in the generated TEITOK XML:

* **Tokens.** Matched coordinates are written to each `<tok>` element as `@bbox="x1 y1 x2 y2"` (page-image pixels,
  the TEITOK convention). Each token also carries `@type="w"` (word) or `@type="pc"` (punctuation character),
  derived from UDPipe's UPOS tag. Alignment runs on the *surface* tokens: for a multi-word token such as "abych" the
  one `<tok>` gets the bbox, its `<dtok>` words none.
* **Lines.** ALTO `<TextLine>` elements are preserved as `<lb id="lb-P.L">` (line break) tags, which also carry
  their own `@bbox`.
* **Blocks.** ALTO `<TextBlock>` elements become `<div type="TextBlock" id="b-P.K">` containers. Their `@subtype` is
  the label of the block's ALTO `TAGREFS` tag (e.g. `paragraph`, `heading`), and their `@lang` is set where the
  block's ALTO `LANG` differs from the document's. Without ALTO there is one `<div type="text">` per page.
* **Graphics.** Non-text elements such as `Illustration` and `GraphicalElement` blocks are parsed and appended to
  their pages as `<figure id="fig-P.K">` tags with their bounding boxes.
* **Pages.** Page boundaries are marked with `<pb n="N" id="pb-N" facs="..." corresp="#facs-N" bbox="0 0 W H"/>`
  elements pointing to the page's `<surface>`. A token is on the page of the ALTO string it aligned to; a token that
  did not align is on the page of its line in the rows file. Pages only move forward, so every page gets exactly one
  `<pb>` (pages without text included). A sentence running over a page break gets its `<pb/>` inside the `<s>`
  (inside the `<name>`, too, when an entity runs over), and the figures of that page follow the sentence. A `<div>`
  stays on the page it opens on.

When a token's matched ALTO strings span more than one page (a rare OCR edge case near page boundaries), a warning
on stderr names the token and the conflicting page indices. The first matched page is used for the bbox in that
case.

### Named-entity spans

Named entity spans are wrapped in `<name>` elements grouping their constituent `<tok>` nodes, with `@sameAs` listing
the token ids. `@type` holds the coarse category (`PER`, `ORG`, `LOC`, or `MISC`, from
[api_util/ner_types.py](../api_util/ner_types.py), the same map the document record's `entities[].type_teitok`
uses), and the raw NameTag label goes in the attribute of its tag set: `@onto` for the default multilingual
OntoNotes model (`<name type="PER" onto="PERSON">`), `@cnec` for the Czech CNEC 2.0 model
(`<name type="PER" cnec="pf">`), `@archaeo` for the archaeological model.

### How tokens are matched to OCR strings

Tokens are matched to ALTO strings by sequence matching on their text, which tolerates the minor character
variations that broke the older greedy matching. Alignment statistics (matched vs. total tokens) are printed to the
console per document; below 90 % a warning asks whether text and layout come from the same document version (e.g.
ocr-postprocess's text with a flexiconv layout). A token that aligned to a page out of reading order loses its box
(the longest in-order run of aligned pages is kept). What can still go wrong with a valid file:
[Pitfalls](reference/teitok.md#pitfalls).
