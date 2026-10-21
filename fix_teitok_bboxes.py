#!/usr/bin/env python3
"""fix_teitok_bboxes.py -- retroactively shift/scale the coordinates of existing TEITOK files.

Rewrites every ``bbox="x1 y1 x2 y2"`` and every ``<surface lrx/lry>`` extent in place,
using the same regex primitives as ``POST /rescale`` (``api_util/bbox_scale.py``), so
it never parses the document with an XML library and therefore also works on legacy
exports that close ``<name>`` with ``</n>`` (repaired on the way through).

Each coordinate becomes ``round((c + dx) * sx)`` -- ``--dx/--dy`` are added *before*
scaling, so ``--dx -297`` removes a 297-unit left margin. With ``--dpi`` the scale is
derived from the ALTO ``MeasurementUnit`` (``--unit``) instead of ``--sx/--sy``.

Page by page (issue #38, C; ``api_util/page_boxes.py``): every ``<surface>`` gets *its own*
extent scaled (they all used to get the first page's), and every box is clamped to the
page it is on -- a shift that would push a coordinate below 0 or past the page edge is
clamped and counted instead of producing a box the stage-4 gate rejects. A ``<change
type="rescaled">`` in ``<revisionDesc>`` records what was done.

Exit codes: 0 every file rewritten · 1 at least one file failed or the path is missing.
"""

import argparse
import sys
from pathlib import Path

from api_util.bbox_scale import dpi_scale, fix_name_close_tags, scale_bbox_coords
from api_util.page_boxes import add_change, clamp_box, rewrite_page_boxes, set_surface_sizes


def process_teitok_file(file_path, args, sx, sy):
    """Rewrite one file in place. Returns the number of bbox values rewritten."""
    with open(file_path, "r", encoding="utf-8") as f:
        xml_text = f.read()

    xml_text, name_repairs = fix_name_close_tags(xml_text)

    boxes = 0

    def transform(bbox_str, surface):
        nonlocal boxes
        if len(bbox_str.split()) != 4:
            return bbox_str, 0
        boxes += 1
        # scale_bbox_coords subtracts dx; the CLI contract is "add --dx", hence the sign flip.
        scaled = scale_bbox_coords(bbox_str, sx, sy, dx=-args.dx, dy=-args.dy)
        if surface is not None and surface.width and surface.height:
            return clamp_box(scaled, round(surface.width * sx), round(surface.height * sy))
        return clamp_box(scaled, None, None)

    xml_text, clamped = rewrite_page_boxes(xml_text, transform)
    xml_text = set_surface_sizes(xml_text, lambda s: (round(s.width * sx), round(s.height * sy)))
    shift = f", shifted by {args.dx:g},{args.dy:g}" if args.dx or args.dy else ""
    xml_text = add_change(
        xml_text,
        "rescaled",
        f"coordinates scaled by {sx:g},{sy:g}{shift} (fix_teitok_bboxes.py)"
        + (f"; {clamped} coordinate(s) clamped to the page" if clamped else ""),
    )

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(xml_text)

    repaired = f", {name_repairs} </n> close tag(s) repaired" if name_repairs else ""
    clamp_note = f", {clamped} coordinate(s) clamped to the page" if clamped else ""
    print(f"[OK] {file_path}: {boxes} bbox value(s) rewritten{repaired}{clamp_note}")
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
