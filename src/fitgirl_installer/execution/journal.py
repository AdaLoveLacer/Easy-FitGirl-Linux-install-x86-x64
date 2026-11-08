"""Durable state of an installation: journal files, resumption and transactions."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from ..models import InstallerError


STATE_VERSION = 1


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


def initial_state(setup_hash: str, plan_hash: str, source: Path, target: Path, components: set[str], args: Any) -> dict[str, Any]:
    """Fresh journal for this plan, components and resource settings."""
    settings = {
        "srep_memory": args.srep_memory, "cpus": args.cpus, "nice": args.nice,
        "limit_2gb": bool(getattr(args, "limit_2gb", False)),
    }
    if args.bzip3_threads is not None:
        settings["bzip3_threads"] = args.bzip3_threads
    if args.memory_high is not None:
        settings["memory_high"] = args.memory_high
    if args.memory_max is not None:
        settings["memory_max"] = args.memory_max
    return {
        "version": STATE_VERSION,
        "setup_sha256": setup_hash,
        "manifest_sha256": plan_hash,
        "source": str(source),
        "target": str(target),
        "components": sorted(components),
        "settings": settings,
        "completed": {},
        "verified": {},
        "active": None,
        "created_at": time.time(),
    }


def validate_state(state: dict[str, Any], expected: dict[str, Any]) -> None:
    """Refuse a journal written for another plan, source, target or settings."""
    immutable = ("version", "setup_sha256", "manifest_sha256", "source", "target", "components", "settings")
    differences = [key for key in immutable if state.get(key) != expected.get(key)]
    if differences:
        raise InstallerError(
            "o journal pertence a outro plano/opções (" + ", ".join(differences) + "); "
            "use o mesmo comando ou um scratch diferente"
        )


def resume_or_start(state_path: Path, expected: dict[str, Any]) -> dict[str, Any]:
    """Continue a compatible journal, refusing to run beside a still-live step."""
    if state_path.exists():
        state = load_state(state_path)
        validate_state(state, expected)
        if state.get("active"):
            pgid = int(state["active"].get("pgid", 0))
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                print("[AVISO] etapa anterior não está mais ativa; ela será repetida desde o início")
            else:
                raise InstallerError(
                    f"a etapa anterior ainda está ativa no grupo {pgid}; não iniciarei uma cópia concorrente"
                )
            state["active"] = None
    else:
        state = expected
    return state
