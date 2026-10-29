"""
tests/test_cli_service_parity.py
================================
Stage 1 of the command line and the service read the same inputs into the same rows
(atrium-project#72, the service–CLI alignment of 2026-10-26).

The service writes an upload as its canonical table (``service/enrichment._write_canonical_csvs``)
and runs the same pipeline on it, so parity means: the rows stage 1 reads from a file directly
(``build_manifest_row.get_rows``) equal the rows it reads from the service's table of the same
file. Both sides read through ``api_util/line_inputs.py`` since v1.2.0-beta. Also pinned here:
the record as the text (``run_pipeline.py --text-from-record`` and a record sent without a
file), the opt-in ``categ`` filter, and the doc_id the runner predicts for each kind of input.

v1.3.0-beta: a table or text upload reaches stage 1 as sent, as the user's file does on the command
line (the TEITOK names the file sent); the service's doc_id keeps what the command line keeps
(``zpráva 1``, not ``zpr_va_1``); ``include_record`` is ``--document-json-out`` alone;
``/enrich_text`` honours ``skip_untrustworthy_lines``; ``--lang`` takes ``cs`` only, as ``lang`` does.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

import run_pipeline
from api_util import build_manifest_row as stage1
from api_util import line_inputs
from api_util.record_layout import record_rows
from atrium_document import canonical_doc_id
from service import enrichment as enr

#: Out of order, a BOM, the `page`/`line` spellings, a page label and ocr-postprocess's categ.
CSV_BYTES = (
    "﻿text,page,line,page_label,categ\n"
    "Druhá strana,2,1,ii,Clear\n"
    "Výzkum proběhl v Praze.,1,2,i,Clear\n"
    "Titul zprávy,1,1,i,Noisy\n"
    "x#@ ~~ %%,1,3,i,Trash\n"
).encode("utf-8")

#: Two pages at a form feed, blank lines inside both.
TXT_BYTES = "První řádek\n\nTřetí řádek\n\fDruhá strana\n\n".encode("utf-8")

#: Text before the first <pb/>, then two labelled pages (flexiconv's tokenized shape).
TEITOK_BYTES = """<?xml version="1.0" encoding="utf-8"?>
<TEI><teiHeader/><text>
<p><lb/><tok>Titulní</tok> <tok>list</tok></p>
<pb n="i"/>
<p><lb/><tok>Úvod</tok> <tok>zprávy</tok>
<lb/><tok>druhý</tok> <tok>řádek</tok></p>
<pb n="ii"/>
<p><lb/><tok>Plán</tok> <tok>výzkumu</tok></p>
</text></TEI>
""".encode("utf-8")


def _xlsx_bytes() -> bytes:
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    first = workbook.active
    first.append(["page_num", "line_num", "text", "page_label"])
    first.append([2, 1, "Strana dvě", "2"])
    first.append([1, 1, "Strana jedna", "1"])
    second = workbook.create_sheet("notes")
    second.append(["line", "text", "page"])
    second.append([2, "Poznámka", 1])
    third = workbook.create_sheet("other")
    third.append(["no text column"])
    third.append(["ignored"])
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def _cli_rows(tmp_path: Path, name: str, data: bytes, skip: bool = False):
    path = tmp_path / "cli" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return stage1.get_rows(str(path), skip_untrustworthy=skip)


def _service_rows(tmp_path: Path, name: str, data: bytes, skip: bool = False):
    """What stage 1 reads in the service: the upload's canonical table."""
    rows = enr.normalize_upload(name, data)
    enr._write_canonical_csvs(rows, tmp_path / "svc", "doc")
    return stage1.get_rows(str(tmp_path / "svc" / "doc.csv"), skip_untrustworthy=skip)


@pytest.mark.parametrize(
    "name, data",
    [
        ("tabulka.csv", CSV_BYTES),
        ("text.txt", TXT_BYTES),
        ("prevod.teitok.xml", TEITOK_BYTES),
    ],
)
def test_stage1_reads_a_file_as_the_service_reads_its_upload(tmp_path, name, data):
    assert _cli_rows(tmp_path, name, data) == _service_rows(tmp_path, name, data)


