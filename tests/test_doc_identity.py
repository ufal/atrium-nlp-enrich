"""Which document a converted flexiconv file is, and which table claims it (issue #38, B).

Stage 1 used to call a converted file by its full name (``report.txt.teitok.xml`` ->
``report.txt``) while stage 4 matched it by ``canonical_doc_id`` of its stem (``report``): a
table ``report.csv`` and its converted twin were then both annotated, and of two same-stem
conversions the first one sorted silently served the table.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from api_util.doc_identity import (
    claimed_by,
    converted_doc_id,
    find_converted,
    layout_source,
    source_doc_id,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
FLEX = REPO_ROOT / "tests" / "fixtures" / "teitok" / "flexiconv"


def test_converted_files_keep_file_identity():
    assert converted_doc_id("x/report.txt.teitok.xml") == "report.txt"
    assert converted_doc_id("report.teitok.xml") == "report"
    assert source_doc_id("report.v2.teitok.xml") == "report"
    assert source_doc_id("CTX1.alto.teitok.xml") == "CTX1"


def test_find_converted_exact_then_unique_then_nothing(tmp_path, capsys):
    for name in ("notes.teitok.xml", "notes.md.teitok.xml", "report.v2.teitok.xml"):
        (tmp_path / name).write_text("<TEI/>", encoding="utf-8")
    assert find_converted("notes", tmp_path) == tmp_path / "notes.teitok.xml"
    assert find_converted("notes.md", tmp_path) == tmp_path / "notes.md.teitok.xml"
    assert find_converted("report", tmp_path) == tmp_path / "report.v2.teitok.xml"
    assert find_converted("missing", tmp_path) is None
    assert find_converted("report", None) is None

    (tmp_path / "report.txt.teitok.xml").write_text("<TEI/>", encoding="utf-8")
    assert find_converted("report", tmp_path) is None  # two candidates: none is used
    assert "ambiguous converted layout" in capsys.readouterr().err


def test_a_table_claims_its_converted_twin(tmp_path):
    (tmp_path / "report.txt.teitok.xml").write_text("<TEI/>", encoding="utf-8")
    (tmp_path / "other.teitok.xml").write_text("<TEI/>", encoding="utf-8")
    assert claimed_by(tmp_path / "report.txt.teitok.xml", ["report"]) == "report"
    assert claimed_by(tmp_path / "other.teitok.xml", ["report"]) == ""
    assert claimed_by(tmp_path / "other.teitok.xml", ["other"]) == "other"


def test_layout_source_prefers_alto(tmp_path):
    alto_dir, flex_dir = tmp_path / "ALTO", tmp_path / "flexiconv"
    alto_dir.mkdir()
    flex_dir.mkdir()
    (flex_dir / "doc.teitok.xml").write_text("<TEI/>", encoding="utf-8")
    assert layout_source("doc", alto_dir, flex_dir) == flex_dir / "doc.teitok.xml"
    (alto_dir / "doc.alto.xml").write_text("<alto/>", encoding="utf-8")
    assert layout_source("doc", alto_dir, flex_dir) == alto_dir / "doc.alto.xml"


def _manifest(tmp_path, converted):
    tables, flex = tmp_path / "tables", tmp_path / "flexiconv"
    tables.mkdir()
    flex.mkdir()
    (tables / "report.csv").write_text("text,page_num,line_num\nTabulka,1,1\n", encoding="utf-8")
    for name in converted:
        shutil.copy(FLEX / "txt.teitok.xml", flex / name)
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
    env = dict(os.environ, ATRIUM_CONFIG=str(cfg), FLEXICONV_ANNOTATE="true")
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    run = subprocess.run(
        ["bash", str(REPO_ROOT / "api_1_manifest.sh")],
        capture_output=True, text=True, cwd=REPO_ROOT, env=env,
    )  # fmt: skip
    assert run.returncode == 0, run.stderr
    rows = (tmp_path / "out" / "manifest.tsv").read_text(encoding="utf-8").splitlines()[1:]
    paradata = next((tmp_path / "out" / "paradata").glob("*.json")).read_text(encoding="utf-8")
    return sorted(r.split("\t")[0] for r in rows), json.loads(paradata)


def test_manifest_annotates_a_table_and_its_converted_twin_once(tmp_path):
    ids, paradata = _manifest(tmp_path, ["report.txt.teitok.xml"])
    assert ids == ["report"]
    assert "layout of table document report" in json.dumps(paradata)


def test_manifest_keeps_ambiguous_conversions_as_documents(tmp_path):
    ids, _ = _manifest(tmp_path, ["report.txt.teitok.xml", "report.md.teitok.xml"])
    assert ids == ["report", "report.md", "report.txt"]
