"""api_util/flexiconv_report.py -- the #10 close-out table, on real flexiconv v0.3.10 output."""

import shutil
from pathlib import Path

from api_util import flexiconv_report

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "teitok" / "flexiconv"


def test_describe_layout_document():
    row = flexiconv_report.describe(FIXTURES / "page.teitok.xml")
    assert (row["source"], row["format"]) == ("sample_page.xml", "xml")
    assert (row["pages"], row["rows"], row["tokens"], row["bbox"]) == (1, 2, 9, 10)
    assert row["core"] == []


def test_describe_plain_document():
    row = flexiconv_report.describe(FIXTURES / "txt.teitok.xml")
    assert (row["source"], row["format"]) == ("sample_txt.txt", "txt")
    assert (row["pages"], row["rows"], row["tokens"], row["bbox"]) == (0, 2, 10, 0)


def test_fixture_directory_passes(capsys):
    assert flexiconv_report.main([str(FIXTURES)]) == 0
    out = capsys.readouterr().out
    assert out.startswith(
        "| Input | Pages | Rows | Tokens | Elements with bbox | `--profile core` |"
    )
    assert "| hocr `sample_hocr.hocr` | 1 | 3 | 13 | 15 | ✅ |" in out
    assert "| txt `sample_txt.txt` | — | 2 | 10 | — | ✅ |" in out
    assert "5/5 document(s)" in out


def test_unconverted_inputs_are_listed_and_fail(tmp_path, capsys):
    out_dir = tmp_path / "flexiconv"
    out_dir.mkdir()
    shutil.copy(FIXTURES / "txt.teitok.xml", out_dir / "report.teitok.xml")
    inputs = tmp_path / "DOCS"
    inputs.mkdir()
    for name in ("report.txt", "scan.pdf", "notes.xyz"):
        (inputs / name).write_text("x", encoding="utf-8")
    assert flexiconv_report.main([str(out_dir), "--inputs", str(inputs)]) == 1
    out = capsys.readouterr().out
    assert "| `scan.pdf` | — | — | — | — | ❌ no TEITOK output |" in out
    assert "notes.xyz" not in out  # not a flexiconv format, never converted
    assert "1/2 document(s)" in out


def test_invalid_document_fails(tmp_path, capsys):
    (tmp_path / "bad.teitok.xml").write_text("<TEI><text><tok>a</tok>", encoding="utf-8")
    assert flexiconv_report.main([str(tmp_path)]) == 1
    assert "❌ not readable" in capsys.readouterr().out


def test_empty_directory_and_usage_errors(tmp_path):
    assert flexiconv_report.main([str(tmp_path)]) == 1
    assert flexiconv_report.main([str(tmp_path / "missing")]) == 2
    assert flexiconv_report.main([str(tmp_path), "--inputs", str(tmp_path / "missing")]) == 2
