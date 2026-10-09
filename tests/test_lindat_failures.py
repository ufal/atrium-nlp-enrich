"""
tests/test_lindat_failures.py
=============================
A LINDAT outage or timeout is not an empty run (atrium-nlp-enrich#41).

Until #41 every failure of the UDPipe and NameTag clients was exit 1, which the service answers as
502 "Pipeline produced no output (empty run, exit 1)": an outage, a timeout and an input that
yields nothing could not be told apart, and the contract tells a client to retry a 502, which is
wrong for an empty input. Each layer is checked here against the real thing it talks to:

* the clients, against stub LINDAT servers on 127.0.0.1 (a server that answers 503, one that is
  too slow, one that answers 400, and a port nobody listens on): exit 6, 7, 8 and 6, and the first
  line on stderr names the service and the cause;
* the stage scripts, run by bash with stub clients: they pass 6, 7 and 8 on and turn anything
  else into 1;
* the service, with the runner's exit code stubbed: 502 ``upstream_unavailable``, 504
  ``limit_exceeded`` naming ``lindat_timeout_s``, 500, and the empty run still 502 with
  ``reason: null`` — on ``/enrich`` and on ``/jobs``.

No network: everything listens on, or dials, the loopback interface.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

requests = pytest.importorskip("requests")

from api_util import call_nametag, call_udpipe, lindat_errors  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


# ── stub LINDAT servers ─────────────────────────────────────────────────────────────────────


def _serve(behaviour):
    """A LINDAT stand-in on 127.0.0.1: ``behaviour`` is ``("status", code)`` or ``("sleep", s)``."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 (http.server's naming)
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            kind, value = behaviour
            if kind == "sleep":
                time.sleep(value)
                status = 200
            else:
                status = value
            body = b'{"result": ""}'
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError:  # the client gave up first (the timeout case)
                pass

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


