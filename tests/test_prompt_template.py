"""
tests/test_prompt_template.py — the system prompt as data (issue #6, C1).

These run against the SHIPPED `prompts/system_prompt.txt` and `prompts/output_template.json`
rather than fixtures wherever the assertion is about what the pipeline actually sends.
A fixture would pass while the real prompt said something else, which is the failure
this module exists to prevent: the guardrail wording and `taxonomy_config.json` are one
decision held in two files, and the build gate can only enforce that if the text it
checks is the text the model gets.
"""

import json
from pathlib import Path

import pytest

import prompt_template as pt

REPO_ROOT = Path(__file__).resolve().parent.parent


def _blocks():
    return pt.load_blocks()


# ── template parsing ────────────────────────────────────────────────────────────


def test_shipped_template_parses_and_declares_every_required_block():
    blocks = _blocks()
    for name in pt.REQUIRED_BLOCKS:
        assert name in blocks, f"required block [[{name}]] missing from the shipped template"
    assert blocks["vocabulary.header"].endswith("THEMATIC VOCABULARY:\n")


def test_every_shipped_block_is_reachable():
    """A block with no flag and no required status would sit in the file rendering
    nothing — the exact dead config `validate_settings` refuses elsewhere."""
    known = set(pt.REQUIRED_BLOCKS) | set(pt.BLOCK_FLAGS) | {
        b for b in pt.GEO_GUARDRAIL_BLOCKS.values() if b
    }
    assert set(_blocks()) <= known, f"unreachable blocks: {set(_blocks()) - known}"


def test_a_body_keeps_its_leading_blank_line_and_normalises_the_trailing_one(tmp_path):
    """Leading blank lines are load-bearing (that is how `vocabulary.header` asks for a
    blank line ahead of it); trailing ones are not, so an editor stripping whitespace
    cannot change the prompt."""
    f = tmp_path / "t.txt"
    f.write_text("[[a]]\n\nbody\n\n\n[[b]]\nx\n", encoding="utf-8")
    blocks = pt.load_blocks(f)
    assert blocks["a"] == "\nbody\n"
    assert blocks["b"] == "x\n"


def test_a_duplicate_block_is_an_error(tmp_path):
    f = tmp_path / "t.txt"
    f.write_text("[[a]]\nfirst\n[[a]]\nsecond\n", encoding="utf-8")
    with pytest.raises(pt.TemplateError, match="duplicate block"):
        pt.load_blocks(f)


def test_text_before_the_first_block_is_an_error(tmp_path):
    """Almost always a typo'd header; silently discarding it would drop prompt text."""
    f = tmp_path / "t.txt"
    f.write_text("[a]\noops\n[[role]]\nx\n", encoding="utf-8")
    with pytest.raises(pt.TemplateError, match="text before the first"):
        pt.load_blocks(f)


def test_comments_before_the_first_block_are_allowed(tmp_path):
    f = tmp_path / "t.txt"
    f.write_text("# a file comment\n\n[[role]]\nx\n", encoding="utf-8")
    assert pt.load_blocks(f) == {"role": "x\n"}


# ── block selection ─────────────────────────────────────────────────────────────


def test_default_config_renders_every_optional_block():
    """An absent flag means "on": a config that says nothing gets the prompt the
    pipeline has always sent, not a silently reduced one."""
    chosen = set(pt.selected_blocks(_blocks(), {}))
    assert set(pt.BLOCK_FLAGS) <= chosen
    assert "guardrail.geographic.strict" in chosen
    assert "guardrail.geographic.preference" not in chosen


@pytest.mark.parametrize("block,flag", sorted(pt.BLOCK_FLAGS.items(), key=lambda kv: kv[1]))
def test_each_flag_actually_removes_its_block(block, flag):
    blocks = _blocks()
    assert block in pt.selected_blocks(blocks, {})
    assert block not in pt.selected_blocks(blocks, {flag: "false"})


def test_required_blocks_ignore_every_flag():
    off = {v: "false" for v in pt.BLOCK_FLAGS.values()}
    chosen = pt.selected_blocks(_blocks(), off)
    assert set(pt.REQUIRED_BLOCKS) <= set(chosen)


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("strict", "guardrail.geographic.strict"),
        ("preference", "guardrail.geographic.preference"),
        ("off", None),
    ],
)
def test_the_guardrail_switch_picks_exactly_one_wording(mode, expected):
    chosen = set(pt.selected_blocks(_blocks(), {"PROMPT_GEO_GUARDRAIL": mode}))
    geo = {b for b in pt.GEO_GUARDRAIL_BLOCKS.values() if b} & chosen
    assert geo == ({expected} if expected else set())


