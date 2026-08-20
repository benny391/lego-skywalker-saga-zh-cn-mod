#!/usr/bin/env python3
"""Redraw all Han glyphs without changing any official FT2 coordinates."""

from __future__ import annotations

import io
import json
from collections import Counter, deque
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import build_bitmap_simplified_font as base
from build_phase2b_font_poc import glyph_geometry, parse_map

ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = ROOT / "all_han_inplace"
FONT_SOURCE = Path(r"C:\Windows\Fonts\NotoSansSC-VF.ttf")
TARGET_SIZE = 38
MIN_SIZE = 12
INNER_GUARD = 6
CLEAR_MARGIN = 12

# U+4EAB is the only Han rectangle overlapping two punctuation slots.
base.EXCLUDED_CODEPOINTS = {0x4E01, 0x4EAB, 0x9F90}


def make_font(size: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONT_SOURCE), size)
    try:
        font.set_variation_by_name("Regular")
    except (AttributeError, OSError):
        pass
    return font


def prepare_safe_boxes() -> tuple[deque[tuple[int, int, int, int]], int]:
    source = base.SOURCE.read_bytes()
    dds_offset = source.index(b"DDS ")
    alpha = Image.open(io.BytesIO(source[dds_offset:])).convert("RGBA").getchannel("A")
    _, pairs = parse_map(source)
    records: list[dict[str, object]] = []
    for codepoint, glyph in pairs:
        if not base.is_han(codepoint) or codepoint in base.EXCLUDED_CODEPOINTS:
            continue
        x, y, width, height, *_ = glyph_geometry(source, glyph)
        ink = alpha.crop((x, y, x + width, y + height)).getbbox()
        if ink is None:
            raise ValueError(f"Official U+{codepoint:04X} is empty")
        # Keep replacement ink away from every official UV edge. The game
        # filters beyond the nominal rectangle, so a six-pixel transparent
        # guard prevents a neighbouring glyph from appearing as a stray dot.
        local = [INNER_GUARD, INNER_GUARD, width - INNER_GUARD, height - INNER_GUARD]
        records.append(
            {
                "global": [x + local[0], y + local[1], x + local[2], y + local[3]],
                "local": local,
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
            # Official glyphs are shelf-packed, so their overlap is almost
            # always a narrow vertical strip. Split that strip and leave one
            # transparent pixel on both sides; no replacement ink can appear
            # in a neighbour's official UV rectangle.
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

    safe_boxes: deque[tuple[int, int, int, int]] = deque()
    for record in records:
        x, y = record["origin"]
        box = record["global"]
        local = (box[0] - x, box[1] - y, box[2] - x, box[3] - y)
        if local[2] <= local[0] or local[3] <= local[1]:
            raise ValueError(f"Collision-safe box collapsed: {local}")
        safe_boxes.append(local)
    return safe_boxes, collision_pairs


SAFE_BOXES, COLLISION_PAIRS = prepare_safe_boxes()


def render_inplace(
    character: str,
    width: int,
    height: int,
    original_ink_bbox: tuple[int, int, int, int],
) -> tuple[Image.Image, int, tuple[int, int, int, int], tuple[int, int, int, int]]:
    del original_ink_bbox
    safe_bbox = SAFE_BOXES.popleft()
    safe_width = safe_bbox[2] - safe_bbox[0]
    safe_height = safe_bbox[3] - safe_bbox[1]
    font = make_font(TARGET_SIZE)
    bbox = font.getbbox(character)
    temp = Image.new("L", (96, 96), 0)
    ImageDraw.Draw(temp).text((8 - bbox[0], 8 - bbox[1]), character, font=font, fill=255)
    ink = temp.crop(temp.getbbox())
    scale = min(1.0, safe_width / ink.width, safe_height / ink.height)
    if scale < 1.0:
        new_size = (
            max(1, min(safe_width, round(ink.width * scale))),
            max(1, min(safe_height, round(ink.height * scale))),
        )
        ink = ink.resize(new_size, Image.Resampling.LANCZOS)
    ink = ink.point(lambda value: 255 if value >= 96 else 0)
    layer = Image.new("L", (width, height), 0)
    left = safe_bbox[0] + (safe_width - ink.width) // 2
    # FT2 positions the variable-height glyph quads on a common baseline.
    # The official font keeps a nearly constant bottom bearing (median 4 px).
    # Use the protected safe-box bottom as one shared 6 px bearing instead of
    # vertically centering inside rectangles whose heights vary by 8+ pixels.
    top = safe_bbox[3] - ink.height
    layer.paste(ink, (left, top))
    rendered = layer.getbbox()
    if rendered is None:
        raise ValueError(f"U+{ord(character):04X} rendered empty")
    effective_size = max(MIN_SIZE, round(TARGET_SIZE * scale))
    return layer, effective_size, safe_bbox, rendered


def main() -> None:
    base.OUTPUT = OUTPUT_ROOT / "ui/font/localisation/font_chinese_nxg.ft2"
    base.REPORT = OUTPUT_ROOT / "font-report.json"
    base.PREVIEW = OUTPUT_ROOT / "font-preview.png"
    base.CONVERT_ALL_HAN = True
    base.CLEAR_FULL_RECT = True
    base.CLEAR_RECT_MARGIN = CLEAR_MARGIN
    base.RESTORE_NON_HAN_AFTER = True
    # Preserve U+4EAB to avoid changing its two overlapping punctuation slots.
    base.render = render_inplace
    base.main()
    if SAFE_BOXES:
        raise ValueError(f"Unused safe boxes after build: {len(SAFE_BOXES)}")
    report = json.loads(base.REPORT.read_text(encoding="utf-8"))
    sizes = Counter(item["font_size"] for item in report["assignments"])
    report["render_policy"] = {
        "font": str(FONT_SOURCE),
        "variation": "Regular",
        "coordinates": "official unchanged",
        "target_size": TARGET_SIZE,
        "minimum_size": MIN_SIZE,
        "inner_transparent_guard": INNER_GUARD,
        "collision_pairs_split": COLLISION_PAIRS,
        "clear_margin": CLEAR_MARGIN,
        "restore_non_han_after_clear": True,
        "excluded_codepoints": ["U+4E01", "U+4EAB", "U+9F90"],
        "target_size_glyphs": sizes[TARGET_SIZE],
        "reduced_glyphs": len(report["assignments"]) - sizes[TARGET_SIZE],
    }
    base.REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["render_policy"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
