"""
tests/test_conllu_processing.py
================================
Unit tests for CoNLL-U processing helpers in ``api_util/``.

Modules under test:
    call_udpipe.merge_conllu_chunks   — pure string → string transform
    call_nametag._get_ne_suffix       — pure tag string helper
    call_nametag.build_sent_page_map  — CoNLL-U file (+ rows sidecar) → page per sentence
    call_nametag.build_word_page_map  — CoNLL-U file (+ rows sidecar) → page per word

No ML models, no network, no GPU required.
"""

import csv
from pathlib import Path

from api_util.call_nametag import _get_ne_suffix, build_sent_page_map, build_word_page_map
from api_util.call_udpipe import merge_conllu_chunks
from api_util.page_rows import Row

SAMPLES = Path(__file__).resolve().parent.parent / "data_samples"

# ─────────────────────────────────────────────────────────────────────────────
# Inline chunk content helpers
# ─────────────────────────────────────────────────────────────────────────────


def _chunk(sent_ids: list[int], suffix: str = "") -> str:
    """Build a minimal CoNLL-U chunk with the given sentence IDs."""
    lines = []
    for sid in sent_ids:
        lines.append(f"# sent_id = {sid}\n")
        lines.append(f"# text = Sentence {sid}.{suffix}\n")
        lines.append(f"1\tWord{sid}\tword\tNOUN\t_\t_\t0\troot\t_\t_\n")
        lines.append("2\t.\t.\tPUNCT\t_\t_\t1\tpunct\t_\tSpaceAfter=No\n")
        lines.append("\n")
    return "".join(lines)


# ════════════════════════════════════════════════════════════════════════════
# merge_conllu_chunks
# ════════════════════════════════════════════════════════════════════════════
class TestMergeConlluChunks:
    def test_empty_list_returns_empty_string(self):
        assert merge_conllu_chunks([]) == ""

    def test_single_chunk_sent_ids_unchanged(self):
        chunk = _chunk([1, 2, 3])
        merged = merge_conllu_chunks([chunk])
        # All three sent_id lines must appear with their original values
        for i in (1, 2, 3):
            assert f"# sent_id = {i}\n" in merged

    def test_single_chunk_no_marker_injected(self):
        chunk = _chunk([1, 2])
        merged = merge_conllu_chunks([chunk])
        assert "# chunk_start" not in merged
        assert "# page_break" not in merged

    def test_two_chunks_second_offset(self):
        """
        Chunk 1 has sent_ids [1, 2]; chunk 2 has [1, 2].
        After merge the second chunk must be renumbered [3, 4].
        """
        merged = merge_conllu_chunks([_chunk([1, 2]), _chunk([1, 2])])
        for i in (1, 2, 3, 4):
            assert f"# sent_id = {i}\n" in merged
        # Original sent_id = 1 from chunk 2 should no longer appear unshifted
        # (it was sent_id=1 but offset by 2 → now 3)
        lines = merged.splitlines()
        sent_id_lines = [ln for ln in lines if ln.startswith("# sent_id")]
        values = [int(val.split("=")[1].strip()) for val in sent_id_lines]
        assert values == [1, 2, 3, 4]

    def test_chunk_start_marked_before_first_sentence_of_second_chunk(self):
        """
        ``# chunk_start = K`` appears immediately before the renumbered ``# sent_id`` of the
        first sentence of every non-first chunk. It marks a chunk, never a page: this marker
        used to be ``# page_break = true`` and was read as a page break by every stage
        (issue #38, A).
        """
        merged = merge_conllu_chunks([_chunk([1, 2]), _chunk([1])])
        lines = merged.splitlines()
        marks = [i for i, ln in enumerate(lines) if ln == "# chunk_start = 2"]
        sid3_positions = [i for i, sp in enumerate(lines) if sp == "# sent_id = 3"]
        assert len(marks) == 1
        assert len(sid3_positions) == 1
        assert marks[0] == sid3_positions[0] - 1
        assert "# page_break" not in merged

    def test_no_marker_before_first_chunk_first_sentence(self):
        merged = merge_conllu_chunks([_chunk([1, 2]), _chunk([1])])
        lines = merged.splitlines()
        first_sid_pos = next(i for i, ln in enumerate(lines) if ln.startswith("# sent_id"))
        if first_sid_pos > 0:
            assert not lines[first_sid_pos - 1].startswith("# chunk_start")

    def test_three_chunks_two_chunk_starts(self):
        merged = merge_conllu_chunks([_chunk([1]), _chunk([1]), _chunk([1])])
        assert merged.count("# chunk_start = ") == 2
        assert "# chunk_start = 2\n" in merged and "# chunk_start = 3\n" in merged

    def test_non_sent_id_lines_pass_through_unchanged(self):
        """Comment lines that are not ``# sent_id`` must be left verbatim."""
        chunk = "# newdoc\n# sent_id = 1\n# text = Hello.\n1\tHello\thello\tNOUN\t_\t_\t0\troot\t_\t_\n\n"
        merged = merge_conllu_chunks([chunk])
        assert "# newdoc\n" in merged
        assert "# text = Hello.\n" in merged

    def test_chunk_with_no_sent_ids_passes_through(self):
        """A chunk containing only comments and token lines must not crash."""
        chunk = "# newdoc\n1\tWord\tword\tNOUN\t_\t_\t0\troot\t_\t_\n\n"
        merged = merge_conllu_chunks([chunk])
        assert "Word" in merged

    def test_merged_output_ends_with_final_chunk_content(self):
        c1 = _chunk([1, 2])
        c2 = _chunk([1], suffix="_final")
        merged = merge_conllu_chunks([c1, c2])
        assert "_final" in merged