def test_an_xlsx_is_read_alike_too(tmp_path):
    data = _xlsx_bytes()
    rows = _cli_rows(tmp_path, "sesit.xlsx", data)
    assert rows == _service_rows(tmp_path, "sesit.xlsx", data)
    assert [(r.page, r.line, r.text) for r in rows] == [
        (1, 1, "Strana jedna"),
        (1, 2, "Poznámka"),
        (2, 1, "Strana dvě"),
    ]


def test_what_both_read_from_each_kind(tmp_path):
    table = _cli_rows(tmp_path, "t.csv", CSV_BYTES)
    assert [(r.page, r.line, r.label) for r in table] == [
        (1, 1, "i"),
        (1, 2, "i"),
        (1, 3, "i"),
        (2, 1, "ii"),
    ]
    text = _cli_rows(tmp_path, "t.txt", TXT_BYTES)
    assert [(r.page, r.line, r.text) for r in text] == [
        (1, 1, "První řádek"),
        (1, 3, "Třetí řádek"),
        (2, 1, "Druhá strana"),
    ]
    teitok = _cli_rows(tmp_path, "t.teitok.xml", TEITOK_BYTES)
    # pages by <pb/> ordinal (the text before the first <pb/> is page 1), labels by pb@n,
    # in document order
    assert [(r.page, r.label, r.text) for r in teitok] == [
        (1, "", "Titulní list"),
        (2, "i", "Úvod zprávy"),
        (2, "i", "druhý řádek"),
        (3, "ii", "Plán výzkumu"),
    ]


def test_the_service_keeps_the_page_label_it_used_to_drop(tmp_path):
    rows = enr.normalize_upload("t.csv", CSV_BYTES)
    assert {r["page_label"] for r in rows} == {"i", "ii"}
    enr._write_canonical_csvs(rows, tmp_path, "doc")
    with open(tmp_path / "doc.csv", encoding="utf-8", newline="") as fh:
        assert next(csv.reader(fh)) == list(line_inputs.TABLE_COLUMNS)


def test_both_refuse_the_same_files(tmp_path, capsys):
    with pytest.raises(enr.UnsupportedUploadType):
        enr.normalize_upload("x.pdf", b"%PDF-1.7")
    assert _cli_rows(tmp_path, "x.pdf", b"%PDF-1.7") == []
    with pytest.raises(ValueError, match="'text' column"):
        enr.normalize_upload("x.csv", b"file,page_num\nA,1\n")
    assert _cli_rows(tmp_path, "x.csv", b"file,page_num\nA,1\n") == []
    assert "'text' column" in capsys.readouterr().err


# ── the opt-in filter ────────────────────────────────────────────────────────────────────────


def test_the_filter_is_off_by_default_and_the_same_on_both_sides_when_on(tmp_path):
    every = _cli_rows(tmp_path, "t.csv", CSV_BYTES)
    assert "x#@ ~~ %%" in [r.text for r in every]
    assert every == _service_rows(tmp_path, "t.csv", CSV_BYTES)
    kept = _cli_rows(tmp_path, "t.csv", CSV_BYTES, skip=True)
    assert "x#@ ~~ %%" not in [r.text for r in kept] and len(kept) == len(every) - 1
    assert kept == _service_rows(tmp_path, "t.csv", CSV_BYTES, skip=True)


def test_the_service_filter_is_the_requests_alone(tmp_path, monkeypatch):
    monkeypatch.setenv("SKIP_UNTRUSTWORTHY_LINES", "true")
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    off = enr._derive_config(tmp_path / "a").read_text(encoding="utf-8").splitlines()
    on = enr._derive_config(tmp_path / "b", None, True).read_text(encoding="utf-8").splitlines()
    assert 'SKIP_UNTRUSTWORTHY_LINES="false"' in off
    assert 'SKIP_UNTRUSTWORTHY_LINES="true"' in on


