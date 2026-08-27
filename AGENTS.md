# Agent guidance

This repository builds a Simplified Chinese mod for the Steam version of
**LEGO Star Wars: The Skywalker Saga**. Game archives, official localization,
extracted FT2 files, executables, and the Oodle DLL are user-owned inputs.
Never commit or redistribute them.

## Production model

`build_mod.py` is the only production orchestrator. The Release Font must be
built from the verified official FT2 plus the pinned Noto Sans SC font. Never
accept `stableReleaseFont`, an extracted generated FT2, or an old font report as
a production input.

Required font stages and SHA-256 values:

```text
official       26E625B240BFB0DF8BB2EFF6557F6C87121E0DA069010B85ED97C18BB7495057
rendered       E9BDE6B390417FDC0684CFCE1352AC05A33444CD4B27A8F0E4AE9365A8610FB0
dotfix         4085FE30D148D073F1F834357DED1B25B386D3EDE63F4AE6055A80BB67464575
edge-clean     511FCD2828C115766F13618ED17C17495C842B09858E74912F197E9B83A7605C
index-fixed    76C0177657F873000A8C3D542CC09369F2404C633C45F2404CDA0B4DF9A762D7
final          CD375749016E18CCB30682320606DDC7BB3F714516F09CF9A194920084C0A93B
```

The recovered renderer intentionally reproduces the tested historical atlas:
Noto Sans SC Regular 40 px, original legacy geometry interpretation,
collision-split official ink footprints, centered proportional scaling,
U+4E01/U+4EAB excluded, and binary threshold 96. This compatibility renderer
is allowed only in `build_font_from_official.py`; structural analysis and route
repair must use `ft2_v14.py`.

After rendering, run `patch_edge_residuals.py`,
`patch_all_safe_orphans.py`, geometry audit, the 53-route index fix, and the
single Pang alias stage in that order. Do not reintroduce the retired ship alias
stage. `船` is native and only `庞` uses U+8907.

The from-scratch geometry report has these invariants: 3077 assignments, 3071
unique full-containment routes, six ambiguous/partial assignments, zero target
collisions. The route repair still changes exactly 53 routes and 65 bytes while
leaving the DDS unchanged.

## Text modes

`textMode=import` accepts a locally supplied mature translation. `textMode=generate`
extracts the official Traditional Chinese CSV and runs deterministic OpenCC plus
the tracked glossary. Both must pass `localization_qa.py` and converge to the
runtime layout `船=726`, `複=42`, `龐=0`, `庞=0`.

Preserve IDs, row count, non-target columns, placeholders, format specifiers,
tags, resource references, escapes, control characters, UTF-8 parseability, and
the exact resource byte length.

## FT2 v14 facts

- Header magic `TNFN`, version 14.
- Character count offset 47; records offset 51; stride 28 (`>7f`).
- Unicode entries are big-endian `>HH` and terminate with `FFFF FFFF`.
- `m_charIdx.m_index` directly indexes `m_chars`.
- Final U+8907 maps to record 2631; `船` maps to record 2403.
- Pang record is `(194,3024,59,54)` and the only writable box is
  `(200,3030)-(248,3073)`.

## Repository hygiene

- Never add complete DAT, FT2/DDS, official CSV, EXE, DLL, or generated archive files.
- Keep local paths configurable and keep private inputs under ignored directories.
- Preserve Oodle chunk count, sizes, and boundaries.
- Never modify the live game installation during a build.
- Stage only files relevant to the requested change.

