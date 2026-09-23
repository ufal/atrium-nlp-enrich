"""tests/test_ner_types.py -- the one NameTag-label -> TEITOK-type map (api_util/ner_types.py)."""

import pytest

import atrium_vocab
from api_util import ner_types
from api_util.ner_types import coarse_type, tagset


def test_cnec_map_matches_the_hub_vocabulary():
    """atrium_vocab.CNEC_TO_ENTITY_TYPE (hub-shared, SKOS-published) declares itself a
    mirror of this map. A difference means one of the two must be re-synced."""
    assert ner_types.CNEC_TO_CONLL == atrium_vocab.CNEC_TO_ENTITY_TYPE


def test_writer_authority_name_is_the_same_object():
    """The hub registry points at teitok_alto._CNEC_TO_CONLL; it must stay this map."""
    from api_util import teitok_alto

    assert teitok_alto._CNEC_TO_CONLL is ner_types.CNEC_TO_CONLL
    assert teitok_alto.CNEC_TO_CONLL is ner_types.CNEC_TO_CONLL


@pytest.mark.parametrize(
    "code, expected",
    [
        # OntoNotes -- the default model (nametag3-multilingual-onto-*) since #11.
        ("PERSON", "PER"),
        ("ORG", "ORG"),
        ("GPE", "LOC"),
        ("LOC", "LOC"),
        ("FAC", "LOC"),
        ("DATE", "MISC"),
        ("NORP", "MISC"),
        # CNEC 2.0
        ("pf", "PER"),
        ("gu", "LOC"),
        ("if", "ORG"),
        ("ty", "MISC"),
        # Archaeological domain model (#7)
        ("LOCATION", "LOC"),
        ("ARTEFACT", "MISC"),
        # Unknown
        ("whatever", "MISC"),
        ("", "MISC"),
    ],
)
def test_coarse_type(code, expected):
    assert coarse_type(code) == expected


def test_every_mapped_value_is_a_coarse_type():
    for table in (ner_types.CNEC_TO_CONLL, ner_types.ONTO_TO_CONLL, ner_types.ARCHAEO_TO_CONLL):
        assert set(table.values()) <= set(ner_types.COARSE_TYPES)


@pytest.mark.parametrize(
    "code, expected",
    [
        ("pf", "cnec"),
        # CNEC codes without a coarse counterpart are still CNEC (sample documents carry them).
        ("ty", "cnec"),
        ("n_", "cnec"),
        ("T", "cnec"),
        ("PERSON", "onto"),
        ("LOCATION", "archaeo"),
        ("x", None),
        ("O", None),
    ],
)
def test_tagset(code, expected):
    assert tagset(code) == expected


def test_label_sets_do_not_collide():
    """tagset() relies on the three label sets being disjoint."""
    cnec, onto, arch = (
        set(ner_types.CNEC_CODES),
        set(ner_types.ONTO_TO_CONLL),
        set(ner_types.ARCHAEO_TO_CONLL),
    )
    assert not (cnec & onto) and not (cnec & arch) and not (onto & arch)
