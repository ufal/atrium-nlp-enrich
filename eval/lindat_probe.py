"""
eval/lindat_probe.py – Do LINDAT's UDPipe and NameTag answer correctly, request after request?

The daily check (atrium-project#78)
-----------------------------------
Every other test of this repository mocks LINDAT. ``.github/workflows/lindat-daily.yml`` runs this
script every day: it sends the same short Czech sentence to UDPipe and the same CoNLL-U to NameTag,
*n* times each on a fresh connection (what the pipeline's scripts do) and *n* times over one
keep-alive session, and fails when a reply is bad. Repeating the request is the point: in October
one broken replica behind LINDAT's balancer answered every other translation request with garbage
(atrium-translator#46), which a single request finds only half the time. The translator runs the
same check for LINDAT Translation (its ``eval/lindat_probe.py``).

A reply is bad when:

* the request fails: an HTTP error, a timeout, a refused or dropped connection;
* UDPipe's reply is not the sentence's analysis (:func:`udpipe_reason`): no CoNLL-U, a token count
  other than the sentence's, a token that is not in the sentence, or a lemma that is not the one
  the model gives these words (``Praze`` → ``Praha``, ``hroby`` → ``hrob``, ``vedl`` → ``vést``);
* NameTag's reply is not the sentence tagged (:func:`nametag_reason`): a token count other than the
  input's, ``Jan Novák`` not tagged as a person, or ``Praze`` not tagged as a place.

The lemmas and the two entities are the models' answers today (``MODEL_UDPIPE``, ``MODEL_NAMETAG``,
as in ``config_api.txt``); a new model that answers differently fails the check on purpose, so the
change is seen before the pipeline's output changes.

With ``--max-bad`` the exit status is 1 when more replies than that are bad, and the lane's issue is
opened or updated; without it the probe only reports. Its summary, with the good/bad pattern per
service and mode and a sample bad reply, is printed last and goes to the run's summary page.

Usage
-----
    python -m eval.lindat_probe
    python -m eval.lindat_probe --n 6 --pause 0.5 --max-bad 0      # the daily check
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests  # noqa: E402

from api_util.call_nametag import NAMETAG_URL  # noqa: E402
from api_util.call_udpipe import UDPIPE_URL  # noqa: E402

#: The models the pipeline uses (config_api.txt); the environment overrides them as it does there.
DEFAULT_MODEL_UDPIPE = "czech-pdt-ud-2.15-241121"
DEFAULT_MODEL_NAMETAG = "nametag3-multilingual-onto-260521"

#: The daily input: a person, a place, numbers and inflected words with known lemmas.
DAILY_TEXT = "Jan Novák vedl v roce 1932 výzkum v Praze a našel 3 hroby."
#: The lemmas the Czech model gives three of its words.
EXPECTED_LEMMAS = {"Praze": "Praha", "hroby": "hrob", "vedl": "vést"}
#: The entities NameTag must find: the words of a person, and of a place.
PERSON_WORDS = ("Jan", "Novák")
PLACE_WORDS = ("Praze",)

GOOD, BAD = "✓", "✗"
_TOKEN = re.compile(r"\w+|[^\w\s]")


def tokens_of(text: str) -> list[str]:
    """The tokens a Czech tokenizer makes of *text*: words, numbers and punctuation marks."""
    return _TOKEN.findall(text)


def conllu_rows(conllu: str) -> list[list[str]]:
    """The word lines of a CoNLL-U text, as their columns (multiword ranges and empty nodes left out)."""
    rows = []
    for line in conllu.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) >= 10 and cols[0].isdigit():
            rows.append(cols)
    return rows


def udpipe_reason(text: str, reply: str) -> str | None:
    """Why *reply* (UDPipe's ``result``) is not the analysis of *text*, or ``None``."""
    rows = conllu_rows(reply)
    if not rows:
        return "no CoNLL-U in the reply"
    expected = tokens_of(text)
    forms = [cols[1] for cols in rows]
    if len(forms) != len(expected):
        return f"{len(forms)} tokens, the sentence has {len(expected)}"
    stray = [form for form in forms if form not in expected]
    if stray:
        return f"tokens not in the sentence: {', '.join(stray[:5])}"
    lemmas = {cols[1]: cols[2] for cols in rows}
    wrong = [
        f"{word}→{lemmas.get(word)}"
        for word, lemma in EXPECTED_LEMMAS.items()
        if word in text and lemmas.get(word) != lemma
    ]
    if wrong:
        return f"unexpected lemmas: {', '.join(wrong)}"
    return None


def _tags(reply: str) -> list[tuple[str, str]]:
    """``(word, tag)`` for every token line of NameTag's CoNLL output (the format ``call_nametag`` reads)."""
    pairs = []
    for line in reply.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) >= 2:
            pairs.append((cols[0], cols[1]))
    return pairs


