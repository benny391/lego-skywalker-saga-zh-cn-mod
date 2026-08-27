#!/usr/bin/env python3
"""Build the verified Simplified Chinese mod and distributable installer.

This is the repository's single public build entry point.  It intentionally
requires user-supplied, legally extracted inputs and never edits the game
installation in place.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TOOLS = ROOT / "tools"
INSTALLER_TEMPLATE = ROOT / "installer-template"
LICENSE = ROOT / "licenses/Noto-Sans-CJK-OFL-1.1.txt"

RESOURCE_TEXT = r"stuff\text\text.csv"
RESOURCE_FONT = r"ui\font\localisation\font_chinese_nxg.ft2"

VERIFIED = {
    "GAME.DAT": {
        "size": 4_064_897_269,
        "source": "F959070D32437B4DE81B3ABA62D2AF42274CE7687242753591DEC569999AF55D",
        "target": "54514B8F0F978E36F2FB96CE32C54DB791B5543C3CABE27D362B088DDD05006B",
    },
    "GAME6.DAT": {
        "size": 1_643_610_491,
        "source": "1DF529C6532324545581CE6144321991FEEDF046BD9F06F024239518015650CF",
        "target": "224E4A677F7941774D26D5AF62CDEEDE9398F683A7C33BE693608FBD3771DD7E",
    },
    "officialRuntimeText": {
        "size": 37_203_703,
        "sha256": "74FBFD207D21A9D0D141D055CE93DD241F6F81BD8E3033207EF600B1B557B3D3",
    },
    "officialReleaseFont": {
        "size": 13_979_024,
        "sha256": "26E625B240BFB0DF8BB2EFF6557F6C87121E0DA069010B85ED97C18BB7495057",
    },
    "notoSansScVariable": {
        "sha256": "763146584CF0710223441356B4395E279021B0806C196614377A7A0174AE074A"
    },
    "releaseFontStages": {
        "rendered": "E9BDE6B390417FDC0684CFCE1352AC05A33444CD4B27A8F0E4AE9365A8610FB0",
        "dotfix": "4085FE30D148D073F1F834357DED1B25B386D3EDE63F4AE6055A80BB67464575",
        "edgeClean": "511FCD2828C115766F13618ED17C17495C842B09858E74912F197E9B83A7605C",
        "indexFixed": "76C0177657F873000A8C3D542CC09369F2404C633C45F2404CDA0B4DF9A762D7",
        "final": "CD375749016E18CCB30682320606DDC7BB3F714516F09CF9A194920084C0A93B",
    },
    "finalRuntimeText": {
        "sha256": "EBE14CC8139E83FCB0E80909642F4529217F73E6CD93E7AC7026387097C203D0"
    },
}


def sha256(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            result.update(chunk)
    return result.hexdigest().upper()


def resolve_path(value: str, base: Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def load_config(path: Path) -> dict[str, object]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    required = (
        "version",
        "gameDirectory",
        "workDirectory",
        "outputDirectory",
    )
    missing = [key for key in required if not raw.get(key)]
    if missing:
        raise ValueError(f"Missing configuration fields: {', '.join(missing)}")
    mode = str(raw.get("textMode", "import"))
    if mode not in {"import", "generate"}:
        raise ValueError(f"Unsupported textMode: {mode}")
    if mode == "import" and not raw.get("translatedText"):
        raise ValueError("textMode=import requires translatedText")
    return raw


def run_tool(script: str, *arguments: object) -> None:
    command = [sys.executable, str(TOOLS / script), *(str(item) for item in arguments)]
    print(f"\n==> {script}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")


def verify_exact(path: Path, label: str, expected_hash: str, expected_size: int | None = None) -> str:
    require_file(path, label)
    if expected_size is not None and path.stat().st_size != expected_size:
        raise ValueError(
            f"{label} size is not verified: {path.stat().st_size} != {expected_size}"
        )
    actual = sha256(path)
    if actual != expected_hash:
        raise ValueError(f"{label} SHA-256 is not verified: {actual} != {expected_hash}")
    print(f"verified {label}: {actual}")
    return actual


def prepare_work_directory(path: Path, clean: bool) -> None:
    marker = path / ".mod-build-root"
    if path.exists():
        if not clean:
            raise FileExistsError(
                f"Work directory already exists: {path}. Use --clean to rebuild it."
            )
        if not marker.is_file():
            raise ValueError(f"Refusing to clean an unmarked directory: {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True)
    marker.write_text("LEGO Skywalker Saga zh-CN build workspace\n", encoding="utf-8")


def check_audit(path: Path) -> None:
    summary = json.loads(path.read_text(encoding="utf-8"))["summary"]
    expected = {
        "assignment_count": 3077,
        "unique_full_containment": 3071,
        "ambiguous_or_partial": 6,
        "target_record_collisions": 0,
    }
    for key, value in expected.items():
        if summary.get(key) != value:
            raise ValueError(f"Geometry audit invariant failed: {key}={summary.get(key)} != {value}")


def check_index_fix(path: Path) -> None:
    report = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "route_count": 53,
        "changed_byte_count": 65,
        "dds_unchanged": True,
    }
    for key, value in expected.items():
        if report.get(key) != value:
            raise ValueError(f"Index-fix invariant failed: {key}={report.get(key)} != {value}")


def check_pang_migration(path: Path) -> None:
    report = json.loads(path.read_text(encoding="utf-8"))
    font = report["font"]
    if font["ship_index"] != 2403 or font["alias_index"] != 2631:
        raise ValueError("Final 船/庞 glyph routes do not match the verified mapping")
    if font["changed_bc3_blocks"] != 79 or font["changed_byte_count"] != 328:
        raise ValueError("Final 庞 glyph edit escaped the from-scratch Release change set")
    if not font["metadata_unchanged"] or not font["unicode_map_unchanged"]:
        raise ValueError("Final 庞 edit changed FT2 metadata or Unicode routing")
    if not report["text"]["validator"]["valid"]:
        raise ValueError("Final localization structure validation failed")


def write_package_readme(path: Path, version: str) -> None:
    path.write_text(
        f"""LEGO Star Wars: The Skywalker Saga 大陆简体中文 Mod {version}