@pytest.fixture
def lindat():
    servers = []

    def start(behaviour):
        server = _serve(behaviour)
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}/api"

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def _closed_port_url():
    """A loopback port nothing listens on: the connection is refused."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}/api"


# ── the clients ─────────────────────────────────────────────────────────────────────────────


def _udpipe(monkeypatch, tmp_path, url, timeout="1", retries="0"):
    chunks = tmp_path / "chunks"
    chunks.mkdir()
    (chunks / "chunk_0.txt").write_text("Ahoj světe.", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "call_udpipe.py",
            "--chunk-dir",
            str(chunks),
            "--model",
            "czech",
            "--output",
            str(tmp_path / "out" / "d.conllu"),
            "--url",
            url,
            "--timeout",
            timeout,
            "--retries",
            retries,
        ],
    )
    with pytest.raises(SystemExit) as stop:
        call_udpipe.main()
    return stop.value.code


def _nametag(monkeypatch, tmp_path, url, timeout="1", retries="0"):
    conllu = tmp_path / "d.conllu"
    conllu.write_text(
        "# sent_id = 1\n1\tAhoj\tahoj\tINTJ\t_\t_\t0\troot\t_\t_\n\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "call_nametag.py",
            "--input",
            str(conllu),
            "--model",
            "czech",
            "--output-dir",
            str(tmp_path / "ne"),
            "--url",
            url,
            "--timeout",
            timeout,
            "--retries",
            retries,
        ],
    )
    with pytest.raises(SystemExit) as stop:
        call_nametag.main()
    return stop.value.code


CLIENTS = {"UDPipe": _udpipe, "NameTag": _nametag}


def _cause(err):
    """The line a client prints about why it stopped (what the service puts first in its error)."""
    lines = [line for line in err.splitlines() if line.startswith(lindat_errors.LINE_PREFIX)]
    assert len(lines) == 1, err
    return lines[0]


@pytest.mark.parametrize("service", sorted(CLIENTS))
def test_a_server_error_after_the_retries_is_exit_6(service, lindat, monkeypatch, tmp_path, capsys):
    code = CLIENTS[service](monkeypatch, tmp_path, lindat(("status", 503)), retries="1")
    assert code == lindat_errors.EXIT_UPSTREAM == 6
    cause = _cause(capsys.readouterr().err)
    assert cause.startswith(f"LINDAT {service} did not answer after 1 retries:"), cause


@pytest.mark.parametrize("service", sorted(CLIENTS))
def test_a_refused_connection_is_exit_6(service, monkeypatch, tmp_path, capsys):
    code = CLIENTS[service](monkeypatch, tmp_path, _closed_port_url())
    assert code == lindat_errors.EXIT_UPSTREAM
    assert _cause(capsys.readouterr().err).startswith(f"LINDAT {service} did not answer")


@pytest.mark.parametrize("service", sorted(CLIENTS))
def test_every_attempt_timing_out_is_exit_7(service, lindat, monkeypatch, tmp_path, capsys):
    # Two attempts (one retry), each cut at 1 s: urllib3 reports the spent retries as a
    # MaxRetryError around a read timeout, which requests raises as a ConnectionError.
    code = CLIENTS[service](monkeypatch, tmp_path, lindat(("sleep", 2.5)), retries="1")
    assert code == lindat_errors.EXIT_UPSTREAM_TIMEOUT == 7
    cause = _cause(capsys.readouterr().err)
    assert cause.startswith(
        f"LINDAT {service} timed out: no answer within 1 s on any of 2 attempt(s)"
    ), cause


@pytest.mark.parametrize("service", sorted(CLIENTS))
def test_a_refused_request_is_exit_8(service, lindat, monkeypatch, tmp_path, capsys):
    code = CLIENTS[service](monkeypatch, tmp_path, lindat(("status", 400)))
    assert code == lindat_errors.EXIT_UPSTREAM_REFUSED == 8
    assert _cause(capsys.readouterr().err).startswith(
        f"LINDAT {service} refused the request (HTTP 400)"
    )


def test_nothing_to_send_is_still_the_empty_run(monkeypatch, tmp_path):
    (tmp_path / "chunks").mkdir()
    monkeypatch.setattr(
        "sys.argv",
        [
            "call_udpipe.py",
            "--chunk-dir",
            str(tmp_path / "chunks"),
            "--model",
            "m",
            "--output",
            str(tmp_path / "o"),
        ],
    )
    with pytest.raises(SystemExit) as stop:
        call_udpipe.main()
    assert stop.value.code == lindat_errors.EXIT_EMPTY == 1


def test_the_codes_do_not_collide_with_the_pipelines_own():
    """2 a missing stage script, 3 the flexiconv preflight, 5 the TEITOK contract, 124 a stopped run."""
    assert set(lindat_errors.UPSTREAM_CODES) == {6, 7, 8}
    assert not set(lindat_errors.UPSTREAM_CODES) & {0, 1, 2, 3, 5, 124}


# ── the stage scripts ───────────────────────────────────────────────────────────────────────


_STUB = """import sys
sys.stderr.write("LINDAT {service} stub: exiting {code}\\n")
sys.exit({code})
"""


def _stage_dir(tmp_path, script, client, code):
    """A copy of the repo's stage script in a scratch tree whose client is a stub exiting `code`."""
    root = tmp_path / "repo"
    (root / "api_util").mkdir(parents=True)
    shutil.copy(REPO / script, root / script)
    for name in ("atrium_paradata.py", "para_licenses.py", "para_config.txt"):
        if (REPO / name).exists():
            shutil.copy(REPO / name, root / name)
    (root / "api_util" / "chunk.py").write_text(
        "import pathlib, sys\npathlib.Path(sys.argv[2], 'chunk_0.txt').write_text('x')\n",
        encoding="utf-8",
    )
    service = "UDPipe" if "udpipe" in client else "NameTag"
    (root / "api_util" / client).write_text(
        _STUB.format(service=service, code=code), encoding="utf-8"
    )
    out = tmp_path / "out"
    (out / "UDP").mkdir(parents=True)
    text = tmp_path / "doc.txt"
    text.write_text("Ahoj světe.", encoding="utf-8")
    (out / "manifest.tsv").write_text(f"file\tpage\tpath\ndoc\t1\t{text}\n", encoding="utf-8")
    (out / "UDP" / "doc.conllu").write_text(
        "# sent_id = 1\n", encoding="utf-8"
    ) if "nametag" in client else None
    config = tmp_path / "config.txt"
    config.write_text(
        "\n".join(
            [
                f'OUTPUT_DIR="{out}"',
                f'CHUNK_DIR="{tmp_path / "chunks"}"',
                f'PARADATA_DIR="{out / "paradata"}"',
                f'CONLLU_INPUT_DIR="{out / "UDP"}"',
                f'TSV_INPUT_DIR="{out / "NE"}"',
                'MODEL_UDPIPE="czech"',
                'MODEL_NAMETAG="czech"',
                'UDPIPE_URL="http://127.0.0.1:9/udpipe"',
                'NAMETAG_URL="http://127.0.0.1:9/nametag"',
                "WORD_CHUNK_LIMIT=900",
                "TIMEOUT=60",
                "MAX_RETRIES=5",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return root, config, out


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
@pytest.mark.parametrize(
    ("script", "client"), [("api_2_udp.sh", "call_udpipe.py"), ("api_3_nt.sh", "call_nametag.py")]
)
@pytest.mark.parametrize(("code", "expected"), [(6, 6), (7, 7), (8, 8), (1, 1), (2, 1), (4, 1)])
def test_a_stage_script_passes_the_lindat_codes_on(tmp_path, script, client, code, expected):
    root, config, out = _stage_dir(tmp_path, script, client, code)
    env = dict(os.environ, ATRIUM_CONFIG=str(config), PYTHONPATH=str(root))
    proc = subprocess.run(
        ["bash", script], cwd=root, env=env, capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == expected, proc.stderr
    if expected in lindat_errors.UPSTREAM_CODES:
        assert f"(exit {code})" in proc.stderr
    if "nametag" in client:
        # a failed document leaves no empty output directory behind for a resumed run to skip
        assert not (out / "NE" / "doc").exists()


# ── the service ─────────────────────────────────────────────────────────────────────────────

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from service.api import app  # noqa: E402


def _run_with(rc, tail):
    result = MagicMock()
    result.returncode = rc
    result.stdout = "=== Stage: udp ===\n"
    result.stderr = tail
    return patch("service.enrichment.subprocess.run", return_value=result)


def _enrich(client):
    return client.post(
        "/enrich",
        files={"file": ("t.csv", b"text,page_num,line_num\nAhoj,1,1", "text/csv")},
        data={"format": "json"},
    )


_LINE_6 = (
    "LINDAT UDPipe did not answer after 5 retries: HTTPSConnectionPool(...): Max retries exceeded"
)
_LINE_7 = "LINDAT NameTag timed out: no answer within 60 s on any of 6 attempt(s): Read timed out"
_LINE_8 = "LINDAT UDPipe refused the request (HTTP 400): 400 Client Error: Bad Request"


def test_an_outage_is_502_upstream_unavailable_naming_the_service():
    with _run_with(6, f"{_LINE_6}\n[CRITICAL ERROR] UDPipe processing failed for doc (exit 6).\n"):
        response = _enrich(TestClient(app))
    assert response.status_code == 502
    body = response.json()
    assert body["reason"] == "upstream_unavailable"
    assert body["detail"].startswith("LINDAT UDPipe did not answer after 5 retries")


def test_a_timeout_is_504_limit_exceeded_naming_lindat_timeout_s():
    with _run_with(7, f"{_LINE_7}\n"):
        response = _enrich(TestClient(app))
    assert response.status_code == 504
    body = response.json()
    assert body["reason"] == "limit_exceeded"
    assert body["limit"]["key"] == "lindat_timeout_s" and body["limit"]["env"] == "LINDAT_TIMEOUT_S"
    assert body["detail"].startswith("LINDAT NameTag timed out")


def test_a_refused_request_is_500_and_not_an_outage():
    with _run_with(8, f"{_LINE_8}\n"):
        response = _enrich(TestClient(app))
    assert response.status_code == 500
    body = response.json()
    assert body["reason"] is None and body["detail"].startswith("LINDAT UDPipe refused the request")


def test_the_empty_run_is_still_a_502_without_a_reason():
    with _run_with(
        1, "[FAIL] Stage(s) processed nothing despite having input and no resume: udp.\n"
    ):
        response = _enrich(TestClient(app))
    assert response.status_code == 502
    body = response.json()
    assert body["reason"] is None and body["detail"].startswith(
        "Pipeline produced no output (empty run, exit 1)"
    )


def test_a_cut_tail_still_names_the_cause():
    with _run_with(6, "…the client's line fell out of the last 4000 characters\n"):
        response = _enrich(TestClient(app))
    assert response.json()["detail"].startswith(
        "LINDAT UDPipe or NameTag did not answer after the retries."
    )


@pytest.mark.parametrize(
    ("rc", "tail", "reason"),
    [(6, _LINE_6, "upstream_unavailable"), (7, _LINE_7, "limit_exceeded"), (1, "", None)],
)
def test_a_job_records_the_reason(rc, tail, reason, monkeypatch):
    """`/jobs/{id}` says why a job failed, as the synchronous answer's `reason` does."""
    import asyncio

    from service import api
    from service.jobs import Job

    monkeypatch.setattr(api, "_semaphore", api._Slots())
    job = Job(job_id="lindat", status="queued")
    with _run_with(rc, f"{tail}\n"):
        asyncio.run(
            api._run_job_background(
                job, [{"text": "Ahoj", "page_num": 1, "line_num": 1}], "d", "cs"
            )
        )
    assert (job.status, job.reason) == ("failed", reason)
    assert job.error.startswith("LINDAT" if reason else "Pipeline produced no output")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
