"""
tests/test_annotation_kit.py
============================
The annotation kit under ``annotation/`` (issue #18) is hand-edited text and data, and it
drifted once already: the Label Studio configuration was committed as ``achaeo_labels.xml``
while the README told annotators to paste ``archaeo_labels.xml``, and the contents table named
neither the doccano pair nor the label JSON. What is kept consistent here, all on the fast lane
(standard library only, no Label Studio or doccano needed):

* the README's contents table names exactly the files of the directory;
* the six ``archaeo`` types, their hotkeys and colours are the same in the Label Studio XML, the
  doccano JSON, ``GUIDELINES.md`` and ``api_util/ner_types.py`` (the TEITOK mapping);
* ``data_samples_converted/`` holds valid Label Studio tasks, and the two samples the README's
  commands make are what those commands make today.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from api_util.ner_types import ARCHAEO_TO_CONLL

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / "annotation"
SAMPLES = KIT / "data_samples_converted"


def _readme_table() -> set[str]:
    """The backticked names in the first column of the README's contents table."""
    names: set[str] = set()
    in_table = False
    for line in (KIT / "README.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("| File"):
            in_table = True
        elif in_table and not line.startswith("|"):
            break
        elif in_table:
            names.update(n.rstrip("/") for n in re.findall(r"`([^`]+)`", line.split("|")[1]))
    return names


def test_the_readme_table_names_exactly_the_files_of_the_kit():
    present = {
        p.name
        for p in KIT.iterdir()
        if p.name != "README.md" and not p.name.startswith((".", "__"))  # .env, __pycache__
    }
    named = _readme_table()
    assert named == present, (
        f"in the table only: {sorted(named - present)}; in the directory only: {sorted(present - named)}"
    )


def _xml_labels() -> dict[str, tuple[str, str]]:
    root = ET.parse(KIT / "archaeo_labels.xml").getroot()
    return {
        el.get("value"): (el.get("hotkey"), el.get("background").lower())
        for el in root.iter("Label")
    }


def _json_labels() -> dict[str, tuple[str, str]]:
    labels = json.loads((KIT / "archaeo_labels.json").read_text(encoding="utf-8"))
    return {d["text"]: (d["suffix_key"], d["background_color"].lower()) for d in labels}


def _guideline_hotkeys() -> dict[str, str]:
    """``{type: hotkey}`` from the table at the top of GUIDELINES.md."""
    rows = re.findall(
        r"^\|\s*`([A-Z]+)`\s*\|\s*(\w)\s*\|",
        (KIT / "GUIDELINES.md").read_text(encoding="utf-8"),
        re.M,
    )
    return dict(rows)


def test_the_six_types_are_the_same_in_every_file_that_names_them():
    xml, doccano, guidelines = _xml_labels(), _json_labels(), _guideline_hotkeys()
    types = set(ARCHAEO_TO_CONLL)
    assert len(types) == 6
    assert set(xml) == set(doccano) == set(guidelines) == types


def test_hotkeys_and_colours_agree_between_the_two_tools_and_the_guidelines():
    xml, doccano, guidelines = _xml_labels(), _json_labels(), _guideline_hotkeys()
    assert xml == doccano, (
        "Label Studio and doccano must show an annotator the same keys and colours"
    )
    assert {t: key for t, (key, _) in xml.items()} == guidelines
    assert len({key for key, _ in xml.values()}) == len(xml), "one hotkey per type"


@pytest.mark.parametrize("sample", sorted(SAMPLES.glob("*.json")), ids=lambda p: p.name)
def test_a_converted_sample_is_made_of_label_studio_tasks_whose_spans_slice_their_text(sample):
    tasks = json.loads(sample.read_text(encoding="utf-8"))
    assert tasks
    for task in tasks:
        text = task["data"]["text"]
        spans = [r["value"] for prediction in task["predictions"] for r in prediction["result"]]
        assert spans
        for span in spans:
            assert text[span["start"] : span["end"]] == span["text"], span


def _convert(tmp_path: Path, *args: str) -> str:
    out = tmp_path / "out.json"
    subprocess.run(
        [sys.executable, str(KIT / "conllu_to_ls.py"), *args, "-o", str(out)],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return out.read_text(encoding="utf-8")


def test_command_2_of_the_readme_makes_import_preannot(tmp_path):
    made = _convert(
        tmp_path,
        "--conllu",
        "data_samples/UDP_NE/CTX000000001/CTX000000001.conllu",
        "--ner-from-misc",
    )
    assert made == (SAMPLES / "import_preannot.json").read_text(encoding="utf-8")


def test_command_3_of_the_readme_makes_import_tsv_from_both_page_chunks(tmp_path):
    chunks = sorted((ROOT / "data_samples" / "NE" / "CTX000000001").glob("CTX000000001-*.tsv"))
    assert len(chunks) == 2
    joined = tmp_path / "CTX000000001.tsv"
    joined.write_bytes(b"".join(c.read_bytes() for c in chunks))
    made = _convert(tmp_path, "--tsv", str(joined))
    assert made == (SAMPLES / "import_tsv.json").read_text(encoding="utf-8")