#: Entity types, after the ``B-``/``I-`` prefix: OntoNotes (the pipeline's model) and the Czech
#: CNEC types (``P`` a person, ``p*`` its parts; ``g*`` a geographical name).
_PERSON_TYPES = {"PERSON", "PER", "P"}
_PLACE_TYPES = {"GPE", "LOC"}


def _types(tag: str) -> list[str]:
    return [part.split("-", 1)[1] for part in tag.split("|") if part[:2] in ("B-", "I-")]


def _is_person(tag: str) -> bool:
    return any(kind in _PERSON_TYPES or kind[:1] == "p" for kind in _types(tag))


def _is_place(tag: str) -> bool:
    return any(kind in _PLACE_TYPES or kind[:1] == "g" for kind in _types(tag))


def nametag_reason(input_tokens: list[str], reply: str) -> str | None:
    """Why *reply* (NameTag's ``result``) is not *input_tokens* tagged, or ``None``."""
    pairs = _tags(reply)
    if not pairs:
        return "no tagged tokens in the reply"
    if [word for word, _ in pairs] != input_tokens:
        return f"{len(pairs)} tokens back for {len(input_tokens)} sent, or not the same words"
    tags = dict(pairs)
    missed = [word for word in PERSON_WORDS if word in tags and not _is_person(tags[word])]
    missed += [word for word in PLACE_WORDS if word in tags and not _is_place(tags[word])]
    if missed:
        return "entities missed: " + ", ".join(f"{word} ({tags[word] or 'O'})" for word in missed)
    return None


def nametag_input(text: str) -> str:
    """A fixed CoNLL-U of *text*'s tokens, so NameTag is checked even on a day UDPipe fails."""
    lines = [
        f"{i}\t{form}\t_\t_\t_\t_\t_\t_\t_\t_" for i, form in enumerate(tokens_of(text), start=1)
    ]
    return "# sent_id = 1\n# text = " + text + "\n" + "\n".join(lines) + "\n\n"


def _result(response) -> str:
    try:
        return str(response.json().get("result", ""))
    except (ValueError, AttributeError, json.JSONDecodeError):
        return ""


