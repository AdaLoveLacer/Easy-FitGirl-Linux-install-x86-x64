"""Calculation and checking of file hashes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from .. import translations
from ..models import InstallerError
from .manifests import parse_manifest


VERIFY_DESCRIPTION = "Verify extracted files against FitGirl's _Redist/fitgirl.md5 manifest."


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


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main() -> int:
    translations.activate(os.environ.get("FITGIRL_LANGUAGE", "pt"))
    parser = argparse.ArgumentParser(description=VERIFY_DESCRIPTION)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--inventory-only", action="store_true", help="somente contar presentes e ausentes")
    parser.add_argument("--present-only", action="store_true", help="ausentes não tornam o comando uma falha")
    args = parser.parse_args()

    root = args.root.resolve()
    rows = parse_manifest(args.manifest)
    state_path = args.state or root / ".fitgirl-verify-state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    else:
        state = {"version": 1, "manifest": str(args.manifest.resolve()), "files": {}}
    if state.get("manifest") != str(args.manifest.resolve()):
        raise SystemExit("[ERRO] o estado pertence a outro manifesto")

    summary = {"total": len(rows), "present": 0, "ok": 0, "mismatch": 0, "missing": 0, "bytes_hashed": 0}
    started = time.time()
    for index, (expected, relative) in enumerate(rows, 1):
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            raise SystemExit(f"[ERRO] caminho escapa da raiz: {relative}")
        if not path.is_file():
            summary["missing"] += 1
            continue
        summary["present"] += 1
        stat = path.stat()
        identity = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "expected": expected}
        cached = state["files"].get(relative)
        if args.inventory_only:
            continue
        if cached and all(cached.get(key) == value for key, value in identity.items()):
            actual = cached["actual"]
        else:
            actual = md5(path)
            state["files"][relative] = {**identity, "actual": actual}
            summary["bytes_hashed"] += stat.st_size
        if actual == expected:
            summary["ok"] += 1
        else:
            summary["mismatch"] += 1
            print(f"[FALHOU] {relative}: esperado={expected} obtido={actual}", flush=True)
        if len(rows) <= 100 or index % 100 == 0:
            atomic_json(state_path, state)
            print(
                f"[MD5] {index}/{len(rows)} ok={summary['ok']} "
                f"falhas={summary['mismatch']} ausentes={summary['missing']}",
                flush=True,
            )
    if not args.inventory_only:
        atomic_json(state_path, state)
    summary["elapsed_seconds"] = round(time.time() - started, 3)
    print("[RESUMO] " + json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
    if summary["mismatch"]:
        return 1
    if summary["missing"] and not args.present_only:
        return 2
    return 0