安装：运行 Install.cmd，选择合法 Steam 游戏目录。
卸载：运行 Uninstall.cmd，或使用安装时生成的备份。

安装器只接受已经验证的官方 GAME.DAT/GAME6.DAT，先校验 SHA-256，
再在临时文件上应用差分补丁；目标哈希正确后才替换游戏资源。

本项目与 TT Games、Warner Bros. Games、Lucasfilm、Disney 或 LEGO Group 无关联。
字体字形来自 Noto Sans CJK，许可证见 licenses 目录。
""",
        encoding="utf-8-sig",
    )


def write_checksums(package: Path) -> None:
    files = sorted(
        item for item in package.rglob("*")
        if item.is_file() and item.name != "SHA256SUMS.txt"
    )
    lines = [
        f"{sha256(item)} *{item.relative_to(package).as_posix().replace('/', chr(92))}"
        for item in files
    ]
    (package / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def make_zip(package: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for item in sorted(package.rglob("*")):
            if item.is_file():
                archive.write(item, item.relative_to(package).as_posix())
    forbidden = {".dat", ".exe", ".dll", ".ft2", ".csv", ".dds"}
    with zipfile.ZipFile(output) as archive:
        leaked = [name for name in archive.namelist() if Path(name).suffix.casefold() in forbidden]
        if leaked:
            raise ValueError(f"Package contains forbidden full game resources: {leaked}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "build-config.json")
    parser.add_argument("--check-only", action="store_true", help="validate all inputs without building")
    parser.add_argument(
        "--font-only",
        action="store_true",
        help="build and audit the Release Font, but never create DAT patches",
    )
    parser.add_argument("--clean", action="store_true", help="remove only a previously marked build directory")
    args = parser.parse_args()

    config_path = args.config.resolve()
    config = load_config(config_path)
    config_base = config_path.parent
    version = str(config["version"])
    text_mode = str(config.get("textMode", "import"))
    game = resolve_path(str(config["gameDirectory"]), config_base)
    translated_text = (
        resolve_path(str(config["translatedText"]), config_base)
        if config.get("translatedText") else None
    )
    work = resolve_path(str(config["workDirectory"]), config_base)
    output_dir = resolve_path(str(config["outputDirectory"]), config_base)
    noto = resolve_path(
        str(config.get("notoFont", r"C:\Windows\Fonts\NotoSansSC-VF.ttf")), config_base
    )
    oodle = resolve_path(str(config.get("oodleDll", game / "oo2core_8_win64.dll")), config_base)
    official_game = resolve_path(
        str(config.get("officialGameDat", game / "GAME.DAT")), config_base
    )
    official_game6 = resolve_path(
        str(config.get("officialGame6Dat", game / "GAME6.DAT")), config_base
    )

    require_file(TOOLS / "audit_release_geometry_routes.py", "geometry audit tool")
    require_file(TOOLS / "build_release_geometry_index_fix.py", "index repair tool")
    require_file(TOOLS / "build_pang_alias_migration.py", "alias migration tool")
    require_file(TOOLS / "repack_zipx_resource.py", "ZIPX repack tool")
    require_file(TOOLS / "repack_oodle_resource.py", "Oodle repack tool")
    require_file(TOOLS / "build_binary_patch.py", "binary patch tool")
    require_file(TOOLS / "extract_resource.py", "resource extraction tool")
    require_file(TOOLS / "build_font_from_official.py", "from-official font builder")
    require_file(TOOLS / "patch_edge_residuals.py", "edge residual repair tool")
    require_file(TOOLS / "patch_all_safe_orphans.py", "orphan cleanup tool")
    require_file(TOOLS / "build_simplified_candidate.py", "from-zero text builder")
    require_file(noto, "Noto Sans SC font")
    require_file(oodle, "game-supplied Oodle DLL")
    require_file(LICENSE, "Noto Sans CJK license")
    verify_exact(official_game, "official GAME.DAT", VERIFIED["GAME.DAT"]["source"], VERIFIED["GAME.DAT"]["size"])
    verify_exact(official_game6, "official GAME6.DAT", VERIFIED["GAME6.DAT"]["source"], VERIFIED["GAME6.DAT"]["size"])
    verify_exact(noto, "Noto Sans SC Variable", VERIFIED["notoSansScVariable"]["sha256"])
    if translated_text is not None:
        require_file(translated_text, "translated text import")
        expected_import_hash = str(config.get("translatedTextSha256", "")).upper()
        if expected_import_hash:
            verify_exact(translated_text, "translated text import", expected_import_hash)
    if args.check_only:
        print(f"\nAll inputs required by textMode={text_mode} are present and verified.")
        return

    zip_path = output_dir / f"lego-skywalker-saga-zh-cn-mod_v{version}.zip"
    build_result = output_dir / f"build-report_v{version}.json"
    if (zip_path.exists() or build_result.exists()) and not args.clean:
        raise FileExistsError(f"Output for version {version} already exists; use --clean to replace it")
    prepare_work_directory(work, args.clean)
    if args.clean:
        zip_path.unlink(missing_ok=True)
        build_result.unlink(missing_ok=True)

    audit = work / "reports/release-index-geometry-audit.json"
    index_root = work / "index-fix"
    final_root = work / "final-resources"
    extracted_text = work / "extracted" / RESOURCE_TEXT
    extracted_font = work / "extracted" / RESOURCE_FONT
    run_tool(
        "extract_resource.py",
        official_game, RESOURCE_TEXT, extracted_text,
        "--expected-sha256", VERIFIED["officialRuntimeText"]["sha256"],
        "--report", work / "reports/official-text-extraction.json",
    )
    run_tool(
        "extract_resource.py",
        official_game6, RESOURCE_FONT, extracted_font,
        "--oodle-dll", oodle,
        "--expected-sha256", VERIFIED["officialReleaseFont"]["sha256"],
        "--report", work / "reports/official-font-extraction.json",
    )

    semantic_text = work / "semantic-text" / RESOURCE_TEXT
    if text_mode == "import":
        assert translated_text is not None
        run_tool("localization_qa.py", "compare", extracted_text, translated_text)
        semantic_text.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(translated_text, semantic_text)
    else:
        glossary = resolve_path(
            str(config.get("glossary", ROOT / "recipe/mainland_glossary.tsv")), config_base
        )
        require_file(glossary, "Mainland terminology glossary")
        run_tool(
            "build_simplified_candidate.py",
            "--source", extracted_text,
            "--glossary", glossary,
            "--output", semantic_text,
            "--report", work / "reports/generated-text.json",
        )
        run_tool("localization_qa.py", "compare", extracted_text, semantic_text)

    rendered_root = work / "font-rendered"
    run_tool(
        "build_font_from_official.py",
        "--official-ft2", extracted_font,
        "--noto", noto,
        "--output-root", rendered_root,
    )
    rendered_font = rendered_root / RESOURCE_FONT
    verify_exact(
        rendered_font, "from-scratch rendered font",
        VERIFIED["releaseFontStages"]["rendered"], VERIFIED["officialReleaseFont"]["size"],
    )
    dotfix_root = work / "font-dotfix"
    run_tool(
        "patch_edge_residuals.py",
        "--source", rendered_font,
        "--output-root", dotfix_root,
        "--expected-source-sha256", VERIFIED["releaseFontStages"]["rendered"],
    )
    dotfix_font = dotfix_root / RESOURCE_FONT
    verify_exact(dotfix_font, "edge-dot-fixed font", VERIFIED["releaseFontStages"]["dotfix"])
    clean_root = work / "font-edge-clean"
    run_tool(
        "patch_all_safe_orphans.py",
        "--source", dotfix_font,
        "--output-root", clean_root,
        "--expected-source-sha256", VERIFIED["releaseFontStages"]["dotfix"],
    )
    font_source = clean_root / RESOURCE_FONT
    verify_exact(font_source, "edge-clean Release atlas", VERIFIED["releaseFontStages"]["edgeClean"])
    report_source = rendered_root / "font-report.json"
    run_tool(
        "audit_release_geometry_routes.py",
        "--font", font_source,
        "--build-report", report_source,
        "--output", audit,
    )
    check_audit(audit)
    run_tool(
        "build_release_geometry_index_fix.py",
        "--base", font_source,
        "--audit", audit,
        "--output-root", index_root,
        "--noto", noto,
    )
    check_index_fix(index_root / "index-fix-report.json")
    verify_exact(
        index_root / RESOURCE_FONT, "index-fixed Release atlas",
        VERIFIED["releaseFontStages"]["indexFixed"],
    )
    run_tool(
        "build_pang_alias_migration.py",
        "--text-source", semantic_text,
        "--font-source", index_root / RESOURCE_FONT,
        "--output-root", final_root,
        "--noto", noto,
    )
    check_pang_migration(final_root / "pang-alias-report.json")
    final_font = final_root / RESOURCE_FONT
    verify_exact(
        final_font, "from-scratch final Release Font",
        VERIFIED["releaseFontStages"]["final"], VERIFIED["officialReleaseFont"]["size"],
    )
    if args.font_only:
        print("\nRelease Font completed from the official FT2; DAT packaging was skipped.")
        return

    archives = work / "archives"
    archives.mkdir(parents=True)
    mod_game = archives / "GAME.DAT"
    mod_game6 = archives / "GAME6.DAT"
    print("\n==> Copying official archives to the isolated build workspace", flush=True)
    shutil.copyfile(official_game, mod_game)
    shutil.copyfile(official_game6, mod_game6)
    run_tool(
        "repack_zipx_resource.py",
        official_game, mod_game, RESOURCE_TEXT, final_root / RESOURCE_TEXT,
    )
    run_tool(
        "repack_oodle_resource.py",
        official_game6, mod_game6, RESOURCE_FONT, final_root / RESOURCE_FONT, oodle,
        "--preserve-chunk-sizes", "--pad-to-allocation",
    )
    if mod_game.stat().st_size != VERIFIED["GAME.DAT"]["size"]:
        raise ValueError("Generated GAME.DAT size changed")
    target_game_hash = sha256(mod_game)
    expected_game_target = str(config.get("expectedTargetGameDatSha256", "")).upper()
    if not expected_game_target and sha256(final_root / RESOURCE_TEXT) == VERIFIED["finalRuntimeText"]["sha256"]:
        expected_game_target = VERIFIED["GAME.DAT"]["target"]
    if expected_game_target and target_game_hash != expected_game_target:
        raise ValueError(f"Generated GAME.DAT hash changed: {target_game_hash} != {expected_game_target}")
    target_game6_hash = verify_exact(
        mod_game6, "generated GAME6.DAT", VERIFIED["GAME6.DAT"]["target"], VERIFIED["GAME6.DAT"]["size"]
    )

    package = work / "package"
    patches = package / "patches"
    reports = work / "reports"
    patches.mkdir(parents=True)
    reports.mkdir(parents=True, exist_ok=True)
    game_patch = patches / "GAME.DAT.gpatch"
    game6_patch = patches / "GAME6.DAT.gpatch"
    game_patch_report = reports / "GAME.DAT.patch-report.json"
    game6_patch_report = reports / "GAME6.DAT.patch-report.json"
    run_tool("build_binary_patch.py", official_game, mod_game, game_patch, "--report", game_patch_report)
    run_tool("build_binary_patch.py", official_game6, mod_game6, game6_patch, "--report", game6_patch_report)

    for name in ("Install.cmd", "Install.ps1", "Uninstall.cmd", "Uninstall.ps1"):
        shutil.copyfile(INSTALLER_TEMPLATE / name, package / name)
    (package / "licenses").mkdir(parents=True)
    shutil.copyfile(LICENSE, package / "licenses" / LICENSE.name)
    write_package_readme(package / "README_简体中文.txt", version)
    patch_report = json.loads(game_patch_report.read_text(encoding="utf-8"))
    patch6_report = json.loads(game6_patch_report.read_text(encoding="utf-8"))
    manifest = {
        "modName": "LEGO Star Wars: The Skywalker Saga - Mainland Simplified Chinese Mod",
        "version": version,
        "gameDirectoryName": "LEGO Star Wars - The Skywalker Saga",
        "gameExecutable": "LEGOSTARWARSSKYWALKERSAGA_DX11.exe",
        "files": [
            {
                "name": "GAME.DAT",
                "size": VERIFIED["GAME.DAT"]["size"],
                "sourceSha256": VERIFIED["GAME.DAT"]["source"],
                "targetSha256": target_game_hash,
                "patch": r"patches\GAME.DAT.gpatch",
                "patchSha256": patch_report["patch_sha256"],
            },
            {
                "name": "GAME6.DAT",
                "size": VERIFIED["GAME6.DAT"]["size"],
                "sourceSha256": VERIFIED["GAME6.DAT"]["source"],
                "targetSha256": target_game6_hash,
                "patch": r"patches\GAME6.DAT.gpatch",
                "patchSha256": patch6_report["patch_sha256"],
            },
        ],
    }
    (package / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_checksums(package)
    make_zip(package, zip_path)
    result = {
        "recipe": "release-font-from-official-v1",
        "textMode": text_mode,
        "semanticTextSha256": sha256(semantic_text),
        "runtimeTextSha256": sha256(final_root / RESOURCE_TEXT),
        "releaseFontSha256": sha256(final_font),
        "version": version,
        "zip": str(zip_path),
        "zip_sha256": sha256(zip_path),
        "zip_size": zip_path.stat().st_size,
        "GAME.DAT": manifest["files"][0],
        "GAME6.DAT": manifest["files"][1],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    build_result.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\nBuild completed successfully:")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
