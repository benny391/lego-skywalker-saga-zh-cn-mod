#!/usr/bin/env python3
"""Build a protected, validated Mainland Simplified Chinese candidate CSV."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "pydeps"))
from opencc import OpenCC  # noqa: E402


SOURCE = ROOT / "extracted/stuff/text/text.csv"
GLOSSARY = ROOT / "mainland_glossary.tsv"
OUTPUT = ROOT / "phase3/stuff/text/text.csv"
REPORT = ROOT / "phase3/candidate-qa.json"
LANGUAGE = "CHINESE TRADITIONAL"

TOKEN_RE = re.compile(
    r"\[\[?[^\[\]\r\n]*\]\]?"
    r"|\{[^{}\r\n]*\}"
    r"|<[^<>\r\n]*>"
    r"|%(?:\d+\$)?[-+#0 ]*\d*(?:\.\d+)?[A-Za-z%]"
    r"|\\(?:[nrt0\\\"']|x[0-9A-Fa-f]{2}|u[0-9A-Fa-f]{4})"
    r"|~(?:~|\d+)"
    r"|[\x1a\uf8ff]"
)
SENTINEL_START = "\ue000"
SENTINEL_END = "\ue001"
CJK_SPACE_CONTEXT = set("，。！？；：、（）《》【】「」『』…—")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def serialize(header: list[str], rows: list[list[str]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def load_glossary(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        entries = list(csv.DictReader(stream, delimiter="\t", strict=True))
    if not entries or set(entries[0]) != {"source", "target", "category", "note"}:
        raise ValueError("Unexpected glossary schema")
    seen: dict[str, str] = {}
    for entry in entries:
        source = entry["source"]
        target = entry["target"]
        if not source or not target:
            raise ValueError("Glossary contains an empty source or target")
        if source in seen and seen[source] != target:
            raise ValueError(f"Conflicting glossary entry: {source!r}")
        seen[source] = target
    # Longest-first replacement prevents a short name from breaking a full name.
    return sorted(entries, key=lambda entry: len(entry["source"]), reverse=True)


def tokens(value: str) -> list[str]:
    return TOKEN_RE.findall(value)


def mask_tokens(value: str) -> tuple[str, list[str]]:
    frozen: list[str] = []

    def replace(match: re.Match[str]) -> str:
        index = len(frozen)
        frozen.append(match.group(0))
        return f"{SENTINEL_START}{index:04X}{SENTINEL_END}"

    return TOKEN_RE.sub(replace, value), frozen


def restore_tokens(value: str, frozen: list[str]) -> str:
    for index, token in enumerate(frozen):
        marker = f"{SENTINEL_START}{index:04X}{SENTINEL_END}"
        if value.count(marker) != 1:
            raise ValueError(f"Protected marker {index} changed or duplicated")
        value = value.replace(marker, token)
    if SENTINEL_START in value or SENTINEL_END in value:
        raise ValueError("Unrestored protected marker")
    return value


def compact_spaces_to_exact_size(
    rows: list[list[str]], language_index: int, bytes_to_remove: int
) -> dict[str, int]:
    """Remove semantically empty ASCII spaces without touching protected tokens.

    UTF-8 ASCII spaces are one byte, so removing exactly the archive byte delta
    restores the official resource size. Prefer spaces adjacent to CJK text and
    punctuation, then spaces immediately following a ``~~`` style terminator.
    """
    remaining = bytes_to_remove
    removed_by_rule: Counter[str] = Counter()

    def is_cjk_context(character: str) -> bool:
        return (
            "\u3400" <= character <= "\u9fff"
            or character in CJK_SPACE_CONTEXT
        )

    for rule in ("cjk_adjacent", "after_style_tag"):
        for row in rows:
            if not remaining:
                break
            value = row[language_index]
            protected = [False] * len(value)
            for match in TOKEN_RE.finditer(value):
                for index in range(match.start(), match.end()):
                    protected[index] = True
            remove: set[int] = set()
            for index, character in enumerate(value):
                if not remaining:
                    break
                if character != " " or protected[index]:
                    continue
                previous = value[index - 1] if index else ""
                following = value[index + 1] if index + 1 < len(value) else ""
                eligible = (
                    (rule == "cjk_adjacent" and (
                        is_cjk_context(previous) or is_cjk_context(following)
                    ))
                    or (rule == "after_style_tag" and value[max(0, index - 2):index] == "~~")
                )
                if eligible:
                    remove.add(index)
                    remaining -= 1
                    removed_by_rule[rule] += 1
            if remove:
                row[language_index] = "".join(
                    character for index, character in enumerate(value)
                    if index not in remove
                )
        if not remaining:
            break
    if remaining:
        raise ValueError(
            f"Could not remove {remaining} of {bytes_to_remove} safe ASCII spaces"
        )
    return dict(removed_by_rule)


def main() -> None:
    source_bytes = SOURCE.read_bytes()
    if source_bytes.startswith(b"\xef\xbb\xbf"):
        raise ValueError("Unexpected UTF-8 BOM")
    with SOURCE.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream, strict=True)
        header = next(reader)
        rows = list(reader)
    if serialize(header, rows) != source_bytes:
        raise ValueError("CSV serializer does not reproduce the official source exactly")
    if any(len(row) != len(header) for row in rows):
        raise ValueError("Inconsistent CSV column count")

    language_index = header.index(LANGUAGE)
    glossary = load_glossary(GLOSSARY)
    converter = OpenCC("tw2sp")
    strict_simplifier = OpenCC("t2s")
    output_rows = [row.copy() for row in rows]
    glossary_hits: Counter[str] = Counter()
    changed_rows = 0
    token_total = 0
    errors: list[dict[str, object]] = []
    samples: list[dict[str, object]] = []

    for row_number, (source_row, output_row) in enumerate(zip(rows, output_rows), 2):
        before = source_row[language_index]
        masked, frozen = mask_tokens(before)
        converted = converter.convert(masked)
        # OpenCC correctly localizes generic 複製 as “拷贝”, but Star Wars
        # cloning terminology must use “克隆”. English alignment makes this
        # distinction without damaging genuine copy/replica UI strings.
        english = source_row[header.index("ENGLISH")].casefold()
        if any(term in english for term in ("clone", "cloning", "cloned", "clones")):
            converted = converted.replace("拷贝", "克隆")
        for post_pass in (False, True):
            for entry in glossary:
                if (entry["category"] == "post") != post_pass:
                    continue
                count = converted.count(entry["source"])
                if count:
                    converted = converted.replace(entry["source"], entry["target"])
                    glossary_hits[entry["source"]] += count
        converted = strict_simplifier.convert(converted)
        after = restore_tokens(converted, frozen)
        output_row[language_index] = after
        token_total += len(frozen)

        row_errors: list[str] = []
        if tokens(before) != tokens(after):
            row_errors.append("protected_tokens_changed")
        if before.count("\n") != after.count("\n"):
            row_errors.append("actual_newlines_changed")
        if not after and before:
            row_errors.append("unexpected_empty_string")
        if "\ufffd" in after:
            row_errors.append("replacement_character_introduced")
        if row_errors:
            errors.append(
                {
                    "row": row_number,
                    "key": source_row[:3],
                    "errors": row_errors,
                    "before": before,
                    "after": after,
                }
            )
        if before != after:
            changed_rows += 1
            if len(samples) < 200:
                samples.append(
                    {
                        "row": row_number,
                        "key": source_row[:3],
                        "before": before,
                        "after": after,
                    }
                )

    if errors:
        raise ValueError(f"Structural validation failed for {len(errors)} rows")
    precompact_bytes = serialize(header, output_rows)
    byte_excess = len(precompact_bytes) - len(source_bytes)
    if byte_excess < 0:
        raise ValueError(
            f"Candidate is {-byte_excess} bytes smaller than the official CSV"
        )
    compaction = compact_spaces_to_exact_size(
        output_rows, language_index, byte_excess
    ) if byte_excess else {}
    output_bytes = serialize(header, output_rows)
    if len(output_bytes) != len(source_bytes):
        raise ValueError(
            f"Exact-size compaction failed: {len(output_bytes)} != {len(source_bytes)}"
        )
    for row_number, (source_row, output_row) in enumerate(zip(rows, output_rows), 2):
        before = source_row[language_index]
        after = output_row[language_index]
        if tokens(before) != tokens(after):
            raise ValueError(
                f"Protected tokens changed during compaction on row {row_number}"
            )
        if before.count("\n") != after.count("\n"):
            raise ValueError(
                f"Newline count changed during compaction on row {row_number}"
            )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(output_bytes)

    # Reparse the emitted artifact rather than trusting only in-memory rows.
    with OUTPUT.open("r", encoding="utf-8", newline="") as stream:
        reparsed = list(csv.reader(stream, strict=True))
    if reparsed[0] != header or reparsed[1:] != output_rows:
        raise ValueError("Emitted CSV did not reparse exactly")
    if any(a[:language_index] + a[language_index + 1 :] != b[:language_index] + b[language_index + 1 :]
           for a, b in zip(rows, output_rows)):
        raise ValueError("A non-Chinese field changed")

    before_values = [row[language_index] for row in rows]
    after_values = [row[language_index] for row in output_rows]
    before_chars = set("".join(before_values))
    after_chars = set("".join(after_values))
    report = {
        "source": str(SOURCE),
        "output": str(OUTPUT),
        "opencc": "tw2sp followed by t2s residual pass / OpenCC 1.1.9",
        "glossary": str(GLOSSARY),
        "source_bytes": len(source_bytes),
        "output_bytes": len(output_bytes),
        "byte_delta_before_space_compaction": byte_excess,
        "space_compaction": compaction,
        "byte_delta": len(output_bytes) - len(source_bytes),
        "source_sha256": sha256(source_bytes),
        "output_sha256": sha256(output_bytes),
        "rows": len(rows),
        "columns": len(header),
        "language_column": LANGUAGE,
        "changed_rows": changed_rows,
        "unchanged_rows": len(rows) - changed_rows,
        "empty_before": sum(not value for value in before_values),
        "empty_after": sum(not value for value in after_values),
        "unique_strings_before": len(set(before_values)),
        "unique_strings_after": len(set(after_values)),
        "characters_before": sum(len(value) for value in before_values),
        "characters_after": sum(len(value) for value in after_values),
        "unique_codepoints_before": len(before_chars),
        "unique_codepoints_after": len(after_chars),
        "added_codepoints": [f"U+{ord(c):04X} {c}" for c in sorted(after_chars - before_chars)],
        "removed_codepoints": [f"U+{ord(c):04X} {c}" for c in sorted(before_chars - after_chars)],
        "protected_token_count": token_total,
        "structural_errors": errors,
        "glossary_hits": [
            {"source": key, "count": count}
            for key, count in glossary_hits.most_common()
        ],
        "samples": samples,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "source_bytes", "output_bytes", "byte_delta", "output_sha256", "rows",
        "changed_rows", "unchanged_rows", "empty_before", "empty_after",
        "characters_before", "characters_after", "unique_codepoints_before",
        "unique_codepoints_after", "protected_token_count", "structural_errors",
    )}, ensure_ascii=False, indent=2))
    print(f"glossary_entries_hit={len(glossary_hits)}/{len(glossary)}")


if __name__ == "__main__":
    main()
