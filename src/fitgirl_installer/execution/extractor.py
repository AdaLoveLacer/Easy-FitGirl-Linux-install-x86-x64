"""Calls to the extraction tools: the internal backend and the setup payload."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..models import InstallerError


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
