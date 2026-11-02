# ATRIUM nlp-enrich: lemmas, syntax and named entities of text lines, as TEITOK

nlp-enrich analyses the text lines of archival documents: it finds each word's lemma (dictionary form), part of speech
and grammar, and the people, places and organisations the text names. It writes one TEITOK file per document, a format
for searching text and showing it over the scan, with tables beside it. Use it on the line tables from ocr-postprocess
or on a born-digital record from digital-convert. The analysis runs at LINDAT, so it needs network access to its
servers.

[Releases](https://github.com/ufal/atrium-nlp-enrich/releases) · [MIT licence](LICENSE) ·
[ATRIUM documentation](https://ufal.github.io/atrium-project/workflows/nlp-enrich/)

## Inputs and outputs

| Input                                                                                                                                            | Output                                                                                                                                                                                    |
|--------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| a line table: CSV or XLSX with a `text` column and optional `page_num`, `line_num` (ocr-postprocess's `DOC_LINE_CATEG/`); a `.txt`; inline lines | per document: CoNLL-U with lemmas, tags, features and syntax; named entities per page (TSV); tokens, lemmas and entities as CSV and as CoNLL-U; an entity summary of the collection (CSV) |
| optionally a layout: the ALTO the table was made from, a TEITOK file converted by flexiconv, or a born-digital ATRIUM record; page images        | TEITOK XML (`teitok-2`), checked against [its XSD](schemas/teitok/README.md) before a stage ends; with a layout, word boxes and a facsimile                                               |
| optionally the ATRIUM document record (JSON) to add to                                                                                           | the record with its `entities` block, each entity pointing at its `<name>` in the TEITOK file; paradata (JSON) of every stage and of the run                                              |

The record follows the hub's [document contract](https://ufal.github.io/atrium-project/ecosystem/document-contract/).
PDF, office files, PAGE XML and hOCR are converted to TEITOK by
[flexiconv](docs/usage.md#convert-other-input-formats-with-flexiconv)
first, from the command line. The command line and the service read the tables, `.txt` files, TEITOK files and
records with the same code; what only one of them does, and why, is in
[the command line and the service](docs/usage.md#the-command-line-and-the-service). Every output file is listed in
[docs/reference/outputs.md](docs/reference/outputs.md); example output of the three synthetic sample documents is in
[data_samples/TEITOK/](data_samples/TEITOK) and its neighbours.

## Quick start

**What you need:** Docker for the published image and a clone of this repository for the sample files, or Python 3.11
and a checkout for the command line. The service calls LINDAT's UDPipe 2 and NameTag 3 over HTTPS on every request,
or the instances `UDPIPE_URL` and `NAMETAG_URL` name. It downloads no model and needs no GPU.

The service from the published image, on a sample table and its ALTO from this repository:

```bash
git clone https://github.com/ufal/atrium-nlp-enrich.git && cd atrium-nlp-enrich
docker run --rm -p 8000:8000 ghcr.io/ufal/atrium-nlp-enrich-api:<version>   # the release without its v, e.g. 1.3.1-beta
curl --fail-with-body -sS -X POST localhost:8000/enrich \
  -F "file=@data_samples/DOC_LINE_CATEG/CTX000000001.csv" \
  -F "alto=@data_samples/ALTO/CTX000000001.alto.xml" -o out.json
```

Expected result (abridged):

```json
{"doc_id": "CTX000000001", "pages": 2, "layout_source": "alto",
 "teitok_schema_valid": true, "teitok_schema_errors": [], "limits_applied": [],
 "ne_summary": [{"file": "CTX000000001", "page": "1", "entities": [
   {"text": "Hradiště u Horní Mezí", "type": "Countries, cities, states", "count": "1"},
   {"text": "Jan Novotný", "type": "People, including fictional", "count": "1"}]}],
 "teitok_xml": "<?xml …", "stages": ["…"], "paradata": {"@type": "CreateAction", "…": "…"}}
```

`teitok_xml` is the document in TEITOK: every word is a `<tok>` with its lemma and tags, and with a `bbox` on the
1654 × 2339 page where it matched an ALTO word. The two entities are `<name type="LOC" onto="GPE">` and
`<name type="PER" onto="PERSON">`. Without the `alto` part, `layout_source` is `rows`: pages and lines, no boxes.
The entities found depend on the NameTag model LINDAT serves.

The request calls LINDAT's UDPipe 2 and NameTag 3 (`UDPIPE_URL`, `NAMETAG_URL`), so the container needs outbound
HTTPS. Without it, after the retries (about a minute), the answer is 502 `upstream_unavailable`, its `detail`
starting `LINDAT UDPipe did not answer after 5 retries`. `POST /rescale`, which fits the boxes of a finished TEITOK
file to page images of another size, needs no network.

The same four stages run from a checkout with `python3 run_pipeline.py`, over the tables `config_api.txt` names
([usage](docs/usage.md#run-the-whole-pipeline-run_pipelinepy)).

## How it works

Stage 1 collects the lines of each document in page and line order and keeps the page of every line. Stage 2 sends
the text to UDPipe 2 in pieces cut at line ends; stage 3 sends the result to NameTag 3. Stage 4 merges both into
tables, CoNLL-U with the entities and TEITOK XML. It takes the layout from ALTO, a converted TEITOK file or the
record, matches each token to its OCR word to give it a box, and checks every TEITOK file against the format before
it finishes. The detail: [docs/how-it-works.md](docs/how-it-works.md).

## Where it fits in ATRIUM

nlp-enrich is the fourth stage of the scanned-document chain: it reads ocr-postprocess's line tables and the
original ALTO. For a born-digital PDF it follows digital-convert, whose record gives the TEITOK file its layout.
[keyword-extract](https://github.com/ufal/atrium-keyword-extract) follows it and reads the record it leaves. The
opt-in `/project_record` can then carry the page categories and keywords back into the TEITOK header. Its image
`ghcr.io/ufal/atrium-nlp-enrich-api` is the production service of the stage. The whole chain: the
[hub's workflow page](https://ufal.github.io/atrium-project/workflows/nlp-enrich/). Its SSH Open Marketplace record:
[NLP enrichment of text lines into TEITOK (UDPipe 2, NameTag 3) -
ATRIUM](https://marketplace.sshopencloud.eu/tool-or-service/EMhu3X).

## Limits and maturity

- **LINDAT is required.** Every run sends the text to LINDAT's UDPipe 2 and NameTag 3, or to the instances
  `UDPIPE_URL` and `NAMETAG_URL` name; there is no local fallback. Without them a run stops with exit code 6 or 7
  and the service answers 502 or 504, so plan for network access or your own instances
  ([exit codes](docs/usage.md#exit-codes)).
- **Czech only.** Both entry points take `cs` only (`--lang`, `lang`), and the UDPipe model is
  `czech-pdt-ud-2.15-241121`. Named entities come from NameTag's general multilingual OntoNotes model, not an
  archaeological one, so its entity types are general. The kit for annotating archaeological training data is in
  [annotation/](annotation/README.md).
- **Positions differ in precision.** With ALTO, a word gets the box of the OCR word it is matched to. A born-digital
  record has line boxes only, so its word boxes are estimated from the line geometry and are in PDF points. A
  flexiconv-converted PDF and a table alone give no boxes
  ([where the positions come from](docs/how-it-works.md#where-the-positions-on-the-page-come-from)).
- **`/jobs` are not durable.** A job lives in the memory of the replica that accepted it, so a restart or redeploy
  loses it (404) and the caller submits it again. `/enrich` is the synchronous alternative
  ([Known limits](service/README.md#known-limits)).
- **Service limits.** Uploads are limited to 5 MB and 30,000 words by default. Split larger input or raise the
  settings ([Limits](service/README.md#limits)).
- **flexiconv is command-line only and optional.** The service takes its output but never runs it, so convert PDF,
  office files, PAGE XML and hOCR before you send them
  ([flexiconv](docs/usage.md#convert-other-input-formats-with-flexiconv)).
- **Two upstream TEITOK readers lose something.** flexiconv drops the words of a multi-word token and flexipipe the
  dependency heads, so check a round trip through them
  ([importing into a TEITOK project](docs/usage.md#importing-into-a-teitok-project)).
- **Not evaluated here.** The tests check the pipeline, the formats and the contracts, not the accuracy of UDPipe or
  NameTag on archival documents, so a person checks the annotation that matters.

## Documentation

| For                 | To                                                                    | Read                                                                                           |
|---------------------|-----------------------------------------------------------------------|------------------------------------------------------------------------------------------------|
| using it            | set it up; run the service, the command line or Docker; fix boxes     | [docs/usage.md](docs/usage.md)                                                                 |
|                     | find an output file, or what can be deleted                           | [docs/reference/outputs.md](docs/reference/outputs.md)                                         |
|                     | look up the TEITOK structure, its composition, tools and pitfalls     | [docs/reference/teitok.md](docs/reference/teitok.md)                                           |
|                     | read the paradata, the provenance and the record schema               | [docs/reference/paradata.md](docs/reference/paradata.md)                                       |
|                     | see the licences and terms of the components                          | [docs/reference/licences.md](docs/reference/licences.md)                                       |
| running the service | deploy and operate it, and read its limits and errors                 | [service/README.md](service/README.md)                                                         |
|                     | see the API contract                                                  | [service/openapi.json](service/openapi.json)                                                   |
|                     | set every key of `config_api.txt` and the LINDAT endpoints            | [docs/configuration.md](docs/configuration.md)                                                 |
| judging the results | check flexiconv on a real collection                                  | [docs/evaluation/flexiconv-collection-check.md](docs/evaluation/flexiconv-collection-check.md) |
|                     | check the TEITOK output contract (the XSD and its gate)               | [schemas/teitok/README.md](schemas/teitok/README.md)                                           |
| changing the code   | understand the stages, the TEITOK format and the coordinates          | [docs/how-it-works.md](docs/how-it-works.md)                                                   |
|                     | set up, test and release; find the history and the working records    | [docs/development.md](docs/development.md)                                                     |
|                     | follow the conventions; read the release history                      | [CONTRIBUTING.md](CONTRIBUTING.md)                                                             |
|                     | find what moved to other repositories                                 | [docs/decisions/2026-10-01-repository-split.md](docs/decisions/2026-10-01-repository-split.md) |
|                     | annotate archaeological named entities (training data)                | [annotation/README.md](annotation/README.md)                                                   |

Terms used across the tools are explained in the
[ATRIUM glossary](https://ufal.github.io/atrium-project/glossary/). The documentation follows the ATRIUM
[documentation style](https://github.com/ufal/atrium-project/blob/main/docs/documentation-style.md).

## Licence, citation and acknowledgements

The code is MIT ([LICENSE](LICENSE)). The annotation is done by LINDAT's
[UDPipe 2](https://lindat.mff.cuni.cz/services/udpipe/api-reference.php) and
[NameTag 3](https://lindat.mff.cuni.cz/services/nametag/api-reference.php) services, offered under the
[LINDAT Terms of Use](https://lindat.mff.cuni.cz/en/terms-of-use). Their engines are MPL 2.0 and the models in use
CC BY-NC-SA 4.0. [flexiconv](https://github.com/ufal/flexiconv) (MIT) is an optional command-line
converter. Each component with its licence or terms: [docs/reference/licences.md](docs/reference/licences.md), from
[para_config.txt](para_config.txt). These do not by themselves set the rights in an output, which depend first on
the source document: see the hub's [Licences and paradata](https://ufal.github.io/atrium-project/ecosystem/licences/).
Cite with [CITATION.cff](CITATION.cff).

Developed by [ÚFAL](https://ufal.mff.cuni.cz/), Charles University. Funded by [ATRIUM](https://atrium-research.eu/)
(GA 101132163), with the support of the LINDAT/CLARIAH-CZ research infrastructure and the AIS CR infrastructure
(LM2023031). Contact: the [issue tracker](https://github.com/ufal/atrium-nlp-enrich/issues), or
lutsai@ufal.mff.cuni.cz.

Keyword extraction and the LLM stage left this repository in October 2026; see
[History of the repository](docs/development.md#history-of-the-repository).
