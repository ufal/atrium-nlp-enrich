# Development

For contributors: the checks to run before a commit, where each maintenance procedure is written down, the
maintainers' working records and the history of the repository. How to contribute (branches, pull requests, commit
messages, the test layout) and the release history are in
[CONTRIBUTING.md](../CONTRIBUTING.md); this page does not repeat them.

```bash
pip install -r requirements-test.txt         # pytest, jsonschema, lxml, openpyxl, the pinned FastAPI test stack
pytest -q                                    # the whole suite, offline: no LINDAT, no models, no GPU
ruff check . && ruff format --check .
shellcheck -e SC1091 api_*.sh api_util/*.sh setup_api_service.sh
python atrium_openapi.py export --app service.api:app --out service/openapi.json   # after an API change
```

The tests check the pipeline's behaviour, the formats and the contracts; they stand in for UDPipe and NameTag, so
they say nothing about the quality of the annotation.

| When you change                                               | Read                                                                                                                                                             |
|---------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| the TEITOK writer (`api_util/teitok_alto.py`)                 | [schemas/teitok/README.md, Keeping this schema current](../schemas/teitok/README.md#keeping-this-schema-current): the XSD, the samples and fixtures move with it |
| the TEITOK readers (`teitok_read.py`, `flexiconv_convert.py`) | [Pitfalls](reference/teitok.md#pitfalls), item 9: re-vendor them into atrium-keyword-extract and atrium-digital-convert                                          |
| the service's API                                             | [service/README.md, OpenAPI](../service/README.md#openapi-the-typed-contract) and [Tests](../service/README.md#tests)                                            |
| a key of `config_api.txt` or an output flag                   | [CONTRIBUTING.md, Output Format Flags](../CONTRIBUTING.md#output-format-flags) and [configuration](configuration.md)                                             |
| the shared modules (`atrium_*.py`, the record schema)         | nothing here: they are vendored from the hub and never edited in this repository ([the record schema](reference/paradata.md#document-record-schema))             |

## Working records

[`agent_dev_logs/`](../agent_dev_logs) is the maintainers' working record. It holds the DEVLOG, a digest and a plan
for each issue, and the issue exports. It is not documentation for users or operators: it cites files and decisions
that have since moved or been deleted. Every other page cites the issue instead. This is the only page that points
to it.

## History of the repository

- **October 2026: keywords and the LLM stage left.** A meeting on 30 September 2026 cut the ATRIUM tools along the
  pipeline's stages instead of along their history. This repository became the morphology, named-entity and TEITOK
  stage only. Keyword extraction moved to [atrium-keyword-extract](https://github.com/ufal/atrium-keyword-extract)
  (`POST /extract_keywords`), and the LLM semantic-enrichment code left with the atrium-llm-enrich split. The change
  was released as v1.0.0-beta and is a breaking change to the API. The image `atrium-nlp-enrich-llm` was published up
  to 0.23.0 only and is not built any more. What moved where, and what the API lost:
  [the decision record](decisions/2026-10-01-repository-split.md).
- **The chain before this stage.** This stage follows
  [atrium-ocr-postprocess](https://github.com/ufal/atrium-ocr-postprocess),
  whose line tables carry the text of each ALTO line, ordered by LayoutReader, in a `text` column.
- **Release history.** Every release is in [CONTRIBUTING.md](../CONTRIBUTING.md#release-history).
