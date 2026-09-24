"""FLEXICONV_ANNOTATE: flexiconv-converted documents through the linguistic stages (#10, stage 6).

Offline end to end. The flexiconv inputs are real v0.3.10 output
(tests/fixtures/teitok/flexiconv/), and the NER-merged CoNLL-U for their text is written by
hand (tests/fixtures/teitok/flexiconv/annotated/), standing in for UDPipe + NameTag, which
need LINDAT. The chain under test:

    manifest (build_manifest_row: text of the converted file)
    -> [UDPipe, NameTag]
    -> stage 4 (summarize_nt_udp.layout_source -> teitok_alto + teitok_layout)
    -> TEITOK format 2 with the converted file's layout
"""

import json
import os
import shutil
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path
from unittest.mock import patch

import pytest

import run_pipeline as rp
from api_util.build_manifest_row import get_sorted_text_and_page_count
from api_util.summarize_nt_udp import layout_source, process_single_document
from api_util.teitok_alto import write_teitok_merged
from api_util.validate_teitok_xml import validate_document

REPO_ROOT = Path(__file__).resolve().parent.parent
FLEX = REPO_ROOT / "tests" / "fixtures" / "teitok" / "flexiconv"
ANNOTATED = FLEX / "annotated"
KINDS = ("page", "hocr", "txt", "md")


def _write(tmp_path, kind, **kwargs):
    out = tmp_path / f"{kind}.teitok.xml"
    assert write_teitok_merged(
        str(ANNOTATED / f"{kind}.conllu"),
        str(out),
        str(FLEX / f"{kind}.teitok.xml"),
        doc_id=kind,
        **kwargs,
    )
    return out


def _root(path):
    return ET.parse(str(path)).getroot()


def _tok(root, form):
    return next(t for t in root.iter("tok") if (t.text or "").strip() == form)


# ── the writer with a converted layout source ────────────────────────────────────────────


@pytest.mark.parametrize("kind", KINDS)
def test_output_is_teitok_format_2(tmp_path, kind):
    out = _write(tmp_path, kind)
    assert validate_document(out) == []
    assert validate_document(out, profile="core") == []
    root = _root(out)
    app = next(a for a in root.iter("application") if a.get("ident") == "atrium-nlp-enrich")
    assert app.get("version") == "teitok-2"
    assert root.iter("s") and all(t.get("id", "").startswith("w-") for t in root.iter("tok"))


@pytest.mark.parametrize("kind", KINDS)
def test_spacing_stays_text_faithful(tmp_path, kind):
    """Rebuild every sentence from token text + tail whitespace (the upstream reading)."""
    for s in _root(_write(tmp_path, kind)).iter("s"):
        toks = list(s.iter("tok"))
        rebuilt = "".join(
            (t.text or "").strip() + (" " if " " in (t.tail or "") else "") for t in toks
        )
        assert rebuilt.rstrip() == s.get("text")


def test_page_xml_layout_is_kept(tmp_path):
    root = _root(_write(tmp_path, "page", model_nametag="nametag3-multilingual-onto-260521"))
    assert _tok(root, "Výzkum").get("bbox") == "100 100 300 150"
    assert _tok(root, ".").get("bbox") is None  # flexiconv did not box it
    assert [lb.get("bbox") for lb in root.iter("lb")] == ["100 100 1100 150", "100 200 1100 250"]
    surface = next(root.iter("surface"))
    assert surface.get("id") == "facs-1" and surface.get("lrx") is None  # no page size known
    assert next(root.iter("graphic")).get("url") == "sample_page/page1.png"
    assert next(root.iter("pb")).get("facs") == "sample_page/page1.png"
    div = next(root.iter("div"))
    assert (div.get("type"), div.get("bbox")) == ("TextBlock", "100 100 1100 300")
    name = next(root.iter("name"))
    assert (name.get("type"), name.get("onto"), name.get("sameAs")) == ("LOC", "GPE", "#w-4")


def test_header_names_flexiconv_and_the_original_document(tmp_path):
    root = _root(_write(tmp_path, "page"))
    assert next(root.iter("note")).text == "sample_page.xml"
    converted = next(c for c in root.iter("change") if c.get("type") == "converted")
    assert converted.get("who") == "flexiconv"
    assert converted.text == "Converted from sample_page.xml by flexiconv"
    root = _root(_write(tmp_path, "hocr"))
    app = next(a for a in root.iter("application") if a.get("ident") == "flexiconv")
    assert app.get("version") == "1.0"


