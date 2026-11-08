"""Coordinate the steps of an audited installation plan."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


def enabled(
    step: dict[str, Any], components: set[str], options: set[str] | None = None
) -> bool:
    """Tell whether a plan step applies to the chosen components and options."""
    required = step.get("if_component")
    excluded = step.get("unless_component")
    condition = step.get("condition")
    option = condition.get("option") if isinstance(condition, dict) else None
    condition_ok = condition is None or bool(option and option in (options or set()))
    return (
        (not required or required in components)
        and (not excluded or excluded not in components)
        and condition_ok
    )


def step_key(index: int, step: dict[str, Any]) -> str:
    """Stable journal key of a step: its 1-based position and identifier."""
    return f"{index:03d}:{step.get('id', step.get('archive', step.get('type', 'step')))}"


def selected_steps(
    manifest: dict[str, Any], components: set[str], options: set[str],
) -> list[tuple[int, dict[str, Any], str]]:
    """List the enabled steps in plan order with their journal keys."""
    return [
        (index, step, step_key(index, step))
        for index, step in enumerate(manifest.get("steps", []), 1)
        if enabled(step, components, options)
    ]


def weighted_steps(
    manifest: dict[str, Any], components: set[str], options: set[str], *,
    source: Path, target: Path, scratch: Path,
    resolve_destination: Callable[[str, Path, Path], Path],
    safe_child: Callable[[Path, str], Path],
) -> list[tuple[int, dict[str, Any], str, int]]:
    """Weigh each enabled step for global progress, reporting the skipped ones.

    Extractions weigh as much as their archive; every other step, and an
    archive that is not present yet, counts as 1 MiB.
    """
    planned: list[tuple[int, dict[str, Any], str, int]] = []
    for index, step in enumerate(manifest.get("steps", []), 1):
        key = step_key(index, step)
        if not enabled(step, components, options):
            print(f"[PULA] {key}: condição de componente não satisfeita")
            continue
        weight = 1024 * 1024
        if step.get("type") == "extract":
            if step.get("archive_root"):
                candidate = safe_child(
                    resolve_destination(step["archive_root"], target, scratch),
                    step["archive"],
                )
            else:
                candidate = safe_child(source, step["archive"])
            if candidate.is_file():
                weight = max(1, candidate.stat().st_size)
        planned.append((index, step, key, weight))
    return planned
