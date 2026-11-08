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


def finish_installation(
    planned: list[tuple[int, dict[str, Any], str, int]], *, target: Path, scratch: Path,
    state_path: Path, state: dict[str, Any], dry_run: bool, quicksfv_x64: Any,
    preserve_verifier: Callable[..., Any],
    write_integration_report: Callable[[Path, Path], dict[str, Any]],
    finalize_transactions: Callable[[Path, Path, dict[str, Any]], Any],
) -> None:
    """Keep the verifier, report the installed files and commit pending transactions."""
    preserve_verifier(
        target, scratch, dry_run, quicksfv_x64,
        preserve_existing_manifest=any(s.get("type") == "merge-manifests" for _, s, _, _ in planned),
    )
    if not dry_run:
        report_path = scratch / "integration-report.json"
        report = write_integration_report(target, report_path)
        print(
            f"[INTEGRAÇÃO] {len(report['game_executable_candidates'])} executáveis candidatos; "
            f"{len(report['redistributables'])} redistribuíveis não executados; relatório: {report_path}"
        )
        finalize_transactions(scratch, state_path, state)
    if sys.stdout.isatty():
        print("Instalação concluída e arquivos verificados." if not dry_run else "Simulação concluída.")
    else:
        print(f"[GLOBAL] 100.0% {'simulado' if dry_run else 'confirmado'}")
        print(f"[INFO] instalação concluída em {target}" if not dry_run else "[INFO] simulação concluída")


@dataclass(frozen=True)
class InstallRequest:
    """What to install, already chosen and resumed by the caller."""

    source: Path
    target: Path
    scratch: Path
    prefix: Path
    manifest_path: Path
    manifest: dict[str, Any]
    components: set[str]
    options: set[str]
    state_path: Path
    state: dict[str, Any]
    wine: Any
    dry_run: bool
    memory_max: Any
    quicksfv_x64: Any


@dataclass(frozen=True)
class InstallServices:
    """Collaborators the coordination needs from the rest of the installer."""

    save_state: Callable[[Path, dict[str, Any]], None]
    validate_runtime_order: Callable[..., Any]
    record_runtime_completion: Callable[..., Any]
    recover_incomplete_transactions: Callable[..., Any]
    ensure_wine_prefix: Callable[..., Any]
    discover_setup: Callable[[Path], Path]
    materialize_temporary_payload: Callable[..., Any]
    materialize_application_payload: Callable[..., Any]
    component_label: Callable[[str, dict[str, Any]], str]
    resolve_destination: Callable[[str, Path, Path], Path]
    safe_child: Callable[[Path, str], Path]
    preserve_verifier: Callable[..., Any]
    write_integration_report: Callable[[Path, Path], dict[str, Any]]
    finalize_transactions: Callable[[Path, Path, dict[str, Any]], Any]
    error_type: type[RuntimeError]


def run_installation(
    request: InstallRequest, *, handlers: Mapping[str, Callable[[StepRun], None]],
    verify_source: Callable[[dict[str, Any]], None], services: InstallServices,
) -> None:
    """Prepare the destination and scratch, run every planned step and finish."""
    r = request
    r.target.mkdir(parents=True, exist_ok=True)
    r.scratch.mkdir(parents=True, exist_ok=True)
    services.save_state(r.state_path, r.state)
    execution_plan = selected_steps(r.manifest, r.components, r.options)
    if not r.dry_run:
        services.validate_runtime_order(r.scratch, r.manifest, r.state, execution_plan)
    services.recover_incomplete_transactions(r.target, r.scratch, r.state_path, r.state)
    if any(
        step.get("type") in {"batch", "exec", "isexec"}
        and enabled(step, r.components, r.options)
        for step in r.manifest.get("steps", [])
    ):
        services.ensure_wine_prefix(
            r.wine, r.prefix, r.scratch, r.state_path, r.state, r.dry_run
        )
    if sys.stdout.isatty():
        print("Plano de instalação validado.")
    else:
        print(f"[INFO] plano: {r.manifest_path}")
    services.materialize_temporary_payload(
        r.manifest, services.discover_setup(r.source), r.scratch, r.state_path, r.state,
        r.dry_run,
    )
    services.materialize_application_payload(
        r.manifest, services.discover_setup(r.source), r.scratch, r.state_path, r.state,
        r.dry_run,
    )
    if sys.stdout.isatty():
        labels = [
            services.component_label(name, r.manifest.get("components", {}).get(name, {}))
            for name in sorted(r.components)
        ]
        print("Conteúdo: " + ", ".join(labels))
    else:
        print(f"[INFO] componentes: {', '.join(sorted(r.components))}")
    if r.memory_max is not None:
        print("[AVISO] MemoryMax é um teto rígido: ao atingi-lo, o kernel pode matar o stream ativo")
    planned = weighted_steps(
        r.manifest, r.components, r.options, source=r.source, target=r.target,
        scratch=r.scratch, resolve_destination=services.resolve_destination,
        safe_child=services.safe_child,
    )
    run_planned_steps(
        planned, r.state, handlers=handlers, verify_source=verify_source,
        check_order=None if r.dry_run else (
            lambda index, step, key: services.validate_runtime_order(
                r.scratch, r.manifest, r.state, execution_plan, current=(index, step, key),
            )
        ),
        record_completion=None if r.dry_run else (
            lambda index, step, key: services.record_runtime_completion(
                r.scratch, r.state, index, step, key,
            )
        ),
        error_type=services.error_type,
    )
    finish_installation(
        planned, target=r.target, scratch=r.scratch, state_path=r.state_path, state=r.state,
        dry_run=r.dry_run, quicksfv_x64=r.quicksfv_x64,
        preserve_verifier=services.preserve_verifier,
        write_integration_report=services.write_integration_report,
        finalize_transactions=services.finalize_transactions,
    )
