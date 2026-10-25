# Development

For contributors: the checks to run before a commit, and where each maintenance procedure is written down. How to
contribute (branches, pull requests, commit messages, the test layout) and the release history are in
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

The design record of every issue is in [`agent_dev_logs/`](../agent_dev_logs) (digests, plans and the DEVLOG).
