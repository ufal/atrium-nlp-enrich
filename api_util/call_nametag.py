#!/usr/bin/env python3
"""
call_nametag.py  –  Send a CoNLL-U file to the NameTag 3 API, receive NER
annotations, and write per-page TSV files. Retries automatically on network errors.

Pages are the source's pages (``api_util/page_rows.py``), not UDPipe's chunks.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from functools import lru_cache
from typing import Any

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    print(
        "[Error] 'requests' library is required. Run: pip install requests urllib3", file=sys.stderr
    )
    sys.exit(1)

from pathlib import Path  # noqa: E402

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from api_util import page_rows  # noqa: E402

NAMETAG_URL = "https://lindat.mff.cuni.cz/services/nametag/api/recognize"


@lru_cache(maxsize=1)
def _lazy_load_torch():
    import torch  # type: ignore

    return torch


@lru_cache(maxsize=1)
def _lazy_load_transformers():
    from transformers import AutoModel, AutoTokenizer  # type: ignore

    return AutoTokenizer, AutoModel


def process_data(data: Any) -> Any:
    """
    Example entry point that only imports heavy ML dependencies when needed.
    """
    torch = _lazy_load_torch()
    AutoTokenizer, AutoModel = _lazy_load_transformers()

    # Replace with real logic.
    _ = torch
    _ = AutoTokenizer
    _ = AutoModel
    return data


# ── API call ──────────────────────────────────────────────────────────────────


def get_robust_session(retries: int) -> requests.Session:
    """Configures a requests session with exponential backoff for 429/5xx errors."""
    session = requests.Session()
    retry_strategy = Retry(
        total=retries,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def call_nametag(
    session: requests.Session, conllu_text: str, model: str, url: str, timeout: int
) -> dict | None:
    """POST CoNLL-U text to NameTag and return the parsed JSON dict."""
    try:
        resp = session.post(
            url,
            data={
                "model": model,
                "input": "conllu",
                "output": "conll",
                "data": conllu_text,
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as exc:
        print(f"  [WARN] NameTag API failed permanently: {exc}", file=sys.stderr)
        return None


# ── sent_id → page mapping ────────────────────────────────────────────────────


def build_word_page_map(conllu_path: str, rows=None) -> list[list[int]]:
    """Per sentence, the page of every syntactic word (what NameTag tags).

    Pages come from the document's rows file (``api_util/page_rows.py``: UDPipe's line ends
    counted against the rows stage 1 wrote). Without one, the legacy per-page convention
    applies: a later ``# sent_id = 1`` starts a page. Chunk markers (``# chunk_start``, the
    old ``# page_break = true``) are never pages (issue #38, A)."""
    return page_rows.word_pages(conllu_path, rows, doc_id=os.path.basename(conllu_path))


def build_sent_page_map(conllu_path: str, rows=None) -> list[int]:
    """Return a list mapping sentence index (0-based) → page number (1-based): the page of the
    sentence's first word. ``[1]`` when the file has no sentences."""
    try:
        pages = build_word_page_map(conllu_path, rows)
    except Exception as exc:
        print(f"[Error] reading CoNLL-U {conllu_path}: {exc}", file=sys.stderr)
        pages = []
    sent_to_page = [p[0] if p else 1 for p in pages]
    if not sent_to_page:
        print(
            f"[Warn] No sentences found in {conllu_path}; "
            "treating entire document as a single page.",
            file=sys.stderr,
        )
        sent_to_page = [1]
    return sent_to_page


# ── NE suffix helper ──────────────────────────────────────────────────────────


def _get_ne_suffix(tag: str) -> str:
    if not tag:
        return ""
    parts = tag.split("|")
    suffixes = []
    for t in parts:
        if t.startswith("B-") or t.startswith("I-"):
            suffixes.append(t.split("-", 1)[1])
        else:
            suffixes.append("")
    return "|".join(suffixes)


# ── response → per-page TSV ───────────────────────────────────────────────────


