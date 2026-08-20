#!/usr/bin/env python3
"""Simplify every convertible FT2 glyph bitmap while preserving its Unicode slot."""

from __future__ import annotations

import hashlib
import io
import json
import math
import sys
from collections import Counter
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "pydeps"))

from opencc import OpenCC  # noqa: E402

from build_phase2b_font_poc import encode_bc3_white, glyph_geometry, parse_map  # noqa: E402


SOURCE = ROOT / "extracted/ui/font/localisation/font_chinese_nxg.ft2"
OUTPUT = ROOT / "bitmap_simplified/ui/font/localisation/font_chinese_nxg.ft2"
REPORT = ROOT / "bitmap_simplified/font-report.json"
PREVIEW = ROOT / "bitmap_simplified/font-preview.png"
FONT_SOURCE = Path(r"C:\Windows\Fonts\NotoSansSC-VF.ttf")
RAW_CHUNK_SIZE = 32768

# Recompressing changed data in these originally sparse Oodle chunks exceeds
# the game's fixed allocation. Any glyph touching one of them is kept wholly
# original, avoiding both archive-layout changes and partially drawn glyphs.
KNOWN_OVERSIZE_CHUNKS = {
    32, 48, 49, 62, 78, 93, 100, 115, 121, 130, 136, 137, 145, 151, 152,
    167, 173, 182, 188, 189, 195, 204, 210, 211, 219, 226, 240, 241, 251,
    256, 262, 271, 277, 278, 286, 293, 299, 308, 314, 315, 316, 323, 329,
    330, 338, 345, 351, 353, 360, 366, 367, 373, 375, 382, 388, 389, 390,
    403, 404, 412, 418, 419,
}
EXCLUDED_CHUNKS: set[int] = set()
CONVERT_ALL_HAN = False
EXCLUDED_CODEPOINTS: set[int] = set()
CLEAR_FULL_RECT = False
CLEAR_RECT_MARGIN = 0
RESTORE_NON_HAN_AFTER = False

# Eight Simplified characters used by the semantic translation have neither a
# native mapping nor a Traditional OpenCC predecessor in the official font.
# These unused top-atlas codepoints become private runtime aliases.
CUSTOM_REPLACEMENTS = {
    0x52DB: 0x55B1,  # 勛 -> 喱
    0x507D: 0x5A05,  # 偽 -> 娅
    0x50A2: 0x62F7,  # 傢 -> 拷
    0x5091: 0x65FA,  # 傑 -> 旺
    0x4F86: 0x6808,  # 來 -> 栈
    0x4F54: 0x82AF,  # 佔 -> 芯
    0x4FC2: 0x857E,  # 係 -> 蕾
    0x4E7E: 0x96BC,  # 乾 -> 隼
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def is_han(codepoint: int) -> bool:
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
    )


def render(
    character: str,
    width: int,
    height: int,
    original_ink_bbox: tuple[int, int, int, int],
) -> tuple[Image.Image, int, tuple[int, int, int, int], tuple[int, int, int, int]]:
    left, top, right, bottom = original_ink_bbox
    # Stay one pixel inside the official glyph's proven footprint. This keeps
    # the original atlas gutter and prevents linear filtering from sampling a
    # neighbour. Official CJK ink boxes are all large enough for this inset.
    safe_bbox = (left + 1, top + 1, right - 1, bottom - 1)
    safe_width = safe_bbox[2] - safe_bbox[0]
    safe_height = safe_bbox[3] - safe_bbox[1]
    if safe_width < 32 or safe_height < 32:
        raise ValueError(f"Official ink box is unexpectedly small: {original_ink_bbox}")
    for size in range(50, 27, -1):
        font = ImageFont.truetype(str(FONT_SOURCE), size)
        try:
            font.set_variation_by_name("Medium")
        except (AttributeError, OSError):
            pass
        bbox = font.getbbox(character)
        glyph_width = bbox[2] - bbox[0]
        glyph_height = bbox[3] - bbox[1]
        if glyph_width <= safe_width and glyph_height <= safe_height:
            alpha = Image.new("L", (width, height), 0)
            draw = ImageDraw.Draw(alpha)
            draw.text(
                (
                    safe_bbox[0] + (safe_width - glyph_width) // 2 - bbox[0],
                    safe_bbox[1] + (safe_height - glyph_height) // 2 - bbox[1],
                ),
                character,
                font=font,
                fill=255,
            )
            # Binary coverage is considerably more Oodle-compressible than
            # anti-aliased BC3 alpha and keeps every original chunk allocation.
            alpha = alpha.point(lambda value: 255 if value >= 96 else 0)
            rendered_bbox = alpha.getbbox()
            if rendered_bbox is None:
                raise ValueError(f"Rendered U+{ord(character):04X} is empty")
            if not (
                safe_bbox[0] <= rendered_bbox[0]
                and safe_bbox[1] <= rendered_bbox[1]
                and rendered_bbox[2] <= safe_bbox[2]
                and rendered_bbox[3] <= safe_bbox[3]
            ):
                raise ValueError(
                    f"Rendered U+{ord(character):04X} escaped safe box: "
                    f"{rendered_bbox} vs {safe_bbox}"
                )
            return alpha, size, safe_bbox, rendered_bbox
    raise ValueError(
        f"Rendered {character} does not fit official ink box {original_ink_bbox}"
    )