def probe(post, url: str, data: dict, judge, n: int, pause: float) -> list[dict]:
    """POST *data* to *url* *n* times through *post*; one result dict per request, judged by *judge*."""
    rows = []
    for index in range(n):
        started = time.monotonic()
        row = {"index": index + 1}
        try:
            response = post(url, data=data, timeout=60)
            row["elapsed"] = time.monotonic() - started
            row["status"] = response.status_code
            row["reply"] = _result(response) if response.status_code == 200 else ""
            row["reason"] = (
                judge(row["reply"])
                if response.status_code == 200
                else f"HTTP {response.status_code}"
            )
        except requests.RequestException as exc:
            row.update(elapsed=time.monotonic() - started, status=None, reply="")
            row["reason"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
        if pause > 0:
            time.sleep(pause)
    return rows


def pattern_of(rows: list[dict]) -> str:
    return "".join(BAD if row["reason"] else GOOD for row in rows)


def verdict(rows: list[dict], max_bad: int | None) -> int:
    """The exit status: 1 when more than *max_bad* replies are bad, else 0 (always 0 without a maximum)."""
    bad = [row for row in rows if row["reason"]]
    if max_bad is None:
        return 0
    print(
        f"check:    {len(bad)} of {len(rows)} bad, at most {max_bad} allowed → {'FAIL' if len(bad) > max_bad else 'OK'}"
    )
    for reason in sorted({row["reason"] for row in bad})[:5]:
        print(f"          {reason}")
    return 1 if len(bad) > max_bad else 0


def _print_rows(label: str, rows: list[dict]) -> None:
    print(f"\n── {label} ──")
    for row in rows:
        mark = BAD if row["reason"] else GOOD
        print(f"#{row['index']:02d} {mark} {row['elapsed']:5.2f}s  {row['reason'] or 'ok'}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Check LINDAT UDPipe and NameTag with repeated identical requests."
    )
    parser.add_argument(
        "--n", type=int, default=6, help="requests per service and mode (default 6)"
    )
    parser.add_argument(
        "--pause", type=float, default=0.0, help="seconds between requests (default 0)"
    )
    parser.add_argument(
        "--max-bad",
        type=int,
        default=None,
        help="exit 1 when more than this many replies, over both services and modes, are bad (default: report only)",
    )
    args = parser.parse_args(argv)

    udpipe_url = os.environ.get("UDPIPE_URL") or UDPIPE_URL
    nametag_url = os.environ.get("NAMETAG_URL") or NAMETAG_URL
    udpipe_model = os.environ.get("MODEL_UDPIPE") or DEFAULT_MODEL_UDPIPE
    nametag_model = os.environ.get("MODEL_NAMETAG") or DEFAULT_MODEL_NAMETAG
    text = DAILY_TEXT
    udpipe_data = {"model": udpipe_model, "tokenizer": "", "tagger": "", "parser": "", "data": text}
    nametag_data = {
        "model": nametag_model,
        "input": "conllu",
        "output": "conll",
        "data": nametag_input(text),
    }
    expected_tokens = tokens_of(text)
    print(f"UDPipe:  {udpipe_url} ({udpipe_model})\nNameTag: {nametag_url} ({nametag_model})")
    print(f"text: {text!r}   requests per service and mode: {args.n}")

    def judge_udpipe(reply: str) -> str | None:
        return udpipe_reason(text, reply)

    def judge_nametag(reply: str) -> str | None:
        return nametag_reason(expected_tokens, reply)

    runs = {}
    for service, url, data, judge in (
        ("udpipe", udpipe_url, udpipe_data, judge_udpipe),
        ("nametag", nametag_url, nametag_data, judge_nametag),
    ):
        runs[(service, "fresh")] = probe(requests.post, url, data, judge, args.n, args.pause)
        _print_rows(
            f"{service}: fresh connection per request (what the pipeline does)",
            runs[(service, "fresh")],
        )
        with requests.Session() as session:
            runs[(service, "session")] = probe(session.post, url, data, judge, args.n, args.pause)
        _print_rows(f"{service}: one keep-alive session", runs[(service, "session")])

    every = [row for rows in runs.values() for row in rows]
    bad_sample = next(((row["reason"], row["reply"][:160]) for row in every if row["reason"]), None)

    print("\n── summary (paste into a report) ──")
    print(f"when:     {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    print(f"input:    {text!r} (identical for every request)")
    for (service, mode), rows in runs.items():
        print(f"{service:8s} {mode:8s} {pattern_of(rows)}")
    if bad_sample:
        print(f"first bad: {bad_sample[0]}")
        if bad_sample[1]:
            print(f"its reply: {bad_sample[1]!r}")
    return verdict(every, args.max_bad)


if __name__ == "__main__":
    raise SystemExit(main())
