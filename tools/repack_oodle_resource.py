#!/usr/bin/env python3
"""Recompress and replace one OODL-chunked resource in a TT Games DAT copy."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_dat_index import parse_archive  # noqa: E402


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def load_oodle(path: Path):
    dll = ctypes.WinDLL(str(path))
    dll.OodleLZ_Compress.argtypes = [
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_longlong,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_longlong,
    ]
    dll.OodleLZ_Compress.restype = ctypes.c_longlong
    dll.OodleLZ_Decompress.argtypes = [
        ctypes.c_void_p,
        ctypes.c_longlong,
        ctypes.c_void_p,
        ctypes.c_longlong,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_longlong,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_longlong,
        ctypes.c_int,
    ]
    dll.OodleLZ_Decompress.restype = ctypes.c_longlong
    return dll


def compress_chunk(dll, raw: bytes, compressor: int, level: int) -> bytes:
    source = ctypes.create_string_buffer(raw)
    destination = ctypes.create_string_buffer(len(raw) + 65536)
    result = dll.OodleLZ_Compress(
        compressor,
        source,
        len(raw),
        destination,
        level,
        None,
        None,
        None,
        None,
        0,
    )
    if result <= 0:
        raise RuntimeError(f"OodleLZ_Compress failed: {result}")
    compressed = destination.raw[:result]

    decoded = ctypes.create_string_buffer(len(raw))
    compressed_buffer = ctypes.create_string_buffer(compressed)
    decoded_size = dll.OodleLZ_Decompress(
        compressed_buffer,
        len(compressed),
        decoded,
        len(raw),
        1,
        0,
        0,
        None,
        0,
        None,
        None,
        None,
        0,
        3,
    )
    if decoded_size != len(raw) or decoded.raw[: len(raw)] != raw:
        raise RuntimeError(
            f"Oodle roundtrip failed: expected {len(raw)}, got {decoded_size}"
        )
    return compressed


def decompress_chunk(dll, compressed: bytes, raw_size: int) -> bytes:
    decoded = ctypes.create_string_buffer(raw_size)
    compressed_buffer = ctypes.create_string_buffer(compressed)
    decoded_size = dll.OodleLZ_Decompress(
        compressed_buffer,
        len(compressed),
        decoded,
        raw_size,
        1,
        0,
        0,
        None,
        0,
        None,
        None,
        None,
        0,
        3,
    )
    if decoded_size != raw_size:
        raise RuntimeError(
            f"Oodle decompression failed: expected {raw_size}, got {decoded_size}"
        )
    return decoded.raw[:raw_size]


def read_original_chunks(
    archive: Path, resource_offset: int, compressed_size: int
) -> list[tuple[bytes, int]]:
    chunks: list[tuple[bytes, int]] = []
    consumed = 0
    with archive.open("rb") as stream:
        stream.seek(resource_offset)
        while consumed < compressed_size:
            header = stream.read(12)
            if len(header) != 12 or header[:4] != b"OODL":
                raise ValueError(f"Invalid OODL header at resource byte {consumed}")
            packed_size, raw_size = struct.unpack_from("<II", header, 4)
            packed = stream.read(packed_size)
            if len(packed) != packed_size:
                raise ValueError("Compressed chunk ended early")
            consumed += 12 + packed_size
            chunks.append((packed, raw_size))
    if consumed != compressed_size:
        raise ValueError(f"Chunk stream size mismatch: {consumed} != {compressed_size}")
    return chunks


def make_stream(
    dll,
    raw: bytes,
    original_chunks: list[tuple[bytes, int]],
    compressor: int,
    level: int,
    preserve_chunk_sizes: bool = False,
) -> tuple[bytes, int]:
    output = bytearray()
    position = 0
    changed_count = 0
    for index, (original_packed, raw_size) in enumerate(original_chunks):
        chunk = raw[position : position + raw_size]
        if len(chunk) != raw_size:
            raise ValueError(f"Resource ended early at chunk {index}")
        original_raw = decompress_chunk(dll, original_packed, raw_size)
        if original_raw == chunk:
            compressed = original_packed
        else:
            compressed = compress_chunk(dll, chunk, compressor, level)
            changed_count += 1
            real_size = len(compressed)
            if preserve_chunk_sizes:
                if real_size > len(original_packed):
                    raise ValueError(
                        f"Changed chunk {index} exceeds its original allocation: "
                        f"{real_size} > {len(original_packed)}"
                    )
                compressed += b"\0" * (len(original_packed) - real_size)
                if decompress_chunk(dll, compressed, raw_size) != chunk:
                    raise RuntimeError(f"Padded chunk {index} failed round-trip")
            print(
                f"changed chunk {index}: {len(original_packed)} -> {real_size} "
                f"stored={len(compressed)}",
                flush=True,
            )
        output.extend(b"OODL")
        output.extend(struct.pack("<II", len(compressed), raw_size))
        output.extend(compressed)
        position += raw_size
    if position != len(raw):
        raise ValueError(f"Resource has {len(raw) - position} trailing bytes")
    return bytes(output), changed_count


def pad_last_chunk(stream: bytes, target_size: int) -> bytes:
    """Pad inside the final Oodle payload so the outer resource size stays fixed."""
    if len(stream) > target_size:
        raise ValueError("Cannot pad a stream that already exceeds the target")
    position = 0
    last_header = -1
    while position < len(stream):
        if stream[position : position + 4] != b"OODL":
            raise ValueError(f"Bad OODL header while padding at {position}")
        packed_size = struct.unpack_from("<I", stream, position + 4)[0]
        last_header = position
        position += 12 + packed_size
    if position != len(stream) or last_header < 0:
        raise ValueError("Invalid OODL stream while padding")
    padding = target_size - len(stream)
    if not padding:
        return stream
    output = bytearray(stream)
    final_packed_size = struct.unpack_from("<I", output, last_header + 4)[0]
    struct.pack_into("<I", output, last_header + 4, final_packed_size + padding)
    output.extend(b"\0" * padding)
    return bytes(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path, help="original archive used for metadata")
    parser.add_argument("target", type=Path, help="archive copy to patch in place")
    parser.add_argument("resource", help="case-insensitive exact archive path")
    parser.add_argument("replacement", type=Path)
    parser.add_argument("oodle_dll", type=Path)
    parser.add_argument("--compressor", type=int, default=13)
    parser.add_argument("--level", type=int, default=9)
    parser.add_argument("--pad-to-allocation", action="store_true")
    parser.add_argument("--preserve-chunk-sizes", action="store_true")
    args = parser.parse_args()

    metadata = parse_archive(args.archive)
    matches = [
        item
        for item in metadata["files"]
        if item["path"].casefold() == args.resource.casefold()
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one matching resource, got {len(matches)}")
    item = matches[0]
    raw = args.replacement.read_bytes()
    if len(raw) != item["size"]:
        raise ValueError(f"Replacement size {len(raw)} != expected {item['size']}")
    if args.archive.resolve() == args.target.resolve():
        raise ValueError("Refusing to patch the original metadata archive")
    if args.target.stat().st_size != args.archive.stat().st_size:
        raise ValueError("Target archive copy has an unexpected size")

    original_chunks = read_original_chunks(
        args.archive, item["offset"], item["compressed_size"]
    )
    print(
        f"resource={item['path']} raw={len(raw)} chunks={len(original_chunks)} "
        f"allocation={item['compressed_size']} sha256={sha256(raw)}"
    )
    stream, changed_count = make_stream(
        load_oodle(args.oodle_dll),
        raw,
        original_chunks,
        args.compressor,
        args.level,
        args.preserve_chunk_sizes,
    )
    print(
        f"compressed={len(stream)} allocation={item['compressed_size']} "
        f"changed_chunks={changed_count}"
    )
    if len(stream) > item["compressed_size"]:
        raise ValueError(
            f"Compressed stream exceeds fixed allocation by "
            f"{len(stream) - item['compressed_size']} bytes"
        )
    if args.pad_to_allocation:
        unpadded_size = len(stream)
        stream = pad_last_chunk(stream, item["compressed_size"])
        # Validate the padded final chunk with the same decoder the game ships.
        position = 0
        last_packed = b""
        last_raw_size = 0
        while position < len(stream):
            packed_size, raw_size = struct.unpack_from("<II", stream, position + 4)
            last_packed = stream[position + 12 : position + 12 + packed_size]
            last_raw_size = raw_size
            position += 12 + packed_size
        decompress_chunk(load_oodle(args.oodle_dll), last_packed, last_raw_size)
        print(f"padded={len(stream) - unpadded_size} final_size={len(stream)}")

    record_size_offset = (
        metadata["index_offset"]
        + metadata["records_offset_in_index"]
        + item["record_index"] * metadata["record_stride"]
        + 8
    )
    with args.target.open("r+b") as stream_file:
        stream_file.seek(item["offset"])
        stream_file.write(stream)
        stream_file.write(b"\0" * (item["compressed_size"] - len(stream)))
        stream_file.seek(record_size_offset)
        stream_file.write(struct.pack(">I", len(stream)))
        stream_file.flush()

    reparsed = parse_archive(args.target)
    verified = next(
        x for x in reparsed["files"] if x["path"].casefold() == args.resource.casefold()
    )
    if verified["compressed_size"] != len(stream):
        raise RuntimeError("Patched archive index did not reparse with the new size")
    print(
        f"patched={args.target} stored_size={len(stream)} "
        f"record_size_offset={record_size_offset}"
    )


if __name__ == "__main__":
    main()
