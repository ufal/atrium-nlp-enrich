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


TWO_PAGES = DOC.replace(
    '<surface id="facs-1" lrx="1000" lry="2000"><graphic url="d-1.png"/></surface>',
    '<surface id="facs-1" lrx="1000" lry="2000"><graphic url="d-1.png"/></surface>\n'
    '    <surface id="facs-2" lrx="2000" lry="1000"><graphic url="d-2.png"/></surface>',
).replace(
    "  </body></text>",
    '    <pb n="2" id="pb-2" facs="d-2.png" corresp="#facs-2"/>\n'
    '    <div type="TextBlock" id="b-2.1" bbox="1900 900 2000 1000"><s id="s-2">'
    '<tok id="w-2" bbox="1900 900 2000 1000">B</tok></s></div>\n'
    "  </body></text>",
)


def test_every_surface_keeps_its_own_extent(tmp_path):
    """Every <surface> used to get the first page's new size."""
    path = _write(tmp_path, "d.teitok.xml", TWO_PAGES)
    assert fix_teitok_bboxes.main(["-i", str(path), "--sx", "0.5", "--sy", "0.5"]) == 0
    out = path.read_text(encoding="utf-8")
    assert 'id="facs-1" lrx="500" lry="1000"' in out
    assert 'id="facs-2" lrx="1000" lry="500"' in out


def test_a_shift_is_clamped_to_the_page(tmp_path, capsys):
    """A shift past the page edge used to leave negative (or off-page) boxes, which the
    next stage-4 gate rejects."""
    path = _write(tmp_path, "d.teitok.xml", TWO_PAGES)
    assert fix_teitok_bboxes.main(["-i", str(path), "--dx", "-150", "--dy", "150"]) == 0
    out = path.read_text(encoding="utf-8")
    assert 'id="w-1" bbox="0 350 0 390"' in out  # 100-150 < 0 -> 0
    assert 'id="w-2" bbox="1750 1000 1850 1000"' in out  # 900+150 > 1000 -> 1000
    assert "clamped" in capsys.readouterr().out


def test_the_rewrite_is_recorded(tmp_path):
    doc = DOC.replace(
        "  <facsimile>",
        '  <teiHeader><revisionDesc><change when="2026-01-01" who="x">made</change>'
        "</revisionDesc></teiHeader>\n  <facsimile>",
    )
    path = _write(tmp_path, "d.teitok.xml", doc)
    assert fix_teitok_bboxes.main(["-i", str(path), "--sx", "2", "--sy", "2"]) == 0
    out = path.read_text(encoding="utf-8")
    assert 'who="atrium-nlp-enrich" type="rescaled">coordinates scaled by 2,2' in out
