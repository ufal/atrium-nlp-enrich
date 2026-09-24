"""The service takes a layout with the text (issue #38, F).

``/enrich`` and ``/jobs`` used to take only .csv/.xlsx/.txt and ran with ``INPUT_ALTO_DIR=""``,
so the service's TEITOK never had a box, and every page carried an invented page image.
Now ``file`` may be a TEITOK document -- flexiconv's conversion of a PDF, DOCX or PAGE XML,
made with the CLI (no GPL code in the service) -- and a table may come with an ``alto`` part.

The end-to-end test runs the real stage-1 and stage-4 scripts inside the service's own
workspace; only UDPipe and NameTag (LINDAT) are stood in for by a prepared CoNLL-U.
"""

import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("fastapi.testclient")
pytest.importorskip("lxml")

from fastapi.testclient import TestClient  # noqa: E402

import service.enrichment as enr  # noqa: E402
from service.api import app  # noqa: E402
from service.enrichment import is_teitok_upload, normalize_upload, sanitize_doc_id  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
PAGE_TEITOK = REPO_ROOT / "tests" / "fixtures" / "teitok" / "flexiconv" / "page.teitok.xml"
SAMPLES = REPO_ROOT / "data_samples"
SAMPLE = "CTX000000003"
_REAL_RUN = subprocess.run

# What UDPipe + NameTag would return for page.teitok.xml's two lines.
_CONLLU = (
    "# sent_id = 1\n# text = Výzkum proběhl v Praze.\n"
    "1\tVýzkum\tvýzkum\tNOUN\t_\t_\t2\tnsubj\t_\t_\n"
    "2\tproběhl\tproběhnout\tVERB\t_\t_\t0\troot\t_\t_\n"
    "3\tv\tv\tADP\t_\t_\t4\tcase\t_\t_\n"
    "4\tPraze\tPraha\tPROPN\t_\t_\t2\tobl\t_\tSpaceAfter=No\n"
    "5\t.\t.\tPUNCT\t_\t_\t2\tpunct\t_\tSpacesAfter=\\n\n\n"
    "# sent_id = 2\n# text = Nalezeno 12 střepů.\n"
    "1\tNalezeno\tnaleznout\tVERB\t_\t_\t0\troot\t_\t_\n"
    "2\t12\t12\tNUM\t_\t_\t3\tnummod\t_\t_\n"
    "3\tstřepů\tstřep\tNOUN\t_\t_\t1\tnsubj\t_\tSpaceAfter=No\n"
    "4\t.\t.\tPUNCT\t_\t_\t1\tpunct\t_\t_\n\n"
)
_NE = "Word\tTag\tNE\n" + "".join(
    f"{w}\t{t}\t\n"
    for w, t in [
        ("Výzkum", "O"),
        ("proběhl", "O"),
        ("v", "O"),
        ("Praze", "B-gu"),
        (".", "O"),
        ("Nalezeno", "O"),
        ("12", "O"),
        ("střepů", "O"),
        (".", "O"),
    ]
)


def _stage_env(cfg):
    env = dict(os.environ, ATRIUM_CONFIG=str(cfg))
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    return env


def _pipeline(cmd, **_kwargs):
    """run_pipeline.py with the LINDAT stages stood in for: real stage 1 and stage 4."""
    cfg = Path(cmd[cmd.index("--config") + 1])
    out = cfg.parent / "out"
    env = _stage_env(cfg)
    logs = []
    first = _REAL_RUN(
        ["bash", str(REPO_ROOT / "api_1_manifest.sh")],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True,
    )  # fmt: skip
    logs.append(first.stdout + first.stderr)
    if first.returncode:
        return SimpleNamespace(returncode=first.returncode, stdout="", stderr="\n".join(logs))
    manifest = (out / "manifest.tsv").read_text(encoding="utf-8").splitlines()[1:]
    for doc, _pages, text_path in (row.split("\t") for row in manifest):
        rows = Path(text_path).with_name(f"{doc}.rows.tsv")
        shutil.copy(rows, out / "UDP" / f"{doc}.rows.tsv")  # what api_2_udp.sh does
        if doc == SAMPLE:  # a committed sample: its own CoNLL-U and NameTag output
            shutil.copy(SAMPLES / "UDP" / f"{doc}.conllu", out / "UDP")
            shutil.copytree(SAMPLES / "NE" / doc, out / "NE" / doc)
            continue
        (out / "UDP" / f"{doc}.conllu").write_text(_CONLLU, encoding="utf-8")
        (out / "NE" / doc).mkdir(parents=True, exist_ok=True)
        (out / "NE" / doc / f"{doc}-1.tsv").write_text(_NE, encoding="utf-8")
    fourth = _REAL_RUN(
        ["bash", str(REPO_ROOT / "api_4_stats.sh")],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True,
    )  # fmt: skip
    logs.append(fourth.stdout + fourth.stderr)
    return SimpleNamespace(returncode=fourth.returncode, stdout="", stderr="\n".join(logs))


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(enr, "_API_JOBS_ROOT", tmp_path)
    monkeypatch.setattr(enr.subprocess, "run", _pipeline)
    return TestClient(app)


