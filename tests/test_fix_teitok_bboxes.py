"""
tests/test_fix_teitok_bboxes.py
===============================
The post-factum coordinate fixer (issue #9). Until 2026-09 it crashed on the first file
it touched — ``fix_name_close_tags()`` returns ``(text, count)`` and
``detect_source_size()`` returns ``(w, h, kind)`` and both were unpacked wrongly — and
the only test exercised the no-arguments error path. These tests run the real rewrite.
"""

import subprocess
import sys
from pathlib import Path

import fix_teitok_bboxes

ROOT = Path(__file__).resolve().parent.parent

DOC = """<?xml version="1.0" encoding="utf-8"?>
<TEI xmlnsoff="http://www.tei-c.org/ns/1.0" lang="cs">
  <facsimile>
    <surface id="facs-1" lrx="1000" lry="2000"><graphic url="d-1.png"/></surface>
  </facsimile>
  <text><body>
    <pb n="1" id="pb-1" facs="d-1.png"/>
    <div type="TextBlock" id="b-1.1" bbox="100 200 900 400">
      <s id="s-1"><name id="n-1" type="LOC" cnec="gu"><tok id="w-1" bbox="100 200 150 240">Praha</tok></name></s>
    </div>
  </body></text>
</TEI>
"""

LEGACY_DOC = DOC.replace("</name>", "</n>")


def _write(tmp_path, name, text=DOC):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_single_file_is_scaled_and_surface_follows(tmp_path):
    path = _write(tmp_path, "d.teitok.xml")
    assert fix_teitok_bboxes.main(["-i", str(path), "--sx", "0.5", "--sy", "0.5"]) == 0
    out = path.read_text(encoding="utf-8")
    assert 'bbox="50 100 75 120"' in out
    assert 'bbox="50 100 450 200"' in out
    assert 'lrx="500"' in out and 'lry="1000"' in out


def test_directory_mode_rewrites_every_xml(tmp_path):
    a = _write(tmp_path, "a.teitok.xml")
    b = _write(tmp_path, "b.teitok.xml")
    assert fix_teitok_bboxes.main(["-i", str(tmp_path), "--sx", "2", "--sy", "2"]) == 0
    for path in (a, b):
        assert 'bbox="200 400 300 480"' in path.read_text(encoding="utf-8")


def test_offset_is_added_before_scaling(tmp_path):
    path = _write(tmp_path, "d.teitok.xml")
    assert fix_teitok_bboxes.main(["-i", str(path), "--dx", "-100", "--dy", "-200"]) == 0
    assert 'bbox="0 0 50 40"' in path.read_text(encoding="utf-8")


def test_dpi_mode_uses_the_measurement_unit(tmp_path):
    path = _write(tmp_path, "d.teitok.xml")
    assert fix_teitok_bboxes.main(["-i", str(path), "--unit", "mm10", "--dpi", "254"]) == 0
    # mm10 at 254 dpi = 1 px per 1/10 mm -> identity
    assert 'bbox="100 200 150 240"' in path.read_text(encoding="utf-8")


def test_legacy_name_close_tag_is_repaired(tmp_path):
    path = _write(tmp_path, "d.teitok.xml", LEGACY_DOC)
    assert fix_teitok_bboxes.main(["-i", str(path)]) == 0
    out = path.read_text(encoding="utf-8")
    assert "</n>" not in out and "</name>" in out


def test_missing_path_is_an_error(tmp_path):
    assert fix_teitok_bboxes.main(["-i", str(tmp_path / "nope.xml")]) == 1


def test_cli_entry_point_runs(tmp_path):
    path = _write(tmp_path, "d.teitok.xml")
    res = subprocess.run(
        [sys.executable, str(ROOT / "fix_teitok_bboxes.py"), "-i", str(path), "--sx", "0.5"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert res.returncode == 0, res.stderr
    assert "[OK]" in res.stdout
