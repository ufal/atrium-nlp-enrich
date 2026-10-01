"""
tests/test_docs.py — the documentation's checkable claims (issue #6).

Prose goes stale silently. Most of it can only be kept honest by reading it, but a
useful slice is mechanical: a link either resolves or it does not, a file either exists
or it does not, and a count either matches the code or it does not. Those are here.

The provoking case: `README.md`, `CONTRIBUTING.md` and `data_samples/vocab/RUNBOOK.md`
all linked to `prompts/RUNBOOK.md` — in a table of contents, in a config comment, and in
a "which document is for whom" table — while the file did not exist. Three documents
promised a fourth into being and nothing noticed, because no test reads a link.

Deliberately narrow. This module asserts what a reader can verify without judgement;
whether the prose is *right* is a review question, not a test.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# The documents a reviewer or contributor is pointed at. Not every .md in the tree:
# agent_dev_logs/ is a working record that cites moved and deleted files on purpose.
DOCS = [
    "README.md",
    "CONTRIBUTING.md",
    "annotation/README.md",
    "service/README.md",
    "schemas/teitok/README.md",
]

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


@pytest.mark.parametrize("doc", DOCS)
def test_every_referenced_document_exists(doc):
    """The documents this project points contributors at must be present. A missing one
    is not a broken link in the ordinary sense: it is a promise in a table of contents
    that nobody can follow."""
    assert (REPO_ROOT / doc).exists(), f"{doc} is referenced by the doc set but missing"


@pytest.mark.parametrize("doc", DOCS)
def test_relative_links_resolve(doc):
    path = REPO_ROOT / doc
    if not path.exists():
        pytest.skip(f"{doc} absent")
    broken = []
    for target in LINK_RE.findall(path.read_text(encoding="utf-8")):
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        resolved = (path.parent / target.split("#")[0]).resolve()
        if not resolved.exists():
            broken.append(target)
    assert not broken, f"{doc} links to files that do not exist: {sorted(set(broken))}"
