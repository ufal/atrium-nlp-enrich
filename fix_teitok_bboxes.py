#!/usr/bin/env python3
"""fix_teitok_bboxes.py -- retroactively shift/scale the coordinates of existing TEITOK files.

Rewrites every ``bbox="x1 y1 x2 y2"`` and every ``<surface lrx/lry>`` extent in place,
using the same regex primitives as ``POST /rescale`` (``api_util/bbox_scale.py``), so
it never parses the document with an XML library and therefore also works on legacy
exports that close ``<name>`` with ``</n>`` (repaired on the way through).

Each coordinate becomes ``round((c + dx) * sx)`` -- ``--dx/--dy`` are added *before*
scaling, so ``--dx -297`` removes a 297-unit left margin. With ``--dpi`` the scale is
derived from the ALTO ``MeasurementUnit`` (``--unit``) instead of ``--sx/--sy``.

Exit codes: 0 every file rewritten · 1 at least one file failed or the path is missing.
"""

import argparse
import sys
from pathlib import Path

from api_util.bbox_scale import (
    detect_source_size,
    dpi_scale,
    fix_name_close_tags,
    rewrite_bboxes,
    scale_bbox_coords,
    set_surface_extent,
)


def process_teitok_file(file_path, args, sx, sy):
    """Rewrite one file in place. Returns the number of bbox values rewritten."""
    with open(file_path, "r", encoding="utf-8") as f:
        xml_text = f.read()

    xml_text, name_repairs = fix_name_close_tags(xml_text)

    boxes = 0

    def scale_fn(bbox_str):
        nonlocal boxes
        if len(bbox_str.split()) == 4:
            boxes += 1
        # scale_bbox_coords subtracts dx; the CLI contract is "add --dx", hence the sign flip.
        return scale_bbox_coords(bbox_str, sx, sy, dx=-args.dx, dy=-args.dy)

    xml_text = rewrite_bboxes(xml_text, scale_fn)

    # detect_source_size() returns (width, height, source_kind); only a real
    # <surface lrx/lry> is rescaled -- a bbox-extent estimate has no element to rewrite.
    w, h, kind = detect_source_size(xml_text)
    if kind == "surface" and w is not None and h is not None:
        xml_text = set_surface_extent(xml_text, round(w * sx), round(h * sy))

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(xml_text)

    repaired = f", {name_repairs} </n> close tag(s) repaired" if name_repairs else ""
    print(f"[OK] {file_path}: {boxes} bbox value(s) rewritten{repaired}")
    return boxes


def build_parser():
    parser = argparse.ArgumentParser(
        description="Retroactively adjust bounding box displacements in generated TEITOK XML files."
    )
    parser.add_argument(
        "-i", "--input", required=True, help="Path to TEITOK XML file or directory of files."
    )
    parser.add_argument(
        "--dx",
        type=float,
        default=0.0,
        help="Horizontal shift added before scaling (e.g. -297 to remove a left margin).",
    )
    parser.add_argument(
        "--dy",
        type=float,
        default=0.0,
        help="Vertical shift added before scaling (e.g. -80 to remove a top margin).",
    )
    parser.add_argument(
        "--sx",
        type=float,
        default=1.0,
        help="Horizontal scale factor (ignored when --dpi is given).",
    )
    parser.add_argument(
        "--sy",
        type=float,
        default=1.0,
        help="Vertical scale factor (ignored when --dpi is given).",
    )
    parser.add_argument(
        "--dpi",
        type=float,
        default=None,
        help="Target DPI; derives the scale from --unit instead of --sx/--sy.",
    )
    parser.add_argument(
        "--alto-dpi",
        type=float,
        default=None,
        help="Source DPI of ALTO pixel coordinates (used if unit is pixel).",
    )
    parser.add_argument(
        "--unit", type=str, default="pixel", help="ALTO MeasurementUnit (pixel, mm10, inch1200)."
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    sx, sy = dpi_scale(args.unit, args.dpi, args.alto_dpi) if args.dpi else (args.sx, args.sy)

    input_path = Path(args.input)
    if input_path.is_file():
        files = [input_path]
    elif input_path.is_dir():
        files = sorted(input_path.glob("*.xml"))
    else:
        print(f"Error: Specified path target {args.input} does not exist.", file=sys.stderr)
        return 1

    failed = 0
    for xml_file in files:
        try:
            process_teitok_file(xml_file, args, sx, sy)
        except (OSError, UnicodeDecodeError) as exc:
            failed += 1
            print(f"[FAIL] {xml_file}: {exc}", file=sys.stderr)

    if failed:
        print(f"{failed} of {len(files)} file(s) could not be rewritten.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
