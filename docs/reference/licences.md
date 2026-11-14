# Licences

For anyone who will publish or reuse what the pipeline produces: which components a run uses, and the licence or
terms under which each is offered.

The code is **MIT** ([LICENSE](../../LICENSE)). The components a run uses are listed below, each with its own
licence or, for a web service, the terms it is offered under. [para_config.txt](../../para_config.txt) declares
them, and every run's paradata lists the ones it used ([paradata](paradata.md)).

| Component                                                                                                        | Licence or terms                                                        | When                                                                                       |
|------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------|--------------------------------------------------------------------------------------------|
| the LINDAT UDPipe and NameTag services                                                                           | [LINDAT Terms of Use](https://lindat.mff.cuni.cz/en/terms-of-use)       | every run, unless `UDPIPE_URL` and `NAMETAG_URL` point at other instances                  |
| UDPipe 2 model, `czech-pdt-ud-2.15-241121` (`MODEL_UDPIPE`)                                                      | CC BY-NC-SA 4.0                                                         | every run (stage 2); declared `always`                                                     |
| NameTag 3 model: the multilingual OntoNotes model, the default `MODEL_NAMETAG`; the Czech CNEC 2.0 one, optional | CC BY-NC-SA 4.0                                                         | every run (stage 3); declared `always`                                                     |
| UDPipe 2 and NameTag 3 engines                                                                                   | MPL 2.0                                                                 | the software behind the services, which this repository calls over HTTP; `conditional`     |
| [flexiconv](https://github.com/ufal/flexiconv), pinned v0.3.12                                                   | MIT ([LICENSE](https://github.com/ufal/flexiconv/blob/v0.3.12/LICENSE)) | only when `api_flexiconv.sh` converts documents; never in the service image; `conditional` |

`always` components are listed for every core run; `conditional` ones only when a run logs them. flexiconv's
LICENSE file and, from v0.3.12, its package metadata say MIT, so `pip show` reports MIT. If you publish work that
used it, cite it as its [CITATION.cff](https://github.com/ufal/flexiconv/blob/v0.3.12/CITATION.cff) asks.

## What the list does not say

The list says what a run used. It does not set the rights in what the run produces. A licence covers what it is
attached to, the LINDAT services have terms of use rather than a licence for their output, and the rights in an
output depend first on the source document, which no tool knows. How the models' licence and the services' terms
bear on the annotations is an open question ([atrium-project#78](https://github.com/ufal/atrium-project/issues/78),
[#6](https://github.com/ufal/atrium-project/issues/6)).

No licence of an output is computed or recorded: since paradata schema 3.0 and record schema 2.0
([atrium-project#84](https://github.com/ufal/atrium-project/issues/84), D2) neither carries a `license` field, and the
paradata list the components, each with its own terms, as facts. Until #78 is settled, AMČR does not publish what this
tool produces through UDPipe and NameTag (D35)
([Licences and paradata](https://ufal.github.io/atrium-project/ecosystem/licences/) on the hub).

Keyword extraction (KER, YAKE, KeyBERT) and the AMČR/TEATER vocabularies (CC0) are declared in
[atrium-keyword-extract](https://github.com/ufal/atrium-keyword-extract)'s `para_config.txt` since v1.0.0-beta of
this repository.
