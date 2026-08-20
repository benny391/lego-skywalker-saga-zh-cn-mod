#!/usr/bin/env python3
"""Audit the Traditional Chinese localization column and its protected syntax."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "extracted/stuff/text/text.csv"
OUTPUT = ROOT / "phase3/localization-audit.json"
LANGUAGE = "CHINESE TRADITIONAL"

TOKEN_PATTERNS = [
    ("square", re.compile(r"\[[^\[\]\r\n]*\]")),
    ("brace", re.compile(r"\{[^{}\r\n]*\}")),
    ("angle", re.compile(r"<[^<>\r\n]*>")),
    ("printf", re.compile(r"%(?:\d+\$)?[-+#0 ]*\d*(?:\.\d+)?[A-Za-z%]")),
    ("escape", re.compile(r"\\(?:[nrt0\\\"']|x[0-9A-Fa-f]{2}|u[0-9A-Fa-f]{4})")),
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def main() -> None:
    raw = SOURCE.read_bytes()
    with SOURCE.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream, strict=True)
        header = next(reader)
        rows = list(reader)
    column = header.index(LANGUAGE)
    values = [row[column] for row in rows]

    token_counts: dict[str, Counter[str]] = {}
    token_samples: dict[str, list[dict[str, object]]] = {}
    for name, pattern in TOKEN_PATTERNS:
        counts: Counter[str] = Counter()
        samples: list[dict[str, object]] = []
        for row_number, (row, value) in enumerate(zip(rows, values), 2):
            found = pattern.findall(value)
            counts.update(found)
            if found and len(samples) < 25:
                samples.append(
                    {
                        "row": row_number,
                        "label": row[0],
                        "tokens": found,
                        "text": value,
                    }
                )
        token_counts[name] = counts
        token_samples[name] = samples

    controls: Counter[str] = Counter()
    for value in values:
        for character in value:
            category = unicodedata.category(character)
            if category.startswith("C") or character in "\r\n\t":
                controls[f"U+{ord(character):04X}"] += 1

    duplicate_keys = Counter(tuple(row[:3]) for row in rows)
    inconsistent_rows = [
        {"row": number, "columns": len(row), "label": row[0] if row else ""}
        for number, row in enumerate(rows, 2)
        if len(row) != len(header)
    ]
    result = {
        "source": str(SOURCE),
        "source_bytes": len(raw),
        "source_sha256": sha256(raw),
        "encoding": "UTF-8 without BOM",
        "columns": header,
        "row_count": len(rows),
        "inconsistent_rows": inconsistent_rows,
        "composite_key_duplicates": [
            {"key": list(key), "count": count}
            for key, count in duplicate_keys.items()
            if count > 1
        ],
        "language": LANGUAGE,
        "nonempty_strings": sum(bool(value) for value in values),
        "empty_strings": sum(not value for value in values),
        "unique_strings": len(set(values)),
        "character_count": sum(len(value) for value in values),
        "unique_codepoints": len(set("".join(values))),
        "control_characters": dict(controls),
        "token_counts": {
            name: {
                "total": sum(counts.values()),
                "unique": len(counts),
                "most_common": counts.most_common(100),
            }
            for name, counts in token_counts.items()
        },
        "token_samples": token_samples,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in (
        "source_bytes", "source_sha256", "row_count", "nonempty_strings",
        "empty_strings", "unique_strings", "character_count", "unique_codepoints",
        "control_characters", "token_counts",
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