# ════════════════════════════════════════════════════════════════════════════
# _get_ne_suffix
# ════════════════════════════════════════════════════════════════════════════
class TestGetNeSuffix:
    def test_empty_string_returns_empty(self):
        assert _get_ne_suffix("") == ""

    def test_none_equivalent_empty_returns_empty(self):
        # Function only receives strings — test falsy empty string
        assert _get_ne_suffix("") == ""

    def test_bio_tag_b_prefix(self):
        assert _get_ne_suffix("B-gu") == "gu"

    def test_bio_tag_i_prefix(self):
        assert _get_ne_suffix("I-ps") == "ps"

    def test_o_tag_returns_empty_string_suffix(self):
        """'O' doesn't start with B-/I- so suffix appended is ''."""
        result = _get_ne_suffix("O")
        # A single part "O" → no B-/I- → appends "" → joins to ""
        assert result == ""

    def test_multi_tag_pipe_separated(self):
        """'B-P|B-pf' → two parts → 'P|pf'."""
        assert _get_ne_suffix("B-P|B-pf") == "P|pf"

    def test_mixed_bio_tags(self):
        """'I-gu|B-gh' → 'gu|gh'."""
        assert _get_ne_suffix("I-gu|B-gh") == "gu|gh"

    def test_plain_tag_no_dash_prefix(self):
        """Tag with no B-/I- prefix produces empty suffix for that part."""
        result = _get_ne_suffix("plain")
        assert result == ""

    def test_three_part_tag(self):
        """'B-A|B-ic|B-gu' → 'A|ic|gu'."""
        assert _get_ne_suffix("B-A|B-ic|B-gu") == "A|ic|gu"


