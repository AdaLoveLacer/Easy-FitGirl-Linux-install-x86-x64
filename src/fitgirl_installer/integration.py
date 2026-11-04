"""Describe Windows integration artifacts without executing or registering them."""

from __future__ import annotations

import json
import os
from pathlib import Path


REDISTRIBUTABLE_MARKERS = (
    "_redist", "redist", "directx", "dxsetup", "vcredist", "vc_redist",
    "dotnet", "physx",
)
NON_GAME_MARKERS = (
    "unins", "crash", "report", "setup", "launcherhelper", "unitycrashhandler",
    "epicwebhelper",
)


def relative_files(root: Path, suffix: str) -> list[Path]:
    return sorted(
        (path for path in root.rglob("*") if path.is_file() and path.suffix.casefold() == suffix),
        key=lambda path: path.relative_to(root).as_posix().casefold(),
    )


def integration_report(target: Path) -> dict:
    executables = relative_files(target, ".exe")

    def relative(path: Path) -> str:
        return path.relative_to(target).as_posix()

    redistributables = [
        path for path in executables
        if any(marker in relative(path).casefold() for marker in REDISTRIBUTABLE_MARKERS)
    ]
    game_candidates = [
        path for path in executables
        if path not in redistributables
        and not any(marker in path.name.casefold() for marker in NON_GAME_MARKERS)
    ]
    game_candidates.sort(key=lambda path: (
        len(path.relative_to(target).parts),
        -path.stat().st_size,
        relative(path).casefold(),
    ))
    registry = relative_files(target, ".reg")
    return {
        "schema": 1,
        "target": str(target.resolve()),
        "policy": {
            "setup_exe": "never_execute",
            "redistributables": "preserve_but_never_execute",
            "registry": "inventory_only_never_import",
            "shortcuts": "not_created_without_validated_game_runner",
            "private_wine": "codec_abi_only_never_game_runner",
        },
        "game_executable_candidates": [relative(path) for path in game_candidates],
        "redistributables": [relative(path) for path in redistributables],
        "registry_files": [relative(path) for path in registry],
    }


def write_integration_report(target: Path, destination: Path) -> dict:
    report = integration_report(target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return report
