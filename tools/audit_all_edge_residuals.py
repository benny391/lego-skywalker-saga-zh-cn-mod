#!/usr/bin/env python3
"""Audit orphan alpha components near every Han FT2 glyph rectangle."""

from __future__ import annotations

import io
import json
from collections import deque
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from build_bitmap_simplified_font import is_han
from build_phase2b_font_poc import glyph_geometry, parse_map

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "surgical_dotfix/ui/font/localisation/font_chinese_nxg.ft2"
OUTPUT = ROOT / "surgical_dotfix/all-edge-residual-audit.json"
MARGIN = 12


def main() -> None:
    data = SOURCE.read_bytes()
    dds_offset = data.index(b"DDS ")
    alpha = Image.open(io.BytesIO(data[dds_offset:])).convert("RGBA").getchannel("A")
    _, pairs = parse_map(data)
    ordinary = Image.new("L", alpha.size, 0)
    near_han = Image.new("L", alpha.size, 0)
    ordinary_draw = ImageDraw.Draw(ordinary)
    near_draw = ImageDraw.Draw(near_han)
    han_rects: list[tuple[int, int, int, int, int, int]] = []
    for codepoint, glyph in pairs:
        if glyph < 3:
            continue
        x, y, width, height, *_ = glyph_geometry(data, glyph)
        ordinary_draw.rectangle((x, y, x + width - 1, y + height - 1), fill=255)
        if is_han(codepoint):
            expanded = (
                max(0, x - MARGIN), max(0, y - MARGIN),
                min(alpha.width - 1, x + width - 1 + MARGIN),
                min(alpha.height - 1, y + height - 1 + MARGIN),
            )
            near_draw.rectangle(expanded, fill=255)
            han_rects.append((x, y, x + width, y + height, codepoint, glyph))

    binary_alpha = alpha.point(lambda value: 255 if value else 0)
    orphan = ImageChops.multiply(
        ImageChops.multiply(binary_alpha, near_han), ImageChops.invert(ordinary)
    )
    coords: set[tuple[int, int]] = set()
    bbox = orphan.getbbox()
    if bbox:
        pixels = orphan.load()
        for y in range(bbox[1], bbox[3]):
            for x in range(bbox[0], bbox[2]):
                if pixels[x, y]:
                    coords.add((x, y))

    components: list[dict[str, object]] = []
    remaining = set(coords)
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
        left = min(x for x, _ in component)
        top = min(y for _, y in component)
        right = max(x for x, _ in component) + 1
        bottom = max(y for _, y in component) + 1
        nearby = []
        for gx1, gy1, gx2, gy2, codepoint, glyph in han_rects:
            if (
                left < gx2 + MARGIN and gx1 - MARGIN < right
                and top < gy2 + MARGIN and gy1 - MARGIN < bottom
            ):
                nearby.append(
                    {
                        "codepoint": f"U+{codepoint:04X}",
                        "character": chr(codepoint),
                        "glyph": glyph,
                        "rect": [gx1, gy1, gx2 - gx1, gy2 - gy1],
                    }
                )
        components.append(
            {
                "pixels": len(component),
                "bbox": [left, top, right, bottom],
                "nearby_han": nearby,
            }
        )

    components.sort(key=lambda item: (-int(item["pixels"]), item["bbox"]))
    report = {
        "source": str(SOURCE),
        "margin": MARGIN,
        "mapping_entries": len(pairs),
        "han_rectangles": len(han_rects),
        "orphan_pixels": len(coords),
        "orphan_components": len(components),
        "components": components,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = dict(report)
    summary["components"] = components[:20]
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