def main() -> None:
    source = SOURCE.read_bytes()
    output = bytearray(source)
    dds_offset = source.index(b"DDS ")
    map_offset, pairs = parse_map(source)
    mapping = dict(pairs)
    glyph_uses = Counter(mapping.values())
    converter = OpenCC("tw2sp")
    atlas = Image.open(io.BytesIO(source[dds_offset:])).convert("RGBA")
    original_alpha = atlas.getchannel("A")

    assignments: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    clear_boxes: list[tuple[int, int, int, int]] = []
    rendered_layers: list[tuple[int, int, Image.Image]] = []
    dirty_blocks: set[tuple[int, int]] = set()
    for codepoint, glyph in pairs:
        if codepoint in EXCLUDED_CODEPOINTS:
            continue
        source_char = chr(codepoint)
        display = chr(CUSTOM_REPLACEMENTS[codepoint]) if codepoint in CUSTOM_REPLACEMENTS else converter.convert(source_char)
        if len(display) != 1 or (
            display == source_char and not (CONVERT_ALL_HAN and is_han(codepoint))
        ):
            continue
        if glyph < 3 or glyph_uses[glyph] != 1:
            raise ValueError(f"Unsafe glyph sharing for U+{codepoint:04X}: {glyph}")
        x, y, width, height, *_ = glyph_geometry(source, glyph)
        clear_margin = CLEAR_RECT_MARGIN if CLEAR_FULL_RECT else 0
        block_left = max(0, x - clear_margin)
        block_top = max(0, y - clear_margin)
        block_right = min(atlas.width, x + width + clear_margin)
        block_bottom = min(atlas.height, y + height + clear_margin)
        glyph_blocks = {
            (block_x, block_y)
            for block_y in range(block_top // 4, math.ceil(block_bottom / 4))
            for block_x in range(block_left // 4, math.ceil(block_right / 4))
        }
        touched_chunks = {
            (
                dds_offset
                + 128
                + (block_y * math.ceil(atlas.width / 4) + block_x) * 16
            ) // RAW_CHUNK_SIZE
            for block_x, block_y in glyph_blocks
        }
        blocked = sorted(touched_chunks & EXCLUDED_CHUNKS)
        if blocked:
            skipped.append(
                {
                    "source": f"U+{codepoint:04X} {source_char}",
                    "would_display": f"U+{ord(display):04X} {display}",
                    "glyph": glyph,
                    "rect": [x, y, width, height],
                    "excluded_chunks": blocked,
                }
            )
            continue
        original_ink_bbox = original_alpha.crop((x, y, x + width, y + height)).getbbox()
        if original_ink_bbox is None:
            raise ValueError(f"Official glyph U+{codepoint:04X} is empty")
        alpha, font_size, safe_bbox, rendered_bbox = render(
            display, width, height, original_ink_bbox
        )
        if CLEAR_FULL_RECT:
            clear_boxes.append((block_left, block_top, block_right, block_bottom))
        else:
            clear_boxes.append(
                (
                    x + original_ink_bbox[0],
                    y + original_ink_bbox[1],
                    x + original_ink_bbox[2],
                    y + original_ink_bbox[3],
                )
            )
        rendered_layers.append((x, y, alpha))
        dirty_blocks.update(glyph_blocks)
        assignments.append(
            {
                "source": f"U+{codepoint:04X} {source_char}",
                "display": f"U+{ord(display):04X} {display}",
                "glyph": glyph,
                "rect": [x, y, width, height],
                "original_ink_bbox": list(original_ink_bbox),
                "safe_bbox": list(safe_bbox),
                "rendered_bbox": list(rendered_bbox),
                "font_size": font_size,
            }
        )

    # Clear every official ink footprint first, then max-composite every new
    # glyph in one pass. Transparent pixels from a later overlapping rectangle
    # can therefore never erase a glyph drawn earlier.
    composed_alpha = original_alpha.copy()
    for box in clear_boxes:
        composed_alpha.paste(0, box)
    replacement_layer = Image.new("L", atlas.size, 0)
    for x, y, alpha in rendered_layers:
        width, height = alpha.size
        existing = replacement_layer.crop((x, y, x + width, y + height))
        replacement_layer.paste(ImageChops.lighter(existing, alpha), (x, y))
    composed_alpha = ImageChops.lighter(composed_alpha, replacement_layer)
    if RESTORE_NON_HAN_AFTER:
        # Expanded Han clearing can touch nearby Latin/punctuation rectangles.
        # Restore every official non-Han bitmap after the clear/draw pass. Han
        # glyphs that physically overlap a non-Han rectangle are excluded by
        # the caller, so this cannot erase a converted character.
        for codepoint, glyph in pairs:
            if glyph < 3 or is_han(codepoint):
                continue
            x, y, width, height, *_ = glyph_geometry(source, glyph)
            original = original_alpha.crop((x, y, x + width, y + height))
            composed_alpha.paste(original, (x, y))
    atlas.putalpha(composed_alpha)

    blocks_w = math.ceil(atlas.width / 4)
    changed_blocks = 0
    for block_x, block_y in sorted(dirty_blocks, key=lambda value: (value[1], value[0])):
        samples = [
            atlas.getpixel((px, py))[3]
            for py in range(block_y * 4, block_y * 4 + 4)
            for px in range(block_x * 4, block_x * 4 + 4)
        ]
        original_samples = [
            original_alpha.getpixel((px, py))
            for py in range(block_y * 4, block_y * 4 + 4)
            for px in range(block_x * 4, block_x * 4 + 4)
        ]
        if samples == original_samples:
            continue
        offset = dds_offset + 128 + (block_y * blocks_w + block_x) * 16
        output[offset:offset + 16] = encode_bc3_white(
            samples, source[offset + 8:offset + 16]
        )
        changed_blocks += 1

    map_size = len(pairs) * 4 + 4  # include the FFFF/FFFF sentinel
    if output[map_offset:map_offset + map_size] != source[map_offset:map_offset + map_size]:
        raise ValueError("Unicode map changed")
    if len(output) != len(source):
        raise ValueError("FT2 size changed")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(output)

    verified = Image.open(io.BytesIO(bytes(output)[dds_offset:])).convert("RGBA")
    empty = []
    for item in assignments:
        x, y, width, height = item["rect"]  # type: ignore[misc]
        if verified.getchannel("A").crop((x, y, x + width, y + height)).getbbox() is None:
            empty.append(item["source"])
    if empty:
        raise ValueError(f"Compressed output contains empty glyphs: {empty[:10]}")

    # Preview samples evenly across atlas height, using decoded output bytes.
    samples = sorted(assignments, key=lambda item: item["rect"][1])  # type: ignore[index]
    samples = samples[::max(1, len(samples) // 32)][:32]
    cells = []
    for item in samples:
        x, y, width, height = item["rect"]  # type: ignore[misc]
        cells.append(verified.crop((x, y, x + width, y + height)).resize((width * 3, height * 3)))
    columns = 8
    cell_width = max(image.width for image in cells)
    cell_height = max(image.height for image in cells)
    canvas = Image.new("RGBA", (columns * cell_width, math.ceil(len(cells) / columns) * cell_height))
    for index, image in enumerate(cells):
        canvas.paste(image, ((index % columns) * cell_width, (index // columns) * cell_height))
    canvas.save(PREVIEW)

    report = {
        "source": str(SOURCE),
        "output": str(OUTPUT),
        "source_sha256": digest(source),
        "output_sha256": digest(output),
        "size": len(output),
        "mapping_entries": len(pairs),
        "mapping_unchanged": True,
        "custom_runtime_aliases": {
            f"U+{source:04X} {chr(source)}": f"U+{target:04X} {chr(target)}"
            for source, target in CUSTOM_REPLACEMENTS.items()
        },
        "convertible_glyphs": len(assignments) + len(skipped),
        "converted_glyphs": len(assignments),
        "fallback_traditional_glyphs": len(skipped),
        "excluded_oodle_chunks": sorted(EXCLUDED_CHUNKS),
        "dirty_blocks_considered": len(dirty_blocks),
        "changed_bc3_blocks": changed_blocks,
        "font_size_distribution": dict(sorted(Counter(item["font_size"] for item in assignments).items(), reverse=True)),
        "empty_glyphs": empty,
        "assignments": assignments,
        "fallbacks": skipped,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "source_sha256", "output_sha256", "size", "mapping_entries",
        "mapping_unchanged", "convertible_glyphs", "converted_glyphs",
        "fallback_traditional_glyphs", "dirty_blocks_considered",
        "changed_bc3_blocks", "font_size_distribution", "empty_glyphs",
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