def test_the_runner_flag_reaches_the_stages(tmp_path, monkeypatch):
    seen = {}

    def fake_run(cmd, env, cwd):
        seen.setdefault("env", env.get("SKIP_UNTRUSTWORTHY_LINES"))
        return 0

    monkeypatch.setattr(run_pipeline, "_run_subprocess", fake_run)
    cfg = enr._derive_config(tmp_path)
    args = ["--config", str(cfg), "--stages", "manifest", "--force", "--skip-untrustworthy-lines"]
    assert run_pipeline.main(args) == 0
    assert seen["env"] == "true"


# ── the record as the text ───────────────────────────────────────────────────────────────────


def _record(tmp_path: Path) -> Path:
    record = {
        "schema_version": "1.0",
        "doc_id": "C-2020-17",
        "pages": [{"page": "i"}, {"page": "1"}],
        "lines": [
            {"page": "i", "line": 1, "text": "Zpráva o výzkumu"},
            {"page": "i", "line": 2, "text": "Ä‚Ä", "categ": "Garbage"},
            {"page": "1", "line": 1, "text": "Hradiště, sonda 2"},
        ],
    }
    path = tmp_path / "C-2020-17.document.json"
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return path


def test_text_from_record_writes_the_table_the_service_makes(tmp_path):
    record_path = _record(tmp_path)
    tables = tmp_path / "tables"
    tables.mkdir()
    written = run_pipeline._write_record_text(str(record_path), str(tables))
    assert written == tables / "C-2020-17.csv"

    record = json.loads(record_path.read_text(encoding="utf-8"))
    enr._write_canonical_csvs(
        record_rows(record), tmp_path / "svc", enr.sanitize_doc_id(record["doc_id"])
    )
    assert written.read_bytes() == (tmp_path / "svc" / "C-2020-17.csv").read_bytes()
    assert [r.text for r in stage1.get_rows(str(written))] == [
        "Zpráva o výzkumu",
        "Hradiště, sonda 2",
    ]


def test_text_from_record_never_replaces_an_input(tmp_path, capsys):
    record_path = _record(tmp_path)
    tables = tmp_path / "tables"
    tables.mkdir()
    (tables / "C-2020-17.csv").write_text("text\nmine\n", encoding="utf-8")
    assert run_pipeline._write_record_text(str(record_path), str(tables)) is None
    assert (tables / "C-2020-17.csv").read_text(encoding="utf-8") == "text\nmine\n"
    assert "not replacing" in capsys.readouterr().err


def test_text_from_record_needs_the_record(tmp_path):
    cfg = enr._derive_config(tmp_path)
    assert run_pipeline.main(["--config", str(cfg), "--text-from-record"]) == 2


# ── the doc_id the runner predicts ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["CTX1.xlsx", "CTX1.txt", "report.v2.csv"])
def test_the_doc_id_of_every_stage1_input_is_predicted(tmp_path, name):
    (tmp_path / name).write_bytes(b"x")
    assert run_pipeline._pipeline_doc_id(str(tmp_path)) == canonical_doc_id(name)


def test_a_converted_teitok_file_gives_the_doc_id_when_no_table_does(tmp_path):
    tables, flexiconv = tmp_path / "tables", tmp_path / "flexiconv"
    tables.mkdir()
    flexiconv.mkdir()
    (flexiconv / "zprava.teitok.xml").write_bytes(TEITOK_BYTES)
    assert run_pipeline._pipeline_doc_id(str(tables)) is None
    assert run_pipeline._pipeline_doc_id(str(tables), str(flexiconv)) == "zprava"
    (tables / "tabulka.csv").write_bytes(CSV_BYTES)
    assert run_pipeline._pipeline_doc_id(str(tables), str(flexiconv)) == "tabulka"


# ── end to end: stage 1's script, and the service field ──────────────────────────────────────


