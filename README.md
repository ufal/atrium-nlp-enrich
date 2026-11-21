# ATRIUM nlp-enrich: lemmas, syntax and named entities of text lines, as TEITOK

nlp-enrich analyses the text lines of archival documents: it finds each word's lemma (dictionary form), part of speech
and grammar, and the people, places and organisations the text names. It writes one TEITOK file per document, a format
for searching text and showing it over the scan, with tables beside it. In the AMČR pipeline it reads the document's
ATRIUM record, which gives the text and the page layout, and adds the linguistic layer and the entities to it. The
analysis runs at LINDAT, so it needs network access to its servers.

Until the terms of LINDAT's services are settled ([atrium-project#78](https://github.com/ufal/atrium-project/issues/78)),
AMČR does not publish outputs made through them: the linguistic layer, the entities, the TEITOK file and the English
metadata.

[Releases](https://github.com/ufal/atrium-nlp-enrich/releases) · [MIT licence](LICENSE) ·
[ATRIUM documentation](https://ufal.github.io/atrium-project/workflows/nlp-enrich/)

## Inputs and outputs

| Input                                                                                                                                                                              | Output                                                                                                                                                     |
|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------|
| the document's ATRIUM record (JSON, schema 2.0), which gives the lines, their pages and their boxes                                                                                | the record with its linguistic fields (`lines[].lemma`, `upos`, `feats`) and its `entities` block, each entity pointing at its `<name>` in the TEITOK file |
| for research and batch use: a line table, CSV or XLSX with a `text` column and optional `page_index`, `page`, `line` (ocr-postprocess's `DOC_LINE_CATEG/`); a `.txt`; inline lines | per document: CoNLL-U, a plain-text format for annotated sentences, with lemmas, tags, features and syntax; named entities per page                        |
| optionally another layout for a table: the ALTO it was made from, or a TEITOK file converted by flexiconv; page images                                                             | TEITOK XML (`teitok-2`), checked against [its XSD](schemas/teitok/README.md) before it is written; the run's paradata                                      |

The record follows the hub's [document contract](https://ufal.github.io/atrium-project/ecosystem/document-contract/).
PDF, office files, PAGE XML and hOCR are converted to TEITOK by
[flexiconv](docs/usage.md#convert-other-input-formats-with-flexiconv) first, from the command line. The command line
and the service read the records, tables, `.txt` files and TEITOK files with the same code; what only one of them
does, and why, is in [the command line and the service](docs/usage.md#the-command-line-and-the-service). Every output
file is listed in [docs/reference/outputs.md](docs/reference/outputs.md).

## Quick start

**What you need:** Python 3.11 and a checkout, or Docker. Network access to LINDAT: the service calls LINDAT's
UDPipe 2 and NameTag 3 over HTTPS on every request, or the instances `UDPIPE_URL` and `NAMETAG_URL` name. It downloads
no model and needs no GPU.

Enrich a sample record of this repository, the record of a two-page born-digital report. From a checkout, start the
service in a second terminal:

```bash
git clone https://github.com/ufal/atrium-nlp-enrich.git && cd atrium-nlp-enrich
python3.11 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r service/requirements.txt
python -m service.api                    # serves on port 8000; leave it running
```

Then call it from the first one:

```bash
curl --fail-with-body -sS -X POST localhost:8000/enrich \
  -F "document_json=@tests/fixtures/record_layout/two_column.document.json" --create-dirs -o out/two_column.json
```

The same from the published image, started in the background and stopped at the end:

```bash
docker run -d --name atrium-nlp-enrich -p 8000:8000 ghcr.io/ufal/atrium-nlp-enrich-api:<version>   # 2.0.0-beta or later, without its v
until curl -fsS localhost:8000/ready >/dev/null; do sleep 2; done
curl --fail-with-body -sS -X POST localhost:8000/enrich \
  -F "document_json=@tests/fixtures/record_layout/two_column.document.json" --create-dirs -o out/two_column.json
docker rm -f atrium-nlp-enrich
```

Expected result (abridged):

```json
{"doc_id": "two_column", "pages": 2, "layout_source": "record",
 "teitok_schema_valid": true, "teitok_schema_errors": [], "limits_applied": [],
 "ne_summary": [{"file": "two_column", "page": "1", "entities": [
   {"text": "Horni Mez", "type": "Countries, cities, states", "count": "1"},
   {"text": "Hradiste u Horni Mezi", "type": "Countries, cities, states", "count": "1"}]}, …],
 "document_json": {"entities": [{"surface": "Horni Mez", "type_teitok": "LOC", "type_onto": "GPE", "teitok_ref": "n-1",
                                 "page": "i", "line": 1, "bbox": [148.518, 19.863, 189.027, 28.863]}, …], …},
 "teitok_xml": "<?xml …", "stages": ["…"], "paradata": {"@type": "CreateAction", "…": "…"}}
```

`teitok_xml` is the document in TEITOK: every word is a `<tok>` with its lemma and tags, and with a `bbox` estimated
from its line's box in the record. The record comes back in `document_json` with the entities and each line's
linguistic fields. The entities found depend on the NameTag model LINDAT serves. Without access to LINDAT, after the
retries (about a minute), the answer is 502 `upstream_unavailable`, its `detail` starting
`LINDAT UDPipe did not answer after 5 retries`. Releases before 2.0.0-beta are described by the README at their tag.

The same four stages run over line tables from a checkout with `python3 run_pipeline.py`, over the tables
`config_api.txt` names ([usage](docs/usage.md#run-the-whole-pipeline-run_pipelinepy)).

## How it works

Stage 1 collects the lines of each document in page and line order and keeps the page of every line. Stage 2 sends
the text to UDPipe 2 in pieces cut at line ends; stage 3 sends the result to NameTag 3. Stage 4 merges both into
tables, CoNLL-U with the entities and TEITOK XML. It takes the layout from the record, an ALTO file or a converted
TEITOK file, matches each token to its OCR word or line to give it a box, and checks every TEITOK file against the
format before it finishes. The detail: [docs/how-it-works.md](docs/how-it-works.md).

## Where it fits in ATRIUM

In the AMČR pipeline nlp-enrich follows ocr-postprocess, the record builder: the record's lines are its text and,
with their boxes and docproc blocks, the TEITOK file's layout, whether they came from a born-digital text layer, the
ATR (AIS CR's text-recognition service) or both. No ALTO is produced or stored in the pipeline; reading ALTO stays for
batch and research use. [keyword-extract](https://github.com/ufal/atrium-keyword-extract) follows it and reads the
record it leaves. The opt-in `/project_record` can then carry the page categories and keywords back into the TEITOK
header. Its image `ghcr.io/ufal/atrium-nlp-enrich-api` is the production service of the step. The whole route: the
hub's [Pipelines](https://ufal.github.io/atrium-project/pipelines/#the-route-through-the-pipeline) page and this
tool's [workflow page](https://ufal.github.io/atrium-project/workflows/nlp-enrich/). Its SSH Open Marketplace record:
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
- **Positions differ in precision.** With ALTO, a word gets the box of the OCR word it is matched to. A record has
  line boxes at best, so its word boxes are estimated from the line geometry, in the record's
  coordinate space; a line whose box is only its block's (`bbox_precision: derived`, ATR text without line breaks)
  gets no coordinates, and the TEITOK header says how many. A flexiconv-converted PDF and a table alone give no boxes
  ([where the positions come from](docs/how-it-works.md#where-the-positions-on-the-page-come-from),
  [TEITOK](docs/reference/teitok.md)).
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
[para_config.txt](para_config.txt). Each run lists the components it used, each with its own licence or terms. No
licence of an output is computed: the rights in an output follow the source document (the hub's
[Licences and paradata](https://ufal.github.io/atrium-project/ecosystem/licences/)).
Cite with [CITATION.cff](CITATION.cff).

Developed by [ÚFAL](https://ufal.mff.cuni.cz/), Charles University. Funded by the European Union under Horizon Europe
([ATRIUM](https://atrium-research.eu/), GA 101132163), with the support of the LINDAT/CLARIAH-CZ (LM2023062) and AIS
CR (LM2023031) research infrastructures, funded by the Ministry of Education, Youth and Sports of the Czech Republic.
Contact: the [issue tracker](https://github.com/ufal/atrium-nlp-enrich/issues), or lutsai@ufal.mff.cuni.cz.

Keyword extraction and the LLM stage left this repository in October 2026; see
[History of the repository](docs/development.md#history-of-the-repository).
