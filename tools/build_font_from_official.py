#!/usr/bin/env python3
"""Rebuild the proven Release atlas deterministically from the official FT2.

The recipe is the recovered, game-tested Release renderer: Noto Sans SC
Regular at 40 px, collision-split official ink footprints, centered scaling,
and the two historically excluded overlapping characters.  No generated FT2
or old build report is accepted as an input.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from collections import Counter, deque
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

import build_bitmap_simplified_font as base
from build_phase2b_font_poc import glyph_geometry, parse_map


EXCLUDED_CODEPOINTS = {0x4E01, 0x4EAB}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def make_font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(path), size)
    try:
        font.set_variation_by_name("Regular")
    except (AttributeError, OSError):
        pass
    return font


def prepare_safe_boxes(source: bytes) -> tuple[deque[tuple[int, int, int, int]], int]:
    dds_offset = source.index(b"DDS ")
    alpha = Image.open(io.BytesIO(source[dds_offset:])).convert("RGBA").getchannel("A")
    _offset, pairs = parse_map(source)
    records: list[dict[str, object]] = []
    for codepoint, glyph in pairs:
        if not base.is_han(codepoint) or codepoint in EXCLUDED_CODEPOINTS:
            continue
        x, y, width, height, *_ = glyph_geometry(source, glyph)
        ink = alpha.crop((x, y, x + width, y + height)).getbbox()
        if ink is None:
            raise ValueError(f"Official U+{codepoint:04X} is empty")
        local = [ink[0], ink[1], ink[2], ink[3]]
        records.append(
            {
                "global": [x + local[0], y + local[1], x + local[2], y + local[3]],
                "origin": (x, y),
            }
        )

    collision_pairs = 0
    for index, first in enumerate(records):
        a = first["global"]
        for second in records[index + 1 :]:
            b = second["global"]
            overlap_x = min(a[2], b[2]) - max(a[0], b[0])
            overlap_y = min(a[3], b[3]) - max(a[1], b[1])
            if overlap_x <= 0 or overlap_y <= 0:
                continue
            collision_pairs += 1
            if overlap_x <= overlap_y:
                midpoint = (max(a[0], b[0]) + min(a[2], b[2])) // 2
                if (a[0] + a[2]) <= (b[0] + b[2]):
                    a[2] = min(a[2], midpoint)
                    b[0] = max(b[0], midpoint + 1)
                else:
                    b[2] = min(b[2], midpoint)
                    a[0] = max(a[0], midpoint + 1)
            else:
                midpoint = (max(a[1], b[1]) + min(a[3], b[3])) // 2
                if (a[1] + a[3]) <= (b[1] + b[3]):
                    a[3] = min(a[3], midpoint)
                    b[1] = max(b[1], midpoint + 1)
                else:
                    b[3] = min(b[3], midpoint)
                    a[1] = max(a[1], midpoint + 1)

    boxes: deque[tuple[int, int, int, int]] = deque()
    for record in records:
        x, y = record["origin"]
        box = record["global"]
        local = (box[0] - x, box[1] - y, box[2] - x, box[3] - y)
        if local[2] <= local[0] or local[3] <= local[1]:
            raise ValueError(f"Collision-safe box collapsed: {local}")
        boxes.append(local)
    return boxes, collision_pairs


def compare_reference(candidate: Path, reference: Path) -> dict[str, object]:
    first = candidate.read_bytes()
    second = reference.read_bytes()
    if len(first) != len(second):
        return {
            "reference": str(reference),
            "reference_sha256": digest(second),
            "same_size": False,
            "byte_identical": False,
        }
    changed_bytes = sum(a != b for a, b in zip(first, second))
    first_dds = first.index(b"DDS ")
    second_dds = second.index(b"DDS ")
    first_alpha = Image.open(io.BytesIO(first[first_dds:])).convert("RGBA").getchannel("A")
    second_alpha = Image.open(io.BytesIO(second[second_dds:])).convert("RGBA").getchannel("A")
    delta = ImageChops.difference(first_alpha, second_alpha)
    return {
        "reference": str(reference),
        "reference_sha256": digest(second),
        "same_size": True,
        "byte_identical": changed_bytes == 0,
        "changed_bytes": changed_bytes,
        "decoded_alpha_delta_bbox": list(delta.getbbox()) if delta.getbbox() else None,
        "decoded_alpha_changed_pixels": sum(value != 0 for value in delta.getdata()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official-ft2", type=Path, required=True)
    parser.add_argument("--noto", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--reference-font", type=Path)
    parser.add_argument("--target-size", type=int, default=40)
    parser.add_argument("--minimum-size", type=int, default=12)
    args = parser.parse_args()

    official = args.official_ft2.read_bytes()
    safe_boxes, collision_pairs = prepare_safe_boxes(official)

    def render(
        character: str,
        width: int,
        height: int,
        original_ink_bbox: tuple[int, int, int, int],
    ) -> tuple[Image.Image, int, tuple[int, int, int, int], tuple[int, int, int, int]]:
        del original_ink_bbox
        safe_bbox = safe_boxes.popleft()
        safe_width = safe_bbox[2] - safe_bbox[0]
        safe_height = safe_bbox[3] - safe_bbox[1]
        font = make_font(args.noto, args.target_size)
        bbox = font.getbbox(character)
        temp = Image.new("L", (96, 96), 0)
        ImageDraw.Draw(temp).text((8 - bbox[0], 8 - bbox[1]), character, font=font, fill=255)
        ink_bbox = temp.getbbox()
        if ink_bbox is None:
            raise ValueError(f"U+{ord(character):04X} rendered empty")
        ink = temp.crop(ink_bbox)
        scale = min(1.0, safe_width / ink.width, safe_height / ink.height)
        if scale < 1.0:
            ink = ink.resize(
                (
                    max(1, min(safe_width, round(ink.width * scale))),
                    max(1, min(safe_height, round(ink.height * scale))),
                ),
                Image.Resampling.LANCZOS,
            )
        ink = ink.point(lambda value: 255 if value >= 96 else 0)
        layer = Image.new("L", (width, height), 0)
        left = safe_bbox[0] + (safe_width - ink.width) // 2
        top = safe_bbox[1] + (safe_height - ink.height) // 2
        layer.paste(ink, (left, top))
        rendered = layer.getbbox()
        if rendered is None:
            raise ValueError(f"U+{ord(character):04X} rendered empty")
        effective_size = max(args.minimum_size, round(args.target_size * scale))
        return layer, effective_size, safe_bbox, rendered

    output = args.output_root / "ui/font/localisation/font_chinese_nxg.ft2"
    report_path = args.output_root / "font-report.json"
    preview = args.output_root / "font-preview.png"
    base.SOURCE = args.official_ft2
    base.OUTPUT = output
    base.REPORT = report_path
    base.PREVIEW = preview
    base.FONT_SOURCE = args.noto
    base.CONVERT_ALL_HAN = True
    base.CLEAR_FULL_RECT = False
    base.CLEAR_RECT_MARGIN = 0
    base.RESTORE_NON_HAN_AFTER = False
    base.EXCLUDED_CODEPOINTS = set(EXCLUDED_CODEPOINTS)
    base.render = render
    base.main()
    if safe_boxes:
        raise ValueError(f"Unused safe boxes after build: {len(safe_boxes)}")

    report = json.loads(report_path.read_text(encoding="utf-8"))
    sizes = Counter(item["font_size"] for item in report["assignments"])
    report["recipe"] = "release-atlas-from-official-v1"
    report["noto_sha256"] = digest(args.noto.read_bytes())
    report["render_policy"] = {
        "variation": "Regular",
        "target_size": args.target_size,
        "minimum_size": args.minimum_size,
        "collision_pairs_split": collision_pairs,
        "excluded_codepoints": [f"U+{value:04X}" for value in sorted(EXCLUDED_CODEPOINTS)],
        "font_size_distribution": dict(sorted(sizes.items(), reverse=True)),
    }
    if args.reference_font:
        report["stable_reference_comparison"] = compare_reference(output, args.reference_font)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "recipe": report["recipe"],
                "source_sha256": report["source_sha256"],
                "output_sha256": report["output_sha256"],
                "noto_sha256": report["noto_sha256"],
                "converted_glyphs": report["converted_glyphs"],
                "stable_reference_comparison": report.get("stable_reference_comparison"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
