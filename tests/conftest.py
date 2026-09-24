"""
tests/conftest.py
=================
Shared pytest fixtures and sys.path wiring for atrium-nlp-enrich unit tests.

sys.path is patched here (once, at collection time) so that every test module
can import from both the repo root (``keywords.py``, ``atrium_paradata.py``)
and the ``api_util/`` subdirectory (``call_udpipe``, ``call_nametag``,
``summarize_nt_udp``).
"""

import sys
from pathlib import Path

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: marks tests as slow integration smoke tests")


# ── path wiring ───────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "api_util"))

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ── CoNLL-U fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def sample_conllu(tmp_path):
    """
    Three-sentence CoNLL-U file written to a temp path.

    Sentences:
        1. "Archeologický výzkum byl proveden."   (ADJ NOUN AUX VERB PUNCT)
        2. "Nalezená keramika a nádoby."           (ADJ NOUN CCONJ NOUN PUNCT)
        3. "Starý výzkum trval."                   (ADJ NOUN VERB PUNCT)

    Lemma counts: výzkum=2, archeologický=1, nalezený=1,
                  keramika=1, nádoba=1, starý=1

    SpaceAfter=No is set on every VERB/ADJ token immediately before a period,
    so "proveden." / "nádoby." / "trval." have no space between word and stop.
    """
    content = (FIXTURES_DIR / "sample.conllu").read_text(encoding="utf-8")
    dest = tmp_path / "sample.conllu"
    dest.write_text(content, encoding="utf-8")
    return str(dest)


@pytest.fixture
def empty_conllu(tmp_path):
    """CoNLL-U file with only a comment header — no token lines."""
    dest = tmp_path / "empty.conllu"
    dest.write_text("# newdoc\n", encoding="utf-8")
    return str(dest)


@pytest.fixture
def two_page_conllu(tmp_path):
    """
    CoNLL-U file whose sent_id counter resets to 1 mid-file,
    simulating a two-page document produced by the original (pre-merge) UDPipe path.

    Expected page map: [1, 1, 2, 2]
    """
    content = (FIXTURES_DIR / "two_page.conllu").read_text(encoding="utf-8")
    dest = tmp_path / "two_page.conllu"
    dest.write_text(content, encoding="utf-8")
    return str(dest)


@pytest.fixture
def page_break_conllu(tmp_path):
    """
    Merged CoNLL-U file with the ``# page_break = true`` comment that
    call_udpipe.merge_conllu_chunks used to write at every UDPipe chunk start.
    It marks a chunk start, never a page (issue #38, A): the renumbered file is
    one page unless a rows file says otherwise.

    Expected page map without rows: [1, 1, 1, 1]
    """
    content = (FIXTURES_DIR / "page_break.conllu").read_text(encoding="utf-8")
    dest = tmp_path / "page_break.conllu"
    dest.write_text(content, encoding="utf-8")
    return str(dest)
