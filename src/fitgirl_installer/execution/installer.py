"""Coordinate the steps of an audited installation plan."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping


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


@dataclass(frozen=True)
class StepRun:
    """One step about to run, with its share of the global progress."""

    index: int
    step: dict[str, Any]
    key: str
    global_base: float
    global_weight: float


def run_planned_steps(
    planned: list[tuple[int, dict[str, Any], str, int]], state: dict[str, Any], *,
    handlers: Mapping[str, Callable[[StepRun], None]],
    verify_source: Callable[[dict[str, Any]], None],
    check_order: Callable[[int, dict[str, Any], str], None] | None,
    record_completion: Callable[[int, dict[str, Any], str], None] | None,
    error_type: type[RuntimeError],
) -> None:
    """Run the weighted steps in order, resuming the ones already completed.

    ``check_order`` and ``record_completion`` are omitted in a dry run.
    """
    total_weight = max(1, sum(item[3] for item in planned))
    finished_weight = sum(
        weight for _, _, key, weight in planned if key in state["completed"]
    )
    for visible_index, (index, step, key, weight) in enumerate(planned, 1):
        global_base = finished_weight / total_weight
        global_weight = weight / total_weight
        if not sys.stdout.isatty():
            print(f"[GLOBAL] {min(99.9, global_base * 100):5.1f}% antes de {key}")
        if step.get("type") == "extract" and not step.get("archive_root"):
            verify_source(step)
        if key in state["completed"]:
            if sys.stdout.isatty():
                print(f"Etapa {visible_index}/{len(planned)} já validada; retomando.")
            else:
                print(f"[OK] {key}: já concluída")
            continue
        if check_order is not None:
            check_order(index, step, key)
        kind = step.get("type")
        if sys.stdout.isatty():
            print(f"Etapa {visible_index}/{len(planned)}: {step.get('description', key)}")
        else:
            print(f"[ETAPA {index}] {step.get('description', key)}")
        handler = handlers.get(kind)
        if handler is None:
            raise error_type(f"tipo de etapa não suportado: {kind}")
        handler(StepRun(index, step, key, global_base, global_weight))
        if record_completion is not None:
            record_completion(index, step, key)
        finished_weight += weight
        if sys.stdout.isatty():
            print(f"Etapa concluída · {min(100, finished_weight / total_weight * 100):.0f}% geral")
        else:
            print(f"[GLOBAL] {min(99.9, finished_weight / total_weight * 100):5.1f}% confirmado")
