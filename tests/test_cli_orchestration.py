"""
tests/test_cli_orchestration.py — every CLI entry point at least parses its arguments.

Lived in ``api_util/`` until 2026-09, outside ``pytest.ini``'s ``testpaths``, so none of
these ever ran.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent


def _missing(*modules):
    return [m for m in modules if importlib.util.find_spec(m) is None]


def test_summarize_nt_udp_cli_help():
    """Ensure the summarization script compiles."""
    res = subprocess.run(
        [sys.executable, str(ROOT_DIR / "api_util" / "summarize_nt_udp.py"), "--help"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "usage" in res.stdout.lower()


def test_fix_teitok_bboxes_missing_args():
    """The bounding box fixer rejects a call without -i (argparse exit 2, no traceback)."""
    res = subprocess.run(
        [sys.executable, str(ROOT_DIR / "fix_teitok_bboxes.py")], capture_output=True, text=True
    )
    assert res.returncode == 2
    assert "Traceback" not in res.stderr
