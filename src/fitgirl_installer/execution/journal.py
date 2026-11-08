"""Durable state of an installation: journal files, resumption and transactions."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from ..models import InstallerError


STATE_VERSION = 1


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    """Write JSON durably: fsync a temporary file, keep the previous one as .bak, then replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if path.is_file():
            backup = path.with_name(f"{path.name}.bak")
            backup_fd, backup_temporary = tempfile.mkstemp(
                prefix=f".{backup.name}.", dir=path.parent
            )
            try:
                with os.fdopen(backup_fd, "wb") as backup_handle:
                    backup_handle.write(path.read_bytes())
                    backup_handle.flush()
                    os.fsync(backup_handle.fileno())
                os.replace(backup_temporary, backup)
            finally:
                try:
                    os.unlink(backup_temporary)
                except FileNotFoundError:
                    pass
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def load_json(path: Path) -> dict[str, Any]:
    """Read a JSON object, reporting unreadable or non-object files as InstallerError."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InstallerError(f"não foi possível ler {path}: {error}") from error
    if not isinstance(value, dict):
        raise InstallerError(f"objeto JSON esperado em {path}")
    return value


def load_state(path: Path) -> dict[str, Any]:
    """Read the journal, falling back to its .bak and preserving the corrupt copy."""
    try:
        return load_json(path)
    except InstallerError as primary_error:
        backup = path.with_name(f"{path.name}.bak")
        if not backup.is_file():
            raise
        try:
            state = load_json(backup)
        except InstallerError:
            raise primary_error
        corrupt = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
        os.replace(path, corrupt)
        atomic_json(path, state)
        print(f"[AVISO] journal inválido preservado em {corrupt}; backup restaurado")
        return state


def initial_state(setup_hash: str, plan_hash: str, source: Path, target: Path, components: set[str], args: Any) -> dict[str, Any]:
    """Fresh journal for this plan, components and resource settings."""
    settings = {
        "srep_memory": args.srep_memory, "cpus": args.cpus, "nice": args.nice,
        "limit_2gb": bool(getattr(args, "limit_2gb", False)),
    }
    if args.bzip3_threads is not None:
        settings["bzip3_threads"] = args.bzip3_threads
    if args.memory_high is not None:
        settings["memory_high"] = args.memory_high
    if args.memory_max is not None:
        settings["memory_max"] = args.memory_max
    return {
        "version": STATE_VERSION,
        "setup_sha256": setup_hash,
        "manifest_sha256": plan_hash,
        "source": str(source),
        "target": str(target),
        "components": sorted(components),
        "settings": settings,
        "completed": {},
        "verified": {},
        "active": None,
        "created_at": time.time(),
    }


def validate_state(state: dict[str, Any], expected: dict[str, Any]) -> None:
    """Refuse a journal written for another plan, source, target or settings."""
    immutable = ("version", "setup_sha256", "manifest_sha256", "source", "target", "components", "settings")
    differences = [key for key in immutable if state.get(key) != expected.get(key)]
    if differences:
        raise InstallerError(
            "o journal pertence a outro plano/opções (" + ", ".join(differences) + "); "
            "use o mesmo comando ou um scratch diferente"
        )


def resume_or_start(state_path: Path, expected: dict[str, Any]) -> dict[str, Any]:
    """Continue a compatible journal, refusing to run beside a still-live step."""
    if state_path.exists():
        state = load_state(state_path)
        validate_state(state, expected)
        if state.get("active"):
            pgid = int(state["active"].get("pgid", 0))
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                print("[AVISO] etapa anterior não está mais ativa; ela será repetida desde o início")
            else:
                raise InstallerError(
                    f"a etapa anterior ainda está ativa no grupo {pgid}; não iniciarei uma cópia concorrente"
                )
            state["active"] = None
    else:
        state = expected
    return state


def _runtime_order_report(
    scratch: Path, manifest: dict[str, Any], state: dict[str, Any],
    planned: list[tuple[int, dict[str, Any], str]], expected: str | None,
    observed: dict[str, Any], reason: str,
) -> InstallerError:
    """Persist a shareable, path-redacted report before stopping installation."""
    timestamp = int(time.time())
    selected = {key: index for index, _step, key in planned}
    report_path = scratch / "reports" / f"runtime-divergence-{timestamp}-{os.getpid()}.json"
    report = {
        "schema": 1,
        "kind": "runtime_execution_order_divergence",
        "created_at": timestamp,
        "game": str(manifest.get("name", "desconhecido")),
        "setup_sha256": str(state.get("setup_sha256", "")),
        "plan_sha256": str(state.get("manifest_sha256", "")),
        "reason": reason,
        "expected_next": (
            {"step": expected, "index": selected.get(expected)} if expected else None
        ),
        "observed": observed,
        "selected_step_count": len(planned),
        "completed_step_count": len(state.get("completed", {})),
        "recent_trace": [
            {
                key: event.get(key)
                for key in ("event", "step", "index", "type", "recorded_at", "source")
                if key in event
            }
            for event in state.get("execution_trace", [])[-20:]
            if isinstance(event, dict)
        ],
        "privacy": "Este relatório não inclui caminhos locais, comandos, argumentos ou conteúdo dos arquivos.",
    }
    atomic_json(report_path, report)
    raise InstallerError(
        f"divergência na ordem de execução detectada: {reason}\n"
        "A instalação foi interrompida antes de iniciar outra etapa. "
        f"Diagnóstico: {report_path}\n"
        "Se puder, envie esse relatório ao suporte para ajudar a corrigir o problema."
    )


def validate_runtime_order(
    scratch: Path, manifest: dict[str, Any], state: dict[str, Any],
    planned: list[tuple[int, dict[str, Any], str]],
    current: tuple[int, dict[str, Any], str] | None = None,
) -> None:
    """Check journal and live dispatch order against the selected plan."""
    positions = {key: position for position, (_index, _step, key) in enumerate(planned)}
    completed = state.setdefault("completed", {})
    completed_keys = list(completed)
    unknown = [key for key in completed_keys if key not in positions]
    if unknown:
        _runtime_order_report(
            scratch, manifest, state, planned, None,
            {"step": unknown[0], "event": "completed_in_journal"},
            "o journal contém uma etapa que não pertence ao plano selecionado",
        )
    completed_positions = sorted(positions[key] for key in completed_keys)
    if completed_positions != list(range(len(completed_positions))):
        # The next expected step is the first plan position missing from the
        # journal, not the count of completed steps: with A and C completed
        # the missing step is B.
        done = set(completed_positions)
        missing = next(position for position in range(len(planned)) if position not in done)
        expected_key = planned[missing][2]
        later = next(key for key in completed_keys if positions[key] > missing)
        _runtime_order_report(
            scratch, manifest, state, planned, expected_key,
            {"step": later, "event": "completed_in_journal", "index": positions[later]},
            "o journal marca uma etapa posterior como concluída antes da etapa esperada",
        )

    trace = state.get("execution_trace")
    if trace is None:
        # Older journals have no trace. Their completed set is a validated
        # prefix, so its only possible order is the manifest order.
        trace = [
            {
                "event": "completed", "step": key, "index": planned[pos][0],
                "type": planned[pos][1].get("type"),
                "recorded_at": completed[key].get("finished_at"),
                "source": "legacy-journal",
            }
            for pos, key in enumerate(key for _i, _s, key in planned if key in completed)
        ]
        state["execution_trace"] = trace
        atomic_json(scratch / "install-state.json", state)
    if not isinstance(trace, list):
        _runtime_order_report(
            scratch, manifest, state, planned, None,
            {"event": "invalid_execution_trace"}, "o rastro de execução do journal está inválido",
        )

    last_position = -1
    trace_completed: set[str] = set()
    for event in trace:
        key = event.get("step") if isinstance(event, dict) else None
        if key not in positions:
            _runtime_order_report(
                scratch, manifest, state, planned, None,
                {"step": key, "event": "invalid_trace_entry"},
                "o rastro contém uma etapa desconhecida ou malformada",
            )
        position = positions[key]
        if position < last_position:
            expected_key = planned[last_position][2]
            _runtime_order_report(
                scratch, manifest, state, planned, expected_key,
                {"step": key, "event": event.get("event"), "index": event.get("index")},
                "o rastro registra uma etapa fora da ordem do plano",
            )
        last_position = position
        if event.get("event") == "completed":
            trace_completed.add(key)
        elif event.get("event") != "started":
            _runtime_order_report(
                scratch, manifest, state, planned, None,
                {"step": key, "event": event.get("event")},
                "o rastro contém um tipo de evento desconhecido",
            )
    missing_trace = [key for key in completed if key not in trace_completed]
    if missing_trace:
        _runtime_order_report(
            scratch, manifest, state, planned, None,
            {"step": missing_trace[0], "event": "completed_without_trace"},
            "o journal e o rastro discordam sobre uma etapa concluída",
        )

    if current is not None:
        completed_count = len(completed)
        expected_key = planned[completed_count][2] if completed_count < len(planned) else None
        _index, step, key = current
        if key != expected_key:
            _runtime_order_report(
                scratch, manifest, state, planned, expected_key,
                {"step": key, "event": "dispatch", "type": step.get("type")},
                "a etapa que seria iniciada não é a próxima etapa pendente do plano",
            )
        trace.append({
            "event": "started", "step": key, "index": _index,
            "type": step.get("type"), "recorded_at": time.time(),
        })
        state["execution_trace"] = trace
        atomic_json(scratch / "install-state.json", state)


def record_runtime_completion(
    scratch: Path, state: dict[str, Any], index: int,
    step: dict[str, Any], key: str,
) -> None:
    """Mark a step completed in the journal and its execution trace."""
    state.setdefault("completed", {})[key] = {"finished_at": time.time()}
    state.setdefault("execution_trace", []).append({
        "event": "completed", "step": key, "index": index,
        "type": step.get("type"), "recorded_at": time.time(),
    })
    atomic_json(scratch / "install-state.json", state)
