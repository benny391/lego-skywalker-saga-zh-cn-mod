#!/usr/bin/env python3
"""Read TT Games .DAT indexes without extracting archive payloads.

This implements only the big-endian .CC40TAD index variant observed in the
installed PC build of LEGO Star Wars: The Skywalker Saga.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import struct
from pathlib import Path


def be_u16(data: bytes, offset: int) -> tuple[int, int]:
    return struct.unpack_from(">H", data, offset)[0], offset + 2


def be_i16(data: bytes, offset: int) -> tuple[int, int]:
    return struct.unpack_from(">h", data, offset)[0], offset + 2


def be_u32(data: bytes, offset: int) -> tuple[int, int]:
    return struct.unpack_from(">I", data, offset)[0], offset + 4


def be_i32(data: bytes, offset: int) -> tuple[int, int]:
    return struct.unpack_from(">i", data, offset)[0], offset + 4


def be_u64(data: bytes, offset: int) -> tuple[int, int]:
    return struct.unpack_from(">Q", data, offset)[0], offset + 8


def cstring(data: bytes, offset: int) -> str:
    end = data.index(0, offset)
    return data[offset:end].decode("utf-8")


def fnv1a64_path(path: str) -> int:
    value = 0xCBF29CE484222325
    for byte in path.upper().replace("/", "\\").encode("utf-8"):
        value ^= byte
        value = (value * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return value


def locate_index(file_path: Path) -> tuple[int, int]:
    with file_path.open("rb") as stream:
        header = stream.read(8)
    raw_offset, index_size = struct.unpack("<II", header)
    if raw_offset & 0x80000000:
        index_offset = ((raw_offset ^ 0xFFFFFFFF) << 8) + 0x100
    else:
        index_offset = raw_offset
    return index_offset, index_size


def parse_archive(file_path: Path) -> dict:
    index_offset, index_size = locate_index(file_path)
    with file_path.open("rb") as stream:
        stream.seek(index_offset)
        data = stream.read(index_size)

    offset = 0
    header_size, offset = be_u32(data, offset)
    signature = data[offset : offset + 8]
    offset += 8
    if signature != b".CC40TAD":
        raise ValueError(f"Unsupported index signature: {signature!r}")

    archive_type, offset = be_i32(data, offset)
    version, offset = be_u32(data, offset)
    file_count, offset = be_u32(data, offset)
    name_count, offset = be_u32(data, offset)
    names_size, offset = be_u32(data, offset)
    names_offset = offset
    offset += names_size

    _dummy, offset = be_u32(data, offset)
    folders: dict[int, str] = {0: ""}
    file_names: list[str] = []
    for name_index in range(name_count):
        name_rel, offset = be_u32(data, offset)
        folder_id, offset = be_u16(data, offset)
        if version >= 2:
            _dummy_id, offset = be_u16(data, offset)
        _some_id, offset = be_i16(data, offset)
        file_id, offset = be_u16(data, offset)
        if name_rel == 0xFFFFFFFF:
            continue
        name = cstring(data, names_offset + name_rel)
        parent = folders.get(folder_id, "")
        full_name = f"{parent}\\{name}" if parent else name
        if name_index == name_count - 1:
            file_id = len(file_names)
        if file_id != 0:
            file_names.append(full_name)
        else:
            folders[name_index] = full_name

    record_type, offset = be_i32(data, offset)
    record_count, offset = be_u32(data, offset)
    if record_count != file_count:
        raise ValueError(f"File-count mismatch: {file_count} vs {record_count}")

    records_offset_in_index = offset
    record_stride = 16 if record_type <= -11 else 12
    records: list[dict] = []
    for _ in range(file_count):
        if record_type <= -11:
            raw_file_offset, offset = be_u64(data, offset)
            file_offset = raw_file_offset & 0xFFFFFFFF
        else:
            file_offset, offset = be_u32(data, offset)
        compressed_size, offset = be_u32(data, offset)
        raw_size, offset = be_u32(data, offset)
        packed = bool(raw_size & 0x80000000) if record_type <= -10 else False
        size = raw_size & 0x7FFFFFFF if record_type <= -10 else raw_size
        records.append(
            {
                "offset": file_offset,
                "compressed_size": compressed_size,
                "size": size,
                "packed": packed,
            }
        )

    crc_to_record: dict[int, int] = {}
    if version >= 2 and offset + (file_count * 8) <= len(data):
        for record_index in range(file_count):
            crc, offset = be_u64(data, offset)
            crc_to_record[crc] = record_index

    files: list[dict] = []
    for name in file_names:
        record_index = crc_to_record.get(fnv1a64_path(name))
        item = {"path": name, "record_index": record_index}
        if record_index is not None:
            item.update(records[record_index])
        files.append(item)

    return {
        "archive": str(file_path),
        "index_offset": index_offset,
        "index_size": index_size,
        "header_size": header_size,
        "archive_type": archive_type,
        "version": version,
        "record_type": record_type,
        "records_offset_in_index": records_offset_in_index,
        "record_stride": record_stride,
        "file_count": file_count,
        "name_count": name_count,
        "resolved_name_count": len(file_names),
        "mapped_name_count": sum(f["record_index"] is not None for f in files),
        "files": files,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--match", default="", help="case-insensitive substring")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--extensions", action="store_true")
    args = parser.parse_args()

    result = parse_archive(args.archive)
    if args.extensions:
        counts = Counter(Path(f["path"]).suffix.casefold() for f in result["files"])
        for extension, count in counts.most_common():
            print(f"{count}\t{extension or '<none>'}")
        return
    needle = args.match.casefold()
    selected = [f for f in result["files"] if needle in f["path"].casefold()]
    if args.json:
        output = dict(result)
        output["files"] = selected
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return

    print(
        "\t".join(
            f"{key}={result[key]}"
            for key in (
                "archive_type",
                "version",
                "file_count",
                "name_count",
                "resolved_name_count",
                "mapped_name_count",
            )
        )
    )
    for item in selected:
        print(
            f"{item.get('record_index')}\t{item.get('offset')}\t"
            f"{item.get('compressed_size')}\t{item.get('size')}\t"
            f"{item.get('packed')}\t{item['path']}"
        )


if __name__ == "__main__":
    main()
