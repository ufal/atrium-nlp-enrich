"""
tests/test_backing_service_urls.py – Endpoint attachability (atrium-project#63).

Factor IV asks that a backing service be swappable by configuration alone. Two
LINDAT-hosted services are reached from this repo — UDPipe 2 and NameTag 3 —
and both must resolve their endpoint the same way, with the same precedence:

    --url  >  environment variable  >  module constant

Each test drives the script's *real* ``main()`` through its *real* argparse
parser and records the URL that reached the network layer, so a regression in
the argument definition, the default, or the threading is caught. The network
layer itself is stubbed; nothing here touches a socket.

``config_facts`` is covered too: it reports the endpoints on ``/info`` and is
what ``service/api.py``'s ``?deep=true`` probe dials, so it has to resolve the
same precedence as the pipeline or the service reports a host it never calls.
"""

from __future__ import annotations

import pytest

requests = pytest.importorskip("requests")

from api_util import call_nametag, call_udpipe  # noqa: E402

UDPIPE_DEFAULT = "https://lindat.mff.cuni.cz/services/udpipe/api/process"
NAMETAG_DEFAULT = "https://lindat.mff.cuni.cz/services/nametag/api/recognize"

STUB_URL = "http://127.0.0.1:9991/udpipe"
FLAG_URL = "http://127.0.0.1:9993/from-flag"


# ── helpers ───────────────────────────────────────────────────────────────────


def _run_udpipe_main(monkeypatch, tmp_path, extra_argv: list[str]) -> str:
    """Run call_udpipe.main() with one chunk; return the URL process_chunk got."""
    chunk_dir = tmp_path / "chunks"
    chunk_dir.mkdir()
    (chunk_dir / "chunk_0.txt").write_text("Ahoj světe.", encoding="utf-8")
    out_file = tmp_path / "out" / "doc.conllu"

    seen: dict[str, str] = {}

    def _fake_process_chunk(session, text, model, timeout, url=call_udpipe.UDPIPE_URL):
        seen["url"] = url
        return "# sent_id = 1\n1\tAhoj\tahoj\n"

    monkeypatch.setattr(call_udpipe, "process_chunk", _fake_process_chunk)
    monkeypatch.setattr(
        "sys.argv",
        [
            "call_udpipe.py",
            "--chunk-dir",
            str(chunk_dir),
            "--model",
            "czech-pdt",
            "--output",
            str(out_file),
        ]
        + extra_argv,
    )

    call_udpipe.main()
    return seen["url"]


def _run_nametag_main(monkeypatch, tmp_path, extra_argv: list[str]) -> str:
    """Run call_nametag.main() on a tiny CoNLL-U; return the URL it dialled."""
    conllu = tmp_path / "doc.conllu"
    conllu.write_text("# sent_id = 1\n1\tAhoj\tahoj\n", encoding="utf-8")
    out_dir = tmp_path / "ne"

    seen: dict[str, str] = {}

    def _fake_call_nametag(session, conllu_text, model, url, timeout):
        seen["url"] = url
        return {"result": "Ahoj\tB-PERSON\n"}

    monkeypatch.setattr(call_nametag, "call_nametag", _fake_call_nametag)
    monkeypatch.setattr(
        "sys.argv",
        [
            "call_nametag.py",
            "--input",
            str(conllu),
            "--model",
            "nametag3",
            "--output-dir",
            str(out_dir),
        ]
        + extra_argv,
    )

    call_nametag.main()
    return seen["url"]


# ── UDPipe ────────────────────────────────────────────────────────────────────


def test_udpipe_defaults_to_the_lindat_constant(monkeypatch, tmp_path):
    monkeypatch.delenv("UDPIPE_URL", raising=False)
    assert _run_udpipe_main(monkeypatch, tmp_path, []) == UDPIPE_DEFAULT
    assert call_udpipe.UDPIPE_URL == UDPIPE_DEFAULT


def test_udpipe_env_redirects_the_request(monkeypatch, tmp_path):
    monkeypatch.setenv("UDPIPE_URL", STUB_URL)
    assert _run_udpipe_main(monkeypatch, tmp_path, []) == STUB_URL


def test_udpipe_flag_beats_env(monkeypatch, tmp_path):
    monkeypatch.setenv("UDPIPE_URL", STUB_URL)
    assert _run_udpipe_main(monkeypatch, tmp_path, ["--url", FLAG_URL]) == FLAG_URL


# ── NameTag ───────────────────────────────────────────────────────────────────
#
# The Python half of call_nametag.py already read the environment before #63 —
# but nothing asserted it, which is how the fact that the *shell* layer clobbers
# NAMETAG_URL before Python ever sees it went unnoticed. These pin the contract
# the stage script now honours.


def test_nametag_defaults_to_the_lindat_constant(monkeypatch, tmp_path):
    monkeypatch.delenv("NAMETAG_URL", raising=False)
    assert _run_nametag_main(monkeypatch, tmp_path, []) == NAMETAG_DEFAULT
    assert call_nametag.NAMETAG_URL == NAMETAG_DEFAULT


def test_nametag_env_redirects_the_request(monkeypatch, tmp_path):
    monkeypatch.setenv("NAMETAG_URL", STUB_URL)
    assert _run_nametag_main(monkeypatch, tmp_path, []) == STUB_URL


def test_nametag_flag_beats_env(monkeypatch, tmp_path):
    monkeypatch.setenv("NAMETAG_URL", STUB_URL)
    assert _run_nametag_main(monkeypatch, tmp_path, ["--url", FLAG_URL]) == FLAG_URL


# ── config_api.txt shape ──────────────────────────────────────────────────────


def test_config_file_uses_the_non_clobbering_default_form():
    """A bare assignment here would re-export over a deployment-set value.

    `source config_api.txt` runs at the top of every stage script, and bash keeps
    the export attribute of an already-exported variable — so the plain form
    silently overwrites the operator's endpoint. Guarding the shape in a test is
    the only thing that stops it being "tidied" back.
    """
    from pathlib import Path

    text = Path(__file__).parent.parent.joinpath("config_api.txt").read_text(encoding="utf-8")
    assert f'UDPIPE_URL="${{UDPIPE_URL:-{UDPIPE_DEFAULT}}}"' in text
    assert f'NAMETAG_URL="${{NAMETAG_URL:-{NAMETAG_DEFAULT}}}"' in text


# ── service reporting surface ─────────────────────────────────────────────────


def test_config_facts_unwraps_shell_default_and_lets_env_win(monkeypatch):
    """/info and the deep health probe must name the endpoint actually in use."""
    enrichment = pytest.importorskip("service.enrichment")
    manager = enrichment.PipelineManager()

    monkeypatch.delenv("UDPIPE_URL", raising=False)
    monkeypatch.delenv("NAMETAG_URL", raising=False)
    facts = manager.config_facts()
    # The raw "${UDPIPE_URL:-...}" string must never escape: _deep_health feeds
    # this value straight to urllib, and the unexpanded form fails every probe.
    assert facts["udpipe_url"] == UDPIPE_DEFAULT
    assert facts["nametag_url"] == NAMETAG_DEFAULT

    monkeypatch.setenv("UDPIPE_URL", STUB_URL)
    monkeypatch.setenv("NAMETAG_URL", FLAG_URL)
    facts = manager.config_facts()
    assert facts["udpipe_url"] == STUB_URL
    assert facts["nametag_url"] == FLAG_URL
    # Model keys stay file-only — they are not deployment-varying config.
    assert facts["udpipe_model"] == "czech-pdt-ud-2.15-241121"
