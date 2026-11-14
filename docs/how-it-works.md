# How nlp-enrich works

For anyone who wants the idea before the details. It answers three questions: what the four stages do to a document,
why the output is TEITOK, and how a word gets its place on the page image. The commands are in [usage](usage.md).
Every element of the TEITOK file is in the [TEITOK reference](reference/teitok.md), and every option in the
[configuration](configuration.md).

On this page: [the flow](#the-flow) · [the four stages](#the-four-stages) ·
[TEITOK XML, the output format](#teitok-xml-the-output-format) ·
[where the positions on the page come from](#where-the-positions-on-the-page-come-from) ·
[ALTO-to-TEITOK generation and coordinate alignment](#alto-to-teitok-xml-generation-and-coordinate-alignment)

## The flow

```
 line table (CSV, XLSX, .txt), or the record      layout, optional: the record | ALTO | flexiconv TEITOK
        |                                                          |      page images, optional
        v                                                          v
 1 manifest --> 2 UDPipe 2 (LINDAT) --> 3 NameTag 3 (LINDAT) --> 4 merge and write --> CSV, CoNLL-U, TEITOK XML,
   text, rows     CoNLL-U                 entities per page                              the record's entities and lines, paradata
```

The command line runs the four stage scripts in order, `api_1_manifest.sh` … `api_4_stats.sh`, by hand or through
`run_pipeline.py`. The service runs `run_pipeline.py` in a fresh workspace for each request
([service/README.md, How it works](../service/README.md#how-it-works)). Annotation happens on LINDAT's servers;
this repository prepares the text, calls the services and assembles their answers.

## The four stages

Each stage script sources [config_api.txt](../config_api.txt) directly for its configuration. Retry logic and
per-attempt error handling live inside the Python helper scripts
([call_udpipe.py](../api_util/call_udpipe.py), [call_nametag.py](../api_util/call_nametag.py)). They use exponential
back-off, set by the `MAX_RETRIES` and `BACKOFF_FACTOR` variables.
[api_util/api_common.sh](../api_util/api_common.sh) is a standalone utility module. It exposes a `log()` helper and
an `api_call_with_retry()` shell function for any custom script that sources it; the four main pipeline scripts do
not. [api_util/](../api_util/) also contains the helper Python scripts for chunking and analysis.

### 1. Manifest

Stage 1 maps the input tables to document ids and page counts, to ensure the correct processing order. It reads
every table or text file in `INPUT_TABLES_DIR` with [api_util/line_inputs.py](../api_util/line_inputs.py), the reader
of the service's uploads too. For each it writes a row of `<OUTPUT_DIR>/manifest.tsv`. Per document it writes
`TEMP_TXT_DIR/<doc_id>.txt` (one line per table row) and, next to it, `TEMP_TXT_DIR/<doc_id>.rows.tsv`: the page,
line, page label and text of every line. Stages 3 and 4 take page numbers from that rows file
([api_util/page_rows.py](../api_util/page_rows.py)).

When the script meets an `.xlsx` file, it goes through every sheet and extracts the content of each one that has a
`text` column. Excel tables with several sheets are therefore read safely.

### 2. UDPipe: morphology and syntax

Stage 2 sends the text to the [UDPipe 2 API](https://lindat.mff.cuni.cz/services/udpipe/api-reference.php). Large
documents are split into chunks (900 words by default) by [chunk.py](../api_util/chunk.py) to respect the API's
limits. The answers are merged back into one valid CoNLL-U file per document. Each CoNLL-U file gets its
`<doc_id>.rows.tsv` copied next to it. The text and its page provenance then stay together on resumed runs and in
containers, where `TEMP/` is not kept.

**Chunking and page boundaries.** [chunk.py](../api_util/chunk.py) splits text on OCR line boundaries, not raw
whitespace, and keeps the newline-separated structure of the source table. UDPipe therefore receives proper
sentence-boundary hints between lines. A chunk is about `WORD_CHUNK_LIMIT` words, **not a page**. When a document
spans several chunks, [call_udpipe.py](../api_util/call_udpipe.py) merges them into one CoNLL-U file and marks where
each chunk starts with `# chunk_start = K`. Pages come from the rows file instead. UDPipe marks every line end
(`SpacesAfter=\n`), so counting those marks, checked against the text of every row, places each token on its line
and page ([page_rows.py](../api_util/page_rows.py)). If the check fails, the characters are aligned instead. Without
a rows file, only an old per-page CoNLL-U file (whose `# sent_id` restarts at 1) has more than one page.

### 3. NameTag: named entities

Stage 3 passes the CoNLL-U files through the [NameTag 3 API](https://lindat.mff.cuni.cz/services/nametag/api-reference.php),
which annotates named entities directly in the syntax trees. It writes them page by page, as IOB TSV files
(`NE/<doc_id>/<doc_id>-P.tsv` holds the tokens of page P). A sentence that runs over a page is split between two
files, in order. The pages come from the rows file. The tags are the labels of the configured NameTag model
(`MODEL_NAMETAG`). The default multilingual model gives OntoNotes 5; the Czech one gives
[CNEC 2.0](https://ufal.mff.cuni.cz/~strakova/cnec2.0/ne-type-hierarchy.pdf).

### 4. Merge, statistics and TEITOK

Stage 4 consolidates the linguistic data from UDPipe (CoNLL-U) and the named entities from NameTag (TSV) into the
final per-document formats. It also writes a summary of entity counts across the whole collection. By default it
writes a TEITOK XML file per
document that merges the tokens with the page layout.

[summarize_nt_udp.py](../api_util/summarize_nt_udp.py) merges these layers and writes every output format. It maps
the NameTag labels to human-readable categories: CNEC 2.0 `g`, `pf`, `if` to "Geographical name", "First name",
"Company/Firm", and OntoNotes `GPE`, `PERSON` to "Countries, cities, states", "People, including fictional". The
TEITOK writer is [teitok_alto.py](../api_util/teitok_alto.py). Every TEITOK file is checked against its output
contract before the stage finishes, and a file that fails stops the stage with exit code `5`. What stage 4 reads
and writes: [the outputs reference](reference/outputs.md#stage-4-inputs-and-outputs).

## TEITOK XML, the output format

**TEITOK XML** (`.teitok.xml`) is the primary enriched output of this pipeline. It is the [TEI](https://tei-c.org/)-based
XML format of the [TEITOK](https://www.teitok.org/) corpus platform, carrying spatially grounded linguistic and
named-entity annotations produced by UDPipe and NameTag. The files follow the conventions the TEITOK tools themselves
read and write ([flexiconv](https://github.com/ufal/flexiconv), [flexipipe](https://github.com/ufal/flexipipe),
teitok-tools). They can therefore go straight into a TEITOK project
([Importing into a TEITOK project](usage.md#importing-into-a-teitok-project)) and be read by flexiconv and flexipipe.
That section lists what each tool keeps on a round trip. Spacing survives all of them; two upstream readers still
lose something (multi-word tokens in flexiconv, dependency heads in flexipipe).

Each document in the collection is serialised as a single `.teitok.xml` file that integrates four layers of
information in a consistent, machine-readable structure:

| Layer                 | Content                                                                                                                                                                                                                     |
|-----------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Layout**            | Page, text-block, and line boundaries with pixel bounding boxes from the source ALTO XML (page origin), scaled to the stored page images when those are available; without a layout, the pages and lines of the input table |
| **Morphology/syntax** | Per-token lemma, UPOS/XPOS tags, morphological features, and dependency relations produced by UDPipe 2; multi-word tokens ("abych" = aby + bych) as one surface `<tok>` with `<dtok>` words                                 |
| **Named entities**    | Entity spans with a coarse category (`PER`, `ORG`, `LOC`, `MISC`) and the raw NameTag label in `@onto` (OntoNotes, the default model), `@cnec` (CNEC 2.0) or `@archaeo` (reserved for #7's model, not trained yet)          |
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
- **Page visualisation with spatial overlays.** Bounding box coordinates on every `<tok>`, `<lb>`, and `<div>` let
  TEITOK's facsimile viewer overlay text highlights directly onto the scanned page image. OCR quality is then
  immediately visible.
- **Layout-aware structure.** Text blocks (`<div type="TextBlock">`), lines (`<lb>`), and graphical elements
  (`<figure>`) preserve the physical layout of the original document.
- **Interoperability.** TEI/XML is a widely adopted standard in digital humanities. Other TEI-aware tools (e.g.
  eXist-db, Oxygen XML Editor) can ingest the files without conversion.

### The format and the standards it builds on

TEITOK XML is not a schema of its own; it layers three sets of conventions, and this repository pins one profile of
them:

- **TEI P5** ([Guidelines](https://tei-c.org/guidelines/p5/)) gives the document skeleton. `teiHeader` holds the
  file, encoding and revision description; `facsimile`/`surface`/`graphic` hold the page images; `text`/`body`/`div`
  hold the text blocks. `pb`/`lb` mark page and line beginnings, `s` sentences, `name` named entities and `figure`
  graphical regions.
- **TEITOK** (the corpus platform, [teitok.org](https://www.teitok.org/)) adds the tokenized layer it searches and
  displays. Every token is a `<tok>` element inline in the running text. A multi-word token keeps its surface form
  with one `<dtok>` per syntactic word. The annotation lives in token attributes, and any element can carry
  `@bbox="x1 y1 x2 y2"` in the pixels of its page image. TEITOK files carry no TEI namespace (`xmlnsoff` keeps the
  URI without declaring it) and use plain `@id`s.
- **Annotation vocabularies** are those of the tools that produced them. Universal Dependencies (CoNLL-U) gives
  `upos`, `feats`, `deprel` and `head`, and the UDPipe model's own tag set gives `xpos`. The NameTag model's entity
  labels (OntoNotes 5 by default, CNEC 2.0, or the [archaeological types](../annotation/README.md)) go in
  `@onto`/`@cnec`/`@archaeo`. They are mapped to four coarse types in `@type` (`PER`, `ORG`, `LOC`, `MISC`) by
  [api_util/ner_types.py](../api_util/ner_types.py). A label no table knows becomes `type="MISC"` with the raw label
  in `@label`.
- **Format 2** is this repository's profile: [schemas/teitok/teitok.xsd](../schemas/teitok/teitok.xsd) plus the
  contract checks ([schemas/teitok/README.md](../schemas/teitok/README.md)), stamped `version="teitok-2"` in
  `appInfo`. The hub's document record ([atrium_document.schema.json](../atrium_document.schema.json)) points into
  it by id.

## Where the positions on the page come from

A word's box in the TEITOK file is only as precise as the layout it came from. The writer takes the layout of a
document from the first of these it finds: its ALTO file, a TEITOK file that flexiconv converted, or the document's
ATRIUM record. In the AMČR pipeline only the record is used: no ALTO is produced or stored (ARÚP's output contract of
12 November 2026, D24; ALTO and flexiconv input stay for batch and research use). If none exists, there is no layout
(see [How a TEITOK document is composed](reference/teitok.md#how-a-teitok-document-is-composed)).

| Layout                                                                    | Boxes in the TEITOK file                                                                                | How precise                                                                                      |
|---------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------|
| ALTO (`INPUT_ALTO_DIR`; the service's `alto` part)                        | every token aligned to an OCR string gets that string's box; lines, text blocks and figures keep theirs | measured: the OCR engine's word coordinates                                                      |
| a flexiconv conversion of PAGE XML, hOCR or ALTO (`FLEXICONV_ANNOTATE`)   | word and line boxes from the source; punctuation that flexiconv did not box has none                    | measured, as in the source                                                                       |
| the ATRIUM record (schema 2.0, the record builder's `lines[]`)            | line boxes from `lines[].bbox`; each word gets the share of its line box that its characters take       | estimated from line geometry, not measured; the TEITOK header says so; in the record's space     |
| … a line with `bbox_precision: derived` (its block's box, ATR text)       | none for the line and its words; the box bounds the block                                               | the header counts such lines                                                                     |
| a flexiconv conversion of PDF, DOCX or text; a table alone; a DOCX record | none: the pages and lines only, without a facsimile                                                     | —                                                                                                |

With the record as the layout, the record's own keys go back into it: `entities[].page` and `line` are the
record's, and each line gets the lemma, UPOS and features of its head token (the first word whose syntactic head lies
outside the line) and the id of that token's `<s>` as `teitok_ref`.

The record's boxes are scaled as ALTO's are: to the page images, or by `IMAGE_DPI`. The service does neither and
answers in points; `POST /rescale` with `scale` = the images' DPI / 72 converts them
([service/README.md, Layout inputs](../service/README.md#layout-inputs)).

## ALTO-to-TEITOK XML generation and coordinate alignment

When `SAVE_TEITOK=true`, [teitok_alto.py](../api_util/teitok_alto.py) reads and processes the internal spatial
hierarchy of the ALTO source.

### Coordinate origin (`BBOX_ORIGIN`)

ALTO positions (`HPOS`, `VPOS`) are measured from the top-left corner of the page image, and TEITOK expects exactly
that. Every TEITOK tool (flexiconv's ALTO/PAGE/hOCR import, teitok-tools) writes `bbox` as page-image pixels. So by
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
  pixel size from the file headers (PNG, JPEG, TIFF; no imaging library needed). It scales the reference extent to
  it: `sx = image width / Page WIDTH` (`/ PrintSpace WIDTH` under `printspace`). Worked example:
  [`data_samples/pages/CTX000000001-1.png`](../data_samples/pages/CTX000000001-1.png) is 827×1170, half the ALTO
  page. With `INPUT_PAGES_DIR=data_samples/pages`, page 1 of `CTX000000001` gets `<surface lrx="827" lry="1170">`
  and the first block moves from `220 160 1420 280` to `110 80 710 140`. Page 2 has no image and stays at tier 3.
  The image draws the ALTO boxes at half scale, so the overlay can be checked by eye
  (`tests/test_teitok_integration.py`).
* **User-set DPI (tier 2).** If no image is available, the scale is derived from the ALTO `<MeasurementUnit>`
  (`inch1200`, `mm10`, or `pixel`), mapped against the `IMAGE_DPI` and `ALTO_DPI` settings. For a born-digital
  record it comes from the canvas unit (`pt`, 1/72 inch).
* **Native processing (fallback, tier 3).** If no image and no DPI is provided, the scale factor is `1.0`.

Two of these fall-backs are easy to miss, because the file stays valid. The writer therefore reports them on stderr,
once per document. The first is a page with no `<doc_id>-<N>.<png|jpg|jpeg|tif|tiff>` in the image folder
(`[Warn] <doc>: no page image in … for page(s) …`): its boxes stay unscaled and its `facs` name is a guess, e.g.
page 2 in the worked example above. The second is tier 3 with an ALTO `MeasurementUnit` other than `pixel`
(`MeasurementUnit is mm10 …`): the boxes are then in 1/10 mm, not pixels, so set `INPUT_PAGES_DIR` or `IMAGE_DPI`.

In every tier `<surface lrx lry>` is the extent of the space the bboxes are measured in. `POST /rescale` and
`fix_teitok_bboxes.py` can therefore rescale a document to any other image size
([Fixing bounding box alignments](usage.md#fixing-bounding-box-alignments)).

**Relative coordinates.** The writer keeps absolute pixels, the form TEITOK's viewers read. flexiconv can also
write relative boxes in IIIF's region syntax, `bbox="pct:x,y,w,h"` (percentages of the page image; from ALTO with
`--option bbox=pct`, on flexiconv's `main` after v0.3.12; [ufal/flexiconv#1](https://github.com/ufal/flexiconv/issues/1)).
The readers here accept them: the core gate passes them, the layout reader turns them into pixels by the page's
size (`pb@bbox` or `surface@bbox`, which flexiconv writes beside them), and the rescale tools leave them as they
are. `api_flexiconv.sh` does not ask for them.

### What the writer keeps of the ALTO hierarchy

The structural and spatial hierarchy of the ALTO file is preserved in the generated TEITOK XML:

* **Tokens.** Matched coordinates are written to each `<tok>` element as `@bbox="x1 y1 x2 y2"` (page-image pixels,
  the TEITOK convention). Each token also carries `@type="w"` (word) or `@type="pc"` (punctuation character),
  derived from UDPipe's UPOS tag. Alignment runs on the *surface* tokens: for a multi-word token such as "abych" the
  one `<tok>` gets the bbox, its `<dtok>` words none.
* **Lines.** ALTO `<TextLine>` elements are preserved as `<lb id="lb-P.L">` (line break) tags, which also carry
  their own `@bbox`.
* **Blocks.** ALTO `<TextBlock>` elements become `<div type="TextBlock" id="b-P.K">` containers. Their `@subtype` is
  the label of the block's ALTO `TAGREFS` tag (e.g. `paragraph`, `heading`). Their `@lang` is set where the block's
  ALTO `LANG` differs from the document's. Without ALTO there is one `<div type="text">` per page.
* **Graphics.** Non-text elements such as `Illustration` and `GraphicalElement` blocks are parsed and appended to
  their pages as `<figure id="fig-P.K">` tags with their bounding boxes.
* **Pages.** Page boundaries are marked with `<pb n="N" id="pb-N" facs="..." corresp="#facs-N" bbox="0 0 W H"/>`
  elements pointing to the page's `<surface>`. A token is on the page of the ALTO string it aligned to. A token that
  did not align is on the page of its line in the rows file. Pages only move forward, so every page gets exactly one
  `<pb>` (pages without text included). A sentence running over a page break gets its `<pb/>` inside the `<s>`
  (inside the `<name>`, too, when an entity runs over). The figures of that page follow the sentence. A `<div>`
  stays on the page it opens on.

A token's matched ALTO strings can span more than one page, a rare OCR edge case near page boundaries. A warning on
stderr then names the token and the conflicting page indices, and the first matched page is used for the bbox.

### Named-entity spans

Named entity spans are wrapped in `<name>` elements grouping their constituent `<tok>` nodes, with `@sameAs` listing
the token ids. `@type` holds the coarse category (`PER`, `ORG`, `LOC`, or `MISC`, from
[api_util/ner_types.py](../api_util/ner_types.py), the same map the document record's `entities[].type_teitok`
uses). The raw NameTag label goes in the attribute of its tag set: `@onto` for the default multilingual
OntoNotes model (`<name type="PER" onto="PERSON">`), `@cnec` for the Czech CNEC 2.0 model
(`<name type="PER" cnec="pf">`), `@archaeo` for the archaeological model once
[#7](https://github.com/ufal/atrium-nlp-enrich/issues/7) trains one (none is trained yet).

### How tokens are matched to OCR strings

Tokens are matched to ALTO strings by sequence matching on their text, which tolerates the minor character
variations that broke the older greedy matching. Alignment statistics (matched vs. total tokens) are printed to the
console per document. Below 90 % a warning asks whether text and layout come from the same document version (e.g.
ocr-postprocess's text with a flexiconv layout). A token that aligned to a page out of reading order loses its box
(the longest in-order run of aligned pages is kept). What can still go wrong with a valid file:
[Pitfalls](reference/teitok.md#pitfalls).
