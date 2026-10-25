"""tests/test_lindat_probe.py — the checks of eval/lindat_probe.py, no network (atrium-project#78).

The daily lane sends LINDAT's UDPipe and NameTag the same input again and again and fails on a
bad reply. These tests hold what "bad" means: an HTTP error, UDPipe's analysis of another text
(token count, stray tokens, changed lemmas), NameTag's tags of another input, or the person and
place of the sentence left untagged. The fixtures have the shape of real replies: UDPipe's
CoNLL-U (as in data_samples, `Praze` → `Praha`) and NameTag's two-column CoNLL output, which
api_util/call_nametag.py reads.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from eval import lindat_probe
from eval.lindat_probe import (
    BAD,
    DAILY_TEXT,
    GOOD,
    nametag_input,
    nametag_reason,
    pattern_of,
    probe,
    tokens_of,
    udpipe_reason,
    verdict,
)

_REPO = Path(__file__).resolve().parent.parent

#: UDPipe's lemmas for the daily sentence (PDT model): the three the probe checks are right.
_LEMMAS = {
    "Jan": "Jan",
    "Novák": "Novák",
    "vedl": "vést",
    "v": "v",
    "roce": "rok",
    "1932": "1932",
    "výzkum": "výzkum",
    "Praze": "Praha",
    "a": "a",
    "našel": "najít",
    "3": "3",
    "hroby": "hrob",
    ".": ".",
}
#: NameTag's tags for the daily sentence (OntoNotes model).
_TAGS = {
    "Jan": "B-PERSON",
    "Novák": "I-PERSON",
    "1932": "B-DATE",
    "Praze": "B-GPE",
    "3": "B-CARDINAL",
}


def _udpipe_reply(lemmas: dict | None = None, forms: list[str] | None = None) -> str:
    lemmas = {**_LEMMAS, **(lemmas or {})}
    forms = forms if forms is not None else tokens_of(DAILY_TEXT)
    lines = [
        f"{i}\t{form}\t{lemmas.get(form, form)}\tX\t_\t_\t0\troot\t_\t_"
        for i, form in enumerate(forms, 1)
    ]
    return "# newdoc\n# sent_id = 1\n# text = " + DAILY_TEXT + "\n" + "\n".join(lines) + "\n\n"


def _nametag_reply(tags: dict | None = None, forms: list[str] | None = None) -> str:
    tags = {**_TAGS, **(tags or {})}
    forms = forms if forms is not None else tokens_of(DAILY_TEXT)
    return "\n".join(f"{form}\t{tags.get(form, 'O')}" for form in forms) + "\n\n"


def test_the_daily_sentence_has_a_person_a_place_numbers_and_the_checked_lemmas():
    tokens = tokens_of(DAILY_TEXT)
    assert tokens[:2] == ["Jan", "Novák"] and "Praze" in tokens and tokens[-1] == "."
    assert {"1932", "3"} <= set(tokens)
    assert set(lindat_probe.EXPECTED_LEMMAS) <= set(tokens)


@pytest.mark.parametrize(
    "reply,expected",
    [
        (_udpipe_reply(), None),
        ("", "no CoNLL-U"),
        ("Internal error", "no CoNLL-U"),
        (_udpipe_reply(forms=tokens_of(DAILY_TEXT)[:-1]), "13 tokens, the sentence has 14"),
        (
            _udpipe_reply(forms=["pravidla"] + tokens_of(DAILY_TEXT)[1:]),
            "tokens not in the sentence: pravidla",
        ),
        (_udpipe_reply({"Praze": "Praze"}), "unexpected lemmas: Praze→Praze"),
    ],
)
def test_udpipe_reason(reply, expected):
    reason = udpipe_reason(DAILY_TEXT, reply)
    assert reason == expected if expected is None else reason.startswith(expected)


@pytest.mark.parametrize(
    "reply,expected",
    [
        (_nametag_reply(), None),
        # the Czech CNEC types are understood too
        (_nametag_reply({"Jan": "B-P|B-pf", "Novák": "I-P|B-ps", "Praze": "B-gu"}), None),
        ("", "no tagged tokens"),
        (_nametag_reply(forms=tokens_of(DAILY_TEXT)[:-2]), "12 tokens back for 14"),
        (_nametag_reply({"Jan": "O", "Novák": "O"}), "entities missed: Jan (O), Novák (O)"),
        (_nametag_reply({"Praze": "B-PERSON"}), "entities missed: Praze (B-PERSON)"),
        # an OntoNotes PRODUCT or PERCENT is no person, though it starts with a P
        (_nametag_reply({"Jan": "B-PRODUCT"}), "entities missed: Jan (B-PRODUCT)"),
    ],
)
def test_nametag_reason(reply, expected):
    reason = nametag_reason(tokens_of(DAILY_TEXT), reply)
    assert reason == expected if expected is None else reason.startswith(expected)


def test_nametag_gets_a_fixed_conllu_of_the_sentence():
    text = nametag_input(DAILY_TEXT)
    rows = [line.split("\t") for line in text.splitlines() if line and not line.startswith("#")]
    assert [cols[1] for cols in rows] == tokens_of(DAILY_TEXT)
    assert all(len(cols) == 10 for cols in rows) and text.endswith("\n\n")


def _response(result, status=200):
    response = MagicMock()
    response.status_code = status
    response.json.return_value = {"result": result}
    return response


def test_probe_records_the_pattern():
    replies = iter([_response(_udpipe_reply()), _response(""), _response("", status=503)])
    rows = probe(
        lambda url, **kw: next(replies),
        "http://x/process",
        {},
        lambda r: udpipe_reason(DAILY_TEXT, r),
        3,
        0,
    )
    assert pattern_of(rows) == GOOD + BAD + BAD
    assert rows[1]["reason"] == "no CoNLL-U in the reply"
    assert rows[2]["reason"] == "HTTP 503"


def test_verdict_fails_only_over_the_maximum_and_reports_only_without_one():
    rows = [{"reason": None}, {"reason": "HTTP 503"}]
    assert verdict(rows, None) == 0
    assert verdict(rows, 1) == 0
    assert verdict(rows, 0) == 1


class _Session:
    def __init__(self, post):
        self.post = post

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.mark.parametrize("bad_every,expected", [(0, 0), (3, 1)])
def test_the_daily_run_exits_1_on_a_bad_reply(monkeypatch, capsys, bad_every, expected):
    sent = []

    def post(url, data, timeout):
        sent.append((url, data["model"]))
        if bad_every and len(sent) % bad_every == 0:
            return _response("", status=502)
        return _response(_udpipe_reply() if "udpipe" in url else _nametag_reply())

    monkeypatch.setenv("UDPIPE_URL", "http://lindat.test/udpipe/api/process")
    monkeypatch.setenv("NAMETAG_URL", "http://lindat.test/nametag/api/recognize")
    monkeypatch.setattr(lindat_probe.requests, "post", post)
    monkeypatch.setattr(lindat_probe.requests, "Session", lambda: _Session(post))
    assert lindat_probe.main(["--n", "2", "--max-bad", "0"]) == expected
    assert len(sent) == 8  # 2 per service and mode
    assert {model for _, model in sent} == {
        lindat_probe.DEFAULT_MODEL_UDPIPE,
        lindat_probe.DEFAULT_MODEL_NAMETAG,
    }
    assert ("FAIL" if expected else "OK") in capsys.readouterr().out


def _config_value(name: str) -> str:
    """A model name as config_api.txt sets it (``NAME="value"``)."""
    for line in (_REPO / "config_api.txt").read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip().strip('"')
    raise AssertionError(f"{name} is not set in config_api.txt")


def test_the_probe_checks_the_models_the_pipeline_uses():
    """A model bump in config_api.txt must move the probe too, or the lane checks a model nobody runs."""
    assert lindat_probe.DEFAULT_MODEL_UDPIPE == _config_value("MODEL_UDPIPE")
    assert lindat_probe.DEFAULT_MODEL_NAMETAG == _config_value("MODEL_NAMETAG")


def test_the_lane_runs_the_probe_daily_and_reports_failures():
    import yaml

    lane = yaml.safe_load(
        (_REPO / ".github" / "workflows" / "lindat-daily.yml").read_text(encoding="utf-8")
    )
    assert lane[True]["schedule"], "the lane runs on a schedule"
    steps = lane["jobs"]["lindat"]["steps"]
    assert any(
        "eval.lindat_probe" in str(step.get("run", "")) and "--max-bad 0" in step["run"]
        for step in steps
    )
    issue = [s for s in steps if "lane-failure-issue" in str(s.get("uses", ""))]
    assert issue and "schedule" in issue[0]["if"]
