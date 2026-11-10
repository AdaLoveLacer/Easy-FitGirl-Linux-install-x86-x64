#!/usr/bin/env python3
"""Minimal progress view for a running QuickSFV process."""

from __future__ import annotations

import argparse
import os
import re
import time
from pathlib import Path


LINE = re.compile(r"^[0-9a-fA-F]{32}\s+[* ](.+)$")


def running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def open_files(pid: int) -> list[Path]:
    try:
        descriptors = list(Path(f"/proc/{pid}/fd").iterdir())
    except OSError:
        return []
    result = []
    for descriptor in descriptors:
        try:
            target = descriptor.readlink()
        except OSError:
            continue
        if target.is_absolute():
            result.append(target)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", required=True, type=int)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    files = []
    for raw in args.manifest.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        match = LINE.match(raw.strip())
        if match:
            files.append(match.group(1).replace("\\", "/").lstrip("./"))
    positions = {name.casefold(): index for index, name in enumerate(files, 1)}
    current_index = 0
    current_name = "..."

    while True:
        active = running(args.pid)
        for path in open_files(args.pid):
            try:
                relative = path.resolve().relative_to(root).as_posix()
            except (OSError, ValueError):
                continue
            index = positions.get(relative.casefold(), 0)
            if index >= current_index:
                current_index = index
                current_name = path.name
        if not active:
            current_index = len(files)
        percent = 100.0 * current_index / max(1, len(files))
        width = 44
        filled = round(width * percent / 100)
        bar = "#" * filled + "-" * (width - filled)
        print(f"\033[2J\033[H{percent:6.1f}%\n[{bar}]\n{current_name}", flush=True)
        if not active:
            break
        time.sleep(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
