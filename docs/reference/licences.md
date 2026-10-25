# Licences

For anyone who will publish or reuse what the pipeline produces: which components a run uses and under which
licence or terms each is offered, and what the licence label in the paradata does and does not mean.

The code is **MIT** ([LICENSE](../../LICENSE)). The components a run uses are listed below, each with its own
licence or, for a web service, the terms it is offered under. [para_config.txt](../../para_config.txt) declares
them, and every run's paradata lists the ones it used ([paradata](paradata.md)).

| Component                                                                                                        | Licence or terms                                                       | When                                                                                       |
|------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------|--------------------------------------------------------------------------------------------|
| the LINDAT UDPipe and NameTag services                                                                           | [LINDAT Terms of Use](https://lindat.mff.cuni.cz/en/terms-of-use)      | every run, unless `UDPIPE_URL` and `NAMETAG_URL` point at other instances                  |
| UDPipe 2 model, `czech-pdt-ud-2.15-241121` (`MODEL_UDPIPE`)                                                      | CC BY-NC-SA 4.0                                                        | every run (stage 2); declared `always`                                                     |
| NameTag 3 model: the multilingual OntoNotes model, the default `MODEL_NAMETAG`; the Czech CNEC 2.0 one, optional | CC BY-NC-SA 4.0                                                        | every run (stage 3); declared `always`                                                     |
| UDPipe 2 and NameTag 3 engines                                                                                   | MPL 2.0                                                                | the software behind the services, which this repository calls over HTTP; `conditional`     |
| [flexiconv](https://github.com/ufal/flexiconv), pinned v0.3.10                                                   | GPL-3.0-or-later (declared in its `pyproject.toml`; no `LICENSE` file) | only when `api_flexiconv.sh` converts documents; never in the service image; `conditional` |

`always` components count for every core run; `conditional` ones only when a run logs them.

## What the computed label means

From the list of components, the shared `para_licenses.py` also computes **one label**: the most restrictive of the
component licences. Every core run uses the UDPipe 2 and NameTag 3 models, so its label is CC BY-NC-SA 4.0;
converting with flexiconv adds its GPL-3.0-or-later. `run_pipeline.py` re-derives the label of its merged record
from the union of every component used across the stages.

The label is a warning about the components, **not the licence of the output**. A licence covers what it is
attached to; the LINDAT services have terms of use, not a licence for their output; and the rights in an output
depend first on the source document, which no tool knows. How the models' licence and the services' terms bear on
the annotations is an open question ([atrium-project#78](https://github.com/ufal/atrium-project/issues/78),
[#6](https://github.com/ufal/atrium-project/issues/6)). The hub explains it in
[Licences and paradata](https://ufal.github.io/atrium-project/ecosystem/licences/).

Keyword extraction (KER, YAKE, KeyBERT) and the AMČR/TEATER vocabularies (CC0) are declared in
[atrium-keyword-extract](https://github.com/ufal/atrium-keyword-extract)'s `para_config.txt` since v1.0.0-beta of
this repository.
