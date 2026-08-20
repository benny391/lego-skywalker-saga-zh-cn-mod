#!/usr/bin/env python3
"""Route semantic 船 through an unused FT2 slot and redraw that slot as 船."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from build_phase2b_font_poc import encode_bc3_white, glyph_geometry, parse_map  # noqa: E402
from localization_qa import compare  # noqa: E402

FONT_SOURCE = ROOT / "surgical_dotfix_all/ui/font/localisation/font_chinese_nxg.ft2"
FONT_REPORT = ROOT / "all_han_inplace/font-report.json"
TEXT_SOURCE = ROOT / "runtime_phase3/stuff/text/text.csv"
OUTPUT_ROOT = ROOT / "ship_alias_fix"
FONT_OUTPUT = OUTPUT_ROOT / "ui/font/localisation/font_chinese_nxg.ft2"
TEXT_OUTPUT = OUTPUT_ROOT / "stuff/text/text.csv"
REPORT_OUTPUT = OUTPUT_ROOT / "ship-alias-report.json"
PREVIEW_OUTPUT = OUTPUT_ROOT / "ship-alias-preview.png"
NOTO = Path(r"C:\Windows\Fonts\NotoSansSC-VF.ttf")

SEMANTIC = "船"
ALIAS = "複"  # U+8907 is mapped by the FT2 but unused in the runtime Chinese column.
TARGET_COLUMN = "CHINESE TRADITIONAL"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def build_text() -> dict[str, object]:
    source_bytes = TEXT_SOURCE.read_bytes()
    rows = list(csv.reader(io.StringIO(source_bytes.decode("utf-8"), newline=""), strict=True))
    target_index = rows[0].index(TARGET_COLUMN)
    before_values = [row[target_index] for row in rows[1:]]
    if any(ALIAS in value for value in before_values):
        raise ValueError(f"Alias {ALIAS} is already used in the runtime Chinese column")
    occurrences = sum(value.count(SEMANTIC) for value in before_values)
    if occurrences <= 0:
        raise ValueError("No 船 occurrences were found")
    for row in rows[1:]:
        row[target_index] = row[target_index].replace(SEMANTIC, ALIAS)

    output_stream = io.StringIO(newline="")
    csv.writer(output_stream, quoting=csv.QUOTE_ALL, lineterminator="\n").writerows(rows)
    output_bytes = output_stream.getvalue().encode("utf-8")
    if len(output_bytes) != len(source_bytes):
        raise ValueError("UTF-8 byte length changed")
    TEXT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    TEXT_OUTPUT.write_bytes(output_bytes)
    validation = compare(TEXT_SOURCE, TEXT_OUTPUT)
    if not validation["valid"]:
        raise ValueError(f"Localization structure validation failed: {validation['errors'][:5]}")
    return {
        "source_sha256": digest(source_bytes),
        "output_sha256": digest(output_bytes),
        "bytes": len(output_bytes),
        "rows": len(rows) - 1,
        "replacements": occurrences,
        "semantic": f"U+{ord(SEMANTIC):04X} {SEMANTIC}",
        "runtime_alias": f"U+{ord(ALIAS):04X} {ALIAS}",
        "validator": validation,
    }


def render_ship(width: int, height: int, safe_bbox: tuple[int, int, int, int]) -> tuple[Image.Image, tuple[int, int, int, int]]:
    safe_width = safe_bbox[2] - safe_bbox[0]
    safe_height = safe_bbox[3] - safe_bbox[1]
    font = ImageFont.truetype(str(NOTO), 38)
    try:
        font.set_variation_by_name("Regular")
    except (AttributeError, OSError):
        pass
    bbox = font.getbbox(SEMANTIC)
    temp = Image.new("L", (96, 96), 0)
    ImageDraw.Draw(temp).text((8 - bbox[0], 8 - bbox[1]), SEMANTIC, font=font, fill=255)
    ink = temp.crop(temp.getbbox())
    scale = min(1.0, safe_width / ink.width, safe_height / ink.height)
    if scale < 1.0:
        ink = ink.resize(
            (max(1, round(ink.width * scale)), max(1, round(ink.height * scale))),
            Image.Resampling.LANCZOS,
        )
    ink = ink.point(lambda value: 255 if value >= 96 else 0)
    layer = Image.new("L", (width, height), 0)
    left = safe_bbox[0] + (safe_width - ink.width) // 2
    top = safe_bbox[3] - ink.height
    layer.paste(ink, (left, top))
    rendered = layer.getbbox()
    if rendered is None:
        raise ValueError("Rendered 船 is empty")
    return layer, rendered


def build_font() -> dict[str, object]:
    source = FONT_SOURCE.read_bytes()
    output = bytearray(source)
    dds_offset = source.index(b"DDS ")
    map_offset, pairs = parse_map(source)
    mapping = dict(pairs)
    if ord(ALIAS) not in mapping or ord(SEMANTIC) not in mapping:
        raise ValueError("Required Unicode mapping is absent")

    assignments = json.loads(FONT_REPORT.read_text(encoding="utf-8"))["assignments"]
    item = next(entry for entry in assignments if entry["source"].startswith(f"U+{ord(ALIAS):04X} "))
    glyph = mapping[ord(ALIAS)]
    if glyph != item["glyph"]:
        raise ValueError("Alias report glyph does not match accepted FT2 mapping")
    x, y, width, height, *_ = glyph_geometry(source, glyph)
    if [x, y, width, height] != item["rect"]:
        raise ValueError("Alias geometry changed")
    safe_local = tuple(item["safe_bbox"])
    safe_global = (x + safe_local[0], y + safe_local[1], x + safe_local[2], y + safe_local[3])

    atlas = Image.open(io.BytesIO(source[dds_offset:])).convert("RGBA")
    original_alpha = atlas.getchannel("A")
    patched_alpha = original_alpha.copy()
    patched_alpha.paste(0, safe_global)
    layer, rendered_local = render_ship(width, height, safe_local)
    rendered_alpha = layer.crop((0, 0, width, height))
    existing = patched_alpha.crop((x, y, x + width, y + height))
    patched_alpha.paste(ImageChops.lighter(existing, rendered_alpha), (x, y))
    atlas.putalpha(patched_alpha)

    blocks_w = math.ceil(atlas.width / 4)
    changed_blocks = 0
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
            output[offset : offset + 16] = encode_bc3_white(samples, source[offset + 8 : offset + 16])
            changed_blocks += 1

    map_size = len(pairs) * 4 + 4
    if output[:dds_offset] != source[:dds_offset]:
        raise ValueError("FT2 metadata changed")
    if output[map_offset : map_offset + map_size] != source[map_offset : map_offset + map_size]:
        raise ValueError("FT2 Unicode map changed")
    if len(output) != len(source):
        raise ValueError("FT2 size changed")
    FONT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    FONT_OUTPUT.write_bytes(output)

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

    preview = Image.new("RGBA", (width * 6 * 2 + 80, height * 6 + 80), (28, 28, 28, 255))
    for index, char in enumerate((SEMANTIC, ALIAS)):
        target_glyph = mapping[ord(char)]
        gx, gy, gw, gh, *_ = glyph_geometry(bytes(output), target_glyph)
        crop = verified.crop((gx, gy, gx + gw, gy + gh)).resize((gw * 6, gh * 6), Image.Resampling.NEAREST)
        preview.alpha_composite(crop, (20 + index * (width * 6 + 40), 40))
    preview.save(PREVIEW_OUTPUT)

    return {
        "source_sha256": digest(source),
        "output_sha256": digest(bytes(output)),
        "bytes": len(output),
        "mapping_unchanged": True,
        "metadata_unchanged": True,
        "alias_glyph": glyph,
        "alias_rect": [x, y, width, height],
        "safe_global": list(safe_global),
        "rendered_local": list(rendered_local),
        "changed_bc3_blocks": changed_blocks,
        "decoded_delta_bbox": list(delta_bbox),
    }


def main() -> None:
    text_report = build_text()
    font_report = build_font()
    report = {"text": text_report, "font": font_report}
    REPORT_OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