def test_hocr_page_size_and_language(tmp_path):
    root = _root(_write(tmp_path, "hocr"))
    surface = next(root.iter("surface"))
    assert (surface.get("lrx"), surface.get("lry")) == ("2162", "3340")
    assert next(root.iter("graphic")).get("url") == "output_page_1.png"
    assert root.get("lang") == "en"  # hOCR's lang, not the UDPipe model's
    assert _tok(root, "METHODIUS").get("bbox") == "802 1263 1327 1337"
    assert [d.get("subtype") for d in root.iter("div")] == ["p", "p"]


def test_plain_documents_keep_their_block_structure_without_a_facsimile(tmp_path):
    txt = _root(_write(tmp_path, "txt"))
    assert list(txt.iter("facsimile")) == []
    assert [d.get("subtype") for d in txt.iter("div")] == ["p", "p"]
    assert not any(el.get("bbox") for el in txt.iter())
    assert next(txt.iter("note")).text == "sample_txt.txt"
    md = _root(_write(tmp_path, "md"))
    assert [d.get("subtype") for d in md.iter("div")] == ["head", "p", "item"]


def _png(path, w, h):
    raw = b"".join(b"\x00" + b"\xff" * ((w + 7) // 8) for _ in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 1, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def test_page_image_is_found_by_its_own_name(tmp_path):
    """A converted page keeps its image name (<pb facs>); with INPUT_PAGES_DIR holding that
    image, the surface gets its size and the boxes stay (already image pixels)."""
    _png(tmp_path / "pages" / "page1.png", 1200, 800)
    root = _root(_write(tmp_path, "page", image_dir=str(tmp_path / "pages")))
    surface = next(root.iter("surface"))
    assert (surface.get("lrx"), surface.get("lry")) == ("1200", "800")
    assert _tok(root, "Výzkum").get("bbox") == "100 100 300 150"


def test_flexiconv_reads_the_annotated_file_back(tmp_path):
    pytest.importorskip("flexiconv")
    from flexiconv.io.teitok_xml import load_teitok

    out = _write(tmp_path, "page")
    doc = load_teitok(str(out))
    tokens = [n.features for n in doc.layers["tokens"].nodes.values()]
    assert [t["form"] for t in tokens] == [
        "Výzkum", "proběhl", "v", "Praze", ".", "Nalezeno", "12", "střepů", ".",
    ]  # fmt: skip
    assert [t["space_after"] for t in tokens[:4]] == [True, True, True, False]


# ── the document record ──────────────────────────────────────────────────────────────────


def test_document_record_gets_boxes_and_ids_from_the_same_parse(tmp_path):
    from api_util.document_hook import run_document_hook

    teitok = _write(tmp_path, "page")
    out_json = tmp_path / "page.document.json"
    run_document_hook(
        doc_id="page",
        teitok_path=str(teitok),
        conllu_path=str(ANNOTATED / "page.conllu"),
        baseline_json=None,
        out_json=str(out_json),
        run_id="260924-120000",
        paradata_ref="paradata/260924-120000_nlp-enrich.json",
        license_detail={},
        alto_path=str(FLEX / "page.teitok.xml"),
    )
    record = json.loads(out_json.read_text(encoding="utf-8"))
    ids = {el.get("id") for el in _root(teitok).iter() if el.get("id")}
    praze = record["entities"][0]
    assert (praze["surface"], praze["type_teitok"], praze["type_onto"]) == ("Praze", "LOC", "GPE")
    assert praze["bbox"] == [620.0, 100.0, 820.0, 150.0]
    assert all(e["teitok_ref"] in ids for e in record["entities"])
    assert record["pages"] == [{"page": "1", "teitok_surface": "facs-1"}]
    jsonschema = pytest.importorskip("jsonschema")
    from atrium_document import load_schema

    jsonschema.validate(record, load_schema())


# ── stage 4: where the layout comes from ─────────────────────────────────────────────────


def test_layout_source_prefers_alto_then_the_converted_file(tmp_path):
    alto_dir, flex_dir = tmp_path / "ALTO", tmp_path / "flexiconv"
    alto_dir.mkdir()
    flex_dir.mkdir()
    shutil.copy(FLEX / "page.teitok.xml", flex_dir / "report.v2.teitok.xml")
    shutil.copy(FLEX / "txt.teitok.xml", flex_dir / "notes.teitok.xml")
    shutil.copy(FLEX / "md.teitok.xml", flex_dir / "notes.md.teitok.xml")

    assert layout_source("notes", alto_dir, flex_dir) == flex_dir / "notes.teitok.xml"
    assert layout_source("notes.md", None, flex_dir) == flex_dir / "notes.md.teitok.xml"
    # flexiconv names by file stem, the manifest / alto-postprocess by canonical_doc_id
    assert layout_source("report", alto_dir, flex_dir) == flex_dir / "report.v2.teitok.xml"
    assert layout_source("report", alto_dir, None) is None
    assert layout_source("missing", alto_dir, flex_dir) is None
    (alto_dir / "notes.alto.xml").write_text("<alto/>", encoding="utf-8")
    assert layout_source("notes", alto_dir, flex_dir) == alto_dir / "notes.alto.xml"


def test_stage_4_hands_the_converted_file_to_the_writer_and_the_hook(tmp_path):
    flex_dir = tmp_path / "flexiconv"
    flex_dir.mkdir()
    shutil.copy(FLEX / "page.teitok.xml", flex_dir / "doc.teitok.xml")
    conllu = tmp_path / "doc.conllu"
    conllu.write_text("1\tPraha\tPraha\tPROPN\t_\t_\t0\troot\t_\t_\n\n", encoding="utf-8")
    ne_dir = tmp_path / "ne"
    ne_dir.mkdir()
    (ne_dir / "doc-1.tsv").write_text("token\ttag\nPraha\tB-gu\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    doc_json = tmp_path / "json"
    doc_json.mkdir()
    with (
        patch("api_util.summarize_nt_udp.write_teitok_merged") as writer,
        patch("api_util.document_hook.run_document_hook") as hook,
    ):
        process_single_document(
            conllu_file=str(conllu),
            ne_dir=str(ne_dir),
            output_dir=str(out_dir),
            save_csv=False,
            save_teitok=True,
            teitok_out=str(tmp_path / "TEITOK"),
            document_json_dir=str(doc_json),
            flexiconv_dir=str(flex_dir),
        )
    assert writer.call_args[0][2] == flex_dir / "doc.teitok.xml"
    assert hook.call_args.kwargs["alto_path"] == str(flex_dir / "doc.teitok.xml")


# ── stage 1: the text ─────────────────────────────────────────────────────────────────────


def test_manifest_text_is_the_converted_documents_rows():
    text, pages = get_sorted_text_and_page_count(str(FLEX / "page.teitok.xml"))
    assert (text, pages) == ("Výzkum proběhl v Praze.\nNalezeno 12 střepů.", 1)
    text, pages = get_sorted_text_and_page_count(str(FLEX / "md.teitok.xml"))
    assert text.splitlines() == ["Nadpis zprávy", "První odstavec důležitý.", "položka seznamu"]


def _python_path_env():
    env = dict(os.environ)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    return env


def test_manifest_row_cli(tmp_path):
    script = REPO_ROOT / "api_util" / "build_manifest_row.py"
    src = tmp_path / "report.v2.teitok.xml"
    shutil.copy(FLEX / "txt.teitok.xml", src)
    run = subprocess.run(
        [sys.executable, str(script), str(src), "--doc-id-only"],
        capture_output=True, text=True, check=True, cwd=REPO_ROOT,
    )  # fmt: skip
    assert run.stdout.strip() == "report.v2"
    assert not (tmp_path / "txt").exists()
    run = subprocess.run(
        [sys.executable, str(script), str(src), "--text-dir", str(tmp_path / "txt")],
        capture_output=True, text=True, check=True, cwd=REPO_ROOT,
    )  # fmt: skip
    doc_id, pages, path = run.stdout.strip().split("\t")
    assert (doc_id, pages) == ("report.v2", "1")
    assert Path(path).read_text(encoding="utf-8").splitlines()[1] == "Druhý odstavec textu."


def _manifest_run(tmp_path, annotate):
    tables, flex = tmp_path / "tables", tmp_path / "flexiconv"
    tables.mkdir(exist_ok=True)
    flex.mkdir(exist_ok=True)
    (tables / "dup.csv").write_text("text,page_num,line_num\nTabulka,1,1\n", encoding="utf-8")
    shutil.copy(FLEX / "txt.teitok.xml", flex / "dup.teitok.xml")
    shutil.copy(FLEX / "page.teitok.xml", flex / "solo.teitok.xml")
    (flex / "empty.teitok.xml").write_text("<TEI><text><body/></text></TEI>", encoding="utf-8")
    cfg = tmp_path / "config.txt"
    cfg.write_text(
        f'OUTPUT_DIR="{tmp_path}/out"\n'
        f'INPUT_TABLES_DIR="{tables}"\n'
        'TEITOK_OUTPUT_DIR="$OUTPUT_DIR/TEITOK"\n'
        f'TEITOK_FLEXICONV_DIR="{flex}"\n'
        f'TEMP_TXT_DIR="{tmp_path}/txt"\n'
        'FLEXICONV_ANNOTATE="${FLEXICONV_ANNOTATE:-false}"\n',
        encoding="utf-8",
    )
    env = _python_path_env()
    env["ATRIUM_CONFIG"] = str(cfg)
    env["FLEXICONV_ANNOTATE"] = "true" if annotate else "false"
    run = subprocess.run(
        ["bash", str(REPO_ROOT / "api_1_manifest.sh")],
        capture_output=True, text=True, cwd=REPO_ROOT, env=env,
    )  # fmt: skip
    assert run.returncode == 0, run.stderr
    rows = (tmp_path / "out" / "manifest.tsv").read_text(encoding="utf-8").splitlines()[1:]
    return {r.split("\t")[0]: r.split("\t")[2] for r in rows}, run


def test_manifest_stage_takes_converted_documents_in_and_tables_win(tmp_path):
    manifest, run = _manifest_run(tmp_path, annotate=True)
    assert set(manifest) == {"dup", "solo"}
    assert Path(manifest["dup"]).read_text(encoding="utf-8") == "Tabulka"  # the table's text
    assert Path(manifest["solo"]).read_text(encoding="utf-8").startswith("Výzkum proběhl")
    assert "empty.teitok.xml: no text" in run.stderr
    paradata = next((tmp_path / "out" / "paradata").glob("*.json"))
    skipped = json.loads(paradata.read_text(encoding="utf-8"))
    assert "doc_id dup already comes from a table input" in json.dumps(skipped)


def test_manifest_stage_ignores_converted_documents_by_default(tmp_path):
    manifest, _ = _manifest_run(tmp_path, annotate=False)
    assert set(manifest) == {"dup"}


# ── the runner ───────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("knob", ["FLEXICONV_ANNOTATE", "REGENERATE_TEITOK"])
def test_one_run_switches_survive_sourcing_the_config(knob):
    """Every stage starts with `source config_api.txt`; a bare `KNOB=false` there would
    overwrite the value the runner (or `KNOB=true bash api_4_stats.sh`) set. The first
    refresh of the samples with REGENERATE_TEITOK=true silently kept the old files."""
    text = (REPO_ROOT / "config_api.txt").read_text(encoding="utf-8")
    assert f'{knob}="${{{knob}:-false}}"' in text
    env = dict(os.environ, **{knob: "true"})
    out = subprocess.run(
        ["bash", "-c", f'source config_api.txt; echo "${knob}"'],
        capture_output=True, text=True, cwd=REPO_ROOT, env=env, check=True,
    )  # fmt: skip
    assert out.stdout.strip() == "true"
    env.pop(knob)
    out = subprocess.run(
        ["bash", "-c", f'source config_api.txt; echo "${knob}"'],
        capture_output=True, text=True, cwd=REPO_ROOT, env=env, check=True,
    )  # fmt: skip
    assert out.stdout.strip() == "false"


def test_runner_with_flexiconv_converts_first_and_annotates(tmp_path, monkeypatch):
    cfg = tmp_path / "config_api.txt"
    cfg.write_text(f'OUTPUT_DIR="{tmp_path}/out"\nFAIL_ON_EMPTY=false\n', encoding="utf-8")
    calls = []
    monkeypatch.setattr(rp, "_run_subprocess", lambda cmd, env, cwd: calls.append((cmd, env)) or 0)
    monkeypatch.setattr(rp, "_space_stages", lambda last: 0.0)

    assert rp.main(["--config", str(cfg), "--with-flexiconv", "--stages", "manifest"]) == 0
    assert [Path(cmd[1]).name for cmd, _ in calls] == ["api_flexiconv.sh", "api_1_manifest.sh"]
    assert all(env["FLEXICONV_ANNOTATE"] == "true" for _, env in calls)

    calls.clear()
    monkeypatch.delenv("FLEXICONV_ANNOTATE", raising=False)
    assert rp.main(["--config", str(cfg), "--stages", "manifest"]) == 0
    assert [Path(cmd[1]).name for cmd, _ in calls] == ["api_1_manifest.sh"]
    assert "FLEXICONV_ANNOTATE" not in calls[0][1]
