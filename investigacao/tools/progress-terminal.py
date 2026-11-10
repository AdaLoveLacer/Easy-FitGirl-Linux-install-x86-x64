#!/usr/bin/env python3
"""Minimal terminal view: global percentage, bar and current basename."""

from __future__ import annotations

import argparse
import os
import re
import time
from pathlib import Path


GLOBAL = re.compile(r"global=\s*([0-9]+(?:\.[0-9]+)?)%")
FILENAME = re.compile(r"^\[FreeArc\] event=filename .*? extra=(.*)$")


def latest(path: Path, pattern: re.Pattern[str], default: str) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return default
    for line in reversed(lines):
        match = pattern.search(line)
        if match:
            return match.group(1)
    return default


def basename(value: str) -> str:
    return re.split(r"[\\/]", value.rstrip("\\/"))[-1] or "..."


def running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--monitor-log", type=Path, required=True)
    parser.add_argument("--extract-log", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()

    while True:
        percent = float(latest(args.monitor_log, GLOBAL, "0"))
        current = basename(latest(args.extract_log, FILENAME, "..."))
        width = 44
        filled = min(width, max(0, round(width * percent / 100)))
        bar = "#" * filled + "-" * (width - filled)
        print(f"\033[2J\033[H{percent:6.1f}%\n[{bar}]\n{current}", flush=True)
        if not running(args.pid):
            break
        time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