def test_stage1_reads_text_files_filters_on_request_and_names_what_it_skips(tmp_path, capfd):
    cfg = enr._derive_config(tmp_path)
    # The service pins the key per request; config_api.txt has the form the runner's flag sets.
    cfg.write_text(
        cfg.read_text(encoding="utf-8").replace(
            'SKIP_UNTRUSTWORTHY_LINES="false"',
            'SKIP_UNTRUSTWORTHY_LINES="${SKIP_UNTRUSTWORTHY_LINES:-false}"',
        ),
        encoding="utf-8",
    )
    (tmp_path / "in" / "tabulka.csv").write_bytes(CSV_BYTES)
    (tmp_path / "in" / "prosty.txt").write_bytes(TXT_BYTES)
    (tmp_path / "in" / "scan.pdf").write_bytes(b"%PDF-1.7")
    args = ["--config", str(cfg), "--stages", "manifest", "--skip-untrustworthy-lines"]
    assert run_pipeline.main(args) == 0

    manifest = (tmp_path / "out" / "manifest.tsv").read_text(encoding="utf-8")
    assert "tabulka\t2\t" in manifest and "prosty\t2\t" in manifest
    text = (tmp_path / "tmp" / "TXT_EXTRACT" / "tabulka.txt").read_text(encoding="utf-8")
    assert "x#@" not in text and "Titul zprávy" in text
    err = capfd.readouterr().err
    assert "skipped" in err and "scan.pdf" in err
    records = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in (tmp_path / "out" / "paradata").glob("*.json")
    ]
    (para,) = [r for r in records if (r.get("config") or {}).get("script") == "api_1_manifest"]
    assert para["config"]["skip_untrustworthy_lines"] == "true"
    assert any("scan.pdf" in str(s) for s in para.get("skipped_files_detail", []))


def test_the_service_passes_skip_untrustworthy_lines_to_the_pipeline(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from service import api

    seen = {}

    def capture(self, rows, doc_id, **kwargs):
        seen.update(kwargs, rows=rows)
        raise enr.PipelineError("stop here", 502, 1)

    monkeypatch.setattr(enr.PipelineManager, "enrich", capture)
    files = {"file": ("tabulka.csv", CSV_BYTES, "text/csv")}
    client = TestClient(api.app)
    client.post("/enrich", files=files, data={"skip_untrustworthy_lines": "true"})
    assert seen["skip_untrustworthy_lines"] is True
    assert {r.get("categ") for r in seen["rows"]} == {"Clear", "Noisy", "Trash"}
    client.post("/enrich", files=files)
    assert seen["skip_untrustworthy_lines"] is False


def test_the_doc_id_of_an_upload_is_the_command_lines():
    for name in ("zpráva 1.csv", "CTX01.v2.csv", "report.teitok.xml", "scan.txt"):
        assert enr.sanitize_doc_id(name) == canonical_doc_id(name)
    assert (
        enr.sanitize_doc_id("bad\tname.csv") == "bad_name"
    )  # a control character cannot be a name
    assert enr.sanitize_doc_id(".hidden.csv") == "hidden"


def test_the_service_hands_stage_1_the_upload_and_returns_a_record_on_request(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from service import api

    seen = {}

    def capture(self, rows, doc_id, **kwargs):
        seen.update(kwargs, doc_id=doc_id)
        raise enr.PipelineError("stop here", 502, 1)

    monkeypatch.setattr(enr.PipelineManager, "enrich", capture)
    client = TestClient(api.app)
    client.post(
        "/enrich",
        files={"file": ("zpráva 1.txt", TXT_BYTES, "text/plain")},
        data={"include_record": "true"},
    )
    assert seen["source"] == ("zpráva 1.txt", TXT_BYTES)
    assert seen["include_record"] is True
    client.post("/enrich", files={"file": ("page.teitok.xml", TEITOK_BYTES, "application/xml")})
    assert seen["source"] is None  # a TEITOK file is its own layout; its rows go in as the table
    client.post(
        "/enrich_text",
        json={
            "lines": [{"text": "x", "categ": "Trash"}],
            "skip_untrustworthy_lines": True,
            "include_record": True,
        },
    )
    assert seen["skip_untrustworthy_lines"] is True and seen["include_record"] is True


def test_lang_other_than_cs_is_refused_on_both_sides(capsys):
    with pytest.raises(SystemExit) as stop:
        run_pipeline.main(["--lang", "de", "--dry-run"])
    assert stop.value.code == 2
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from service import api

    response = TestClient(api.app).post(
        "/enrich", files={"file": ("a.csv", CSV_BYTES, "text/csv")}, data={"lang": "de"}
    )
    assert response.status_code == 422
