"""ner_types.py -- one mapping from NameTag labels to the coarse TEITOK entity types.

TEITOK ``<name type=...>`` and ``atrium_document`` ``entities[].type_teitok`` both use the
four-concept ``entity-type`` scheme (PER / ORG / LOC / MISC, SKOS-published by the hub's
``atrium_vocab.py``). NameTag emits one of three label sets, depending on the model:

* **CNEC 2.0** (``nametag3-czech-cnec2.0-*``): fine codes such as ``pf``, ``gu``, ``if``.
  ``CNEC_TO_CONLL`` is the authority the hub's ``atrium_vocab.CNEC_TO_ENTITY_TYPE`` mirrors
  (``tests/test_ner_types.py`` keeps the two equal); ``teitok_alto._CNEC_TO_CONLL`` is this
  same object, kept under the name the hub's registry points at.
* **OntoNotes 5** (``nametag3-multilingual-onto-*``, the pipeline default since #11):
  ``PERSON``, ``GPE``, ``ORG``, ...
* **Archaeological domain types** (the #7 NameTag model): ``LOCATION``, ``ARTEFACT``, ...

Before 2026-09 the TEITOK writer knew only CNEC, so every OntoNotes entity was written
``type="MISC" cnec="PERSON"`` while the document record mapped the same entity to PER.
"""

CNEC_TO_CONLL = {
    "p": "PER",
    "p_": "PER",
    "P": "PER",
    "pf": "PER",
    "ps": "PER",
    "pm": "PER",
    "ph": "PER",
    "pc": "PER",
    "pd": "PER",
    "pp": "PER",
    "i": "ORG",
    "i_": "ORG",
    "I": "ORG",
    "ia": "ORG",
    "if": "ORG",
    "io": "ORG",
    "ic": "ORG",
    "g": "LOC",
    "G": "LOC",
    "g_": "LOC",
    "gu": "LOC",
    "gl": "LOC",
    "gq": "LOC",
    "gr": "LOC",
    "gs": "LOC",
    "gc": "LOC",
    "gt": "LOC",
    "gh": "LOC",
}

# Every CNEC 2.0 type code NameTag can emit, including those without a coarse PER/ORG/LOC
# counterpart (times, numbers, addresses, artefacts, ... -> MISC). Used to recognise the
# tagset, so ``<name cnec="ty">`` stays a CNEC label rather than an unknown one.
CNEC_CODES = frozenset(CNEC_TO_CONLL) | frozenset(
    {
        # a / A -- addresses, numbers in addresses
        "a", "A", "ah", "at", "az",
        # C -- bibliographic items
        "C",
        # m -- media names
        "m", "me", "mi", "mn", "ms",
        # n / N -- numbers
        "n", "N", "n_", "na", "nb", "nc", "ni", "no", "ns",
        # o -- artefacts
        "o", "o_", "oa", "oe", "om", "op", "or",
        # t / T -- time expressions
        "t", "T", "td", "tf", "th", "tm", "tt", "ty",
    }
)  # fmt: skip

ONTO_TO_CONLL = {
    "PERSON": "PER",
    "ORG": "ORG",
    "GPE": "LOC",
    "LOC": "LOC",
    "FAC": "LOC",
    "NORP": "MISC",
    "PRODUCT": "MISC",
    "EVENT": "MISC",
    "WORK_OF_ART": "MISC",
    "LAW": "MISC",
    "LANGUAGE": "MISC",
    "DATE": "MISC",
    "TIME": "MISC",
    "PERCENT": "MISC",
    "MONEY": "MISC",
    "QUANTITY": "MISC",
    "ORDINAL": "MISC",
    "CARDINAL": "MISC",
    "MISC": "MISC",
}

ARCHAEO_TO_CONLL = {
    "LOCATION": "LOC",
    "ARTEFACT": "MISC",
    "PERIOD": "MISC",
    "CONTEXT": "MISC",
    "MATERIAL": "MISC",
    "SPECIES": "MISC",
}

COARSE_TYPES = ("PER", "ORG", "LOC", "MISC")

# TEITOK attribute that carries the raw label next to the coarse @type, per tagset.
TAGSET_ATTRIBUTE = {"cnec": "cnec", "onto": "onto", "archaeo": "archaeo", None: "label"}


def tagset(code: str):
    """``"cnec"``, ``"onto"``, ``"archaeo"`` or ``None`` (unknown label)."""
    if code in CNEC_CODES:
        return "cnec"
    if code in ONTO_TO_CONLL:
        return "onto"
    if code in ARCHAEO_TO_CONLL:
        return "archaeo"
    return None


def coarse_type(code: str) -> str:
    """Coarse TEITOK type for a NameTag label; unknown labels are ``MISC``."""
    for table in (CNEC_TO_CONLL, ONTO_TO_CONLL, ARCHAEO_TO_CONLL):
        if code in table:
            return table[code]
    return "MISC"
