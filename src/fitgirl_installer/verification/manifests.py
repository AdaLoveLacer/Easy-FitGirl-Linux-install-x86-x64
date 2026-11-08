"""Reading and combination of FitGirl MD5 manifests."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Callable, Collection

from ..models import InstallerError


LINE = re.compile(r"^([0-9a-fA-F]{32})\s+[* ](.+)$")


def parse_manifest(path: Path) -> list[tuple[str, str]]:
    rows = []
    for number, raw in enumerate(path.read_text(encoding="utf-8-sig", errors="replace").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        match = LINE.match(line)
        if not match:
            raise ValueError(f"linha MD5 inválida {number}: {raw!r}")
        relative = match.group(2).replace("\\", "/")
        while relative.startswith("../"):
            relative = relative[3:]
        rows.append((match.group(1).lower(), relative))
    return rows


def manifest_parts(
    source: Path, target: Path, components: Collection[str], *,
    safe_child: Callable[[Path, str], Path],
) -> list[Path]:
    """List the base manifest and the addons to combine, refusing incomplete or conflicting ones.

    An addon whose files are all absent and whose component was not chosen
    is inactive and left out; one with only part of its files is refused.
    """
    base = source / "fitgirl.md5"
    if not base.is_file():
        raise InstallerError(f"manifesto base ausente: {base}")
    parts = [base]
    seen = dict((relative.casefold(), digest) for digest, relative in parse_manifest(base))
    for addon in sorted(source.glob("*.addon"), key=lambda p: p.name.casefold()):
        rows = parse_manifest(addon)
        present = [safe_child(target, relative).is_file() for _, relative in rows]
        if rows and not any(present) and addon.stem not in components:
            print(f"[MANIFESTOS] addon inativo: {addon.name}")
            continue
        if not all(present):
            raise InstallerError(f"addon incompleto: {addon.name}")
        for digest, relative in rows:
            previous = seen.setdefault(relative.casefold(), digest)
            if previous != digest:
                raise InstallerError(f"hashes conflitantes nos manifestos: {relative}")
        parts.append(addon)
    return parts


def write_combined_manifest(parts: list[Path], destination: Path) -> None:
    """Write the parts as destination/fitgirl.md5 atomically, validating the result first."""
    content = b"".join(p.read_bytes().rstrip(b"\r\n") + b"\r\n" for p in parts)
    temporary = destination / f".fitgirl.md5.merge-{os.getpid()}"
    try:
        with temporary.open("wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        parse_manifest(temporary)
        os.replace(temporary, destination / "fitgirl.md5")
    finally:
        temporary.unlink(missing_ok=True)
