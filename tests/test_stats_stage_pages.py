"""api_4_stats.sh end to end on a committed sample: real pages, and the contract gate.

CTX000000002 has four pages. Before issue #38 stage 4 read UDPipe's chunk markers as pages,
so its summary said "page 1" for everything and its TEITOK kept page 4's first line on
page 3. The stage now reads the rows file stage 2 keeps next to the CoNLL-U.
"""

import csv
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLES = REPO_ROOT / "data_samples"
DOC = "CTX000000002"

pytest.importorskip("lxml", reason="the stage's output-contract gate needs lxml")


def _stage4(tmp_path, extra_teitok=None):
    out = tmp_path / "out"
    (out / "UDP").mkdir(parents=True)
    shutil.copy(SAMPLES / "UDP" / f"{DOC}.conllu", out / "UDP")
    shutil.copy(SAMPLES / "UDP" / f"{DOC}.rows.tsv", out / "UDP")
    shutil.copytree(SAMPLES / "NE" / DOC, out / "NE" / DOC)
    if extra_teitok is not None:
        (out / "TEITOK").mkdir()
        (out / "TEITOK" / "old.teitok.xml").write_text(extra_teitok, encoding="utf-8")
    cfg = tmp_path / "config.txt"
    cfg.write_text(
        f'OUTPUT_DIR="{out}"\n'
        'CONLLU_INPUT_DIR="$OUTPUT_DIR/UDP"\n'
        'TSV_INPUT_DIR="$OUTPUT_DIR/NE"\n'
        'SUMMARY_OUTPUT_DIR="$OUTPUT_DIR/UDP_NE"\n'
        'TEITOK_OUTPUT_DIR="$OUTPUT_DIR/TEITOK"\n'
        f'INPUT_ALTO_DIR="{SAMPLES / "ALTO"}"\n'
        'PARADATA_DIR="$OUTPUT_DIR/paradata"\n'
        f'TEMP_TXT_DIR="{tmp_path / "txt"}"\n'
        'MODEL_NAMETAG="nametag3-czech-cnec2.0-240830"\n'
        "SAVE_CSV=true\nSAVE_CONLLU_NE=true\nSAVE_TEITOK=true\n",
        encoding="utf-8",
    )
    env = dict(os.environ, ATRIUM_CONFIG=str(cfg))
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    run = subprocess.run(
        ["bash", str(REPO_ROOT / "api_4_stats.sh")],
        capture_output=True, text=True, cwd=REPO_ROOT, env=env,
    )  # fmt: skip
    return out, run


def test_stage_4_writes_real_pages(tmp_path):
    out, run = _stage4(tmp_path)
    assert run.returncode == 0, run.stdout + run.stderr

    with open(out / "UDP_NE" / DOC / f"{DOC}.csv", encoding="utf-8") as fh:
        pages = [row["page_id"] for row in csv.DictReader(fh)]
    assert sorted(set(pages), key=int) == ["1", "2", "3", "4"]
    tokens_on_page_4 = [p for p in pages if p == "4"]
    assert len(tokens_on_page_4) == 11  # "Soubor nálezů byl uložen v depozitáři." + "A123/2024"

    # the summary has a row per page with entities: the pages whose NE file has a B- tag
    with_entities = sorted(
        re.search(r"-(\d+)\.tsv$", f.name).group(1)
        for f in (SAMPLES / "NE" / DOC).glob("*.tsv")
        if "\tB-" in f.read_text(encoding="utf-8")
    )
    with open(out / "summary_ne_counts.csv", encoding="utf-8-sig") as fh:
        summary_pages = [row["page"] for row in csv.DictReader(fh)]
    assert summary_pages == with_entities and len(with_entities) > 1

    # Pages, lines and tokens as in the committed sample. (Not byte-identical: NE/ holds
    # OntoNotes tags, while the committed TEITOK was written from the CNEC-tagged UDP_NE/
    # CoNLL-U -- the samples predate the OntoNotes default; a LINDAT refresh aligns them.)
    def layout(path):
        root = ET.parse(path).getroot()
        return [
            (el.tag, el.get("id"), el.get("bbox"))
            for el in root.find("text").iter()
            if el.tag in ("pb", "lb", "tok", "s", "div")
        ]

    written = out / "TEITOK" / f"{DOC}.teitok.xml"
    assert layout(written) == layout(SAMPLES / "TEITOK" / f"{DOC}.teitok.xml")
    s5 = ET.parse(written).getroot().find(".//s[@id='s-5']")
    assert [el.get("id") for el in s5.iter() if el.tag in ("pb", "lb")] == [
        "lb-3.2",
        "pb-4",
        "lb-4.1",
    ]


def test_stage_4_exits_5_when_the_output_contract_fails(tmp_path):
    """A teitok-2 file with a duplicate page id passes the XSD but not the contract; the
    stage halts with exit 5 -- not 1, which means "the run produced nothing"."""
    broken = (SAMPLES / "TEITOK" / f"{DOC}.teitok.xml").read_text(encoding="utf-8")
    broken = broken.replace('id="pb-3"', 'id="pb-2"', 1)
    _, run = _stage4(tmp_path, extra_teitok=broken)
    assert run.returncode == 5, run.stdout + run.stderr
    assert "TEITOK output contract failed" in run.stderr
    assert "duplicate @id 'pb-2'" in run.stderr