def test_an_unknown_guardrail_mode_is_an_error():
    with pytest.raises(pt.TemplateError, match="PROMPT_GEO_GUARDRAIL"):
        pt.selected_blocks(_blocks(), {"PROMPT_GEO_GUARDRAIL": "loose"})


def test_a_template_missing_the_selected_guardrail_is_an_error(tmp_path):
    """Flag and template drifting apart must fail loudly: the prompt would otherwise
    silently carry no geographic rule while the config says it does."""
    f = tmp_path / "t.txt"
    f.write_text("[[role]]\nr\n[[rule.json_only]]\nj\n[[vocabulary.header]]\nV:\n", encoding="utf-8")
    with pytest.raises(pt.TemplateError, match="which the template does not define"):
        pt.selected_blocks(pt.load_blocks(f), {"PROMPT_GEO_GUARDRAIL": "strict"})


# ── rendering ───────────────────────────────────────────────────────────────────


def test_preamble_ends_at_the_vocabulary_anchor_and_footer_follows_it():
    preamble, footer = pt.render({})
    assert preamble.endswith("THEMATIC VOCABULARY:\n")
    assert footer.startswith("\nEXAMPLES:")
    assert "EXAMPLES" not in preamble


def test_the_default_render_is_the_prompt_the_pipeline_shipped_with():
    """Byte-for-byte against the wording that was hard-coded in llm_run.py before the
    template existed. Moving text into a file must not change what the model reads —
    otherwise every score before and after this refactor is incomparable."""
    preamble, footer = pt.render({})
    assert preamble == (
        "You are an expert archaeological data extractor. "
        "Analyze the MARKED LINE enclosed in <target_line> ... </target_line> "
        "within its surrounding document context.\n"
        "1. Extract ONLY archaeological entities, features, periods, or materials "
        "from the marked line. "
        "Do NOT extract names of researchers, dates, conjunctions, or "
        "administrative words.\n"
        "2. Select the SINGLE most relevant category from the thematic vocabulary "
        "list below.\n"
        "CRITICAL: If the marked line is purely administrative, a table of contents, "
        "a generic heading (e.g. page numbers, titles, author names, 'Práce:', "
        "'Obsah:', literature references) or lacks direct archaeological context, "
        "you MUST select 'Nerelevantní (meta-text)'.\n"
        "NEVER select a country name, language name, or geographic region name "
        "as the teater_category for any line — including administrative lines. "
        "For any line that lacks direct archaeological significance, "
        "you MUST use 'Nerelevantní (meta-text)'.\n"
        "When extracting keywords, normalize obvious OCR artifacts and typos to "
        "their correct Czech forms. "
        "Do NOT include garbled tokens or split words as keywords. "
        "Prefer the normalized phrase over the raw OCR text.\n"
        "You MUST use the exact Czech term as written in the vocabulary.\n"
        "You MUST respond ONLY with a valid JSON object matching the requested "
        "schema.\n\n"
        "THEMATIC VOCABULARY:\n"
    )
    assert footer == (
        "\nEXAMPLES:\n\n"
        'Input line: "Výzkum odhalil základy gotického kostela ze 14. '
        'století."\n'
        "Correct output:\n"
        "{\n"
        '  "extracted_keywords_cs": ["základy", "gotický kostel"],\n'
        '  "extracted_keywords_en": ["foundations", "Gothic church"],\n'
        '  "teater_category": "kostel",\n'
        '  "confidence_score": 0.92\n'
        "}\n\n"
        'Input line: "Praha, dne 6. října 1956, Dr. Solle"\n'
        "Correct output:\n"
        "{\n"
        '  "extracted_keywords_cs": [],\n'
        '  "extracted_keywords_en": [],\n'
        '  "teater_category": "Nerelevantní (meta-text)",\n'
        '  "confidence_score": 1.0\n'
        "}\n"
    )


def test_turning_a_block_off_removes_exactly_that_text():
    full, _ = pt.render({})
    without, _ = pt.render({"PROMPT_OCR_NORMALISATION": "false"})
    assert "normalize obvious OCR artifacts" in full
    assert "normalize obvious OCR artifacts" not in without
    # and nothing else moved
    assert len(full) > len(without)
    assert without == full.replace(_blocks()["rule.ocr_normalisation"], "")


