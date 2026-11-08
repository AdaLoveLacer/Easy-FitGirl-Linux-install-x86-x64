"""Discovery and configuration of the Wine used to run the codecs."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from ..models import InstallerError
from ..runtime import RuntimeErrorDetail


def discover_wine(
    *, root: Path, ensure_bundled_wine: Callable[[Path], Path | None],
) -> list[Path]:
    """List usable Wine binaries: override, private runtime, /mnt tools, system and Proton."""
    candidates: list[Path] = []
    configured = os.environ.get("FITGIRL_WINE_BIN")
    if configured:
        selected = Path(configured).expanduser().resolve()
        if not selected.is_file() or not os.access(selected, os.X_OK):
            raise InstallerError(f"override de desenvolvimento FITGIRL_WINE_BIN inválido: {selected}")
        return [selected]
    try:
        bundled = ensure_bundled_wine(root)
    except RuntimeErrorDetail as error:
        raise InstallerError(str(error)) from error
    if bundled is not None:
        return [bundled]
    mnt = Path("/mnt")
    if mnt.is_dir():
        candidates.extend(sorted(mnt.glob("*/Tools/fitgirl-wine/*/bin/wine")))
    system_wine = shutil.which("wine")
    if system_wine:
        candidates.append(Path(system_wine))
    steam_roots = [
        Path.home() / ".steam/root", Path.home() / ".steam/steam",
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "Steam",
        Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
    ]
    for steam in steam_roots:
        for pattern in (
            "compatibilitytools.d/*/files/bin/wine", "compatibilitytools.d/*/dist/bin/wine",
            "steamapps/common/Proton*/files/bin/wine", "steamapps/common/Proton*/dist/bin/wine",
        ):
            candidates.extend(sorted(steam.glob(pattern)))
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen and resolved.is_file() and os.access(resolved, os.X_OK):
            seen.add(resolved)
            unique.append(resolved)
    return unique


def select_codec_runtime(discover_wine: Callable[[], list[Path]]) -> Path:
    """No technical runtime prompt in the normal extraction workflow."""
    candidates = discover_wine()
    for wine in candidates:
        try:
            result = subprocess.run(
                [str(wine), "--version"], text=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=10, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            return wine
    raise InstallerError(
        "nenhum Wine/Proton utilizável foi encontrado. Instale Wine/Proton "
        "compatível ou configure FITGIRL_WINE_BIN para um executável existente"
    )
