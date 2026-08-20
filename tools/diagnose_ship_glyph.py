#!/usr/bin/env python3
"""Render the accepted FT2 slots for 船/葛 beside Noto references."""

from __future__ import annotations

import io
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from build_phase2b_font_poc import glyph_geometry, parse_map

ROOT = Path(__file__).resolve().parent
SOURCES = [
    ("official", ROOT / "extracted/ui/font/localisation/font_chinese_nxg.ft2"),
    ("redrawn", ROOT / "all_han_inplace/ui/font/localisation/font_chinese_nxg.ft2"),
    ("accepted", ROOT / "surgical_dotfix_all/ui/font/localisation/font_chinese_nxg.ft2"),
]
TARGETS = "船葛"
OUTPUT = ROOT / "ship-glyph-diagnostic.png"


def main() -> None:
    scale = 6
    margin = 8
    cell_w, cell_h = 460, 430
    canvas = Image.new("RGBA", (cell_w * len(TARGETS), cell_h * len(SOURCES)), (30, 30, 30, 255))
    draw = ImageDraw.Draw(canvas)
    label = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 17)
    report = []
    for row, (name, path) in enumerate(SOURCES):
        data = path.read_bytes()
        atlas = Image.open(io.BytesIO(data[data.index(b"DDS ") :])).convert("RGBA")
        mapping = dict(parse_map(data)[1])
        for col, char in enumerate(TARGETS):
            glyph = mapping[ord(char)]
            x, y, width, height, *rest = glyph_geometry(data, glyph)
            crop = atlas.crop((x - margin, y - margin, x + width + margin, y + height + margin))
            crop = crop.resize((crop.width * scale, crop.height * scale), Image.Resampling.NEAREST)
            left, top = col * cell_w, row * cell_h
            canvas.alpha_composite(crop, (left + 8, top + 50))
            draw.text((left + 8, top + 8), f"{name}: {char} U+{ord(char):04X}, glyph {glyph}", font=label, fill="white")
            draw.rectangle(
                (
                    left + 8 + margin * scale,
                    top + 50 + margin * scale,
                    left + 8 + (margin + width) * scale,
                    top + 50 + (margin + height) * scale,
                ),
                outline=(255, 40, 40, 255),
                width=2,
            )
            report.append({"source": name, "character": char, "glyph": glyph, "geometry": [x, y, width, height, *rest]})
    canvas.save(OUTPUT)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(OUTPUT)


if __name__ == "__main__":
    main()
