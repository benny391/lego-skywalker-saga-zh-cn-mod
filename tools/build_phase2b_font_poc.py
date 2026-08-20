#!/usr/bin/env python3
"""Build a same-size FT2 v14 font PoC containing the missing glyphs 测 and 试.

For the isolated test only, two one-use Traditional-Chinese glyph slots are
reassigned. The FT2 header, glyph geometry, DDS dimensions, and file length stay
unchanged so the result can be tested with the existing fixed-size archive path.
"""

from __future__ import annotations

import hashlib
import io
import math
import struct
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "extracted/ui/font/localisation/font_chinese_nxg.ft2"
OUTPUT = ROOT / "phase2b/ui/font/localisation/font_chinese_nxg.ft2"
PREVIEW = ROOT / "phase2b/font-preview.png"
FONT_SOURCE = Path(r"C:\Windows\Fonts\NotoSansSC-VF.ttf")

GEOMETRY_OFFSET = 111
GEOMETRY_STRIDE = 28
# Unicode-map glyph IDs include three special glyphs that are not represented
# at the front of the packed geometry array.
GEOMETRY_GLYPH_BIAS = 3
MAP_MARKER = bytes.fromhex("001a0001002000200021002100220002")

# These source characters occur once each in the official Traditional Chinese
# column. Replacing them is acceptable only in this isolated PoC, not a release.
REPLACEMENTS = {
    ord("亨"): ord("测"),
    ord("亭"): ord("试"),
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def parse_map(data: bytes) -> tuple[int, list[tuple[int, int]]]:
    offset = data.find(MAP_MARKER)
    if offset < 0:
        raise ValueError("FT2 v14 Unicode map marker was not found")
    pairs: list[tuple[int, int]] = []
    pos = offset
    while pos + 4 <= len(data):
        codepoint, glyph = struct.unpack_from(">HH", data, pos)
        if codepoint == 0xFFFF and glyph == 0xFFFF:
            break
        pairs.append((codepoint, glyph))
        pos += 4
    if len(pairs) != 3291 or pairs != sorted(pairs):
        raise ValueError("Unexpected FT2 Unicode map count or ordering")
    return offset, pairs


def glyph_geometry(data: bytes, glyph: int) -> tuple[int, int, int, int, float, float, float]:
    geometry_index = glyph - GEOMETRY_GLYPH_BIAS
    if geometry_index < 0:
        raise ValueError(f"Glyph {glyph} has no ordinary geometry record")
    y, width, height, advance, x_offset, cell_width, x = struct.unpack_from(
        ">7f", data, GEOMETRY_OFFSET + geometry_index * GEOMETRY_STRIDE
    )
    ints = (round(x), round(y), round(width), round(height))
    if any(abs(value - round(value)) > 0.001 for value in (x, y, width, height)):
        raise ValueError(f"Non-integral atlas geometry for glyph {glyph}")
    return ints[0], ints[1], ints[2], ints[3], advance, x_offset, cell_width


def alpha_palette(a0: int, a1: int) -> list[int]:
    if a0 > a1:
        return [a0, a1] + [((7 - i) * a0 + i * a1) // 7 for i in range(1, 7)]
    return [a0, a1] + [((5 - i) * a0 + i * a1) // 5 for i in range(1, 5)] + [0, 255]


def encode_bc3_white(alpha: list[int], color_part: bytes | None = None) -> bytes:
    """Encode BC3 alpha while optionally preserving the source color bytes."""
    if len(alpha) != 16:
        raise ValueError("BC3 block must have 16 alpha samples")
    a0, a1 = 255, 0
    palette = alpha_palette(a0, a1)
    bits = 0
    for index, value in enumerate(alpha):
        nearest = min(range(8), key=lambda item: abs(palette[item] - value))
        bits |= nearest << (3 * index)
    alpha_part = bytes((a0, a1)) + bits.to_bytes(6, "little")
    if color_part is None:
        # White RGB565 endpoints and color index 0 for every texel.
        color_part = struct.pack("<HHI", 0xFFFF, 0xFFFF, 0)
    if len(color_part) != 8:
        raise ValueError("BC3 color portion must contain 8 bytes")
    return alpha_part + color_part


def render_glyph(character: str, width: int, height: int) -> Image.Image:
    font = ImageFont.truetype(str(FONT_SOURCE), 50)
    try:
        font.set_variation_by_name("Bold")
    except (AttributeError, OSError):
        pass
    bbox = font.getbbox(character)
    glyph_width = bbox[2] - bbox[0]
    glyph_height = bbox[3] - bbox[1]
    if glyph_width > width - 2 or glyph_height > height - 2:
        raise ValueError(f"Rendered {character} does not fit {width}x{height}: {bbox}")
    alpha = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(alpha)
    left = (width - glyph_width) // 2 - bbox[0]
    top = (height - glyph_height) // 2 - bbox[1]
    draw.text((left, top), character, font=font, fill=255)
    return alpha


def patch_dds_blocks(
    output: bytearray,
    atlas: Image.Image,
    dds_offset: int,
    rect: tuple[int, int, int, int],
) -> None:
    x, y, width, height = rect
    blocks_w = math.ceil(atlas.width / 4)
    for block_y in range(y // 4, math.ceil((y + height) / 4)):
        for block_x in range(x // 4, math.ceil((x + width) / 4)):
            alpha: list[int] = []
            for py in range(block_y * 4, block_y * 4 + 4):
                for px in range(block_x * 4, block_x * 4 + 4):
                    alpha.append(atlas.getpixel((px, py))[3])
            block_offset = dds_offset + 128 + (block_y * blocks_w + block_x) * 16
            block = encode_bc3_white(alpha, bytes(output[block_offset + 8:block_offset + 16]))
            output[block_offset : block_offset + 16] = block


def main() -> None:
    source = SOURCE.read_bytes()
    output = bytearray(source)
    dds_offset = source.find(b"DDS ")
    if dds_offset != struct.unpack_from(">I", source, 0)[0] + 4:
        raise ValueError("Unexpected FT2/DDS boundary")
    map_offset, pairs = parse_map(source)
    mapping = dict(pairs)
    glyph_uses = Counter(mapping.values())

    atlas = Image.open(io.BytesIO(source[dds_offset:])).convert("RGBA")
    if atlas.size != (3628, 3824):
        raise ValueError(f"Unexpected atlas dimensions: {atlas.size}")

    details: list[dict[str, object]] = []
    previews: list[Image.Image] = []
    for old_cp, new_cp in REPLACEMENTS.items():
        if new_cp in mapping:
            raise ValueError(f"Target U+{new_cp:04X} already exists")
        glyph = mapping.pop(old_cp)
        if glyph_uses[glyph] != 1:
            raise ValueError(f"Source glyph {glyph} is shared")
        mapping[new_cp] = glyph
        x, y, width, height, advance, x_offset, cell_width = glyph_geometry(source, glyph)
        rendered = render_glyph(chr(new_cp), width, height)
        atlas.paste(Image.new("RGBA", (width, height), (255, 255, 255, 0)), (x, y))
        atlas.putalpha(atlas.getchannel("A"))
        # Put the new alpha into the slot while keeping white RGB.
        patch = Image.new("RGBA", (width, height), (255, 255, 255, 0))
        patch.putalpha(rendered)
        atlas.paste(patch, (x, y))
        patch_dds_blocks(output, atlas, dds_offset, (x, y, width, height))
        previews.append(patch.resize((width * 4, height * 4)))
        details.append(
            {
                "removed": f"U+{old_cp:04X} {chr(old_cp)}",
                "added": f"U+{new_cp:04X} {chr(new_cp)}",
                "glyph": glyph,
                "rect": (x, y, width, height),
                "advance": advance,
                "x_offset": x_offset,
                "cell_width": cell_width,
            }
        )

    new_pairs = sorted(mapping.items())
    if len(new_pairs) != len(pairs):
        raise ValueError("Unicode map size changed")
    output[map_offset : map_offset + 4 * len(new_pairs)] = b"".join(
        struct.pack(">HH", cp, glyph) for cp, glyph in new_pairs
    )

    if len(output) != len(source):
        raise ValueError("FT2 byte length changed")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(output)

    # Decode the modified DXT5 bytes again; the preview therefore verifies the
    # actual compressed data, not merely the pre-compression render.
    verified_atlas = Image.open(io.BytesIO(bytes(output)[dds_offset:])).convert("RGBA")
    verified: list[Image.Image] = []
    for item in details:
        x, y, width, height = item["rect"]  # type: ignore[misc]
        verified.append(verified_atlas.crop((x, y, x + width, y + height)).resize((width * 4, height * 4)))
    canvas = Image.new("RGBA", (sum(image.width for image in verified), max(image.height for image in verified)))
    cursor = 0
    for image in verified:
        canvas.paste(image, (cursor, 0))
        cursor += image.width
    canvas.save(PREVIEW)

    _, check_pairs = parse_map(bytes(output))
    check_map = dict(check_pairs)
    for cp in REPLACEMENTS.values():
        if cp not in check_map:
            raise ValueError(f"Round-trip map is missing U+{cp:04X}")
    for cp in REPLACEMENTS:
        if cp in check_map:
            raise ValueError(f"Round-trip map still contains removed U+{cp:04X}")

    print(f"source_size={len(source)} output_size={len(output)}")
    print(f"source_sha256={sha256(source)}")
    print(f"output_sha256={sha256(output)}")
    for item in details:
        print(item)


if __name__ == "__main__":
    main()
