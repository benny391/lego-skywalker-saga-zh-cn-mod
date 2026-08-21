#!/usr/bin/env python3
"""Apply only uniquely recovered Release glyph routes to the FT2 Unicode map."""

from __future__ import annotations

import hashlib
import io
import json
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ft2_v14 import parse_char_records, parse_unicode_map


ROOT = Path(__file__).resolve().parent
BASE = ROOT / "ship_alias_fix/ui/font/localisation/font_chinese_nxg.ft2"
AUDIT = ROOT / "release_index_geometry_audit.json"
OUTPUT_ROOT = ROOT / "release_geometry_index_fix"
OUTPUT = OUTPUT_ROOT / "ui/font/localisation/font_chinese_nxg.ft2"
REPORT = OUTPUT_ROOT / "index-fix-report.json"
PREVIEW = OUTPUT_ROOT / "index-fix-preview.png"
NOTO = Path(r"C:\Windows\Fonts\NotoSansSC-VF.ttf")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def main() -> None:
    raw = BASE.read_bytes()
    dds_offset = raw.index(b"DDS ")
    records = parse_char_records(raw)
    map_offset, pairs = parse_unicode_map(raw)
    pair_positions = {
        codepoint: map_offset + index * 4 for index, (codepoint, _slot) in enumerate(pairs)
    }
    mapping = dict(pairs)
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    routes = [
        route
        for route in audit["routes"]
        if route["status"] == "unique" and route["new_index"] != route["old_index"]
    ]
    if len(routes) != 53:
        raise ValueError(f"Expected 53 deterministic shifts, got {len(routes)}")
    if any(route["old_index"] - route["new_index"] not in range(55, 60) for route in routes):
        raise ValueError("Recovered shifts no longer follow the verified shelf stride")

    output = bytearray(raw)
    allowed_positions = set()
    for route in routes:
        codepoint = int(route["source"].split(" ", 1)[0][2:], 16)
        if mapping[codepoint] != route["old_index"]:
            raise ValueError(f"Map/audit mismatch for U+{codepoint:04X}")
        if not 0 <= route["new_index"] < len(records):
            raise ValueError(f"Out-of-range recovered index for U+{codepoint:04X}")
        position = pair_positions[codepoint] + 2
        struct.pack_into(">H", output, position, route["new_index"])
        allowed_positions.update((position, position + 1))

    parsed_offset, parsed_pairs = parse_unicode_map(bytes(output))
    if parsed_offset != map_offset or len(parsed_pairs) != len(pairs):
        raise ValueError("Unicode table shape changed")
    if bytes(output[dds_offset:]) != raw[dds_offset:]:
        raise ValueError("DDS changed in an index-only build")
    changed_positions = [
        position for position, (before, after) in enumerate(zip(raw, output)) if before != after
    ]
    if any(position not in allowed_positions for position in changed_positions):
        raise ValueError("A byte outside the selected map indices changed")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(output)
    make_preview(raw, dds_offset, records, routes)
    report = {
        "base": str(BASE),
        "output": str(OUTPUT),
        "base_sha256": digest(raw),
        "output_sha256": digest(output),
        "dds_sha256": digest(raw[dds_offset:]),
        "dds_unchanged": True,
        "unicode_pair_count": len(pairs),
        "route_count": len(routes),
        "changed_byte_count": len(changed_positions),
        "allowed_index_byte_count": len(allowed_positions),
        "excluded_ambiguous": ["U+4E00 一", "U+4E8C 二", "U+65E5 日"],
        "routes": routes,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "routes"}, ensure_ascii=False, indent=2))


def make_preview(raw: bytes, dds_offset: int, records, routes) -> None:
    atlas = Image.open(io.BytesIO(raw[dds_offset:])).convert("RGBA")
    font = ImageFont.truetype(str(NOTO), 38)
    label_font = ImageFont.truetype(str(NOTO), 18)
    columns = 4
    cell_w, cell_h = 250, 126
    rows = (len(routes) + columns - 1) // columns
    canvas = Image.new("RGBA", (columns * cell_w, rows * cell_h), (28, 28, 28, 255))
    draw = ImageDraw.Draw(canvas)
    for position, route in enumerate(routes):
        left = (position % columns) * cell_w
        top = (position // columns) * cell_h
        semantic = route["display"].split(" ", 1)[1]
        runtime = route["source"].split(" ", 1)[1]
        layer = Image.new("L", (64, 64), 0)
        bbox = font.getbbox(semantic)
        ImageDraw.Draw(layer).text((8 - bbox[0], 8 - bbox[1]), semantic, font=font, fill=255)
        expected = Image.merge("RGBA", (layer, layer, layer, layer))
        record = records[route["new_index"]]
        x, y, width, height = record.rect
        actual = atlas.crop((x, y, x + width, y + height))
        actual.thumbnail((64, 64), Image.Resampling.NEAREST)
        canvas.alpha_composite(expected, (left + 18, top + 42))
        canvas.alpha_composite(actual, (left + 105, top + 42))
        draw.text((left + 12, top + 8), f"{runtime}→{semantic}  {route['old_index']}→{route['new_index']}", font=label_font, fill=(240, 240, 240, 255))
        draw.text((left + 18, top + 102), "期望", font=label_font, fill=(170, 210, 255, 255))
        draw.text((left + 105, top + 102), "现有槽", font=label_font, fill=(170, 255, 190, 255))
    PREVIEW.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(PREVIEW)


if __name__ == "__main__":
    main()

