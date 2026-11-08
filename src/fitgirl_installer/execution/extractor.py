"""Calls to the extraction tools: the internal backend and the setup payload."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, ContextManager

from ..models import InstallerError
from .journal import atomic_json


@dataclass(frozen=True)
class ExtractionServices:
    """Collaborators an extraction needs from the rest of the installer."""

    resolve_destination: Callable[[str, Path, Path], Path]
    safe_child: Callable[[Path, str], Path]
    verify_source: Callable[[dict[str, Any]], Path]
    command_prefix: Callable[[], list[str]]
    run_process: Callable[..., None]
    working_directory: Path


def run_extract(
    step: dict[str, Any], args: Any, source: Path, target: Path,
    scratch: Path, prefix: Path, state_path: Path, state: dict[str, Any],
    global_base: float = 0.0, global_weight: float = 1.0,
    payload_ready: bool = False, *, services: ExtractionServices,
) -> None:
    """Run the extraction backend for one archive of the plan."""
    archive_root = step.get("archive_root")
    if archive_root:
        archive = services.safe_child(
            services.resolve_destination(archive_root, target, scratch), step["archive"]
        )
        if not archive.is_file() and not args.dry_run:
            raise InstallerError(f"arquivo intermediário ausente: {archive}")
        archive_arguments = ["--archive-path", str(archive)]
    else:
        archive = services.verify_source(step)
        archive_arguments = ["--archive", archive.name]
    destination = services.resolve_destination(step.get("destination", "app"), target, scratch)
    if step.get("destination_suffix"):
        destination = services.safe_child(destination, step["destination_suffix"])
    command = services.command_prefix() + [
        str(args.backend), "-d", str(source), "-t", str(destination),
        "-w", str(scratch), *archive_arguments, "--wine", str(args.wine),
        "--prefix", str(prefix), "--monitor-interval", str(args.monitor_interval),
        "--global-base", f"{global_base:.9f}",
        "--global-weight", f"{global_weight:.9f}",
    ]
    if payload_ready:
        command.append("--payload-ready")
    if step.get("archive_path_filter"):
        command.extend(["--archive-path-filter", str(step["archive_path_filter"])])
    if args.srep_memory:
        command.extend(["--srep-memory", str(args.srep_memory)])
    if args.bzip3_threads:
        command.extend(["--bzip3-threads", str(args.bzip3_threads)])
    if step.get("archive_workdir"):
        archive_workdir = services.safe_child(target, step["archive_workdir"])
        command.extend(["--archive-workdir", str(archive_workdir)])
    for pattern in step.get("filters", []):
        command.extend(["--include", str(pattern)])
    services.run_process(command, services.working_directory, state_path, state, args.dry_run)
    if step.get("delete_archive_after") and not args.dry_run:
        archive.unlink(missing_ok=True)


@dataclass(frozen=True)
class PayloadServices:
    """Collaborators the setup payload extraction needs from the installer."""

    sha256: Callable[[Path], str]
    wait_process: Callable[..., int]
    forwarding_signals: Callable[[], ContextManager[Any]]
    default_innoextract: Path


def _payload_snapshot(
    directory: Path, expected: set[str], *, allow_extra: bool = False,
    sha256: Callable[[Path], str],
) -> dict[str, dict[str, Any]] | None:
    if not directory.is_dir():
        return None
    actual = {
        path.name.casefold(): path for path in directory.iterdir() if path.is_file()
    }
    if not expected.issubset(actual) or (not allow_extra and set(actual) != expected):
        return None
    return {
        key: {
            "name": actual[key].name,
            "size": actual[key].stat().st_size,
            "sha256": sha256(actual[key]),
        }
        for key in sorted(expected)
    }


def _payload_tree_snapshot(
    directory: Path, expected: set[str], *, sha256: Callable[[Path], str],
) -> dict[str, dict[str, Any]] | None:
    if not directory.is_dir():
        return None
    actual = {
        path.relative_to(directory).as_posix().casefold(): path
        for path in directory.rglob("*") if path.is_file()
    }
    if set(actual) != expected:
        return None
    return {
        key: {
            "path": actual[key].relative_to(directory).as_posix(),
            "size": actual[key].stat().st_size,
            "sha256": sha256(actual[key]),
        }
        for key in sorted(expected)
    }


def materialize_temporary_payload(
    manifest: dict[str, Any], setup: Path, scratch: Path,
    state_path: Path, state: dict[str, Any], dry_run: bool,
    innoextract: Path | None = None, *, services: PayloadServices,
) -> None:
    """Extract audited ExtractTemporaryFile dependencies through atomic staging."""
    inventory = manifest.get("temporary_payload_files", [])
    if not inventory:
        return
    expected_names = [str(item["name"]) for item in inventory]
    expected = {name.casefold() for name in expected_names}
    if len(expected) != len(expected_names):
        raise InstallerError("payload temporário contém nomes duplicados sem distinção de caixa")
    destination = scratch / "setup-payload" / "tmp"
    recorded = state.get("payload", {}).get("files")
    if recorded and destination.is_dir():
        current = _payload_snapshot(destination, expected, allow_extra=True, sha256=services.sha256)
        if current == recorded:
            print(f"[OK] payload temporário: {len(expected)} arquivos já validados")
            return
        print("[AVISO] payload temporário divergiu do journal; será preservado e reconstruído")
        if state.get("completed"):
            raise InstallerError(
                "payload temporário divergiu após etapas concluídas; "
                "reconstrução automática recusada para preservar mutações e auxiliares"
            )
    tool = (innoextract or services.default_innoextract).resolve()
    if not tool.is_file() or not os.access(tool, os.X_OK):
        raise InstallerError(f"innoextract indisponível para materializar payload: {tool}")
    command = [
        str(tool), "--silent", "--timestamps", "none",
        "--output-dir", "STAGING",
    ]
    for name in expected_names:
        command.extend(["--include", f"tmp/{name}"])
    command.append(str(setup))
    if dry_run:
        command[command.index("STAGING")] = str(scratch / ".payload-stage.DRY-RUN")
        if sys.stdout.isatty():
            print("Preparando arquivos temporários…")
        else:
            print("[PAYLOAD]", shlex.join(command))
        return
    scratch.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix=".payload-stage-", dir=scratch))
    staging_tmp = staging_root / "tmp"
    log = scratch / "payload-innoextract.log"
    command[command.index("STAGING")] = str(staging_root)
    if sys.stdout.isatty():
        print("Preparando arquivos temporários…")
    else:
        print("[PAYLOAD]", shlex.join(command))
    try:
        with log.open("w", encoding="utf-8") as output:
            with services.forwarding_signals() as forwarder:
                process = subprocess.Popen(
                    command, stdout=output, stderr=subprocess.STDOUT,
                    text=True, start_new_session=True,
                )
                forwarder.attach(process)
                state["active"] = {
                    "pid": process.pid, "pgid": process.pid, "command": command,
                    "started_at": time.time(), "kind": "payload",
                }
                atomic_json(state_path, state)
                returncode = services.wait_process(process, state_path, state)
        if returncode:
            raise InstallerError(
                f"innoextract encerrou com código {returncode}; veja {log} e {staging_root}"
            )
        snapshot = _payload_snapshot(staging_tmp, expected, sha256=services.sha256)
        if snapshot is None:
            actual = (
                sorted(path.name for path in staging_tmp.iterdir() if path.is_file())
                if staging_tmp.is_dir() else []
            )
            raise InstallerError(
                "innoextract não produziu o conjunto temporário exato; "
                f"obtidos={actual}; staging preservado em {staging_root}"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            quarantine = destination.with_name(
                f"tmp.stale-{int(time.time())}-{os.getpid()}"
            )
            os.replace(destination, quarantine)
            print(f"[PAYLOAD] árvore anterior preservada em {quarantine}")
        os.replace(staging_tmp, destination)
        staging_root.rmdir()
        state["payload"] = {
            "setup_sha256": state.get("setup_sha256"),
            "files": snapshot,
            "materialized_at": time.time(),
        }
        atomic_json(state_path, state)
        print(f"[PAYLOAD] {len(snapshot)} arquivos publicados e validados")
    except Exception:
        if staging_root.exists() and not any(staging_root.iterdir()):
            staging_root.rmdir()
        raise


def materialize_application_payload(
    manifest: dict[str, Any], setup: Path, scratch: Path,
    state_path: Path, state: dict[str, Any], dry_run: bool,
    innoextract: Path | None = None, *, services: PayloadServices,
) -> None:
    """Materialize active {app} setup files into an atomic payload tree."""
    inventory = manifest.get("application_payload_files", [])
    legacy_required = {
        str(step["manifest"]).replace("\\", "/").casefold()
        for step in manifest.get("steps", [])
        if step.get("type") == "verify" and step.get("manifest_root", "payload_app") == "payload_app"
    } if not inventory else set()
    if not inventory and not legacy_required:
        return
    if legacy_required:
        for name in legacy_required:
            if not name.startswith("_redist/") or ".." in Path(name).parts:
                raise InstallerError("manifesto legado fora de _Redist")
        inventory = [{"path": name} for name in sorted(legacy_required)]
        inventory += [{"path": name} for name in (
            "_Redist/QuickSFV.EXE", "_Redist/QuickSFV.ini", "_Redist/*.addon",
        )]
    expected_paths = [str(item["path"]).replace("\\", "/") for item in inventory]
    expected = {path.casefold() for path in expected_paths}
    if len(expected) != len(expected_paths):
        raise InstallerError("payload de aplicação contém caminhos duplicados")
    destination = scratch / "setup-payload" / "app"
    recorded = state.get("payload", {}).get("app_files")
    if recorded and destination.is_dir():
        current = _payload_tree_snapshot(
            destination, set(recorded) if legacy_required else expected, sha256=services.sha256,
        )
        if current == recorded:
            print(f"[OK] payload de aplicação: {len(expected)} arquivos já validados")
            return
        print("[AVISO] payload de aplicação divergiu do journal; será preservado")
    if legacy_required and destination.is_dir() and not recorded:
        actual = {
            path.relative_to(destination).as_posix().casefold()
            for path in destination.rglob("*") if path.is_file()
        }
        allowed = all(
            name in legacy_required or name in {"_redist/quicksfv.exe", "_redist/quicksfv.ini"}
            or (name.startswith("_redist/") and name.count("/") == 1 and name.endswith(".addon"))
            for name in actual
        )
        snapshot = (
            _payload_tree_snapshot(destination, actual, sha256=services.sha256)
            if legacy_required.issubset(actual) and allowed else None
        )
        if snapshot is not None:
            state.setdefault("payload", {})["app_files"] = snapshot
            state["payload"]["app_materialized_at"] = time.time()
            atomic_json(state_path, state)
            print(f"[OK] payload legado de aplicação adotado e validado: {len(snapshot)} arquivos")
            return
    tool = (innoextract or services.default_innoextract).resolve()
    if not tool.is_file() or not os.access(tool, os.X_OK):
        raise InstallerError(f"innoextract indisponível para materializar payload: {tool}")
    command = [
        str(tool), "--silent", "--timestamps", "none",
        "--output-dir", "STAGING",
    ]
    for path in expected_paths:
        command.extend(["--include", f"app/{path}"])
    command.append(str(setup))
    if dry_run:
        command[command.index("STAGING")] = str(scratch / ".app-payload-stage.DRY-RUN")
        if sys.stdout.isatty():
            print("Preparando arquivos da instalação…")
        else:
            print("[PAYLOAD-APP]", shlex.join(command))
        return
    scratch.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix=".app-payload-stage-", dir=scratch))
    staging_app = staging_root / "app"
    log = scratch / "payload-app-innoextract.log"
    command[command.index("STAGING")] = str(staging_root)
    if sys.stdout.isatty():
        print("Preparando arquivos da instalação…")
    else:
        print("[PAYLOAD-APP]", shlex.join(command))
    try:
        with log.open("w", encoding="utf-8") as output:
            with services.forwarding_signals() as forwarder:
                process = subprocess.Popen(
                    command, stdout=output, stderr=subprocess.STDOUT,
                    text=True, start_new_session=True,
                )
                forwarder.attach(process)
                state["active"] = {
                    "pid": process.pid, "pgid": process.pid, "command": command,
                    "started_at": time.time(), "kind": "payload-app",
                }
                atomic_json(state_path, state)
                returncode = services.wait_process(process, state_path, state)
        if returncode:
            raise InstallerError(
                f"innoextract encerrou com código {returncode}; veja {log} e {staging_root}"
            )
        if legacy_required:
            actual = {
                p.relative_to(staging_app).as_posix().casefold()
                for p in staging_app.rglob("*") if p.is_file()
            }
            allowed = all(
                name in legacy_required or name in {"_redist/quicksfv.exe", "_redist/quicksfv.ini"}
                or (name.startswith("_redist/") and name.count("/") == 1 and name.endswith(".addon"))
                for name in actual
            )
            snapshot = _payload_tree_snapshot(staging_app, actual, sha256=services.sha256) if legacy_required.issubset(actual) and allowed else None
        else:
            snapshot = _payload_tree_snapshot(staging_app, expected, sha256=services.sha256)
        if snapshot is None:
            actual = (
                sorted(path.relative_to(staging_app).as_posix()
                       for path in staging_app.rglob("*") if path.is_file())
                if staging_app.is_dir() else []
            )
            raise InstallerError(
                "innoextract não produziu o payload de aplicação exato; "
                f"obtidos={actual}; staging preservado em {staging_root}"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            quarantine = destination.with_name(
                f"app.stale-{int(time.time())}-{os.getpid()}"
            )
            os.replace(destination, quarantine)
            print(f"[PAYLOAD-APP] árvore anterior preservada em {quarantine}")
        os.replace(staging_app, destination)
        staging_root.rmdir()
        state.setdefault("payload", {})["app_files"] = snapshot
        state["payload"]["app_materialized_at"] = time.time()
        atomic_json(state_path, state)
        print(f"[PAYLOAD-APP] {len(snapshot)} arquivos publicados e validados")
    except Exception:
        if staging_root.exists() and not any(staging_root.iterdir()):
            staging_root.rmdir()
        raise
