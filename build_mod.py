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
    "stableRuntimeText": {
        "sha256": "9AB6897D2302584A88EDDB2F37D2D98D662D3419A5E982075B47EB084C24DECC"
    },
    "stableReleaseFont": {
        "sha256": "F3D7043BF85203A7957C2BD59CD835E48D3CCFFB170DC6498583D23B2BF047D2"
    },
    "releaseFontBuildReport": {
        "sha256": "D824961496BA1F1DE4743E7ACE5710E0A08C2D4CB4A018794B4FAF3FF3F86C12"
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
        "stableRuntimeText",
        "stableReleaseFont",
        "releaseFontBuildReport",
        "workDirectory",
        "outputDirectory",
    )
    missing = [key for key in required if not raw.get(key)]
    if missing:
        raise ValueError(f"Missing configuration fields: {', '.join(missing)}")
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
        "assignment_count": 3076,
        "unique_full_containment": 3073,
        "ambiguous_or_partial": 3,
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
    if font["changed_bc3_blocks"] != 77 or font["changed_byte_count"] != 314:
        raise ValueError("Final 庞 glyph edit escaped the verified BC3 change set")
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
    parser.add_argument("--clean", action="store_true", help="remove only a previously marked build directory")
    args = parser.parse_args()

    config_path = args.config.resolve()
    config = load_config(config_path)
    config_base = config_path.parent
    version = str(config["version"])
    game = resolve_path(str(config["gameDirectory"]), config_base)
    stable_text = resolve_path(str(config["stableRuntimeText"]), config_base)
    stable_font = resolve_path(str(config["stableReleaseFont"]), config_base)
    build_report = resolve_path(str(config["releaseFontBuildReport"]), config_base)
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
    require_file(noto, "Noto Sans SC font")
    require_file(oodle, "game-supplied Oodle DLL")
    require_file(LICENSE, "Noto Sans CJK license")
    verify_exact(official_game, "official GAME.DAT", VERIFIED["GAME.DAT"]["source"], VERIFIED["GAME.DAT"]["size"])
    verify_exact(official_game6, "official GAME6.DAT", VERIFIED["GAME6.DAT"]["source"], VERIFIED["GAME6.DAT"]["size"])
    verify_exact(stable_text, "stable runtime text", VERIFIED["stableRuntimeText"]["sha256"])
    verify_exact(stable_font, "stable Release font", VERIFIED["stableReleaseFont"]["sha256"])
    verify_exact(build_report, "Release font build report", VERIFIED["releaseFontBuildReport"]["sha256"])
    if args.check_only:
        print("\nAll inputs match the verified v2026.08.22 recipe.")
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
    run_tool(
        "audit_release_geometry_routes.py",
        "--font", stable_font,
        "--build-report", build_report,
        "--output", audit,
    )
    check_audit(audit)
    run_tool(
        "build_release_geometry_index_fix.py",
        "--base", stable_font,
        "--audit", audit,
        "--output-root", index_root,
        "--noto", noto,
    )
    check_index_fix(index_root / "index-fix-report.json")
    run_tool(
        "build_pang_alias_migration.py",
        "--text-source", stable_text,
        "--font-source", index_root / RESOURCE_FONT,
        "--output-root", final_root,
        "--noto", noto,
    )
    check_pang_migration(final_root / "pang-alias-report.json")

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
    target_game_hash = verify_exact(
        mod_game, "generated GAME.DAT", VERIFIED["GAME.DAT"]["target"], VERIFIED["GAME.DAT"]["size"]
    )
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
        "recipe": "verified-v2026.08.22",
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
