#!/usr/bin/env python3
"""Build a gzip-compressed block patch between two same-size large files."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import struct
from pathlib import Path

MAGIC = b"LSWSPAT1"
SCAN_SIZE = 1024 * 1024
BLOCK_SIZE = 4096
MAX_RUN = 16 * 1024 * 1024


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    source_size = args.source.stat().st_size
    target_size = args.target.stat().st_size
    if source_size != target_size:
        raise ValueError(f"Patch requires equal sizes: {source_size} != {target_size}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    changed_blocks = 0
    changed_bytes_stored = 0
    records = 0
    run_start: int | None = None
    run_data = bytearray()

    with args.source.open("rb") as old, args.target.open("rb") as new, gzip.open(
        args.output, "wb", compresslevel=9
    ) as patch:
        patch.write(MAGIC)
        patch.write(struct.pack("<Q", target_size))

        def flush() -> None:
            nonlocal run_start, run_data, records, changed_bytes_stored
            if run_start is None:
                return
            patch.write(struct.pack("<QI", run_start, len(run_data)))
            patch.write(run_data)
            records += 1
            changed_bytes_stored += len(run_data)
            run_start = None
            run_data = bytearray()

        file_offset = 0
        while True:
            old_chunk = old.read(SCAN_SIZE)
            new_chunk = new.read(SCAN_SIZE)
            if not old_chunk and not new_chunk:
                break
            if len(old_chunk) != len(new_chunk):
                raise ValueError("Input lengths diverged while scanning")
            if old_chunk == new_chunk:
                flush()
                file_offset += len(old_chunk)
                continue
            for relative in range(0, len(old_chunk), BLOCK_SIZE):
                old_block = old_chunk[relative : relative + BLOCK_SIZE]
                new_block = new_chunk[relative : relative + BLOCK_SIZE]
                absolute = file_offset + relative
                if old_block != new_block:
                    changed_blocks += 1
                    if (
                        run_start is None
                        or run_start + len(run_data) != absolute
                        or len(run_data) + len(new_block) > MAX_RUN
                    ):
                        flush()
                        run_start = absolute
                    run_data.extend(new_block)
                else:
                    flush()
            file_offset += len(old_chunk)
        flush()
        patch.write(struct.pack("<QI", 0xFFFFFFFFFFFFFFFF, 0))

    report = {
        "source": str(args.source),
        "target": str(args.target),
        "patch": str(args.output),
        "source_size": source_size,
        "target_size": target_size,
        "source_sha256": sha256(args.source),
        "target_sha256": sha256(args.target),
        "patch_sha256": sha256(args.output),
        "patch_size": args.output.stat().st_size,
        "block_size": BLOCK_SIZE,
        "changed_blocks": changed_blocks,
        "records": records,
        "uncompressed_patch_data": changed_bytes_stored,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
