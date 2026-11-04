#!/usr/bin/env python3
"""Minimal MD5 terminal view: percentage, bar and current basename."""

from __future__ import annotations

import argparse
import os
import re
import time
from pathlib import Path


PROGRESS = re.compile(r"^\[MD5\]\s+(\d+)/(\d+)")


def running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def progress(path: Path) -> tuple[int, int]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 0, 1
    for line in reversed(lines):
        match = PROGRESS.match(line)
        if match:
            return int(match.group(1)), int(match.group(2))
    return 0, 1


def current_file(pid: int, previous: str) -> str:
    directory = Path(f"/proc/{pid}/fd")
    try:
        descriptors = list(directory.iterdir())
    except OSError:
        return previous
    for descriptor in reversed(descriptors):
        try:
            target = descriptor.readlink()
        except OSError:
            continue
        value = str(target)
        if "/fm7-" in value and not value.endswith(".log"):
            return target.name
    return previous


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", required=True, type=int)
    parser.add_argument("--log", required=True, type=Path)
    args = parser.parse_args()
    filename = "..."
    while True:
        active = running(args.pid)
        done, total = progress(args.log)
        if not active:
            done = total
        filename = current_file(args.pid, filename)
        percent = min(100.0, 100.0 * done / max(1, total))
        width = 44
        filled = round(width * percent / 100)
        bar = "#" * filled + "-" * (width - filled)
        print(f"\033[2J\033[H{percent:6.1f}%\n[{bar}]\n{filename}", flush=True)
        if not active:
            break
        time.sleep(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
