#!/usr/bin/env python3
"""Surgically clear confirmed right-edge residual pixels from the preferred FT2."""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
from pathlib import Path

from PIL import Image

from build_phase2b_font_poc import encode_bc3_white, glyph_geometry, parse_map

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "all_han_inplace_roundtrip/ui/font/localisation/font_chinese_nxg.ft2"
OUTPUT_ROOT = ROOT / "surgical_dotfix"
OUTPUT = OUTPUT_ROOT / "ui/font/localisation/font_chinese_nxg.ft2"
REPORT = OUTPUT_ROOT / "dotfix-report.json"
EXPECTED_SOURCE_SHA = os.environ.get("TSS_EDGE_FIX_SOURCE_SHA256", "").upper()
TARGETS = "有更"
RIGHT_SCAN = 12
VERTICAL_SCAN = 8


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def main() -> None:
    source = SOURCE.read_bytes()
    if not EXPECTED_SOURCE_SHA:
        raise ValueError("Set TSS_EDGE_FIX_SOURCE_SHA256 to the verified input FT2 SHA-256")
    if digest(source) != EXPECTED_SOURCE_SHA:
        raise ValueError("Preferred black-dot FT2 source hash changed")
    output = bytearray(source)
    dds_offset = source.index(b"DDS ")
    map_offset, pairs = parse_map(source)
    mapping = dict(pairs)
    atlas = Image.open(io.BytesIO(source[dds_offset:])).convert("RGBA")
    original_alpha = atlas.getchannel("A")
    patched_alpha = original_alpha.copy()
    cleared: list[dict[str, object]] = []
    changed_pixels: set[tuple[int, int]] = set()

    ordinary_rects = []
    for codepoint, glyph in pairs:
        if glyph < 3:
            continue
        x, y, width, height, *_ = glyph_geometry(source, glyph)
        ordinary_rects.append((x, y, x + width, y + height, codepoint, glyph))

    for character in TARGETS:
        glyph = mapping[ord(character)]
        x, y, width, height, *_ = glyph_geometry(source, glyph)
        scan = (x + width, max(0, y - VERTICAL_SCAN), x + width + RIGHT_SCAN, min(atlas.height, y + height + VERTICAL_SCAN))
        # The scan strip must not intersect any other official glyph rectangle.
        conflicts = [
            item for item in ordinary_rects
            if item[5] != glyph
            and scan[0] < item[2] and item[0] < scan[2]
            and scan[1] < item[3] and item[1] < scan[3]
        ]
        if conflicts:
            raise ValueError(f"Unsafe right strip for {character}: {conflicts[:3]}")
        pixels = []
        for py in range(scan[1], scan[3]):
            for px in range(scan[0], scan[2]):
                if original_alpha.getpixel((px, py)):
                    patched_alpha.putpixel((px, py), 0)
                    changed_pixels.add((px, py))
                    pixels.append((px, py))
        if not pixels:
            raise ValueError(f"No residual pixels found for {character}")
        cleared.append(
            {
                "character": character,
                "codepoint": f"U+{ord(character):04X}",
                "glyph": glyph,
                "glyph_rect": [x, y, width, height],
                "scan_rect": list(scan),
                "cleared_pixels": len(pixels),
                "cleared_bbox": [
                    min(px for px, _ in pixels), min(py for _, py in pixels),
                    max(px for px, _ in pixels) + 1, max(py for _, py in pixels) + 1,
                ],
            }
        )

    atlas.putalpha(patched_alpha)
    blocks_w = math.ceil(atlas.width / 4)
    changed_blocks = {(px // 4, py // 4) for px, py in changed_pixels}
    for block_x, block_y in changed_blocks:
        samples = [
            patched_alpha.getpixel((px, py))
            for py in range(block_y * 4, block_y * 4 + 4)
            for px in range(block_x * 4, block_x * 4 + 4)
        ]
        offset = dds_offset + 128 + (block_y * blocks_w + block_x) * 16
        output[offset : offset + 16] = encode_bc3_white(samples, source[offset + 8 : offset + 16])

    if output[:dds_offset] != source[:dds_offset]:
        raise ValueError("FT2 metadata changed")
    if output[map_offset : map_offset + len(pairs) * 4 + 4] != source[map_offset : map_offset + len(pairs) * 4 + 4]:
        raise ValueError("Unicode map changed")
    if len(output) != len(source):
        raise ValueError("FT2 size changed")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(output)
    verified = Image.open(io.BytesIO(bytes(output)[dds_offset:])).convert("RGBA").getchannel("A")
    decoded_differences = []
    for py in range(atlas.height):
        for px in range(atlas.width):
            if original_alpha.getpixel((px, py)) != verified.getpixel((px, py)):
                decoded_differences.append((px, py))
    unexpected = set(decoded_differences) - changed_pixels
    if unexpected:
        raise ValueError(f"Decoded changes escaped target pixels: {sorted(unexpected)[:10]}")
    if set(decoded_differences) != changed_pixels:
        raise ValueError("Not every requested residual pixel became transparent")

    report = {
        "source": str(SOURCE),
        "output": str(OUTPUT),
        "source_sha256": digest(source),
        "output_sha256": digest(output),
        "metadata_identical": True,
        "file_size_identical": True,
        "changed_blocks": len(changed_blocks),
        "changed_decoded_pixels": len(decoded_differences),
        "unexpected_decoded_pixels": 0,
        "targets": cleared,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
