#!/usr/bin/env python3
"""Replace a ZIPX/RC4 chunked resource in-place while keeping its allocation fixed."""

from __future__ import annotations

import argparse
import hashlib
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_dat_index import parse_archive  # noqa: E402


CHUNK_SIZE = 32768


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def rc4(data: bytes, key: bytes) -> bytes:
    state = list(range(256))
    j = 0
    for i in range(256):
        j = (j + state[i] + key[i % len(key)]) & 0xFF
        state[i], state[j] = state[j], state[i]
    output = bytearray()
    i = j = 0
    for value in data:
        i = (i + 1) & 0xFF
        j = (j + state[i]) & 0xFF
        state[i], state[j] = state[j], state[i]
        output.append(value ^ state[(state[i] + state[j]) & 0xFF])
    return bytes(output)


def raw_deflate(data: bytes) -> bytes:
    compressor = zlib.compressobj(level=9, wbits=-15)
    return compressor.compress(data) + compressor.flush()


def build_stream(
    raw: bytes, allocation: int, *, compact: bool = False
) -> tuple[bytes, dict[str, int]]:
    chunks = [raw[pos : pos + CHUNK_SIZE] for pos in range(0, len(raw), CHUNK_SIZE)]
    if not chunks:
        chunks = [b""]
    uncompressed_storage = len(raw) + 12 * len(chunks)
    saving_needed = max(0, uncompressed_storage - allocation)
    compressed_index = -1
    desired_packed_size = 0
    compressed_payload = b""
    if saving_needed:
        for index, chunk in enumerate(chunks):
            desired = len(chunk) - saving_needed
            if desired <= 0:
                continue
            candidate = raw_deflate(chunk)
            if len(candidate) <= desired:
                compressed_index = index
                desired_packed_size = len(candidate) if compact else desired
                compressed_payload = (
                    candidate if compact
                    else candidate + b"\0" * (desired - len(candidate))
                )
                break
        if compressed_index < 0:
            raise ValueError(
                f"No single chunk can save the required {saving_needed} bytes"
            )

    output = bytearray()
    for index, chunk in enumerate(chunks):
        if index == compressed_index:
            packed = compressed_payload
        else:
            packed = chunk
        packed_size = len(packed)
        encrypted = rc4(packed, struct.pack("<I", packed_size))
        output.extend(b"ZIPX")
        output.extend(struct.pack("<II", packed_size, len(chunk)))
        output.extend(encrypted)
    if len(output) > allocation:
        raise ValueError(f"ZIPX stream exceeds allocation by {len(output) - allocation}")
    if len(output) < allocation and not compact:
        raise ValueError(
            "ZIPX stream is smaller than allocation; expected exact one-chunk padding"
        )
    return bytes(output), {
        "chunks": len(chunks),
        "uncompressed_storage": uncompressed_storage,
        "saving_needed": saving_needed,
        "compressed_chunk": compressed_index,
        "compressed_deflate_bytes": (
            len(compressed_payload.rstrip(b"\0")) if compressed_index >= 0 else 0
        ),
        "compressed_chunk_stored_bytes": desired_packed_size,
    }


def decode_stream(stream: bytes, expected_raw_size: int) -> bytes:
    output = bytearray()
    position = 0
    while position < len(stream) and len(output) < expected_raw_size:
        if stream[position : position + 4] != b"ZIPX":
            raise ValueError(f"Invalid ZIPX signature at {position}")
        packed_size, raw_size = struct.unpack_from("<II", stream, position + 4)
        start = position + 12
        encrypted = stream[start : start + packed_size]
        if len(encrypted) != packed_size:
            raise ValueError("ZIPX payload ended early")
        packed = rc4(encrypted, struct.pack("<I", packed_size))
        if packed_size == raw_size:
            chunk = packed
        else:
            chunk = zlib.decompress(packed, wbits=-15)
        if len(chunk) != raw_size:
            raise ValueError(f"ZIPX raw-size mismatch: {len(chunk)} != {raw_size}")
        output.extend(chunk)
        position = start + packed_size
    if position != len(stream) or len(output) != expected_raw_size:
        raise ValueError(
            f"ZIPX totals mismatch: stored {position}/{len(stream)}, "
            f"raw {len(output)}/{expected_raw_size}"
        )
    return bytes(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path, help="official archive used for metadata")
    parser.add_argument("target", type=Path, help="same-size archive copy to patch")
    parser.add_argument("resource", help="case-insensitive exact archive path")
    parser.add_argument("replacement", type=Path)
    parser.add_argument(
        "--compact",
        action="store_true",
        help=(
            "store the real deflate length, shrink the indexed compressed size, "
            "and leave the remaining original allocation as an unused gap"
        ),
    )
    args = parser.parse_args()

    metadata = parse_archive(args.archive)
    matches = [
        item for item in metadata["files"]
        if item["path"].casefold() == args.resource.casefold()
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one resource match, got {len(matches)}")
    item = matches[0]
    if args.archive.resolve() == args.target.resolve():
        raise ValueError("Refusing to patch the official metadata archive")
    if args.archive.stat().st_size != args.target.stat().st_size:
        raise ValueError("Target archive copy has an unexpected size")
    raw = args.replacement.read_bytes()
    original_allocation = item["compressed_size"]
    packed, details = build_stream(
        raw, original_allocation, compact=args.compact
    )
    if decode_stream(packed, len(raw)) != raw:
        raise ValueError("ZIPX in-memory roundtrip failed")

    record_offset = (
        metadata["index_offset"]
        + metadata["records_offset_in_index"]
        + item["record_index"] * metadata["record_stride"]
    )
    compressed_size_offset = record_offset + 8
    raw_size_offset = record_offset + 12
    with args.target.open("r+b") as stream:
        stream.seek(item["offset"])
        stream.write(packed)
        if len(packed) < original_allocation:
            stream.write(b"\0" * (original_allocation - len(packed)))
        stream.seek(compressed_size_offset)
        stream.write(struct.pack(">I", len(packed)))
        stream.seek(raw_size_offset)
        stream.write(struct.pack(">I", len(raw)))
        stream.flush()

    reparsed = parse_archive(args.target)
    verified = next(
        value for value in reparsed["files"]
        if value["path"].casefold() == args.resource.casefold()
    )
    if verified["compressed_size"] != len(packed):
        raise ValueError("Patched compressed size did not reparse correctly")
    if verified["size"] != len(raw):
        raise ValueError("Patched raw size did not reparse correctly")
    print(
        f"resource={item['path']} raw={len(raw)} stored={len(packed)} "
        f"original_allocation={original_allocation} "
        f"sha256={sha256(raw)}"
    )
    for key, value in details.items():
        print(f"{key}={value}")
    print(
        f"patched={args.target} compressed_size_offset={compressed_size_offset} "
        f"raw_size_offset={raw_size_offset}"
    )


if __name__ == "__main__":
    main()
