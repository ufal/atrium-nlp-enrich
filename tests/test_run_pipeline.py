"""
tests/test_run_pipeline.py
==========================
Unit tests for the pure helper functions in ``run_pipeline.py``.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

import run_pipeline as rp


class TestParseConfig:
    def _write(self, tmp_path, body):
        p = tmp_path / "config_api.txt"
        p.write_text(body, encoding="utf-8")
        return p

    def test_simple_assignment(self, tmp_path):
        cfg = self._write(tmp_path, 'OUTPUT_DIR="./out"\n')
        values = rp._parse_config(cfg)
        assert values["OUTPUT_DIR"] == "./out"

    def test_var_expansion_braced(self, tmp_path):
        cfg = self._write(tmp_path, 'OUTPUT_DIR="./out"\nPARADATA_DIR="${OUTPUT_DIR}/paradata"\n')
        values = rp._parse_config(cfg)
        assert values["PARADATA_DIR"] == "./out/paradata"

    def test_var_expansion_unbraced(self, tmp_path):
        cfg = self._write(
            tmp_path, 'OUTPUT_DIR="./out"\nINPUT_TABLES_DIR="$OUTPUT_DIR/DOC_LINE_CATEG"\n'
        )
        values = rp._parse_config(cfg)
        assert values["INPUT_TABLES_DIR"] == "./out/DOC_LINE_CATEG"

    def test_default_form_takes_the_environment_or_the_default(self, tmp_path, monkeypatch):
        """config_api.txt's env-overridable knobs (`TEITOK_ENRICHMENT="${TEITOK_ENRICHMENT:-false}"`)
        were kept literally, so an exported TEITOK_ENRICHMENT=true never reached the runner."""
        cfg = self._write(tmp_path, 'KNOB="${KNOB:-false}"\nOTHER="${UNSET_KNOB:-}"\n')
        monkeypatch.delenv("KNOB", raising=False)
        monkeypatch.delenv("UNSET_KNOB", raising=False)
        assert rp._parse_config(cfg) == {"KNOB": "false", "OTHER": ""}
        monkeypatch.setenv("KNOB", "true")
        assert rp._parse_config(cfg)["KNOB"] == "true"
        monkeypatch.setenv("KNOB", "")
        assert rp._parse_config(cfg)["KNOB"] == "false"

    def test_comment_and_blank_lines_ignored(self, tmp_path):
        cfg = self._write(tmp_path, "# comment\n\nOUTPUT_DIR=x\n")
        values = rp._parse_config(cfg)
        assert values == {"OUTPUT_DIR": "x"}


class TestBuildPlan:
    def _args(self, **kwargs):
        ns = argparse.Namespace(
            stages=["manifest", "udp", "nt", "stats"],
            config=Path("dummy"),
            force=False,
        )
        for k, v in kwargs.items():
            setattr(ns, k, v)
        return ns

    _VALUES = {
        "OUTPUT_DIR": "./out",
        "PARADATA_DIR": "./out/paradata",
        "INPUT_TABLES_DIR": "./out/DOC_LINE_CATEG",
        "FAIL_ON_EMPTY": "true",
    }

    def test_core_only_plan_has_four_stages(self):
        plan = rp._build_plan(self._args(), self._VALUES)
        names = [s["name"] for s in plan["stage_plan"]]
        assert names == ["manifest", "udp", "nt", "stats"]

    def test_force_flag_overrides_fail_on_empty(self):
        vals = dict(self._VALUES, FAIL_ON_EMPTY="true")
        plan = rp._build_plan(self._args(force=True), vals)
        assert plan["fail_on_empty"] is False


class TestDocumentJsonOutReporting:
    """(atrium-project#10, J4) ``--document-json-out`` promised a file; say so when there
    isn't one.

    A document-hook failure degrades to a stderr warning inside
    ``summarize_nt_udp.process_single_document()`` and the runner exits **0** with the
    promised file absent. That degradation is correct per rule 3 — every other nlp-enrich
    output is present and valid, and a standalone run must not die because an upstream
    baseline was missing — but it left an automated caller with no way to notice short of
    grepping stderr for a line printed hundreds of lines earlier. These tests pin the
    terminal stdout marker that closes the gap, and equally that it stays silent on the
    happy path (a marker that always fires is one nobody can act on).
    """

    def _config(self, tmp_path):
        cfg = tmp_path / "config_api.txt"
        cfg.write_text(
            f'OUTPUT_DIR="{tmp_path}/out"\n'
            f'PARADATA_DIR="{tmp_path}/out/paradata"\n'
            f'INPUT_TABLES_DIR="{tmp_path}/in"\n'
            "FAIL_ON_EMPTY=true\n",
            encoding="utf-8",
        )
        (tmp_path / "in").mkdir()
        # Exactly one CSV, so _pipeline_doc_id() resolves the id both ends of the bridge
        # agree on rather than falling back to globbing.
        (tmp_path / "in" / "CTX000000001.csv").write_text(
            "text,page_num,line_num\nPraha,1,1\n", encoding="utf-8"
        )
        return cfg

    def test_marker_on_stdout_when_no_record_was_produced(self, tmp_path, monkeypatch, capsys):
        cfg = self._config(tmp_path)
        out_json = tmp_path / "asked_for.document.json"

        # Stage runs, exits 0, writes no document record — exactly what a swallowed
        # document-hook failure looks like from out here.
        monkeypatch.setattr(rp, "_run_subprocess", lambda cmd, env, cwd: 0)

        rc = rp.main(
            ["--config", str(cfg), "--stages", "stats", "--document-json-out", str(out_json)]
        )

        captured = capsys.readouterr()
        assert rc == 0, "the graceful degradation must survive: detectable, not fatal"
        assert not out_json.exists()
        assert rp.DOC_JSON_NOT_WRITTEN_MARKER in captured.out
        assert str(out_json) in captured.out
        # On stdout, not only stderr — the whole point is that a caller capturing stdout
        # sees it without parsing the log stream.
        assert rp.DOC_JSON_NOT_WRITTEN_MARKER not in captured.err

    def test_no_marker_when_the_record_was_written(self, tmp_path, monkeypatch, capsys):
        cfg = self._config(tmp_path)
        out_json = tmp_path / "asked_for.document.json"

        def _fake_stage(cmd, env, cwd):
            """Write the record where the bridge told the stats stage to put it."""
            scratch = Path(cmd[cmd.index("--document-json-dir") + 1])
            (scratch / "CTX000000001.document.json").write_text(
                '{"schema_version": "1.0", "doc_id": "CTX000000001"}', encoding="utf-8"
            )
            return 0

        monkeypatch.setattr(rp, "_run_subprocess", _fake_stage)

        rc = rp.main(
            ["--config", str(cfg), "--stages", "stats", "--document-json-out", str(out_json)]
        )

        captured = capsys.readouterr()
        assert rc == 0
        assert out_json.exists()
        assert rp.DOC_JSON_NOT_WRITTEN_MARKER not in captured.out

    def test_a_seed_the_hook_never_rewrote_is_not_handed_back(self, tmp_path, monkeypatch, capsys):
        """The hook raised (summarize_nt_udp.py warns and carries on): the scratch record is still
        the caller's own seed. Copying it out returned the caller's record as if enriched."""
        cfg = self._config(tmp_path)
        baseline = tmp_path / "baseline.document.json"
        baseline.write_text('{"schema_version": "1.0", "doc_id": "CTX000000001"}', encoding="utf-8")
        out_json = tmp_path / "asked_for.document.json"
        monkeypatch.setattr(rp, "_run_subprocess", lambda cmd, env, cwd: 0)

        rc = rp.main(
            ["--config", str(cfg), "--stages", "stats"]
            + ["--document-json", str(baseline), "--document-json-out", str(out_json)]
        )

        captured = capsys.readouterr()
        assert rc == 0
        assert not out_json.exists()
        assert rp.DOC_JSON_NOT_WRITTEN_MARKER in captured.out
        assert "the document hook did not update the record" in captured.err

    def test_no_marker_when_the_flag_was_never_passed(self, tmp_path, monkeypatch, capsys):
        """No promise, nothing to report — the marker must not appear for the majority of
        runs that never ask for a document record."""
        cfg = self._config(tmp_path)
        monkeypatch.setattr(rp, "_run_subprocess", lambda cmd, env, cwd: 0)

        rc = rp.main(["--config", str(cfg), "--stages", "stats"])

        assert rc == 0
        assert rp.DOC_JSON_NOT_WRITTEN_MARKER not in capsys.readouterr().out


def test_is_empty_failure_strict():
    stats_all_skipped = {"total": 3, "processed": 0, "skipped": 3}

    # strict=False: skipped >= total means it's considered NOT an empty failure (a cached run)
    assert rp._is_empty_failure(stats_all_skipped, strict=False) is False

    # strict=True: processed == 0 means it IS an empty failure
    assert rp._is_empty_failure(stats_all_skipped, strict=True) is True


# ── the stages' Python and the exit code (atrium-nlp-enrich#42) ───────────────


def _stage_python(tmp_path, missing=()):
    """A `python3` on its own PATH that cannot import ``missing`` (it answers the probe)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "python3"
    # Called as `python3 -c <probe> <module>...`: print the asked modules that are missing.
    script = (
        "#!/bin/sh\n"
        "shift 2\n"
        'for m in "$@"; do\n'
        "  case ' MISSING ' in *\" $m \"*) printf '%s ' \"$m\" ;; esac\n"
        "done\n"
        "echo\n"
    )
    exe.write_text(script.replace("MISSING", " ".join(missing)), encoding="utf-8")
    exe.chmod(0o755)
    return bindir


def test_a_stage_python_without_lxml_is_named_with_the_fix(tmp_path):
    bindir = _stage_python(tmp_path, missing=("lxml",))
    problem = rp._stage_python_problem(
        {"PATH": str(bindir)}, ["manifest", "udp", "nt", "stats"], {}
    )
    assert f"({bindir / 'python3'})" in problem
    assert "cannot import lxml." in problem
    assert "-m pip install -r requirements.txt" in problem


def test_a_stage_python_with_the_packages_passes(tmp_path):
    bindir = _stage_python(tmp_path)
    assert rp._stage_python_problem({"PATH": str(bindir)}, ["udp", "stats"], {}) is None


def test_lxml_is_not_asked_for_when_stage_4_writes_no_teitok(tmp_path):
    bindir = _stage_python(tmp_path, missing=("lxml",))
    env = {"PATH": str(bindir)}
    assert rp._stage_python_problem(env, ["stats"], {"SAVE_TEITOK": "false"}) is None
    assert rp._stage_python_problem(env, ["manifest"], {}) is None


def test_no_python3_on_path_is_said(tmp_path):
    problem = rp._stage_python_problem({"PATH": str(tmp_path)}, ["udp"], {})
    assert "there is none on PATH" in problem


def test_a_virtual_environment_s_bin_goes_first_on_the_stages_path(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setattr(rp.sys, "executable", "/opt/venv/bin/python")
    monkeypatch.setattr(rp.sys, "prefix", "/opt/venv")
    monkeypatch.setattr(rp.sys, "base_prefix", "/usr")
    assert rp._build_stage_env()["PATH"] == "/opt/venv/bin" + os.pathsep + "/usr/bin"

    monkeypatch.setattr(rp.sys, "base_prefix", "/opt/venv")  # not a virtual environment
    assert rp._build_stage_env()["PATH"] == "/usr/bin"


def test_a_failed_preflight_stops_before_any_stage(tmp_path, monkeypatch, capsys):
    from service.enrichment import _derive_config

    cfg = _derive_config(tmp_path)
    ran = []
    monkeypatch.setattr(rp, "_run_subprocess", lambda cmd, env, cwd: ran.append(cmd) or 0)
    monkeypatch.setattr(rp, "_stage_python_problem", lambda env, stages, values: "no lxml")

    assert rp.main(["--config", str(cfg), "--stages", "stats"]) == 3
    assert ran == []
    assert "[ERROR] no lxml" in capsys.readouterr().err

    # --force overrides exit 3 (README, "Exit codes")
    assert rp.main(["--config", str(cfg), "--stages", "stats", "--force"]) == 0
    assert len(ran) == 1


def test_the_command_line_exits_with_the_runner_s_code(tmp_path):
    """A bare main() exited 0 whatever it returned: a failed stage read as a success to the
    service and to every script (atrium-nlp-enrich#42)."""
    from service.enrichment import _derive_config

    cfg = _derive_config(tmp_path)  # no input: --strict-empty makes the empty manifest fail
    proc = subprocess.run(
        [sys.executable, str(rp._REPO_ROOT / "run_pipeline.py"), "--config", str(cfg)]
        + ["--stages", "manifest", "--strict-empty"],
        cwd=str(rp._REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "[FAIL] Stage(s) processed nothing" in proc.stderr
