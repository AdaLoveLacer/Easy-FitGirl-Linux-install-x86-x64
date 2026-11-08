"""Durable state of an installation: journal files, resumption and transactions."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from ..models import InstallerError


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    """Write JSON durably: fsync a temporary file, keep the previous one as .bak, then replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if path.is_file():
            backup = path.with_name(f"{path.name}.bak")
            backup_fd, backup_temporary = tempfile.mkstemp(
                prefix=f".{backup.name}.", dir=path.parent
            )
            try:
                with os.fdopen(backup_fd, "wb") as backup_handle:
                    backup_handle.write(path.read_bytes())
                    backup_handle.flush()
                    os.fsync(backup_handle.fileno())
                os.replace(backup_temporary, backup)
            finally:
                try:
                    os.unlink(backup_temporary)
                except FileNotFoundError:
                    pass
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def load_json(path: Path) -> dict[str, Any]:
    """Read a JSON object, reporting unreadable or non-object files as InstallerError."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InstallerError(f"não foi possível ler {path}: {error}") from error
    if not isinstance(value, dict):
        raise InstallerError(f"objeto JSON esperado em {path}")
    return value


def load_state(path: Path) -> dict[str, Any]:
    """Read the journal, falling back to its .bak and preserving the corrupt copy."""
    try:
        return load_json(path)
    except InstallerError as primary_error:
        backup = path.with_name(f"{path.name}.bak")
        if not backup.is_file():
            raise
        try:
            state = load_json(backup)
        except InstallerError:
            raise primary_error
        corrupt = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
        os.replace(path, corrupt)
        atomic_json(path, state)
        print(f"[AVISO] journal inválido preservado em {corrupt}; backup restaurado")
        return state
