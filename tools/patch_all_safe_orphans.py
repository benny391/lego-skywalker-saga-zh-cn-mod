#!/usr/bin/env python3
"""Clear only orphan pixels attributable to converted Han glyphs."""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
from collections import deque
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from build_bitmap_simplified_font import is_han
from build_phase2b_font_poc import alpha_palette, glyph_geometry, parse_map

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "surgical_dotfix/ui/font/localisation/font_chinese_nxg.ft2"
OUTPUT_ROOT = ROOT / "surgical_dotfix_all"
OUTPUT = OUTPUT_ROOT / "ui/font/localisation/font_chinese_nxg.ft2"
REPORT = OUTPUT_ROOT / "orphan-fix-report.json"
EXPECTED_SOURCE_SHA = os.environ.get("TSS_ORPHAN_FIX_SOURCE_SHA256", "").upper()
MARGIN = 12
PRESERVED_HAN = {0x4E01, 0x4EAB}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def gap(bbox: tuple[int, int, int, int], rect: tuple[int, int, int, int]) -> int:
    dx = max(rect[0] - bbox[2], bbox[0] - rect[2], 0)
    dy = max(rect[1] - bbox[3], bbox[1] - rect[3], 0)
    return max(dx, dy)


def main() -> None:
    source = SOURCE.read_bytes()
    if not EXPECTED_SOURCE_SHA:
        raise ValueError("Set TSS_ORPHAN_FIX_SOURCE_SHA256 to the verified input FT2 SHA-256")
    if digest(source) != EXPECTED_SOURCE_SHA:
        raise ValueError("Surgical two-glyph source hash changed")
    output = bytearray(source)
    dds_offset = source.index(b"DDS ")
    map_offset, pairs = parse_map(source)
    atlas = Image.open(io.BytesIO(source[dds_offset:])).convert("RGBA")
    original_alpha = atlas.getchannel("A")
    patched_alpha = original_alpha.copy()
    blocks_w = math.ceil(atlas.width / 4)

    ordinary_mask = Image.new("L", atlas.size, 0)
    near_han_mask = Image.new("L", atlas.size, 0)
    ordinary_draw = ImageDraw.Draw(ordinary_mask)
    near_draw = ImageDraw.Draw(near_han_mask)
    rects: list[tuple[int, int, int, int, int, int, bool]] = []
    for codepoint, glyph in pairs:
        if glyph < 3:
            continue
        x, y, width, height, *_ = glyph_geometry(source, glyph)
        rect = (x, y, x + width, y + height, codepoint, glyph, is_han(codepoint))
        rects.append(rect)
        ordinary_draw.rectangle((x, y, x + width - 1, y + height - 1), fill=255)
        if rect[6]:
            near_draw.rectangle(
                (
                    max(0, x - MARGIN), max(0, y - MARGIN),
                    min(atlas.width - 1, x + width - 1 + MARGIN),
                    min(atlas.height - 1, y + height - 1 + MARGIN),
                ),
                fill=255,
            )

    orphan = ImageChops.multiply(
        ImageChops.multiply(original_alpha.point(lambda value: 255 if value else 0), near_han_mask),
        ImageChops.invert(ordinary_mask),
    )
    orphan_coords: set[tuple[int, int]] = set()
    bbox = orphan.getbbox()
    if bbox:
        pixels = orphan.load()
        for y in range(bbox[1], bbox[3]):
            for x in range(bbox[0], bbox[2]):
                if pixels[x, y]:
                    orphan_coords.add((x, y))

    remaining = set(orphan_coords)
    cleared_components = []
    preserved_components = []
    clear_pixels: set[tuple[int, int]] = set()
    while remaining:
        start = remaining.pop()
        queue = deque([start])
        component = [start]
        while queue:
            x, y = queue.popleft()
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if not dx and not dy:
                        continue
                    point = (x + dx, y + dy)
                    if point in remaining:
                        remaining.remove(point)
                        queue.append(point)
                        component.append(point)
        component_bbox = (
            min(x for x, _ in component), min(y for _, y in component),
            max(x for x, _ in component) + 1, max(y for _, y in component) + 1,
        )
        distances = [(gap(component_bbox, rect[:4]), rect) for rect in rects]
        minimum = min(distance for distance, _ in distances)
        nearest = [rect for distance, rect in distances if distance == minimum]
        safe = all(rect[6] and rect[4] not in PRESERVED_HAN for rect in nearest)
        item = {
            "pixels": len(component),
            "bbox": list(component_bbox),
            "nearest": [
                {
                    "codepoint": f"U+{rect[4]:04X}",
                    "glyph": rect[5],
                    "han": rect[6],
                    "distance": minimum,
                }
                for rect in nearest
            ],
        }
        if safe:
            component_blocks = {(x // 4, y // 4) for x, y in component}
            unsafe_blocks = []
            for block_x, block_y in component_blocks:
                offset = dds_offset + 128 + (block_y * blocks_w + block_x) * 16
                palette = alpha_palette(source[offset], source[offset + 1])
                if 0 not in palette:
                    unsafe_blocks.append([block_x, block_y])
            if unsafe_blocks:
                safe = False
                item["preserve_reason"] = "BC3 block has no exact transparent index"
                item["unsafe_blocks"] = unsafe_blocks
        if safe:
            clear_pixels.update(component)
            cleared_components.append(item)
        else:
            preserved_components.append(item)

    for x, y in clear_pixels:
        patched_alpha.putpixel((x, y), 0)
    atlas.putalpha(patched_alpha)
    pixels_by_block: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for x, y in clear_pixels:
        pixels_by_block.setdefault((x // 4, y // 4), []).append((x, y))
    changed_blocks = set(pixels_by_block)
    for (block_x, block_y), block_pixels in pixels_by_block.items():
        offset = dds_offset + 128 + (block_y * blocks_w + block_x) * 16
        block = bytearray(source[offset : offset + 16])
        palette = alpha_palette(block[0], block[1])
        zero_indices = [index for index, value in enumerate(palette) if value == 0]
        if not zero_indices:
            raise ValueError(f"BC3 block {(block_x, block_y)} has no exact transparent index")
        zero_index = zero_indices[0]
        bits = int.from_bytes(block[2:8], "little")
        for x, y in block_pixels:
            sample = (y % 4) * 4 + (x % 4)
            bits &= ~(7 << (3 * sample))
            bits |= zero_index << (3 * sample)
        block[2:8] = bits.to_bytes(6, "little")
        output[offset : offset + 16] = block

    if output[:dds_offset] != source[:dds_offset]:
        raise ValueError("FT2 metadata changed")
    if output[map_offset : map_offset + len(pairs) * 4 + 4] != source[map_offset : map_offset + len(pairs) * 4 + 4]:
        raise ValueError("Unicode map changed")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(output)

    verified = Image.open(io.BytesIO(bytes(output)[dds_offset:])).convert("RGBA").getchannel("A")
    differences = {
        (x, y)
        for y in range(atlas.height)
        for x in range(atlas.width)
        if original_alpha.getpixel((x, y)) != verified.getpixel((x, y))
    }
    if differences != clear_pixels:
        raise ValueError(
            f"Decoded pixel delta mismatch: expected {len(clear_pixels)}, got {len(differences)}"
        )

    report = {
        "source": str(SOURCE),
        "output": str(OUTPUT),
        "source_sha256": digest(source),
        "output_sha256": digest(output),
        "mapping_unchanged": True,
        "metadata_identical": True,
        "total_orphan_components": len(cleared_components) + len(preserved_components),
        "cleared_components": len(cleared_components),
        "cleared_pixels": len(clear_pixels),
        "preserved_components": len(preserved_components),
        "preserved_pixels": sum(item["pixels"] for item in preserved_components),
        "changed_blocks": len(changed_blocks),
        "unexpected_decoded_pixels": 0,
        "preserved": preserved_components,
        "cleared": cleared_components,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in {"preserved", "cleared"}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
