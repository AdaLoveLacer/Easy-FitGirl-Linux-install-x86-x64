"""Read setup metadata from an extracted ISS script."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def section(lines: list[str], name: str) -> list[str]:
    marker = f"[{name.lower()}]"
    start = next(
        (index + 1 for index, line in enumerate(lines) if line.strip().lower() == marker),
        None,
    )
    if start is None:
        return []
    end = next(
        (index for index in range(start, len(lines)) if lines[index].lstrip().startswith("[")),
        len(lines),
    )
    return lines[start:end]


def field(line: str, name: str) -> str | None:
    match = re.search(rf'(?:^|;)\s*{re.escape(name)}:\s*"([^"]*)"', line, re.IGNORECASE)
    return match.group(1) if match else None


def components_from_iss(path: Path) -> dict[str, dict[str, Any]]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    components: dict[str, dict[str, Any]] = {}
    for line in section(lines, "Components"):
        name = field(line, "Name")
        if not name:
            continue
        description = field(line, "Description") or name
        types = set((field(line, "Types") or "").split())
        item = components.setdefault(
            name,
            {"description": description, "default": bool(types & {"full", "custom"})},
        )
        if description.isascii() or not item["description"].isascii():
            item["description"] = description
        item["default"] = item["default"] or bool(types & {"full", "custom"})
    return components


def disk_space_from_iss(path: Path) -> dict[str, Any] | None:
    """Read the installer's extra-space declaration, not an exact output size."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    values = []
    for line in section(lines, "Setup"):
        if not re.match(r"\s*ExtraDiskSpaceRequired\s*=", line, re.I):
            continue
        match = re.fullmatch(r"\s*ExtraDiskSpaceRequired\s*=\s*(\d+)\s*", line, re.I)
        if not match:
            return None
        values.append(int(match.group(1)))
    if len(values) != 1 or values[0] <= 0:
        return None
    return {
        "extra_required_bytes": values[0],
        "source": "ISS [Setup].ExtraDiskSpaceRequired",
        "selection_specific": False,
    }


