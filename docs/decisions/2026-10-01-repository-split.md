# 2026-10-01: keywords and the LLM stage leave nlp-enrich

**In short:** keyword extraction and the LLM stage left nlp-enrich on 2026-10-01. It now covers morphology, named
entities and TEITOK only, and keywords are atrium-keyword-extract's `POST /extract_keywords`. For a user, the keyword
parameters and response fields are gone from this API, and records written before the change read as before. The
page does not describe how keywords are produced today: that is in atrium-keyword-extract's README.

**Decision:** keyword extraction and the LLM controlled-vocabulary stage leave nlp-enrich; it keeps the morphology,
named-entity and TEITOK stage.

**Status:** done, released as v1.0.0-beta. The API change is breaking, hence the major version.

**Why:** the meeting of 30 September 2026 cut the ATRIUM tools along the pipeline's stages instead of along their
history ([the hub's development history](https://ufal.github.io/atrium-project/development-history/)).

**Consequence:** the API lost the `kw_method` and `num_keywords` parameters, some response fields and a block of
`/info`; the image `atrium-nlp-enrich-llm` is not built any more; the keyword licences moved with the code. The
details are in the record below.

> Dated note, released as v1.0.0-beta. Moved from the README's "Where things went" in the documentation overhaul
> ([atrium-project#79](https://github.com/ufal/atrium-project/issues/79)); the text is as last edited on 2026-10-05.

For readers looking for something that used to be here. Since v1.0.0-beta this repository is the morphology /
named-entity / TEITOK stage only. The October 2026 split of the ATRIUM tool repositories moved the rest:

| What                                                             | Now in                                                                                                                                                                                                                       | Was                                    |
|------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------|
| Keyword extraction: KeyBERT, YAKE, KER; `POST /extract_keywords` | [atrium-keyword-extract](https://github.com/ufal/atrium-keyword-extract)                                                                                                                                                     | `keywords.py`, `--kw*`, `kw_method`    |
| The LLM controlled-vocabulary stage                              | [atrium-keyword-extract](https://github.com/ufal/atrium-keyword-extract), by way of atrium-llm-enrich and atrium-digital-convert (until atrium-keyword-extract#2 lands, the code is at atrium-digital-convert `v1.0.0-beta`; it has since moved to atrium-keyword-extract) | `llm_run.py`, `vocab_*.py`, `prompts/` |
| OCR output postprocessing (ALTO and the other OCR formats)       | [atrium-ocr-postprocess](https://github.com/ufal/atrium-ocr-postprocess)                                                                                                                                                     | `atrium-alto-postprocess`              |

The API lost the `kw_method` and `num_keywords` parameters, the `keywords`, `method_requested`, `method_used` and
`llm` response fields and the `keyword_methods` block of `/info`: a breaking change, hence the major version.
Records written before it are read as before.

The images: `atrium-nlp-enrich-llm` was published up to 0.23.0 only and is not built any more. The licences of the
keyword methods and the vocabularies moved with them, to atrium-keyword-extract's `para_config.txt`.

Since this note, atrium-keyword-extract carries the controlled (LLM) kind itself; its README describes the current
state ([atrium-keyword-extract](https://github.com/ufal/atrium-keyword-extract#readme)). The release history of
this repository is in [CONTRIBUTING.md](../../CONTRIBUTING.md#release-history).
