#!/usr/bin/env python3
"""Retire the temporary ship alias and reuse its proven FT2 slot for 庞.

The accepted Release build encoded semantic 船 as runtime 複 and rendered 船
in the U+8907 glyph slot.  The later FT2 v14 index audit recovered the real 船
route, so this migration restores 船 in text, encodes semantic 庞 as runtime
複, and redraws only the already-modified U+8907 slot as 庞.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

from build_phase2b_font_poc import encode_bc3_white
from ft2_v14 import parse_char_records, parse_unicode_map
from localization_qa import compare


TARGET_COLUMN = "CHINESE TRADITIONAL"
SHIP = "船"
ALIAS = "複"
TRAD_PANG = "龐"
SIMP_PANG = "庞"
EXPECTED_ALIAS_INDEX = 2631
EXPECTED_SHIP_INDEX = 2403
EXPECTED_ALIAS_RECT = (194, 3024, 59, 54)
# This is the exact local box modified by the already-tested ship alias patch.
# The old geometry reader described the record as 60x55; the corrected v14
# parser shows 59x54, so the proven box has a six-pixel leading and five-pixel
# trailing gutter.
SAFE_LOCAL = (6, 6, 54, 49)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def build_text(source_path: Path, output_path: Path) -> dict[str, object]:
    source = source_path.read_bytes()
    rows = list(csv.reader(io.StringIO(source.decode("utf-8"), newline=""), strict=True))
    target_index = rows[0].index(TARGET_COLUMN)
    before = [row[target_index] for row in rows[1:]]
    counts_before = {
        char: sum(value.count(char) for value in before)
        for char in (SHIP, ALIAS, TRAD_PANG, SIMP_PANG)
    }
    expected = {SHIP: 0, ALIAS: 726, TRAD_PANG: 42, SIMP_PANG: 0}
    if counts_before != expected:
        raise ValueError(f"Unexpected migration input counts: {counts_before} != {expected}")

    for row in rows[1:]:
        value = row[target_index]
        # The order matters: old ship aliases become real 船 before 龐 is routed
        # through the now-free alias codepoint.
        row[target_index] = value.replace(ALIAS, SHIP).replace(TRAD_PANG, ALIAS)

    stream = io.StringIO(newline="")
    csv.writer(stream, quoting=csv.QUOTE_ALL, lineterminator="\n").writerows(rows)
    output = stream.getvalue().encode("utf-8")
    if len(output) != len(source):
        raise ValueError(f"UTF-8 byte length changed: {len(source)} -> {len(output)}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(output)

    validation = compare(source_path, output_path)
    if not validation["valid"]:
        raise ValueError(f"Localization validation failed: {validation['errors'][:5]}")
    after = [row[target_index] for row in rows[1:]]
    counts_after = {
        char: sum(value.count(char) for value in after)
        for char in (SHIP, ALIAS, TRAD_PANG, SIMP_PANG)
    }
    expected_after = {SHIP: 726, ALIAS: 42, TRAD_PANG: 0, SIMP_PANG: 0}
    if counts_after != expected_after:
        raise ValueError(f"Unexpected migration output counts: {counts_after} != {expected_after}")
    return {
        "source": str(source_path),
        "output": str(output_path),
        "source_sha256": digest(source),
        "output_sha256": digest(output),
        "bytes": len(output),
        "rows": len(rows) - 1,
        "counts_before": {f"U+{ord(k):04X}": v for k, v in counts_before.items()},
        "counts_after": {f"U+{ord(k):04X}": v for k, v in counts_after.items()},
        "validator": validation,
    }


def render_pang(width: int, height: int, safe_local: tuple[int, int, int, int], font_path: Path) -> Image.Image:
    safe_width = safe_local[2] - safe_local[0]
    safe_height = safe_local[3] - safe_local[1]
    font = ImageFont.truetype(str(font_path), 38)
    try:
        font.set_variation_by_name("Regular")
    except (AttributeError, OSError):
        pass
    bbox = font.getbbox(SIMP_PANG)
    temp = Image.new("L", (96, 96), 0)
    ImageDraw.Draw(temp).text((8 - bbox[0], 8 - bbox[1]), SIMP_PANG, font=font, fill=255)
    ink_bbox = temp.getbbox()
    if ink_bbox is None:
        raise ValueError("Rendered 庞 is empty")
    ink = temp.crop(ink_bbox)
    scale = min(1.0, safe_width / ink.width, safe_height / ink.height)
    if scale < 1.0:
        ink = ink.resize(
            (max(1, round(ink.width * scale)), max(1, round(ink.height * scale))),
            Image.Resampling.LANCZOS,
        )
    ink = ink.point(lambda value: 255 if value >= 96 else 0)
    layer = Image.new("L", (width, height), 0)
    left = safe_local[0] + (safe_width - ink.width) // 2
    top = safe_local[3] - ink.height
    layer.paste(ink, (left, top))
    return layer


def build_font(source_path: Path, output_path: Path, preview_path: Path, font_path: Path) -> dict[str, object]:
    source = source_path.read_bytes()
    output = bytearray(source)
    dds_offset = source.index(b"DDS ")
    records = parse_char_records(source)
    map_offset, pairs = parse_unicode_map(source)
    mapping = dict(pairs)
    alias_index = mapping.get(ord(ALIAS))
    ship_index = mapping.get(ord(SHIP))
    if alias_index != EXPECTED_ALIAS_INDEX:
        raise ValueError(f"Unexpected U+8907 index: {alias_index}")
    if ship_index != EXPECTED_SHIP_INDEX:
        raise ValueError(f"Real 船 route is not repaired: {ship_index}")

    x, y, width, height = records[alias_index].rect
    if (x, y, width, height) != EXPECTED_ALIAS_RECT:
        raise ValueError(f"Unexpected alias rectangle: {(x, y, width, height)}")
    safe_local = SAFE_LOCAL
    safe_global = (
        x + safe_local[0], y + safe_local[1], x + safe_local[2], y + safe_local[3]
    )

    atlas = Image.open(io.BytesIO(source[dds_offset:])).convert("RGBA")
    original_alpha = atlas.getchannel("A")
    patched_alpha = original_alpha.copy()
    patched_alpha.paste(0, safe_global)
    layer = render_pang(width, height, safe_local, font_path)
    existing = patched_alpha.crop((x, y, x + width, y + height))
    patched_alpha.paste(ImageChops.lighter(existing, layer), (x, y))
    atlas.putalpha(patched_alpha)

    blocks_w = math.ceil(atlas.width / 4)
    changed_blocks = 0
    allowed_alpha_bytes: set[int] = set()
    for block_y in range(safe_global[1] // 4, math.ceil(safe_global[3] / 4)):
        for block_x in range(safe_global[0] // 4, math.ceil(safe_global[2] / 4)):
            samples = [
                atlas.getpixel((px, py))[3]
                for py in range(block_y * 4, block_y * 4 + 4)
                for px in range(block_x * 4, block_x * 4 + 4)
            ]
            old = [
                original_alpha.getpixel((px, py))
                for py in range(block_y * 4, block_y * 4 + 4)
                for px in range(block_x * 4, block_x * 4 + 4)
            ]
            if samples == old:
                continue
            offset = dds_offset + 128 + (block_y * blocks_w + block_x) * 16
            output[offset : offset + 16] = encode_bc3_white(
                samples, source[offset + 8 : offset + 16]
            )
            allowed_alpha_bytes.update(range(offset, offset + 8))
            changed_blocks += 1

    map_size = len(pairs) * 4 + 4
    if output[:dds_offset] != source[:dds_offset]:
        raise ValueError("FT2 metadata changed")
    if output[map_offset : map_offset + map_size] != source[map_offset : map_offset + map_size]:
        raise ValueError("FT2 Unicode map changed")
    if len(output) != len(source):
        raise ValueError("FT2 size changed")
    changed_positions = [
        position for position, (before, after) in enumerate(zip(source, output)) if before != after
    ]
    if any(position not in allowed_alpha_bytes for position in changed_positions):
        raise ValueError("A byte outside the selected BC3 alpha blocks changed")

    verified = Image.open(io.BytesIO(bytes(output)[dds_offset:])).convert("RGBA")
    delta = ImageChops.difference(original_alpha, verified.getchannel("A"))
    delta_bbox = delta.getbbox()
    if delta_bbox is None:
        raise ValueError("Font patch produced no decoded pixel changes")
    if not (
        safe_global[0] <= delta_bbox[0]
        and safe_global[1] <= delta_bbox[1]
        and delta_bbox[2] <= safe_global[2]
        and delta_bbox[3] <= safe_global[3]
    ):
        raise ValueError(f"Decoded changes escaped alias safe box: {delta_bbox} vs {safe_global}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(output)
    crop = verified.crop((x, y, x + width, y + height))
    glyph_bbox = crop.getchannel("A").getbbox()
    if glyph_bbox is None:
        raise ValueError("Decoded 庞 glyph is empty")
    if not (
        safe_local[0] < glyph_bbox[0]
        and safe_local[1] < glyph_bbox[1]
        and glyph_bbox[2] < safe_local[2]
        and glyph_bbox[3] < safe_local[3]
    ):
        raise ValueError(f"Decoded 庞 glyph lacks a clear safe-box gutter: {glyph_bbox}")
    enlarged = crop.resize((width * 8, height * 8), Image.Resampling.NEAREST)
    preview = Image.new("RGBA", enlarged.size, (28, 28, 28, 255))
    preview.alpha_composite(enlarged)
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    preview.save(preview_path)
    return {
        "source": str(source_path),
        "output": str(output_path),
        "source_sha256": digest(source),
        "output_sha256": digest(bytes(output)),
        "bytes": len(output),
        "metadata_unchanged": True,
        "unicode_map_unchanged": True,
        "ship_index": ship_index,
        "alias_index": alias_index,
        "alias_rect": [x, y, width, height],
        "safe_global": list(safe_global),
        "changed_bc3_blocks": changed_blocks,
        "changed_byte_count": len(changed_positions),
        "decoded_delta_bbox": list(delta_bbox),
        "decoded_glyph_bbox": list(glyph_bbox),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text-source", type=Path, required=True)
    parser.add_argument("--font-source", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--noto", type=Path, default=Path(r"C:\Windows\Fonts\NotoSansSC-VF.ttf"))
    args = parser.parse_args()
    text_output = args.output_root / "stuff/text/text.csv"
    font_output = args.output_root / "ui/font/localisation/font_chinese_nxg.ft2"
    report = {
        "text": build_text(args.text_source, text_output),
        "font": build_font(
            args.font_source,
            font_output,
            args.output_root / "pang-alias-preview.png",
            args.noto,
        ),
    }
    report_path = args.output_root / "pang-alias-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
