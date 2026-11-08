"""Reading and combination of FitGirl MD5 manifests."""

from __future__ import annotations

import re
from pathlib import Path


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