def test_a_converted_teitok_upload_is_text_and_layout(client):
    response = client.post(
        "/enrich",
        files={"file": ("report.teitok.xml", PAGE_TEITOK.read_bytes(), "application/xml")},
        data={"kw_method": "none"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["doc_id"] == "report"
    assert body["layout_source"] == "teitok"
    assert body["teitok_schema_valid"] is True, body["teitok_schema_errors"]

    root = ET.fromstring(body["teitok_xml"])
    assert root.find(".//application[@ident='atrium-nlp-enrich']").get("version") == "teitok-2"
    assert root.find(".//note[@n='orgfile']").text == "sample_page.xml"
    toks = {t.text: t for t in root.iter("tok")}
    assert toks["Výzkum"].get("bbox") == "100 100 300 150"  # the PAGE XML word box
    assert toks["Praze"].get("bbox") == "620 100 820 150"
    pb = next(root.iter("pb"))
    assert pb.get("facs") == "sample_page/page1.png" and pb.get("corresp") == "#facs-1"
    assert [lb.get("bbox") for lb in root.iter("lb")] == ["100 100 1100 150", "100 200 1100 250"]
    # the converted file was the table's layout, not a second document
    assert [row["file"] for row in body["ne_summary"]] == ["report"]


def test_a_table_without_layout_has_pages_but_no_invented_images(client):
    csv = "text,page_num,line_num\nVýzkum proběhl v Praze.,1,1\nNalezeno 12 střepů.,2,1\n"
    response = client.post(
        "/enrich",
        files={"file": ("report.csv", csv.encode("utf-8"), "text/csv")},
        data={"kw_method": "none"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["layout_source"] == "rows"
    root = ET.fromstring(body["teitok_xml"])
    assert [(pb.get("id"), pb.get("facs")) for pb in root.iter("pb")] == [
        ("pb-1", None),
        ("pb-2", None),
    ]
    assert root.find("facsimile") is None
    assert root.find(".//note[@n='orgfile']").text == "report.csv"


def test_a_table_with_its_alto_gets_boxes_and_a_facsimile(client):
    """alto-postprocess's DOC_LINE_CATEG table of a page plus that page's ALTO."""
    response = client.post(
        "/enrich",
        files={
            "file": (f"{SAMPLE}.csv", (SAMPLES / "DOC_LINE_CATEG" / f"{SAMPLE}.csv").read_bytes()),
            "alto": (f"{SAMPLE}.alto.xml", (SAMPLES / "ALTO" / f"{SAMPLE}.alto.xml").read_bytes()),
        },
        data={"kw_method": "none"},
    )  # fmt: skip
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["layout_source"] == "alto"
    assert body["teitok_schema_valid"] is True, body["teitok_schema_errors"]
    root = ET.fromstring(body["teitok_xml"])
    assert root.find("facsimile/surface").get("id") == "facs-1"
    assert next(root.iter("pb")).get("bbox") == "0 0 1654 2339"
    assert all(t.get("bbox") for t in root.iter("tok") if t.get("type") == "w")


def test_layout_part_rules(client):
    teitok = PAGE_TEITOK.read_bytes()
    alto = (REPO_ROOT / "data_samples" / "ALTO" / "CTX000000003.alto.xml").read_bytes()
    page_xml = b'<PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2019"/>'
    cases = [
        (("a.txt", b"Praha\n"), ("a.alto.xml", alto), "goes with a .csv or .xlsx"),
        (("a.teitok.xml", teitok), ("a.alto.xml", alto), "carries its own layout"),
        (("a.csv", b"text\nPraha\n"), ("a.xml", page_xml), "convert them with api_flexiconv.sh"),
        (("a.teitok.xml", b"<TEI><text><tok id='w-1'/><tok id='w-1'/></text></TEI>"), None, "duplicate"),
    ]  # fmt: skip
    for upload, alto_part, message in cases:
        files = {"file": (upload[0], upload[1], "application/octet-stream")}
        if alto_part:
            files["alto"] = (alto_part[0], alto_part[1], "application/xml")
        response = client.post("/enrich", files=files, data={"kw_method": "none"})
        assert response.status_code == 422, (upload[0], response.text)
        assert message in response.json()["detail"], response.json()["detail"]


def test_exit_5_is_its_own_error(tmp_path, monkeypatch):
    monkeypatch.setattr(enr, "_API_JOBS_ROOT", tmp_path)
    monkeypatch.setattr(
        enr.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=5, stdout="", stderr="[FAIL] x"),
    )
    response = TestClient(app).post(
        "/enrich",
        files={"file": ("a.csv", b"text\nPraha\n", "text/csv")},
        data={"kw_method": "none"},
    )
    assert response.status_code == 500
    assert "output contract" in response.json()["detail"]


def test_upload_helpers():
    assert is_teitok_upload("x.teitok.xml", b"")
    assert is_teitok_upload("x.xml", b"<?xml version='1.0'?><TEI>")
    assert not is_teitok_upload("x.xml", b"<alto/>")
    assert sanitize_doc_id("report.teitok.xml") == "report"
    assert sanitize_doc_id("CTX1.alto.xml") == "CTX1"
    rows = normalize_upload("a.txt", b"one\ntwo\n\x0cthree\n")
    assert [(r["page_num"], r["line_num"], r["text"]) for r in rows] == [
        (1, 1, "one"),
        (1, 2, "two"),
        (2, 1, "three"),
    ]
