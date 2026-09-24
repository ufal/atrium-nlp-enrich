"""api_util/page_rows.py: which line and page every token came from (issue #38, A)."""

from api_util.page_rows import (
    Row,
    count_newlines,
    find_rows,
    normalize_row_text,
    page_labels,
    place_units,
    read_rows,
    read_surface,
    resplit_ne,
    rows_source,
    word_pages,
    write_rows,
)


def _conllu(tmp_path, text, name="doc.conllu"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _line(no, form, misc="_"):
    return f"{no}\t{form}\t{form.lower()}\tX\t_\t_\t0\troot\t_\t{misc}\n"


def test_row_text_is_one_line():
    assert normalize_row_text("a\nb\r\nc\x0cd\u2028e  ") == "a b c d e"
    assert normalize_row_text(None) == ""


def test_rows_file_round_trip_with_its_source(tmp_path):
    rows = [Row(1, 1, "", "Alfa"), Row(2, 1, "II", "Beta\tgama")]
    path = tmp_path / "doc.rows.tsv"
    write_rows(path, rows, source="tables/doc.csv")
    assert read_rows(path) == rows
    assert rows_source(path) == "doc.csv"
    write_rows(path, rows)
    assert read_rows(path) == rows and rows_source(path) == ""
    assert read_rows(tmp_path / "missing.rows.tsv") is None
    assert page_labels(rows) == {2: "II"}


def test_rows_are_found_next_to_the_conllu_first(tmp_path):
    udp, txt = tmp_path / "UDP", tmp_path / "TXT"
    udp.mkdir()
    txt.mkdir()
    conllu = _conllu(udp, "", "doc.conllu")
    write_rows(txt / "doc.rows.tsv", [Row(1, 1, "", "a")])
    assert find_rows(conllu, txt) == txt / "doc.rows.tsv"
    write_rows(udp / "doc.rows.tsv", [Row(1, 1, "", "a")])
    assert find_rows(conllu, txt) == udp / "doc.rows.tsv"
    assert find_rows(tmp_path / "other.conllu") is None


def test_escaped_backslash_is_not_a_line_end():
    assert count_newlines(r"\n") == 1
    assert count_newlines(r"\n\n") == 2
    assert count_newlines(r"\\n") == 0
    assert count_newlines(r"\s\n") == 1


def test_line_ends_and_chunk_starts_place_units(tmp_path):
    path = _conllu(
        tmp_path,
        "# sent_id = 1\n"
        + _line(1, "A")
        + _line(2, "B", r"SpacesAfter=\n")
        + "\n# chunk_start = 2\n# sent_id = 2\n"
        + _line(1, "C")
        + "\n# sent_id = 3\n"
        + _line(1, "D", r"SpacesBefore=\n|SpaceAfter=No")
        + "\n",
    )
    rows = [Row(1, 1, "", "A B"), Row(1, 2, "", "C"), Row(2, 1, "", "D")]
    places, method = place_units(read_surface(path), rows, "doc")
    assert method == "newline"
    assert [(p.page, p.line) for p in places] == [(1, 1), (1, 1), (1, 2), (2, 1)]


def test_a_multi_word_token_is_one_unit(tmp_path):
    path = _conllu(
        tmp_path,
        "# sent_id = 1\n"
        "1-2\tabych\t_\t_\t_\t_\t_\t_\t_\tSpacesAfter=\\n\n"
        + _line(1, "aby")
        + _line(2, "bych")
        + _line(3, "šel")
        + "\n",
    )
    sentences = read_surface(path)
    assert [(u["form"], u["n_words"]) for u in sentences[0]["surface"]] == [
        ("abych", 2),
        ("šel", 1),
    ]
    rows = [Row(1, 1, "", "abych"), Row(2, 1, "", "šel")]
    assert word_pages(path, rows) == [[1, 1, 2]]


def test_characters_align_when_the_line_ends_disagree(tmp_path, capsys):
    """Rows that do not match UDPipe's line ends (a stale rows file, or text edited in
    between) fall back to aligning the characters."""
    path = _conllu(tmp_path, "# sent_id = 1\n" + _line(1, "Alfa") + _line(2, "beta") + "\n")
    rows = [Row(1, 1, "", "Alfa"), Row(2, 1, "", "beta")]
    places, method = place_units(read_surface(path), rows, "doc")
    assert method == "chars"
    assert [p.page for p in places] == [1, 2]
    assert "character alignment" in capsys.readouterr().err


def test_without_rows_only_a_sent_id_restart_is_a_page(tmp_path):
    path = _conllu(
        tmp_path,
        "# sent_id = 1\n"
        + _line(1, "A")
        + "\n# page_break = true\n# sent_id = 2\n"
        + _line(1, "B")
        + "\n# sent_id = 1\n"
        + _line(1, "C")
        + "\n",
    )
    assert word_pages(path) == [[1], [1], [2]]


def test_resplit_moves_ne_lines_to_their_pages(tmp_path):
    ne = tmp_path / "NE" / "doc"
    ne.mkdir(parents=True)
    (ne / "doc-1.tsv").write_text("Word\tTag\tNE\nA\tO\t\nB\tB-P\tPER\n", encoding="utf-8")
    (ne / "doc-2.tsv").write_text("Word\tTag\tNE\nC\tO\t\n", encoding="utf-8")
    path = _conllu(
        tmp_path,
        "# sent_id = 1\n"
        + _line(1, "A", r"SpacesAfter=\n")
        + _line(2, "B", r"SpacesAfter=\n")
        + _line(3, "C")
        + "\n",
    )
    rows = [Row(1, 1, "", "A"), Row(2, 1, "", "B"), Row(2, 2, "", "C")]
    assert resplit_ne(path, ne, rows, "doc") == 2
    assert (ne / "doc-1.tsv").read_text(encoding="utf-8") == "Word\tTag\tNE\nA\tO\t\n"
    assert (ne / "doc-2.tsv").read_text(encoding="utf-8") == "Word\tTag\tNE\nB\tB-P\tPER\nC\tO\t\n"

    short = tmp_path / "NE3"
    short.mkdir()
    (short / "doc-1.tsv").write_text("Word\tTag\tNE\nA\tO\t\n", encoding="utf-8")
    assert resplit_ne(path, short, rows, "doc") is None  # token counts differ: untouched
    assert (short / "doc-1.tsv").exists()
