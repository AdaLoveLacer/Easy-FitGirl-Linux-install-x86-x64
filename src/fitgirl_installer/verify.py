#!/usr/bin/env python3
"""Verify extracted files against FitGirl's _Redist/fitgirl.md5 manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fitgirl_installer import i18n


LINE = re.compile(r"^([0-9a-fA-F]{32})\s+[* ](.+)$")


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


def md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(16 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    i18n.activate(os.environ.get("FITGIRL_LANGUAGE", "pt"))
    parser = argparse.ArgumentParser(description=__doc__)
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


if __name__ == "__main__":
    raise SystemExit(main())