def test_the_template_path_is_configurable(tmp_path):
    f = tmp_path / "variant.txt"
    f.write_text("[[role]]\nvariant role\n[[rule.json_only]]\nj\n[[vocabulary.header]]\nV:\n",
                 encoding="utf-8")
    preamble, _ = pt.render({"PROMPT_TEMPLATE": str(f), "PROMPT_GEO_GUARDRAIL": "off"})
    assert preamble.startswith("variant role")


# ── the guardrail's two halves ──────────────────────────────────────────────────


def test_guardrail_text_returns_the_wording_actually_in_force():
    strict = pt.guardrail_text({"PROMPT_GEO_GUARDRAIL": "strict"})
    pref = pt.guardrail_text({"PROMPT_GEO_GUARDRAIL": "preference"})
    assert "NEVER select a country name" in strict
    assert "genuinely about it" in pref
    assert pt.guardrail_text({"PROMPT_GEO_GUARDRAIL": "off"}) == ""


def test_the_shipped_config_and_the_shipped_taxonomy_agree():
    """The invariant vocab_build.py enforces, asserted here too so a bad pairing fails
    the fast test lane and not only the build."""
    from vocab_manager import VocabularyManager

    config = pt.load_run_config(REPO_ROOT / "llm_config.txt")
    manager = VocabularyManager(config_path=str(REPO_ROOT / "data_samples" / "taxonomy_config.json"))
    assert manager.geo_guardrail_problems(pt.guardrail_text(config)) == []


def test_the_strict_wording_carries_every_marker_the_config_looks_for():
    """`geo_guardrail.prompt_markers` is how the build recognises the clause. If the
    wording is edited without the markers, the gate silently stops detecting it."""
    from vocab_manager import VocabularyManager

    manager = VocabularyManager(config_path=str(REPO_ROOT / "data_samples" / "taxonomy_config.json"))
    strict = pt.guardrail_text({"PROMPT_GEO_GUARDRAIL": "strict"}).lower()
    for marker in manager.geo_guardrail()["prompt_markers"]:
        assert marker.lower() in strict, f"marker {marker!r} not in the strict wording"


# ── the committed output template ───────────────────────────────────────────────


def test_output_template_is_valid_and_documents_the_record_shape():
    tpl = pt.output_template()
    assert tpl["shape"] == "array of records"
    assert tpl["example_records"], "the template must carry at least one example record"
    for record in tpl["example_records"]:
        assert set(record) >= {
            "file_id", "page", "line", "categ", "quality_score", "original_text", "enrichment",
        }


def test_output_template_fields_match_the_documented_field_list():
    """The prose `fields` block and the machine-readable `example_records` are two
    statements of the same contract; a reader who trusts one must not be misled."""
    tpl = pt.output_template()
    documented = set(tpl["fields"]["enrichment"])
    for record in tpl["example_records"]:
        assert set(record["enrichment"]) == documented


def test_output_template_matches_the_schema_the_model_is_given():
    """The four fields `build_schema` declares must be exactly the four the template
    says the model returns — `teater_category_ids` is the one addition, attached after
    inference rather than generated."""
    src = (REPO_ROOT / "llm_run.py").read_text(encoding="utf-8")
    model_fields = {"extracted_keywords_cs", "extracted_keywords_en",
                    "teater_category", "confidence_score"}
    for field in model_fields:
        assert f"{field}: " in src, f"{field} is not declared in build_schema"

    documented = set(pt.output_record_fields())
    assert documented == model_fields | {"teater_category_ids"}


def test_the_prompt_examples_agree_with_the_output_template():
    """The examples in the prompt teach the model the output shape; the template
    documents it for consumers. They are the same contract stated twice, so they get
    checked against each other rather than trusted separately."""
    _, footer = pt.render({})
    example_blocks = [b for b in footer.split("Correct output:\n")[1:]]
    assert len(example_blocks) >= 2

    model_fields = set(pt.output_record_fields()) - {"teater_category_ids"}
    for block in example_blocks:
        obj = json.loads(block[block.index("{") : block.index("}") + 1])
        assert set(obj) == model_fields, f"prompt example fields {set(obj)} != {model_fields}"


def test_the_metatext_example_shows_empty_keyword_arrays():
    """A rule the pipeline also enforces in code (llm_utils blanks them). The example
    must not contradict it, or the model is being shown one thing and corrected after."""
    _, footer = pt.render({})
    block = footer.split("Correct output:\n")[2]
    obj = json.loads(block[block.index("{") : block.index("}") + 1])
    assert obj["teater_category"] == "Nerelevantní (meta-text)"
    assert obj["extracted_keywords_cs"] == []
    assert obj["extracted_keywords_en"] == []
