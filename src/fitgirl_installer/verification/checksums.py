"""Calculation and checking of file hashes."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable

from ..models import InstallerError


def file_hash(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256(path: Path) -> str:
    return file_hash(path, "sha256")


def md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(16 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_archive(
    step: dict[str, Any], source: Path, state_path: Path, state: dict[str, Any],
    dry_run: bool, *, safe_child: Callable[[Path, str], Path],
    save_state: Callable[[Path, dict[str, Any]], None],
) -> Path:
    """Check a source volume against the plan's MD5, once per size and mtime."""
    archive = safe_child(source, step["archive"])
    if not archive.is_file():
        raise InstallerError(f"volume ausente: {archive}")
    expected_md5 = step.get("md5")
    archive_stat = archive.stat()
    identity = {"size": archive_stat.st_size, "mtime_ns": archive_stat.st_mtime_ns, "md5": expected_md5}
    if expected_md5 and state.setdefault("verified", {}).get(archive.name) != identity:
        if dry_run:
            print(f"[VALIDA] MD5 {archive.name}: {expected_md5}")
        else:
            print(f"[VALIDA] calculando MD5 de {archive.name}...")
            actual_md5 = file_hash(archive, "md5")
            if actual_md5.lower() != expected_md5.lower():
                raise InstallerError(
                    f"MD5 inválido em {archive.name}: esperado {expected_md5}, obtido {actual_md5}"
                )
            state["verified"][archive.name] = identity
            save_state(state_path, state)
    return archive
