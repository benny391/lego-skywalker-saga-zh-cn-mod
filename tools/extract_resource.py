#!/usr/bin/env python3
"""Extract one verified resource from a TT Games DAT without modifying it."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyze_dat_index import parse_archive  # noqa: E402
from repack_oodle_resource import (  # noqa: E402
    decompress_chunk,
    load_oodle,
    read_original_chunks,
)
from repack_zipx_resource import decode_stream  # noqa: E402


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def extract(archive: Path, resource: str, output: Path, oodle_dll: Path | None) -> dict[str, object]:
    metadata = parse_archive(archive)
    matches = [
        item for item in metadata["files"]
        if item["path"].casefold() == resource.casefold()
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one resource match, got {len(matches)}")
    item = matches[0]
    with archive.open("rb") as stream:
        stream.seek(item["offset"])
        stored = stream.read(item["compressed_size"])
    if len(stored) != item["compressed_size"]:
        raise ValueError("Stored resource ended early")

    signature = stored[:4]
    if signature == b"ZIPX":
        raw = decode_stream(stored, item["size"])
        encoding = "ZIPX"
        chunk_count = stored.count(b"ZIPX")
    elif signature == b"OODL":
        if oodle_dll is None or not oodle_dll.is_file():
            raise FileNotFoundError("An Oodle DLL is required to extract this resource")
        dll = load_oodle(oodle_dll)
        chunks = read_original_chunks(archive, item["offset"], item["compressed_size"])
        raw = b"".join(
            decompress_chunk(dll, packed, raw_size)
            for packed, raw_size in chunks
        )
        encoding = "OODL"
        chunk_count = len(chunks)
    else:
        if item["compressed_size"] != item["size"]:
            raise ValueError(f"Unsupported resource signature: {signature!r}")
        raw = stored
        encoding = "stored"
        chunk_count = 1

    if len(raw) != item["size"]:
        raise ValueError(f"Extracted size mismatch: {len(raw)} != {item['size']}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(raw)
    report = {
        "archive": str(archive),
        "resource": item["path"],
        "output": str(output),
        "encoding": encoding,
        "chunk_count": chunk_count,
        "stored_size": item["compressed_size"],
        "raw_size": len(raw),
        "sha256": digest(raw),
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("resource")
    parser.add_argument("output", type=Path)
    parser.add_argument("--oodle-dll", type=Path)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    report = extract(args.archive, args.resource, args.output, args.oodle_dll)
    if args.expected_sha256:
        expected = args.expected_sha256.upper()
        if report["sha256"] != expected:
            args.output.unlink(missing_ok=True)
            raise ValueError(
                f"Extracted SHA-256 is not verified: {report['sha256']} != {expected}"
            )
    if args.report:
        import json

        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    import json

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
