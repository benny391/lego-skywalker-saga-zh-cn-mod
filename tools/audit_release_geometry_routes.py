#!/usr/bin/env python3
"""Recover index-only routes from the exact rectangles used by the Release builder."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from ft2_v14 import parse_char_records, parse_unicode_map


ROOT = Path(__file__).resolve().parent
FONT = ROOT / "ship_alias_fix/ui/font/localisation/font_chinese_nxg.ft2"
BUILD_REPORT = ROOT / "all_han_inplace/font-report.json"
OUTPUT = ROOT / "release_index_geometry_audit.json"


def area(box: tuple[int, int, int, int]) -> int:
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def intersection(
    first: tuple[int, int, int, int], second: tuple[int, int, int, int]
) -> tuple[int, int, int, int]:
    return (
        max(first[0], second[0]),
        max(first[1], second[1]),
        min(first[2], second[2]),
        min(first[3], second[3]),
    )


def main() -> None:
    raw = FONT.read_bytes()
    records = parse_char_records(raw)
    _map_offset, pairs = parse_unicode_map(raw)
    mapping = dict(pairs)
    report = json.loads(BUILD_REPORT.read_text(encoding="utf-8"))
    routes = []
    target_uses: dict[int, list[str]] = defaultdict(list)

    for item in report["assignments"]:
        codepoint = int(item["source"].split(" ", 1)[0][2:], 16)
        old_index = mapping[codepoint]
        if old_index != item["glyph"]:
            raise ValueError(f"Report/map mismatch for U+{codepoint:04X}")
        x, y, width, height = item["rect"]
        rendered = item["rendered_bbox"]
        ink = (
            x + rendered[0],
            y + rendered[1],
            x + rendered[2],
            y + rendered[3],
        )
        ink_area = area(ink)
        candidates = []
        for record in records:
            rx, ry, rw, rh = record.rect
            rect = (rx, ry, rx + rw, ry + rh)
            overlap = area(intersection(ink, rect))
            if not overlap:
                continue
            coverage = overlap / ink_area
            record_area = area(rect)
            waste = (record_area - overlap) / record_area
            candidates.append((coverage, -waste, record.index, rect))
        candidates.sort(reverse=True)
        if not candidates:
            routes.append(
                {
                    "source": item["source"],
                    "display": item["display"],
                    "old_index": old_index,
                    "new_index": None,
                    "builder_rect": item["rect"],
                    "global_rendered_bbox": list(ink),
                    "coverage": 0.0,
                    "full_containment_candidates": 0,
                    "unique_full_containment": False,
                    "status": "no_candidate",
                    "top_candidates": [],
                }
            )
            continue
        best = candidates[0]
        full = [candidate for candidate in candidates if candidate[0] == 1.0]
        unique_full = len(full) == 1
        new_index = full[0][2] if unique_full else best[2]
        target_uses[new_index].append(chr(codepoint))
        routes.append(
            {
                "source": item["source"],
                "display": item["display"],
                "old_index": old_index,
                "new_index": new_index,
                "builder_rect": item["rect"],
                "global_rendered_bbox": list(ink),
                "new_rect": list(records[new_index].rect),
                "coverage": round(best[0], 6),
                "full_containment_candidates": len(full),
                "unique_full_containment": unique_full,
                "status": "unique" if unique_full else "ambiguous_or_partial",
                "top_candidates": [
                    {
                        "index": candidate[2],
                        "rect": list(records[candidate[2]].rect),
                        "coverage": round(candidate[0], 6),
                        "waste": round(-candidate[1], 6),
                    }
                    for candidate in candidates[:4]
                ],
            }
        )

    collisions = {
        str(index): values
        for index, values in target_uses.items()
        if len(values) > 1
    }
    summary = {
        "font": str(FONT),
        "font_sha256": hashlib.sha256(raw).hexdigest().upper(),
        "assignment_count": len(routes),
        "unique_full_containment": sum(
            route["unique_full_containment"] for route in routes
        ),
        "ambiguous_or_partial": sum(
            not route["unique_full_containment"] for route in routes
        ),
        "target_record_collisions": len(collisions),
    }
    result = {"summary": summary, "collisions": collisions, "routes": routes}
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

