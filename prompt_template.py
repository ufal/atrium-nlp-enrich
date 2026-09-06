"""
prompt_template.py — the system prompt's instruction text, as data rather than code.

The prompt used to be two string literals inside ``llm_run.py``. That made every
wording change a Python edit, and it made one particular change — relaxing the
geographic guardrail (issue #6, C1/M11/M12) — a code change that had to be kept in step
with a config file by hand. Both halves now live in a plain text file that a domain
reviewer can edit, and which of its blocks reach the model is a set of flags in
``llm_config.txt``.

**Import-light on purpose.** ``llm_run.py`` pulls in torch, transformers and pysqlite3;
``vocab_build.py`` must not. Both need to know what the prompt says, so this module
depends on nothing outside the standard library and can be imported from either side —
which is what lets the build gate check the *rendered* prompt rather than grepping
Python source for a sentence.

Template format
---------------
A block header is ``[[name]]`` alone on a line; everything up to the next header is that
block's body. Order in the file is render order: to move a rule, move it in the file.
A body's trailing newlines are normalised to exactly one, so an editor that strips
trailing whitespace cannot silently change the prompt; leading blank lines are kept,
because that is how a block asks for a blank line before itself.

    [[role]]
    You are an expert archaeological data extractor. …

    [[guardrail.geographic.strict]]
    NEVER select a country name, …

Selection
---------
:data:`REQUIRED_BLOCKS` always render. Every other block is gated by a flag in
:data:`BLOCK_FLAGS` — a plain ``true``/``false`` in the config. The geographic guardrail
is the one three-way switch (``strict`` / ``preference`` / ``off``), because that is the
shape of the actual decision: the wording is not merely on or off, it has two forms and
the vocabulary must agree with whichever is in force (see
``vocab_manager.geo_guardrail_problems``).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_TEMPLATE = REPO_ROOT / "prompts" / "system_prompt.txt"
DEFAULT_OUTPUT_TEMPLATE = REPO_ROOT / "prompts" / "output_template.json"

_HEADER_RE = re.compile(r"^\[\[([A-Za-z0-9_.]+)\]\]\s*$")

# Rendered whatever the config says. Removing any of these would produce a prompt that
# does not describe the task, the output contract, or where the vocabulary begins.
REQUIRED_BLOCKS = ("role", "rule.json_only", "vocabulary.header")

# block name -> the llm_config.txt flag that includes it. Every one defaults to true:
# the shipped configuration renders the prompt the pipeline has always sent.
BLOCK_FLAGS: Dict[str, str] = {
    "task.extract": "PROMPT_TASK_EXTRACT",
    "task.select": "PROMPT_TASK_SELECT",
    "rule.metatext": "PROMPT_METATEXT_RULE",
    "rule.ocr_normalisation": "PROMPT_OCR_NORMALISATION",
    "rule.exact_term": "PROMPT_EXACT_TERM",
    "examples": "PROMPT_EXAMPLES",
}

# The three-way switch. Values map to the block that carries that wording; "off" renders
# no guardrail at all.
GEO_GUARDRAIL_FLAG = "PROMPT_GEO_GUARDRAIL"
GEO_GUARDRAIL_BLOCKS: Dict[str, Optional[str]] = {
    "strict": "guardrail.geographic.strict",
    "preference": "guardrail.geographic.preference",
    "off": None,
}
DEFAULT_GEO_GUARDRAIL = "strict"

# Blocks the vocabulary is rendered between: everything before `vocabulary.header` is
# the instruction preamble, everything after it is appended once the terms are in.
VOCABULARY_ANCHOR = "vocabulary.header"


# Where the template lives, overridable per run so a variant prompt is a config edit
# rather than a file swap.
TEMPLATE_PATH_FLAG = "PROMPT_TEMPLATE"


class TemplateError(ValueError):
    """A template or flag problem that would produce a prompt nobody intended."""


def template_path(
    config: Optional[Dict[str, str]] = None, override: Optional[Path] = None
) -> Path:
    """Resolve the template file: explicit argument, then ``PROMPT_TEMPLATE``, then the
    shipped default. A relative configured path is taken against the repo root, so the
    same config works whatever directory the run started in."""
    if override is not None:
        return Path(override)
    configured = (config or {}).get(TEMPLATE_PATH_FLAG)
    if not configured:
        return DEFAULT_TEMPLATE
    path = Path(configured)
    return path if path.is_absolute() else REPO_ROOT / path


def load_run_config(path: Path) -> Dict[str, str]:
    """Read a ``KEY=VALUE`` config file. A duplicate of ``llm_utils.load_config`` on
    purpose: that module imports torch, and both ``vocab_build.py`` and this module's
    own tests need the prompt flags without paying for a GPU stack."""
    config: Dict[str, str] = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            config[key.strip()] = value.strip()
    return config


def load_blocks(path: Optional[Path] = None) -> Dict[str, str]:
    """Parse a template file into ``{block name: body}``, preserving file order.

    Raises :class:`TemplateError` on a duplicate block name — a silently-shadowed block
    is exactly the kind of edit this file exists to make reviewable — and on text before
    the first header, which is almost always a typo'd header.
    """
    path = Path(path) if path else DEFAULT_TEMPLATE
    if not path.exists():
        raise TemplateError(f"prompt template not found: {path}")

    blocks: Dict[str, List[str]] = {}
    current: Optional[str] = None
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        match = _HEADER_RE.match(raw)
        if match:
            name = match.group(1)
            if name in blocks:
                raise TemplateError(f"{path}:{lineno}: duplicate block [[{name}]]")
            blocks[name] = []
            current = name
            continue
        if current is None:
            if raw.strip() and not raw.lstrip().startswith("#"):
                raise TemplateError(f"{path}:{lineno}: text before the first [[block]]")
            continue
        blocks[current].append(raw)

    # Normalise each body to end in exactly one newline; keep leading blank lines, which
    # are how a block asks for a blank line ahead of itself.
    return {name: "\n".join(lines).rstrip("\n") + "\n" for name, lines in blocks.items()}


def _is_true(value: object, default: bool = True) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def resolve_geo_guardrail(config: Optional[Dict[str, str]] = None) -> str:
    """The configured guardrail mode, validated. See :data:`GEO_GUARDRAIL_BLOCKS`."""
    raw = (config or {}).get(GEO_GUARDRAIL_FLAG, DEFAULT_GEO_GUARDRAIL)
    mode = str(raw).strip().lower()
    if mode not in GEO_GUARDRAIL_BLOCKS:
        raise TemplateError(
            f"{GEO_GUARDRAIL_FLAG}={raw!r} is not one of {sorted(GEO_GUARDRAIL_BLOCKS)}"
        )
    return mode


def selected_blocks(
    blocks: Dict[str, str], config: Optional[Dict[str, str]] = None
) -> List[str]:
    """Block names to render, in template order, for this configuration.

    A flag naming a block the template does not define is an error rather than a no-op:
    it means the flag and the template have drifted apart, and the prompt is then not
    the one the config describes.
    """
    config = config or {}
    mode = resolve_geo_guardrail(config)
    guardrail_block = GEO_GUARDRAIL_BLOCKS[mode]

    missing = [b for b in REQUIRED_BLOCKS if b not in blocks]
    if missing:
        raise TemplateError(f"prompt template is missing required block(s): {missing}")
    if guardrail_block and guardrail_block not in blocks:
        raise TemplateError(
            f"{GEO_GUARDRAIL_FLAG}={mode!r} needs block [[{guardrail_block}]], "
            "which the template does not define"
        )

    chosen: List[str] = []
    for name in blocks:  # dict preserves the template's own order
        if name in REQUIRED_BLOCKS:
            chosen.append(name)
        elif name in BLOCK_FLAGS:
            if _is_true(config.get(BLOCK_FLAGS[name])):
                chosen.append(name)
        elif name in GEO_GUARDRAIL_BLOCKS.values():
            if name == guardrail_block:
                chosen.append(name)
        else:
            raise TemplateError(
                f"block [[{name}]] has no flag in BLOCK_FLAGS and is not required — "
                "add a flag for it, or remove it from the template"
            )
    return chosen


def render(
    config: Optional[Dict[str, str]] = None,
    path: Optional[Path] = None,
    blocks: Optional[Dict[str, str]] = None,
) -> tuple[str, str]:
    """Return ``(preamble, footer)`` — the prompt with the vocabulary left out.

    ``preamble`` runs from ``role`` through ``vocabulary.header`` inclusive and is what
    the term list is appended to; ``footer`` is everything after it (the examples). The
    vocabulary itself is rendered by ``llm_run.build_system_prompt``, which is the only
    place that knows about truncation.
    """
    blocks = blocks if blocks is not None else load_blocks(template_path(config, path))
    names = selected_blocks(blocks, config)
    if VOCABULARY_ANCHOR not in names:
        raise TemplateError(f"[[{VOCABULARY_ANCHOR}]] must render — it is where terms go")
    split = names.index(VOCABULARY_ANCHOR)
    preamble = "".join(blocks[n] for n in names[: split + 1])
    footer = "".join(blocks[n] for n in names[split + 1 :])
    return preamble, footer


def describe(config: Optional[Dict[str, str]] = None, path: Optional[Path] = None) -> str:
    """One line per block, for the run banner: what the model is actually being told."""
    blocks = load_blocks(template_path(config, path))
    active = set(selected_blocks(blocks, config))
    mode = resolve_geo_guardrail(config)
    lines = [f"  prompt blocks (geo guardrail: {mode})"]
    for name in blocks:
        mark = "on " if name in active else "off"
        lines.append(f"    [{mark}] {name}")
    return "\n".join(lines)


def guardrail_text(
    config: Optional[Dict[str, str]] = None, path: Optional[Path] = None
) -> str:
    """Just the guardrail wording currently in force ("" when the mode is ``off``).

    ``vocab_build.py`` checks this against ``taxonomy_config.json``'s declared
    ``geo_guardrail``, so the vocabulary and the prompt cannot disagree about whether
    geographic terms are selectable.
    """
    mode = resolve_geo_guardrail(config)
    block = GEO_GUARDRAIL_BLOCKS[mode]
    if block is None:
        return ""
    return load_blocks(template_path(config, path)).get(block, "")


def output_template(path: Optional[Path] = None) -> dict:
    """The committed per-document output shape (``prompts/output_template.json``).

    Read it to know what ``<doc_id>_enriched.json`` looks like without running the
    pipeline; a test asserts it stays in step with the fields the schema actually emits.
    """
    import json

    path = Path(path) if path else DEFAULT_OUTPUT_TEMPLATE
    if not path.exists():
        raise TemplateError(f"output template not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def output_record_fields(path: Optional[Path] = None) -> Sequence[str]:
    """The enrichment field names the output template documents, in order."""
    tpl = output_template(path)
    example = (tpl.get("example_records") or [{}])[0]
    return list((example.get("enrichment") or {}).keys())
