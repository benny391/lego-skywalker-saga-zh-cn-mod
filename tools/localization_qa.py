#!/usr/bin/env python3
"""Analyze and validate TSS localization CSV edits.

The validator treats every column except CHINESE TRADITIONAL as immutable and
compares structural tokens in the translated cell as multisets.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path


TARGET_COLUMN = "CHINESE TRADITIONAL"
TOKEN_PATTERNS = {
    "braces": re.compile(r"\{[^{}\r\n]*\}"),
    "printf": re.compile(
        r"%(?:\d+\$)?[-+#0 ']*(?:\d+|\*)?(?:\.(?:\d+|\*))?"
        r"(?:hh|h|ll|l|j|z|t|L)?[diuoxXfFeEgGaAcspn%]"
    ),
    "angle_tags": re.compile(r"<[^<>\r\n]+>"),
    "square_tags": re.compile(r"\[/?[A-Za-z][^\]\r\n]*\]"),
    "double_square_refs": re.compile(r"\[\[[^\]\r\n]+\]\]"),
    "tilde_markup": re.compile(r"~~|~[0-9A-Za-z_:#.+-]+"),
    "escapes": re.compile(r"\\(?:[nrt0\\\"']|x[0-9A-Fa-f]{2}|u[0-9A-Fa-f]{4})"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> tuple[list[str], list[list[str]]]:
    # utf-8-sig accepts a BOM but does not require one. Decoding errors are fatal.
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, strict=True)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError("CSV is empty") from exc
        rows = list(reader)
    bad_widths = [(index + 2, len(row)) for index, row in enumerate(rows) if len(row) != len(header)]
    if bad_widths:
        raise ValueError(f"Rows with wrong column count: {bad_widths[:20]}")
    if TARGET_COLUMN not in header:
        raise ValueError(f"Missing target column: {TARGET_COLUMN}")
    return header, rows


def key_for(header: list[str], row: list[str]) -> tuple[str, str, str]:
    return tuple(row[header.index(name)] for name in ("LABEL", "PLATFORM", "TYPE"))


def token_signature(text: str) -> dict[str, Counter[str]]:
    signature = {name: Counter(pattern.findall(text)) for name, pattern in TOKEN_PATTERNS.items()}
    signature["controls"] = Counter(f"U+{ord(ch):04X}" for ch in text if ord(ch) < 32)
    return signature


def analyze(path: Path) -> dict:
    raw = path.read_bytes()
    header, rows = read_csv(path)
    target_index = header.index(TARGET_COLUMN)
    keys = [key_for(header, row) for row in rows]
    duplicates = [list(key) for key, count in Counter(keys).items() if count > 1]
    values = [row[target_index] for row in rows]
    token_totals: dict[str, int] = Counter()
    for value in values:
        for name, tokens in token_signature(value).items():
            token_totals[name] += sum(tokens.values())
    return {
        "path": str(path),
        "sha256": sha256(path),
        "encoding": "UTF-8" + (" with BOM" if raw.startswith(b"\xef\xbb\xbf") else " without BOM"),
        "newline_bytes": {"CRLF": raw.count(b"\r\n"), "LF": raw.count(b"\n")},
        "columns": len(header),
        "header": header,
        "string_rows": len(rows),
        "unique_composite_keys": len(set(keys)),
        "duplicate_composite_keys": duplicates[:100],
        "target_nonempty": sum(bool(value) for value in values),
        "target_empty": sum(not value for value in values),
        "target_unique_values": len(set(values)),
        "target_codepoints": len(set("".join(values))),
        "structural_token_totals": dict(token_totals),
    }


def compare(before_path: Path, after_path: Path) -> dict:
    before_header, before_rows = read_csv(before_path)
    after_header, after_rows = read_csv(after_path)
    errors: list[dict] = []
    if before_header != after_header:
        errors.append({"kind": "header_changed"})
    if len(before_rows) != len(after_rows):
        errors.append(
            {"kind": "row_count_changed", "before": len(before_rows), "after": len(after_rows)}
        )
    if before_header != after_header:
        return {"valid": False, "errors": errors}

    target_index = before_header.index(TARGET_COLUMN)
    immutable_indexes = [index for index in range(len(before_header)) if index != target_index]
    for row_index, (before, after) in enumerate(zip(before_rows, after_rows), start=2):
        for column_index in immutable_indexes:
            if before[column_index] != after[column_index]:
                errors.append(
                    {
                        "kind": "immutable_field_changed",
                        "row": row_index,
                        "column": before_header[column_index],
                    }
                )
        before_text, after_text = before[target_index], after[target_index]
        if before_text and not after_text:
            errors.append({"kind": "unexpected_empty_target", "row": row_index})
        before_tokens, after_tokens = token_signature(before_text), token_signature(after_text)
        for token_kind in before_tokens:
            if before_tokens[token_kind] != after_tokens[token_kind]:
                errors.append(
                    {
                        "kind": "structural_tokens_changed",
                        "row": row_index,
                        "token_kind": token_kind,
                        "before": dict(before_tokens[token_kind]),
                        "after": dict(after_tokens[token_kind]),
                    }
                )

    result = {
        "valid": not errors,
        "before_sha256": sha256(before_path),
        "after_sha256": sha256(after_path),
        "before_rows": len(before_rows),
        "after_rows": len(after_rows),
        "errors_count": len(errors),
        "errors": errors[:500],
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    analyze_parser = subparsers.add_parser("analyze")
    analyze_parser.add_argument("file", type=Path)
    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("before", type=Path)
    compare_parser.add_argument("after", type=Path)
    args = parser.parse_args()
    result = analyze(args.file) if args.command == "analyze" else compare(args.before, args.after)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == "compare" and not result["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
