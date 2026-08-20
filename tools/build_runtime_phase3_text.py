#!/usr/bin/env python3
"""Encode semantic Simplified text through glyph-backed runtime aliases."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "pydeps"))

from opencc import OpenCC  # noqa: E402

from build_bitmap_simplified_font import CUSTOM_REPLACEMENTS  # noqa: E402
from build_phase2b_font_poc import parse_map  # noqa: E402


SOURCE = ROOT / "phase3/stuff/text/text.csv"
FONT = ROOT / "extracted/ui/font/localisation/font_chinese_nxg.ft2"
OUTPUT = ROOT / "runtime_phase3/stuff/text/text.csv"
REPORT = ROOT / "runtime_phase3/alias-report.json"
TARGET_COLUMN = "CHINESE TRADITIONAL"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def main() -> None:
    source_bytes = SOURCE.read_bytes()
    source_text = source_bytes.decode("utf-8")
    rows = list(csv.reader(io.StringIO(source_text, newline=""), strict=True))
    if not rows or TARGET_COLUMN not in rows[0]:
        raise ValueError("Localization target column is missing")

    # Prove that csv round-tripping itself is byte-identical before edits.
    identity = io.StringIO(newline="")
    csv.writer(identity, quoting=csv.QUOTE_ALL, lineterminator="\n").writerows(rows)
    if identity.getvalue().encode("utf-8") != source_bytes:
        raise ValueError("CSV serialization is not byte-stable")

    mapping = dict(parse_map(FONT.read_bytes())[1])
    converter = OpenCC("tw2sp")
    reverse: dict[int, list[int]] = defaultdict(list)
    reserved = set(CUSTOM_REPLACEMENTS)
    for codepoint in mapping:
        converted = converter.convert(chr(codepoint))
        if len(converted) == 1 and converted != chr(codepoint) and codepoint not in reserved:
            reverse[ord(converted)].append(codepoint)
    for candidates in reverse.values():
        candidates.sort()
    custom_reverse = {target: source for source, target in CUSTOM_REPLACEMENTS.items()}

    target_index = rows[0].index(TARGET_COLUMN)
    alias_by_target: dict[int, int] = {}
    occurrences: Counter[tuple[int, int]] = Counter()
    unresolved: Counter[int] = Counter()
    for row in rows[1:]:
        value = row[target_index]
        encoded = []
        for character in value:
            codepoint = ord(character)
            if codepoint <= 0x20 or codepoint in mapping:
                encoded.append(character)
                continue
            alias = alias_by_target.get(codepoint)
            if alias is None:
                if codepoint in reverse:
                    alias = reverse[codepoint][0]
                elif codepoint in custom_reverse:
                    alias = custom_reverse[codepoint]
                else:
                    unresolved[codepoint] += 1
                    encoded.append(character)
                    continue
                alias_by_target[codepoint] = alias
            encoded.append(chr(alias))
            occurrences[(codepoint, alias)] += 1
        row[target_index] = "".join(encoded)

    if unresolved:
        details = [(f"U+{cp:04X}", chr(cp), count) for cp, count in unresolved.items()]
        raise ValueError(f"Characters without runtime aliases: {details}")

    output_stream = io.StringIO(newline="")
    csv.writer(output_stream, quoting=csv.QUOTE_ALL, lineterminator="\n").writerows(rows)
    output_bytes = output_stream.getvalue().encode("utf-8")
    if len(output_bytes) != len(source_bytes):
        raise ValueError(f"Runtime text size changed: {len(output_bytes)} != {len(source_bytes)}")

    # Every changed character is three-byte CJK -> three-byte CJK, and its
    # alias glyph is configured to display exactly the original semantic char.
    for target, alias in alias_by_target.items():
        if alias in CUSTOM_REPLACEMENTS:
            displayed = CUSTOM_REPLACEMENTS[alias]
        else:
            converted = converter.convert(chr(alias))
            displayed = ord(converted) if len(converted) == 1 else -1
        if displayed != target:
            raise ValueError(
                f"Alias U+{alias:04X} does not display U+{target:04X}"
            )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(output_bytes)
    report = {
        "source": str(SOURCE),
        "output": str(OUTPUT),
        "source_sha256": digest(source_bytes),
        "output_sha256": digest(output_bytes),
        "bytes": len(output_bytes),
        "rows": len(rows) - 1,
        "unique_aliased_characters": len(alias_by_target),
        "aliased_occurrences": sum(occurrences.values()),
        "custom_alias_characters": sum(target in custom_reverse for target in alias_by_target),
        "unresolved": 0,
        "aliases": [
            {
                "semantic": f"U+{target:04X} {chr(target)}",
                "runtime": f"U+{alias:04X} {chr(alias)}",
                "occurrences": occurrences[(target, alias)],
                "custom": alias in CUSTOM_REPLACEMENTS,
            }
            for target, alias in sorted(alias_by_target.items())
        ],
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "source_sha256", "output_sha256", "bytes", "rows",
        "unique_aliased_characters", "aliased_occurrences",
        "custom_alias_characters", "unresolved",
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
