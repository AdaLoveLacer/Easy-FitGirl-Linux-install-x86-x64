"""Central host compatibility requirements for the standalone runtime."""

from __future__ import annotations

import ctypes.util
import json
import os
import platform
import shutil
import sys
import tarfile
from pathlib import Path
from typing import Any


MIN_GLIBC = (2, 38)
MIN_PYTHON = (3, 12)
REQUIRED_COMMANDS = (
    "python3", "bash", "tar", "gzip", "awk", "tail", "readlink", "mktemp",
    "grep", "sed", "cat", "cp", "mv", "rm", "mkdir", "tr", "tee",
    "chmod", "dirname", "basename", "env",
)
OPTIONAL_COMMANDS = ("taskset", "nice", "findmnt")


def _version_tuple(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for item in value.split("."):
        digits = "".join(char for char in item if char.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def _distribution() -> dict[str, str]:
    values: dict[str, str] = {}
    path = Path("/etc/os-release")
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            key, separator, value = line.partition("=")
            if separator and key in {"ID", "VERSION_ID", "PRETTY_NAME"}:
                values[key.lower()] = value.strip().strip('"')
    return values


def _wine_candidates() -> list[Path]:
    candidates: list[Path] = []
    configured = os.environ.get("FITGIRL_WINE_BIN")
    if configured:
        candidates.append(Path(configured).expanduser())
    system = shutil.which("wine")
    if system:
        candidates.append(Path(system))
    home = Path.home()
    data_home = Path(os.environ.get("XDG_DATA_HOME", home / ".local/share"))
    steam_roots = [
        home / ".steam/root", home / ".steam/steam", data_home / "Steam",
        home / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
    ]
    for steam in steam_roots:
        for pattern in (
            "compatibilitytools.d/*/files/bin/wine",
            "compatibilitytools.d/*/dist/bin/wine",
            "steamapps/common/Proton*/files/bin/wine",
            "steamapps/common/Proton*/dist/bin/wine",
        ):
            candidates.extend(steam.glob(pattern))
    mnt = Path("/mnt")
    if mnt.is_dir():
        candidates.extend(sorted(mnt.glob("*/Tools/fitgirl-wine/*/bin/wine")))
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            if resolved not in seen and resolved.is_file() and os.access(resolved, os.X_OK):
                seen.add(resolved)
                unique.append(resolved)
        except OSError:
            continue
    return unique


def host_report() -> dict[str, Any]:
    libc_name, libc_version = platform.libc_ver()
    machine = platform.machine().lower()
    python = tuple(sys.version_info[:2])
    libraries = {
        "libstdc++": ctypes.util.find_library("stdc++"),
        "libgcc_s": ctypes.util.find_library("gcc_s"),
    }
    commands = {command: shutil.which(command) for command in REQUIRED_COMMANDS}
    optional_commands = {command: shutil.which(command) for command in OPTIONAL_COMMANDS}
    wine_candidates = _wine_candidates()
    reasons: list[str] = []

    if platform.system() != "Linux":
        reasons.append("o projeto requer Linux")
    if machine not in {"x86_64", "amd64"}:
        reasons.append("o runtime atual requer arquitetura x86-64")
    if libc_name != "glibc" or _version_tuple(libc_version) < MIN_GLIBC:
        reasons.append("é necessária glibc 2.38 ou superior")
    if python < MIN_PYTHON:
        reasons.append("é necessário Python 3.12 ou superior")
    if not hasattr(tarfile, "data_filter"):
        reasons.append("Python precisa oferecer tarfile.data_filter para extração segura")
    for name, path in libraries.items():
        if path is None:
            reasons.append(f"biblioteca de sistema ausente: {name}")
    for name, path in commands.items():
        if path is None:
            reasons.append(f"comando de sistema ausente: {name}")
    if not wine_candidates:
        reasons.append("Wine/Proton ausente; instale-o ou configure FITGIRL_WINE_BIN")

    return {
        "supported": not reasons,
        "distribution": _distribution(),
        "architecture": machine,
        "libc": {"name": libc_name, "version": libc_version, "minimum": "2.38"},
        "python": {"version": platform.python_version(), "minimum": "3.12"},
        "libraries": libraries,
        "commands": commands,
        "optional_commands": optional_commands,
        "wine_runtime": {
            "available": bool(wine_candidates),
            "candidates": [str(path) for path in wine_candidates],
        },
        "empirically_tested_distributions": [
            "Debian 13 (x86-64)",
            "Ubuntu 24.04 LTS (x86-64)",
            "CachyOS rolling (x86-64)",
        ],
        "limitations": [
            "outras distribuições que atendam aos requisitos não têm validação empírica",
            "bibliotecas Wine carregadas dinamicamente e todos os codecs não são verificadas nesta checagem",
        ],
        "issues": reasons,
    }


def compatibility_error(report: dict[str, Any] | None = None) -> str | None:
    current = report or host_report()
    if current["supported"]:
        return None
    distribution = current["distribution"].get("pretty_name", "Linux não identificado")
    detected = (
        f"Ambiente detectado: {distribution}; arquitetura {current['architecture']}; "
        f"{current['libc']['name'] or 'libc'} {current['libc']['version'] or 'desconhecida'}; "
        f"Python {current['python']['version']}.\n"
    )
    return detected + "Requisitos incompatíveis:\n" + "\n".join(
        f"  - {issue}" for issue in current["issues"]
    ) + "\nConsulte docs/ARCHITECTURE.md para os requisitos completos."


def report_json() -> str:
    return json.dumps(host_report(), ensure_ascii=False, indent=2, sort_keys=True)