def write_tsv_files(response_json: dict, pages: list, out_dir: str, doc_id: str) -> int:
    """Parse NameTag JSON result and write one TSV file per page (``<doc_id>-<page>.tsv``).

    ``pages`` is per sentence either a page number or a list with the page of every word
    (``build_word_page_map``); a sentence that crosses a page is split between two files.
    If NameTag returns a different number of tokens for a sentence, all of them go to its
    first word's page. Pages only increase, so concatenating the files in page order gives
    the tokens in document order (``summarize_nt_udp.get_sorted_tsv_content``)."""
    tagged = response_json.get("result", "")
    sentences = [s for s in tagged.strip().split("\n\n") if s.strip()]
    flat = [p for entry in pages for p in (entry if isinstance(entry, list) else [entry])]
    last_page = max(flat, default=1)

    tokens_by_page: defaultdict[int, list[tuple[str, str]]] = defaultdict(list)

    for idx, sent_block in enumerate(sentences):
        entry = pages[idx] if idx < len(pages) else last_page
        tokens = []
        for line in sent_block.split("\n"):
            if line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) < 2:
                continue
            tokens.append((cols[0], cols[1]))
        if isinstance(entry, list) and len(entry) == len(tokens):
            word_pages = entry
        else:
            first = entry[0] if isinstance(entry, list) and entry else entry
            word_pages = [first if isinstance(first, int) else last_page] * len(tokens)
        for (word, tag), page_num in zip(tokens, word_pages, strict=True):
            tokens_by_page[page_num].append((word, tag))

    os.makedirs(out_dir, exist_ok=True)
    for page_num, token_list in tokens_by_page.items():
        out_path = os.path.join(out_dir, f"{doc_id}-{page_num}.tsv")
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write("Word\tTag\tNE\n")
            for word, tag in token_list:
                fh.write(f"{word}\t{tag}\t{_get_ne_suffix(tag)}\n")

    return len(tokens_by_page)


# ── main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send CoNLL-U to NameTag API and write per-page TSV files."
    )
    parser.add_argument("--input", required=True, help="Input CoNLL-U file.")
    parser.add_argument("--model", required=True, help="NameTag model identifier.")
    parser.add_argument("--output-dir", required=True, help="Directory for per-page TSV output.")
    parser.add_argument(
        "--url",
        # See the matching note in call_udpipe.py: an empty NAMETAG_URL (which
        # is what a compose container carries when the operator sets nothing)
        # must mean "unset", not "post to the empty string".
        default=os.environ.get("NAMETAG_URL") or NAMETAG_URL,
        help="NameTag API endpoint URL.",
    )
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument(
        "--text-dir",
        default=os.environ.get("TEMP_TXT_DIR") or None,
        help="stage 1's TEMP_TXT_DIR: where <doc>.rows.tsv is when it is not next to --input",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"[Error] CoNLL-U file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    doc_id = os.path.splitext(os.path.basename(args.input))[0]

    rows_path = page_rows.find_rows(args.input, args.text_dir)
    rows = page_rows.read_rows(rows_path) if rows_path else None
    if rows is None:
        print(
            f"  [NameTag] {doc_id}: no rows file; pages follow the legacy convention "
            "(re-run stage 1 to get real pages)",
            file=sys.stderr,
        )
    word_pages = build_word_page_map(args.input, rows)

    with open(args.input, "r", encoding="utf-8") as fh:
        conllu_text = fh.read()

    print(f"  [NameTag] Sending {doc_id} ({len(word_pages)} sentences)...")

    session = get_robust_session(args.retries)
    response_json = call_nametag(session, conllu_text, args.model, args.url, args.timeout)

    if response_json is None:
        print(f"[Error] NameTag failed permanently for {doc_id}.", file=sys.stderr)
        sys.exit(1)

    n_pages = write_tsv_files(response_json, word_pages, args.output_dir, doc_id)
    print(f"  [NameTag] Written {n_pages} page TSV file(s) → {args.output_dir}")


if __name__ == "__main__":
    main()
