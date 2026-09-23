import base64
from pathlib import Path
from unittest.mock import patch

# Base64 encoded minimal 1x1 transparent PNG to act as our data sample
MINIMAL_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAACklEQVR4nGMAAQAABQABDQottAAAAABJRU5ErkJggg=="
)


def test_cli_argparse_dpi_support():
    """Ensure that the summarize_nt_udp.py pipeline natively understands dpi and alto-dpi arguments."""
    from api_util.summarize_nt_udp import build_parser

    parser = build_parser()
    help_text = parser.format_help()
    assert "--dpi" in help_text, "Missing --dpi flag in argparse configuration."
    assert "--alto-dpi" in help_text, "Missing --alto-dpi flag in argparse configuration."

    # The parser must accept the flags in-process without erroring out
    args = parser.parse_args(["--dpi", "300", "--alto-dpi", "200"])
    assert args.dpi == 300.0
    assert args.alto_dpi == 200.0


def test_process_single_document_threading(tmp_path):
    """Guarantee thread execution of process_single_document natively pushes DPI args to write_teitok_merged."""
    from api_util.summarize_nt_udp import process_single_document

    with patch("api_util.summarize_nt_udp.write_teitok_merged") as mock_write:
        teitok_out_dir = tmp_path / "TEITOK"

        # Create dummy prerequisites to prevent the pipeline from exiting early
        ne_dir = tmp_path / "dummy_ne_dir"
        ne_dir.mkdir()
        conllu_file = tmp_path / "dummy.conllu"
        conllu_file.write_text("")

        process_single_document(
            conllu_file=str(conllu_file),
            ne_dir=str(ne_dir),
            output_dir=str(tmp_path),
            save_csv=False,
            save_teitok=True,
            teitok_out=str(teitok_out_dir),
            alto_dir="dummy_alto_dir",
            dpi=300.0,
            alto_dpi=200.0,
        )

        assert mock_write.call_count >= 1, "write_teitok_merged was never called"
        _, kwargs = mock_write.call_args
        assert kwargs.get("dpi") == 300.0
        assert kwargs.get("alto_dpi") == 200.0


def test_minimal_png_generation(tmp_path):
    """Provide the minimal PNG binary to prevent CI failures when testing ALTO alignments."""
    pages_dir = tmp_path / "data_samples" / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    png_file = pages_dir / "CTX000000001-1.png"
    with open(png_file, "wb") as f:
        f.write(base64.b64decode(MINIMAL_PNG_B64))

    assert png_file.exists()
    assert png_file.stat().st_size > 0


def test_cli_bbox_origin_and_model_flags():
    from api_util.summarize_nt_udp import build_parser

    args = build_parser().parse_args(
        ["--bbox-origin", "printspace", "--model-nametag", "nametag3-x", "--model-udpipe", "u"]
    )
    assert (args.bbox_origin, args.model_nametag, args.model_udpipe) == (
        "printspace",
        "nametag3-x",
        "u",
    )


def test_per_document_mode_threads_dpi_origin_and_models(tmp_path, monkeypatch):
    """api_4_stats.sh runs per-document mode. Before this fix it dropped --dpi/--alto-dpi
    (so IMAGE_DPI never applied), and the NameTag model came only from an environment
    variable that api_4_stats.sh never exports."""
    import api_util.summarize_nt_udp as summarize

    for key in ("MODEL_NAMETAG", "MODEL_UDPIPE", "BBOX_ORIGIN"):
        monkeypatch.delenv(key, raising=False)
    captured = {}

    def fake_process(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(summarize, "process_single_document", fake_process)
    argv = [
        "--conllu", str(tmp_path / "d.conllu"),
        "--ne-dir", str(tmp_path),
        "--output-dir", str(tmp_path),
        "--dpi", "300",
        "--alto-dpi", "200",
        "--bbox-origin", "printspace",
        "--model-nametag", "nametag3-multilingual-onto-260521",
    ]  # fmt: skip
    try:
        summarize.main(argv)
    except SystemExit as exc:
        assert exc.code == 0
    assert captured["dpi"] == 300.0 and captured["alto_dpi"] == 200.0
    assert captured["bbox_origin"] == "printspace"
    assert captured["model_nametag"] == "nametag3-multilingual-onto-260521"


def test_teitok_is_written_once_and_after_the_ner_merge(tmp_path):
    """The pre-merge write_teitok_merged() call read a merged CoNLL-U that did not exist
    yet; the TEITOK must come from the merged file, once."""
    from api_util.summarize_nt_udp import process_single_document

    conllu = tmp_path / "doc.conllu"
    conllu.write_text("1\tPraha\tPraha\tPROPN\t_\t_\t0\troot\t_\t_\n\n", encoding="utf-8")
    ne_dir = tmp_path / "ne"
    ne_dir.mkdir()
    (ne_dir / "doc-1.tsv").write_text("token\ttag\nPraha\tB-gu\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    with patch("api_util.summarize_nt_udp.write_teitok_merged") as mock_write:
        mock_write.side_effect = lambda conllu_path, *a, **k: Path(conllu_path).exists()
        process_single_document(
            conllu_file=str(conllu),
            ne_dir=str(ne_dir),
            output_dir=str(out_dir),
            save_csv=False,
            save_teitok=True,
            teitok_out=str(tmp_path / "TEITOK"),
            bbox_origin="printspace",
        )
    assert mock_write.call_count == 1
    args, kwargs = mock_write.call_args
    assert Path(args[0]) == out_dir / "doc.conllu" and Path(args[0]).exists()
    assert kwargs["bbox_origin"] == "printspace"