# ════════════════════════════════════════════════════════════════════════════
# build_sent_page_map
# ════════════════════════════════════════════════════════════════════════════
class TestBuildSentPageMap:
    def test_single_page_all_mapped_to_page_1(self, sample_conllu):
        """
        ``sample.conllu`` has 3 sentences (sent_id 1,2,3) all on one page.
        The first ``# sent_id = 1`` triggers page 1; subsequent ones stay on 1.
        """
        page_map = build_sent_page_map(sample_conllu)
        assert page_map == [1, 1, 1]

    def test_sent_id_reset_starts_new_page(self, two_page_conllu):
        """
        Legacy two-page file: sent_ids 1,2 then reset to 1,2.
        Expected page map: [1, 1, 2, 2].
        """
        page_map = build_sent_page_map(two_page_conllu)
        assert page_map == [1, 1, 2, 2]

    def test_old_page_break_marker_is_a_chunk_start_not_a_page(self, page_break_conllu):
        """
        ``# page_break = true`` was written by merge_conllu_chunks at every UDPipe chunk
        start, so it never meant a page (issue #38, A). Without a rows file the document is
        one page; with one, the rows say where pages begin.
        """
        assert build_sent_page_map(page_break_conllu) == [1, 1, 1, 1]

    def test_empty_file_returns_sentinel_page_1(self, empty_conllu):
        """No sent_id markers → returns [1] as the fallback sentinel."""
        page_map = build_sent_page_map(empty_conllu)
        assert page_map == [1]

    def test_nonexistent_file_returns_sentinel(self, tmp_path):
        page_map = build_sent_page_map(str(tmp_path / "missing.conllu"))
        assert page_map == [1]

    def test_page_numbers_are_monotonically_non_decreasing(self, two_page_conllu):
        """Page numbers must never decrease across the sentence list."""
        page_map = build_sent_page_map(two_page_conllu)
        for a, b in zip(page_map, page_map[1:], strict=False):
            assert b >= a, f"Page number decreased: {a} → {b}"

    def test_result_length_equals_sentence_count(self, sample_conllu):
        """The map must have exactly one entry per sentence in the file."""
        page_map = build_sent_page_map(sample_conllu)
        # sample.conllu has 3 sentences
        assert len(page_map) == 3

    def test_rows_give_the_pages_across_chunks(self, tmp_path):
        """
        Two chunks ("A B" + "C" / "D"): the chunk start is a line boundary, the rows say
        which line is on which page -- page 2 starts inside the first chunk.
        """
        content = (
            "# sent_id = 1\n1\tA\ta\tNOUN\t_\t_\t0\troot\t_\tSpacesAfter=\\n\n\n"
            "# sent_id = 2\n1\tB\tb\tNOUN\t_\t_\t0\troot\t_\t_\n\n"
            "# chunk_start = 2\n"
            "# sent_id = 3\n1\tC\tc\tNOUN\t_\t_\t0\troot\t_\tSpacesAfter=\\n\n\n"
            "# sent_id = 4\n1\tD\td\tNOUN\t_\t_\t0\troot\t_\t_\n\n"
        )
        conllu_path = tmp_path / "doc.conllu"
        conllu_path.write_text(content, encoding="utf-8")
        rows = [Row(1, 1, "", "A"), Row(2, 1, "", "B"), Row(2, 2, "", "C"), Row(3, 1, "", "D")]
        assert build_sent_page_map(str(conllu_path), rows) == [1, 2, 2, 3]

    def test_released_sample_sentence_crosses_pages(self):
        """CTX000000002: s-5 starts on page 3 and ends on page 4 ("Soubor nálezů ...")."""
        conllu = SAMPLES / "UDP" / "CTX000000002.conllu"
        rows = [
            Row(int(r["page_num"]), int(r["line_num"]), "", r["text"].strip())
            for r in csv.DictReader(
                (SAMPLES / "DOC_LINE_CATEG" / "CTX000000002.csv")
                .read_text(encoding="utf-8")
                .splitlines()
            )
            if r["text"].strip()
        ]
        assert build_sent_page_map(str(conllu), rows) == [1, 2, 2, 3, 3, 4]
        pages = build_word_page_map(str(conllu), rows)
        assert pages[4] == [3, 3, 3, 4, 4, 4, 4, 4, 4, 4]
