# Agent guidance

This repository documents and builds a Simplified Chinese mod for the Steam
version of **LEGO Star Wars: The Skywalker Saga**. Treat game archives, official
localization data, extracted fonts, executables, and the game-supplied Oodle DLL
as user-owned inputs. Never commit or redistribute them.

## Current accepted solution

The accepted font solution is **Release atlas + index-only routing repair**.

- Use the visually stable Release `font_chinese_nxg.ft2` as the font input.
- Preserve the DDS payload byte-for-byte. Its verified format is one
  `DXT5`/BC3 atlas of `3628 x 3824` pixels with no mipmaps.
- Repair only the big-endian `m_charIdx.m_index` fields in the FT2 Unicode map.
- Repack with the original Oodle chunk count, sizes, and boundaries.
- Do not redraw the complete atlas and do not recompress texture chunks.

The stable index-only build changes 53 deterministic routes. The generated FT2
changes 65 bytes, all inside approved two-byte Unicode-map index fields. It
leaves all DDS bytes unchanged and requires only two metadata-containing Oodle
chunks to be recompressed.

## Why 53 routes move

The old Release font builder parsed FT2 v14 geometry four bytes late and also
applied an incorrect three-record bias. For mapped glyph `g`, its drawing
rectangle was effectively assembled from:

```text
x      = records[g].u
y      = records[g - 1].v
width  = records[g - 1].width
height = records[g - 1].height
```

At shelf boundaries this places the rendered glyph in a different physical
record, normally 55-59 indices earlier. `audit_release_geometry_routes.py`
recovers the destination from the Release builder's recorded rendered-pixel
box. A route is accepted only when exactly one correct FT2 record fully contains
that box. This yields 3073 unique routes, zero destination collisions, and 53
routes whose index actually needs changing.

Known examples:

```text
失  824 -> 768
控 1332 -> 1276
維 2290 -> 2234   (display: 维)
義 2346 -> 2290   (display: 义)
運 2906 -> 2851   (display: 运)
頂 3134 -> 3077   (display: 顶)
```

`一`, `二`, and `日` are the three non-unique/partial geometry cases. Leave
their Release mappings unchanged.

## FT2 v14 facts

Use `tools/ft2_v14.py`; do not restore the older parser.

- Header magic: `TNFN`
- Version: `14`
- Character count offset: `47`
- Character records offset: `51`
- Character record stride: `28` bytes (`>7f`)
- `m_charIdx.m_index` directly indexes `m_chars`; there is no glyph bias.
- Unicode-map entries are sorted big-endian `>HH` pairs and terminate with
  `FFFF FFFF`.

## Required build and validation order

1. Produce or select the stable Release FT2 from legally extracted user data.
2. Run `tools/audit_release_geometry_routes.py` against the Release builder's
   `all_han_inplace/font-report.json`.
3. Require these audit invariants:
   - 3076 assignments inspected;
   - 3073 unique full-containment routes;
   - three ambiguous/partial routes;
   - zero target-record collisions.
4. Run `tools/build_release_geometry_index_fix.py`.
5. Require exactly 53 changed routes and only shelf shifts of 55-59 records.
6. Require the DDS SHA-256 before and after to be identical.
7. Require every changed byte to be inside an approved `m_charIdx` index field.
8. Repack with `repack_oodle_resource.py --preserve-chunk-sizes
   --pad-to-allocation` and verify by fully extracting the resource again.
9. Never install while the game process is running. Keep the stable Release
   archive as the immediate rollback file.

## Rejected approaches

Do not use these as the default or release path:

- full-atlas Noto Sans SC redraw;
- per-glyph BC3 texture rewrites for ordinary mapping errors;
- dynamically rearranged Oodle chunk streams;
- visual similarity alone to choose a glyph record;
- the old `GEOMETRY_OFFSET = 111` / `GEOMETRY_GLYPH_BIAS = 3` parser.

These approaches produced wrong glyphs, clipping, intermittent black lines, or
startup failures in testing. The intermittent artifacts could also affect
unchanged characters, so a successful single launch is not sufficient proof.

## Localization safety

For `text.csv` changes, preserve IDs, row count, non-target language columns,
placeholders, format specifiers, tags, resource references, escape sequences,
control characters, and CSV UTF-8 parseability. Run `localization_qa.py` before
packaging.

## Remaining limitation

The final text needs 2956 unique Han characters. The stable font covers 2955 in
Simplified Chinese. The only remaining Traditional glyph is `龐` (42 text
occurrences): 22 in `庞达·巴巴/庞达`, 16 in `庞大`, three in `庞沃卡`, and one in
`庞然大物`.

There is no mapped or already-rendered `庞` glyph in the Release atlas, so this
cannot be fixed by index routing. Keep `龐` unless the user explicitly accepts
either a one-glyph texture edit or non-standard text substitutions. Do not
silently rename proper nouns.

## Repository hygiene

- Never add complete DAT files, FT2/DDS files, official CSV data, EXEs, DLLs,
  generated archives, or binary patches tied to copyrighted inputs.
- Keep source paths configurable; do not commit local absolute paths as public
  defaults unless they are conventional Windows font/game locations and clearly
  documented as examples.
- Stage only files relevant to the requested change.

