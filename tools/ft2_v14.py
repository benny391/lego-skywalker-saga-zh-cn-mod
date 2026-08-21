#!/usr/bin/env python3
"""Verified Skywalker Saga FT2 v14 table parser.

The format stores a vector of 28-byte m_chars records followed by m_charIdx
entries.  m_charIdx.m_index directly indexes m_chars.  Earlier project scripts
started each m_chars record four bytes late and then attempted to compensate
with a glyph bias; that mixed fields from adjacent records.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"TNFN"
FORMAT_VERSION = 14
CHAR_COUNT_OFFSET = 47
CHAR_RECORDS_OFFSET = 51
CHAR_RECORD_STRIDE = 28
UNICODE_MAP_MARKER = bytes.fromhex("001a0001002000200021002100220002")


@dataclass(frozen=True)
class GlyphRecord:
    index: int
    u: float
    v: float
    width: float
    height: float
    top: float
    left: float
    advance: float

    @property
    def rect(self) -> tuple[int, int, int, int]:
        values = (self.u, self.v, self.width, self.height)
        if any(abs(value - round(value)) > 0.001 for value in values):
            raise ValueError(f"Non-integral glyph rectangle at index {self.index}: {values}")
        return tuple(round(value) for value in values)  # type: ignore[return-value]


def parse_char_records(data: bytes) -> list[GlyphRecord]:
    if data[8:12] != MAGIC:
        raise ValueError(f"Unexpected FT2 magic: {data[8:12]!r}")
    version = struct.unpack_from(">I", data, 12)[0]
    if version != FORMAT_VERSION:
        raise ValueError(f"Expected FT2 v14, got v{version}")
    count = struct.unpack_from(">I", data, CHAR_COUNT_OFFSET)[0]
    records = []
    for index in range(count):
        fields = struct.unpack_from(">7f", data, CHAR_RECORDS_OFFSET + index * CHAR_RECORD_STRIDE)
        records.append(GlyphRecord(index, *fields))
    return records


def parse_unicode_map(data: bytes) -> tuple[int, list[tuple[int, int]]]:
    offset = data.find(UNICODE_MAP_MARKER)
    if offset < 0:
        raise ValueError("FT2 v14 m_charIdx marker was not found")
    pairs: list[tuple[int, int]] = []
    position = offset
    while position + 4 <= len(data):
        codepoint, index = struct.unpack_from(">HH", data, position)
        if (codepoint, index) == (0xFFFF, 0xFFFF):
            break
        pairs.append((codepoint, index))
        position += 4
    if pairs != sorted(pairs):
        raise ValueError("FT2 m_charIdx is not sorted")
    return offset, pairs


def unicode_to_record(data: bytes) -> dict[int, GlyphRecord]:
    records = parse_char_records(data)
    _offset, pairs = parse_unicode_map(data)
    result = {}
    for codepoint, index in pairs:
        if index >= len(records):
            raise ValueError(f"U+{codepoint:04X} has out-of-range m_index {index}")
        result[codepoint] = records[index]
    return result

