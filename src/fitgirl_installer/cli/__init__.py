#!/usr/bin/env python3
"""Interactive standalone installer for FitGirl repacks on Linux."""

from __future__ import annotations

import argparse
import contextlib
import functools
import hashlib
from importlib import import_module
import json
import os
import re
import shutil
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ..planning.script_flow import SCHEMA_VERSION as IFPS_IR_SCHEMA_VERSION, write_cfg_report
from ..compatibility import compatibility_error, report_json
from ..verification.integration import write_integration_report
from ..planning.planner import PLAN_COMPILER_VERSION, write_manifest
from ..execution import extractor
from ..execution import installer
from ..execution import journal
from ..execution.journal import (
    atomic_json, finalize_transactions, initial_state, load_json, load_state,
    record_runtime_completion, recover_incomplete_transactions, restore_transaction,
    validate_runtime_order,
)
from ..models import InstallerError
from ..execution.installer import enabled, step_key
from ..planning import analyzer
from ..planning.analyzer import disk_space_from_iss
from ..planning.audit import write_audit
from ..platform import wine
from ..runtime import ensure_bundled_wine
from ..verification import manifests
from ..verification import checksums
from ..verification.checksums import sha256
from ..resource_limits import detect_limits, parse_cpu_list
from .presentation import _wizard_page, _component_label, format_size
from . import menus
from .menus import (
    DestinationMenuServices, prompt_components, prompt_yes_no, prompt_path,
    prompt_positive_int, prompt_cpu_list,
)


ROOT = Path(__file__).resolve().parents[3]
MANIFEST_DIR = ROOT / "manifests"


def pe_machine(path: Path) -> int | None:
    """Return the PE COFF machine without loading or executing the binary."""
    try:
        with path.open("rb") as handle:
            if handle.read(2) != b"MZ":
                return None
            handle.seek(0x3C)
            pe_offset = int.from_bytes(handle.read(4), "little")
            handle.seek(pe_offset)
            if handle.read(4) != b"PE\0\0":
                return None
            return int.from_bytes(handle.read(2), "little")
    except (OSError, ValueError):
        return None


def discover_setup(source: Path) -> Path:
    return analyzer.discover_setup(source, error_type=InstallerError)


def find_manifest(setup_hash: str, explicit: Path | None) -> tuple[Path, dict[str, Any]]:
    if explicit:
        manifest = load_json(explicit)
        path = explicit
    else:
        candidates = []
        for path in sorted(MANIFEST_DIR.glob("*.json")):
            candidate = load_json(path)
            if setup_hash in candidate.get("setup_sha256", []):
                candidates.append((path, candidate))
        if len(candidates) != 1:
            raise InstallerError(
                "nenhum manifesto inequívoco corresponde ao setup.exe; "
                "use --manifest após analisar o CompiledCode.bin"
            )
        path, manifest = candidates[0]
    accepted = manifest.get("setup_sha256", [])
    if setup_hash not in accepted:
        raise InstallerError(
            f"manifesto {path} não aceita este setup.exe ({setup_hash}); "
            "recusei executar um plano possivelmente incompatível"
        )
    blockers = manifest.get("semantic_blockers", [])
    if blockers:
        details = "; ".join(str(item) for item in blockers)
        raise InstallerError(
            f"manifesto {path} bloqueado por efeito externo não representado no plano: {details}"
        )
    if manifest.get("draft") or manifest.get("review_required"):
        raise InstallerError(
            f"manifesto {path} ainda é rascunho; revise condições/ações e remova "
            "draft/review_required antes de instalar"
        )
    return path, manifest


def manifest_hash(manifest: dict[str, Any]) -> str:
    encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def safe_child(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    resolved_root = root.resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as error:
        raise InstallerError(f"caminho do manifesto escapa da raiz permitida: {relative}") from error
    return candidate


def parse_components(manifest: dict[str, Any], source: Path, requested: list[str], disabled: list[str]) -> set[str]:
    definitions = manifest.get("components", {})
    if not isinstance(definitions, dict):
        raise InstallerError("components inválido no manifesto")
    selected = {name for name, data in definitions.items() if data.get("default", False)}
    known = set(definitions)
    unknown = (set(requested) | set(disabled)) - known
    if unknown:
        raise InstallerError(f"componentes desconhecidos: {', '.join(sorted(unknown))}")
    selected.update(requested)
    selected.difference_update(disabled)
    for name in tuple(selected):
        availability = definitions[name].get("available_if")
        if availability and not (source / availability).is_file():
            print(f"[AVISO] componente {name} desativado: {availability} não está presente")
            selected.remove(name)
    for name, data in definitions.items():
        if data.get("required") and name not in selected:
            raise InstallerError(f"o componente obrigatório {name} não pode ser desativado")
    return selected


def discover_wine() -> list[Path]:
    return wine.discover_wine(root=ROOT, ensure_bundled_wine=ensure_bundled_wine)


def select_codec_runtime() -> Path:
    """No technical runtime prompt in the normal extraction workflow."""
    return wine.select_codec_runtime(discover_wine)


def discover_analysis_tool(environment: str, bundled_name: str, command: str) -> Path | None:
    return analyzer.discover_analysis_tool(
        environment, bundled_name, command, root=ROOT, pe_machine=pe_machine,
    )


def wine_z_path(path: Path) -> str:
    return "Z:" + str(path.resolve()).replace("/", "\\")


def _analysis_services() -> analyzer.AnalysisServices:
    """Bind the analysis to this module's helpers, looked up at call time."""
    return analyzer.AnalysisServices(
        read_json=load_json, save_json=atomic_json, sha256=sha256,
        write_cfg=write_cfg_report, write_manifest=write_manifest, write_audit=write_audit,
        find_tool=discover_analysis_tool, pe_machine=pe_machine, discover_wine=discover_wine,
        wine_z_path=wine_z_path, compiler_version=PLAN_COMPILER_VERSION,
        schema_version=IFPS_IR_SCHEMA_VERSION, error_type=InstallerError,
    )


def generate_manifest_draft(source: Path, setup: Path, setup_hash: str) -> tuple[Path, dict[str, Any]]:
    """Analyze an unknown setup without executing it and cache all review evidence."""
    return analyzer.generate_manifest_draft(
        source, setup, setup_hash, services=_analysis_services(),
    )


@functools.lru_cache(maxsize=1)
def local_mounts() -> list[dict[str, Any]]:
    try:
        result = subprocess.run(
            ["findmnt", "--json", "--real", "-o", "TARGET,SOURCE,FSTYPE,OPTIONS"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, check=False,
        )
        if result.returncode:
            return []
        def flatten(rows):
            for row in rows:
                yield row
                yield from flatten(row.get("children", []))
        return [row for row in flatten(json.loads(result.stdout).get("filesystems", []))
                if str(row.get("source", "")).startswith("/dev/")]
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


def discover_game_roots() -> list[Path]:
    configured = os.environ.get("FITGIRL_GAMES_DIR")
    first = Path(configured).expanduser() if configured else Path.home() / "Games"
    roots = [first.resolve()]
    mounts = local_mounts()
    home_mounts = [row for row in mounts if Path.home().is_relative_to(Path(row['target']))]
    home_device = max(home_mounts, key=lambda row: len(row['target']))['source'].split('[', 1)[0] if home_mounts else None
    seen = {home_device} if home_device else set()
    for row in mounts:
        mount = Path(row['target'])
        device = row['source'].split('[', 1)[0]
        if device in seen or mount == Path('/') or str(mount).startswith(('/boot', '/var/', '/root', '/srv/')):
            continue
        seen.add(device)
        roots.append(mount / "Games")
    return list(dict.fromkeys(roots))


def destination_is_writable(path: Path) -> bool:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return probe.is_dir() and os.access(probe, os.W_OK | os.X_OK) and not (os.statvfs(probe).f_flag & os.ST_RDONLY)
    except OSError:
        return False


def storage_label(path: Path) -> str:
    matches = [
        row for row in local_mounts()
        if path.resolve().is_relative_to(Path(row["target"]).resolve())
    ]
    if not matches:
        return "disco local"
    row = max(matches, key=lambda item: len(str(item["target"])))
    source = str(row.get("source", "disco")).split("[", 1)[0]
    fstype = str(row.get("fstype", "")).strip()
    return f"{source}, {fstype}" if fstype else source


def discover_quicksfv_x64(source: Path) -> Path | None:
    """Find a compatible verifier without asking the user for technical paths."""
    approved_hashes = {
        # QuickSFV 2.36 x64, validated empirically on the FM7 installation.
        "410d63c8ce116d613e775631c089dcdbb7893ef2120313289c29c381b7b0924e",
    }
    configured = os.environ.get("FITGIRL_QUICKSFV_X64")
    if configured:
        candidate = Path(configured).expanduser().resolve()
        if candidate.is_file() and pe_machine(candidate) == 0x8664:
            return candidate
        raise InstallerError(f"FITGIRL_QUICKSFV_X64 não aponta para um QuickSFV x64 válido: {candidate}")
    data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    candidates = [
        data / "fitgirl-installer/tools/QuickSFV.exe",
        data / "fitgirl-installer/tools/QuickSFV-x64.exe",
        source / "_Redist/QuickSFV.EXE",
    ]
    # Existing installations are a useful local source. Keep the scan shallow.
    for games in discover_game_roots():
        if games.is_dir():
            candidates.extend(sorted(games.glob("*/_Redist/QuickSFV.EXE")))
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen and resolved.is_file():
            seen.add(resolved)
            if pe_machine(resolved) == 0x8664 and sha256(resolved) in approved_hashes:
                return resolved
    return None


def validate_external_game_target(target: Path, prefix: Path | None = None) -> None:
    target = target.resolve()
    default_prefix = Path(os.environ.get("WINEPREFIX", Path.home() / ".wine")).expanduser().resolve()
    for root in (default_prefix, prefix.resolve() if prefix is not None else None):
        if root is not None and (target == root or root in target.parents or (prefix is not None and target in root.parents)):
            raise InstallerError("o destino do jogo deve ficar separado do prefixo Wine")
    for ancestor in (target, *target.parents):
        if (ancestor / "system.reg").is_file() and (ancestor / "dosdevices").is_dir():
            raise InstallerError(f"o destino está dentro de um prefixo Wine: {ancestor}")


def _destination_validation_message(target: Path) -> str | None:
    try:
        validate_external_game_target(target)
    except InstallerError as error:
        return str(error)
    if not destination_is_writable(target):
        return "não é possível criar a pasta neste disco; escolha outro destino gravável"
    return None


def prompt_destination(
    game_name: str, *, wizard: bool = False, details: list[str] | None = None,
) -> Path:
    services = DestinationMenuServices(
        roots=tuple(discover_game_roots()),
        storage_label=storage_label,
        is_writable=destination_is_writable,
        validation_message=_destination_validation_message,
    )
    return menus.prompt_destination(
        game_name, services=services, wizard=wizard, details=details
    )


def default_game_name(manifest: dict[str, Any], source: Path) -> str:
    name = str(manifest.get("name") or source.name)
    name = re.sub(r"\s*\[FitGirl Repack\]\s*", "", name, flags=re.IGNORECASE)
    name = name.strip() or source.name
    if name in {".", ".."} or "/" in name or "\\" in name:
        raise InstallerError("nome do jogo inválido para compor o destino")
    return name


def target_work_id(target: Path, setup_hash: str) -> str:
    """Keep separate resumable journals for sibling targets of the same game."""
    return re.sub(r"[^a-z0-9]+", "-", target.name.casefold()).strip("-") or setup_hash[:12]


def repack_size(source: Path) -> int:
    """Cheap directory metadata only: no hashing or codec execution."""
    return sum(
        path.stat().st_size for path in source.iterdir()
        if path.is_file() and (
            path.name.casefold() == "setup.exe"
            or (path.name.casefold().startswith("fg-") and path.suffix.casefold() == ".bin")
        )
    )


def declared_disk_space(
    manifest: dict[str, Any], manifest_path: Path, setup_hash: str,
) -> int | None:
    metadata = manifest.get("disk_space")
    if isinstance(metadata, dict):
        value = metadata.get("extra_required_bytes")
        if type(value) is int and value > 0:
            return value
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    candidates = [
        manifest_path.parent / "innounp/install_script.iss",
        cache / "fitgirl-installer/plans" / setup_hash / "innounp/install_script.iss",
    ]
    for path in candidates:
        if path.is_file():
            estimate = disk_space_from_iss(path)
            if estimate:
                return estimate["extra_required_bytes"]
    return None


def selected_repack_size(
    source: Path, manifest: dict[str, Any], components: set[str],
    options: set[str] | None = None,
) -> int | None:
    paths = {discover_setup(source)}
    for step in manifest.get("steps", []):
        if step.get("type") == "extract" and not step.get("archive_root") and enabled(step, components, options):
            paths.add(safe_child(source, step["archive"]))
    if not all(path.is_file() for path in paths):
        return None
    return sum(path.stat().st_size for path in paths)


def interactive_install(source: Path) -> int:
    """Collect every user-facing choice in the terminal; no CLI flags required."""
    source = source.expanduser().resolve()
    if not source.is_dir():
        raise InstallerError(f"diretório do repack não existe: {source}")
    wine = select_codec_runtime()
    setup_hash = sha256(discover_setup(source))
    explicit_manifest = os.environ.get("FITGIRL_MANIFEST")
    explicit_path = Path(explicit_manifest).expanduser().resolve() if explicit_manifest else None
    try:
        manifest_path, manifest = find_manifest(setup_hash, explicit_path)
    except InstallerError as error:
        if explicit_path is not None:
            raise
        print(f"[INFO] {error}")
        manifest_path, manifest = generate_manifest_draft(
            source, discover_setup(source), setup_hash
        )
        if manifest.get("semantic_blockers"):
            details = "; ".join(str(item) for item in manifest["semantic_blockers"])
            raise InstallerError(
                f"plano automático salvo em {manifest_path}, mas bloqueado por efeito externo: {details}"
            ) from error
        raise InstallerError(
            f"plano automático gerado em {manifest_path}, com "
            f"{len(manifest.get('steps', []))} etapas; instalação recusada porque "
            "condições e ações ainda não foram comprovadas"
        ) from error
    game_name = default_game_name(manifest, source)
    compacted_size = repack_size(source)
    estimate = declared_disk_space(manifest, manifest_path, setup_hash)
    destination_details = [
        f"Jogo: {game_name}",
        f"Origem: {source.name}",
        f"Arquivos compactados: {format_size(compacted_size)}",
        f"Espaço declarado pelo instalador: {format_size(estimate) if estimate else 'não informado'}",
        "O setup e o jogo não serão executados.",
    ]
    target = prompt_destination(game_name, wizard=True, details=destination_details)
    requested, disabled = prompt_components(manifest, source, wizard=True)

    srep_memory = None
    bzip3_threads = None
    cpus = None
    nice = 0
    memory_high = None
    memory_max = None
    quicksfv_x64 = discover_quicksfv_x64(source)
    limit_2gb = False
    limits = detect_limits()
    _wizard_page(3, "Desempenho", [
        "Automático é o recomendado. Ajustes manuais só são necessários em casos específicos.",
    ])
    if prompt_yes_no("Deseja limitar manualmente os recursos?", False):
        print(f"Disponível: {len(limits.cpus)} CPUs · até {limits.memory_budget_mib} MiB de memória para o instalador.")
        if limits.memory_budget_mib >= 2048:
            limit_2gb = prompt_yes_no("Usar o perfil de memória 2 GiB deste repack?", False)
        if limits.memory_budget_mib >= 128:
            srep_memory = prompt_positive_int(
                "Memória do SREP em MiB (somente esse descompressor)", minimum=128,
                maximum=limits.memory_budget_mib,
            )
        bzip3_threads = prompt_positive_int(
            "Threads BZip3 (somente esse codec)", len(limits.cpus),
            minimum=1, maximum=len(limits.cpus),
        )
        print("CPUs aplica-se a todos os codecs; é diferente das threads BZip3.")
        cpus = prompt_cpu_list(limits.cpus)
        nice = prompt_positive_int("Reduzir prioridade (nice, de 1 a 19)", minimum=1, maximum=19) or 0
        if limits.memory_budget_mib >= 512:
            memory_high = prompt_positive_int(
                "MemoryHigh em MiB (limite suave)", minimum=512,
                maximum=limits.memory_budget_mib,
            )
            memory_max = prompt_positive_int(
                "MemoryMax em MiB (limite rígido; pode reiniciar uma etapa)",
                minimum=max(512, memory_high or 512),
                maximum=limits.memory_budget_mib,
            )
        if memory_high and memory_max and memory_high > memory_max:
            raise InstallerError("MemoryHigh não pode exceder MemoryMax")

    work_id = target_work_id(target, setup_hash)
    scratch = target.parent / ".fitgirl-work" / work_id
    prefix = scratch / "wine-prefix"
    validate_external_game_target(target, prefix)
    components = parse_components(manifest, source, requested, disabled)

    selected_size = selected_repack_size(source, manifest, components, {"use2gb"} if limit_2gb else set())
    selected_labels = [
        _component_label(name, manifest.get("components", {}).get(name, {}))
        for name in sorted(components)
    ]
    resource_summary = "Automático (recomendado)"
    if any((srep_memory, bzip3_threads, cpus, nice, memory_high, memory_max, limit_2gb)):
        values = []
        if srep_memory is not None:
            values.append(f"SREP {srep_memory} MiB")
        if bzip3_threads is not None:
            values.append(f"BZip3 {bzip3_threads} threads")
        if cpus:
            values.append(f"CPUs {cpus}")
        if nice:
            values.append(f"nice {nice}")
        if memory_high is not None:
            values.append(f"MemoryHigh {memory_high} MiB")
        if memory_max is not None:
            values.append(f"MemoryMax {memory_max} MiB")
        if limit_2gb:
            values.append("perfil 2 GiB")
        resource_summary = ", ".join(values) or "Personalizado"
    review_details = [
        f"Jogo: {game_name}",
        f"Destino: {target}",
        f"Conteúdo: {', '.join(selected_labels) or 'somente arquivos principais'}",
        f"Dados selecionados: {format_size(selected_size) if selected_size is not None else 'há volumes ausentes'}",
        f"Recursos: {resource_summary}",
        "Validação: manifestos MD5/CRC internos",
    ]
    if estimate is not None:
        review_details.append(f"Espaço declarado pelo repack: {format_size(estimate)}")
    if target.exists():
        review_details.append("A pasta de destino já existe; confira se é a instalação pretendida.")
    _wizard_page(4, "Revisar e iniciar", review_details)
    print("A instalação é retomável. O jogo não será configurado para iniciar.")
    if not prompt_yes_no("Iniciar ou retomar agora?", True):
        print("Instalação cancelada; nenhum arquivo foi alterado.")
        return 0

    args = argparse.Namespace(
        source=source,
        target=target,
        scratch=scratch,
        manifest=manifest_path,
        wine=wine,
        prefix=prefix,
        backend=Path(os.environ.get("FITGIRL_BACKEND", ROOT / "libexec/fitgirl-extract")),
        component=requested,
        no_component=disabled,
        interactive=False,
        srep_memory=srep_memory,
        bzip3_threads=bzip3_threads,
        memory_high=memory_high,
        memory_max=memory_max,
        cpus=cpus,
        nice=nice,
        monitor_interval=10,
        quicksfv_x64=quicksfv_x64,
        limit_2gb=limit_2gb,
        dry_run=False,
    )
    return install(args)


def resolve_destination(value: str, target: Path, scratch: Path) -> Path:
    roots = {
        "app": target,
        "tmp": scratch / "setup-payload" / "tmp",
        "scratch": scratch,
        "payload_app": scratch / "setup-payload" / "app",
    }
    try:
        return roots[value]
    except KeyError as error:
        raise InstallerError(f"destino lógico desconhecido no manifesto: {value}") from error


def _payload_services() -> extractor.PayloadServices:
    """Bind the payload extraction to this module's helpers, looked up at call time."""
    return extractor.PayloadServices(
        sha256=sha256, wait_process=wait_process, forwarding_signals=forwarding_signals,
        default_innoextract=ROOT / "libexec/innoextract",
    )


def materialize_temporary_payload(
    manifest: dict[str, Any], setup: Path, scratch: Path,
    state_path: Path, state: dict[str, Any], dry_run: bool,
    innoextract: Path | None = None,
) -> None:
    extractor.materialize_temporary_payload(
        manifest, setup, scratch, state_path, state, dry_run, innoextract,
        services=_payload_services(),
    )


def materialize_application_payload(
    manifest: dict[str, Any], setup: Path, scratch: Path,
    state_path: Path, state: dict[str, Any], dry_run: bool,
    innoextract: Path | None = None,
) -> None:
    extractor.materialize_application_payload(
        manifest, setup, scratch, state_path, state, dry_run, innoextract,
        services=_payload_services(),
    )


def set_ini_value(path: Path, section_name: str, key: str, value: str) -> bool:
    """Update one INI value atomically while preserving encoding and newlines."""
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
        encoding = "utf-8"
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
        encoding = "cp1252"
    newline = "\r\n" if b"\r\n" in raw else "\n"
    trailing_newline = text.endswith(("\n", "\r"))
    lines = text.splitlines()
    section_index: int | None = None
    section_end = len(lines)
    for index, line in enumerate(lines):
        match = re.match(r"^\s*\[([^]]+)\]\s*$", line)
        if not match:
            continue
        if section_index is not None:
            section_end = index
            break
        if match.group(1).casefold() == section_name.casefold():
            section_index = index
    changed = False
    if section_index is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([f"[{section_name}]", f"{key}={value}"])
        changed = True
    else:
        for index in range(section_index + 1, section_end):
            match = re.match(r"^(\s*([^=;#]+?)\s*=\s*)(.*)$", lines[index])
            if not match or match.group(2).strip().casefold() != key.casefold():
                continue
            replacement = match.group(1) + value
            changed = replacement != lines[index]
            lines[index] = replacement
            break
        else:
            lines.insert(section_end, f"{key}={value}")
            changed = True
    if not changed:
        return False
    result = newline.join(lines) + (newline if trailing_newline else "")
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temporary.write_bytes(result.encode(encoding))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def expand_plan_constants(
    value: str, source: Path, target: Path, scratch: Path,
    prefix: Path, wine: Path,
) -> str:
    roots = {
        "app": target,
        "tmp": scratch / "setup-payload" / "tmp",
        "src": source,
    }

    def replace(match: re.Match[str]) -> str:
        return wine_path(roots[match.group(1).casefold()], prefix, wine)

    return re.sub(r"\{(app|tmp|src)\}", replace, value, flags=re.IGNORECASE)


def run_ini_write(
    step: dict[str, Any], args: argparse.Namespace, source: Path, target: Path,
    scratch: Path, prefix: Path, state_path: Path, state: dict[str, Any],
) -> None:
    root = resolve_destination(step.get("file_root", "tmp"), target, scratch)
    path = safe_child(root, step["file"])
    value = expand_plan_constants(
        str(step["value"]), source, target, scratch, prefix, args.wine
    )
    print(f"[INI] {path} [{step['section']}] {step['key']}={value}")
    if args.dry_run:
        return
    if not path.is_file():
        raise InstallerError(f"arquivo INI do payload ausente: {path}")
    set_ini_value(path, str(step["section"]), str(step["key"]), value)
    payload_files = state.get("payload", {}).get("files", {})
    payload_key = path.name.casefold()
    if payload_key in payload_files:
        payload_files[payload_key] = {
            "name": path.name,
            "size": path.stat().st_size,
            "sha256": sha256(path),
        }
        atomic_json(state_path, state)


def wine_path(path: Path, prefix: Path, wine: Path) -> str:
    absolute = path.resolve()
    drive_c = (prefix / "drive_c").resolve()
    try:
        relative = absolute.relative_to(drive_c)
        return "C:\\" + str(relative).replace("/", "\\")
    except ValueError:
        pass
    if str(absolute).startswith("/mnt/"):
        return "W:" + str(absolute)[4:].replace("/", "\\")
    winepath = wine.parent / "winepath"
    converter = [str(winepath)] if winepath.is_file() else [str(wine), "winepath.exe"]
    result = subprocess.run(
        [*converter, "-w", str(absolute)],
        env={**os.environ, "WINEPREFIX": str(prefix), "WINEDEBUG": "-all"},
        text=True,
        stdout=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        raise InstallerError(f"winepath não converteu {absolute}")
    return result.stdout.strip().replace("\r", "")


def command_prefix(args: argparse.Namespace) -> list[str]:
    command: list[str] = []
    if args.memory_high is not None or args.memory_max is not None:
        command.extend(["systemd-run", "--user", "--scope", "--quiet"])
        if args.memory_high is not None:
            command.extend(["-p", f"MemoryHigh={args.memory_high}M"])
        if args.memory_max is not None:
            command.extend(["-p", f"MemoryMax={args.memory_max}M"])
    if args.cpus:
        command.extend(["taskset", "--cpu-list", args.cpus])
    if args.nice != 0:
        command.extend(["nice", "-n", str(args.nice)])
    return command


def ensure_wine_prefix(
    wine: Path, prefix: Path, scratch: Path,
    state_path: Path, state: dict[str, Any], dry_run: bool,
) -> None:
    """Initialize Wine non-interactively and expose /mnt as the audited W: drive."""
    wineboot = wine.parent / "wineboot"
    if not (prefix / "system.reg").is_file():
        command = [str(wineboot), "-i"] if wineboot.is_file() else [str(wine), "wineboot.exe", "-i"]
        environment = {
            **os.environ,
            "WINEPREFIX": str(prefix),
            "WINEDEBUG": "-all",
            "WINEDLLOVERRIDES": "mscoree,mshtml=",
        }
        if sys.stdout.isatty():
            print("Preparando ambiente para os codecs…")
        else:
            print(f"[PREFIXO] inicializando {prefix}")
        if not dry_run:
            prefix.mkdir(parents=True, exist_ok=True)
        run_process(
            command, ROOT, state_path, state, dry_run, environment
        )
    link = prefix / "dosdevices" / "w:"
    if not sys.stdout.isatty():
        print(f"[PREFIXO] {link} -> /mnt")
    if dry_run:
        return
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_dir() and not link.is_symlink():
        raise InstallerError(f"dosdevice W: inesperadamente é diretório: {link}")
    link.unlink(missing_ok=True)
    link.symlink_to("/mnt")


def run_process(
    command: list[str], cwd: Path, state_path: Path, state: dict[str, Any],
    dry_run: bool, environment: dict[str, str] | None = None,
    success_codes: tuple[int, ...] = (0,),
) -> None:
    if sys.stdout.isatty():
        print("Executando etapa auxiliar…")
    else:
        print("[EXEC]", shlex.join(command))
    if dry_run:
        return
    with forwarding_signals() as forwarder:
        process = subprocess.Popen(command, cwd=cwd, env=environment, start_new_session=True)
        forwarder.attach(process)
        state["active"] = {"pid": process.pid, "pgid": process.pid, "command": command, "started_at": time.time()}
        atomic_json(state_path, state)
        returncode = wait_process(process, state_path, state)
    if returncode not in success_codes:
        raise InstallerError(f"etapa encerrou com código {returncode}")


class SignalForwarder:
    """Forward SIGINT/SIGTERM to a child's group across its whole journaled life.

    A signal that arrives before the child exists is held and forwarded as
    soon as it starts; one that arrives after the child ended is delivered
    again when the forwarding stops, so an interruption is never lost.
    """

    def __init__(self) -> None:
        self.process: subprocess.Popen[Any] | None = None
        self.pending: list[int] = []
        self.after_exit: list[int] = []

    def __call__(self, requested: int, _frame: Any) -> None:
        if self.process is None:
            self.pending.append(requested)
        elif self.process.poll() is not None:
            self.after_exit.append(requested)
        else:
            self._forward(requested)

    def _forward(self, requested: int) -> None:
        assert self.process is not None
        name = signal.Signals(requested).name
        print(f"[AVISO] {name} recebido; encerrando o grupo ativo {self.process.pid}")
        try:
            os.killpg(self.process.pid, requested)
        except ProcessLookupError:
            pass

    def attach(self, process: subprocess.Popen[Any]) -> None:
        self.process = process
        for requested in self.pending:
            self._forward(requested)
        self.pending.clear()


@contextlib.contextmanager
def forwarding_signals():
    """Install a SignalForwarder before a child starts and keep it until its journal entry is cleared."""
    forwarder = SignalForwarder()
    previous = {
        requested: signal.signal(requested, forwarder)
        for requested in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        yield forwarder
    finally:
        for requested, handler in previous.items():
            signal.signal(requested, handler)
    for requested in forwarder.pending + forwarder.after_exit:
        signal.raise_signal(requested)


def wait_process(
    process: subprocess.Popen[Any], state_path: Path, state: dict[str, Any]
) -> int:
    previous_handlers: dict[signal.Signals, Any] = {}

    def forward(requested: int, _frame: Any) -> None:
        name = signal.Signals(requested).name
        print(f"[AVISO] {name} recebido; encerrando o grupo ativo {process.pid}")
        try:
            os.killpg(process.pid, requested)
        except ProcessLookupError:
            pass

    for requested in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[requested] = signal.signal(requested, forward)
    try:
        return process.wait()
    finally:
        for requested, previous in previous_handlers.items():
            signal.signal(requested, previous)
        state["active"] = None
        atomic_json(state_path, state)


def run_extract(
    step: dict[str, Any], args: argparse.Namespace, source: Path, target: Path,
    scratch: Path, prefix: Path, state_path: Path, state: dict[str, Any],
    global_base: float = 0.0, global_weight: float = 1.0,
    payload_ready: bool = False,
) -> None:
    extractor.run_extract(
        step, args, source, target, scratch, prefix, state_path, state,
        global_base, global_weight, payload_ready,
        services=extractor.ExtractionServices(
            resolve_destination=resolve_destination, safe_child=safe_child,
            verify_source=lambda planned: verify_archive(planned, args, source, state_path, state),
            command_prefix=lambda: command_prefix(args), run_process=run_process,
            working_directory=ROOT,
        ),
    )


def verify_archive(
    step: dict[str, Any], args: argparse.Namespace, source: Path,
    state_path: Path, state: dict[str, Any]
) -> Path:
    return checksums.verify_archive(
        step, source, state_path, state, args.dry_run,
        safe_child=safe_child, save_state=atomic_json,
    )


def run_batch(
    step: dict[str, Any], args: argparse.Namespace, target: Path, scratch: Path,
    prefix: Path, state_path: Path, state: dict[str, Any]
) -> None:
    script_root = resolve_destination(step.get("script_root", "tmp"), target, scratch)
    script = safe_child(script_root, step["script"])
    if not script.is_file() and not args.dry_run:
        raise InstallerError(f"pós-processamento ausente: {script}")
    cwd_root = resolve_destination(step.get("cwd", "app"), target, scratch)
    cwd = safe_child(cwd_root, step.get("cwd_suffix", ""))
    if not args.dry_run:
        cwd.mkdir(parents=True, exist_ok=True)
    script_argument = str(script) if args.dry_run else wine_path(script, prefix, args.wine)
    command = command_prefix(args) + [
        str(args.wine), "cmd.exe", "/d", "/c", "call", script_argument
    ]
    environment = os.environ.copy()
    environment.update({"WINEPREFIX": str(prefix), "WINEDEBUG": "-all"})
    if sys.stdout.isatty():
        print("Executando pós-processamento…")
    else:
        print("[EXEC]", shlex.join(command), f"(cwd={cwd})")
    if args.dry_run:
        return
    with forwarding_signals() as forwarder:
        process = subprocess.Popen(command, cwd=cwd, env=environment, start_new_session=True)
        forwarder.attach(process)
        state["active"] = {"pid": process.pid, "pgid": process.pid, "command": command, "started_at": time.time()}
        atomic_json(state_path, state)
        returncode = wait_process(process, state_path, state)
    if returncode:
        raise InstallerError(f"script {script.name} encerrou com código {returncode}")


def run_exec(
    step: dict[str, Any], args: argparse.Namespace, target: Path, scratch: Path,
    prefix: Path, state_path: Path, state: dict[str, Any]
) -> None:
    executable_root = resolve_destination(step.get("executable_root", "tmp"), target, scratch)
    executable = safe_child(executable_root, step["executable"])
    if not executable.is_file() and not args.dry_run:
        raise InstallerError(f"executável de pós-processamento ausente: {executable}")
    cwd = resolve_destination(step.get("cwd", "app"), target, scratch)
    if step.get("cwd_suffix"):
        cwd = safe_child(cwd, step["cwd_suffix"])
    executable_argument = str(executable) if args.dry_run else wine_path(executable, prefix, args.wine)
    command = command_prefix(args) + [str(args.wine), executable_argument]
    command.extend(str(value) for value in step.get("args", []))
    environment = os.environ.copy()
    environment.update({"WINEPREFIX": str(prefix), "WINEDEBUG": "-all"})
    run_process(command, cwd, state_path, state, args.dry_run, environment)
    if args.dry_run:
        return
    for relative in step.get("delete_after", []):
        candidate = safe_child(cwd, relative)
        if candidate.is_dir():
            raise InstallerError(f"delete_after aceita somente arquivos: {candidate}")
        candidate.unlink(missing_ok=True)


def windows_argv(command_line: str) -> list[str]:
    """Parse the quoting rules used by CommandLineToArgvW."""
    result: list[str] = []
    index = 0
    while index < len(command_line):
        while index < len(command_line) and command_line[index] in " \t":
            index += 1
        if index >= len(command_line):
            break
        argument: list[str] = []
        quoted = False
        while index < len(command_line):
            if command_line[index] in " \t" and not quoted:
                break
            backslashes = 0
            while index < len(command_line) and command_line[index] == "\\":
                backslashes += 1
                index += 1
            if index < len(command_line) and command_line[index] == '"':
                argument.extend("\\" * (backslashes // 2))
                if backslashes % 2:
                    argument.append('"')
                else:
                    quoted = not quoted
                index += 1
                continue
            argument.extend("\\" * backslashes)
            if index < len(command_line) and not (
                command_line[index] in " \t" and not quoted
            ):
                argument.append(command_line[index])
                index += 1
        result.append("".join(argument))
    return result


def isexec_command(
    step: dict[str, Any], args: argparse.Namespace, source: Path, target: Path,
    scratch: Path, prefix: Path,
) -> list[str]:
    executable = str(step["executable"])
    environment_roots = (source, target, scratch, prefix, args.wine)
    if executable.casefold() == "{cmd}":
        expression_parts: list[str] = []
        for part in step.get("parameter_expression", []):
            expanded = expand_plan_constants(
                str(part["value"]), *environment_roots
            )
            if part.get("operation") == "expanded_quoted":
                if '"' in expanded:
                    raise InstallerError(
                        "ISExec contém aspas internas em expanded_quoted"
                    )
                expanded = f'"{expanded}"'
            expression_parts.append(expanded)
        expression = "".join(expression_parts)
        if not expression:
            raise InstallerError("ISExec {cmd} sem expressão de parâmetros comprovada")
        if expression[:3].casefold() == "/c ":
            expression = expression[3:]
        return command_prefix(args) + [
            str(args.wine), "cmd.exe", "/d", "/s", "/c",
            *windows_argv(expression),
        ]
    expanded_executable = expand_plan_constants(
        executable, *environment_roots
    )
    parameters = expand_plan_constants(
        str(step.get("parameters") or ""), *environment_roots
    )
    if executable.casefold().endswith((".bat", ".cmd")):
        return command_prefix(args) + [
            str(args.wine), "cmd.exe", "/d", "/s", "/c", "call",
            expanded_executable, *windows_argv(parameters),
        ]
    return command_prefix(args) + [
        str(args.wine), expanded_executable, *windows_argv(parameters),
    ]


def transaction_paths(
    step: dict[str, Any], target: Path, scratch: Path
) -> list[Path]:
    result: list[Path] = []
    for item in step.get("rollback_paths", []):
        root = resolve_destination(str(item["root"]), target, scratch)
        pattern = str(item["path"])
        if item.get("glob"):
            for candidate in root.glob(pattern):
                resolved = candidate.resolve()
                safe_child(root, str(resolved.relative_to(root.resolve())))
                result.append(resolved)
        else:
            result.append(safe_child(root, pattern))
    unique: dict[str, Path] = {}
    for path in result:
        unique[str(path)] = path
    return list(unique.values())


def begin_transaction(
    key: str, step: dict[str, Any], target: Path, scratch: Path,
    state_path: Path, state: dict[str, Any], dry_run: bool,
) -> None:
    journal.begin_transaction(
        key, step, scratch, state_path, state, dry_run,
        mutable_paths=lambda: transaction_paths(step, target, scratch),
    )


def fart_expected_outputs(
    parameters: str, cwd: Path,
) -> tuple[int, dict[Path, bytes]]:
    """Prove the output of the supported ASCII whole-word FART invocation."""
    values = windows_argv(parameters)
    if len(values) != 4 or values[0] != "-w" or values[1] not in {"*.txt", "*.bat"}:
        raise InstallerError("invocação FART não comprovada")
    try:
        needle, replacement = (value.encode("ascii") for value in values[2:])
    except UnicodeEncodeError as error:
        raise InstallerError("FART: codificação não comprovada") from error
    if not needle:
        raise InstallerError("FART: padrão vazio")
    pattern = re.compile(rb"(?<![A-Za-z0-9_])" + re.escape(needle) + rb"(?![A-Za-z0-9_])")
    count = 0
    outputs = {}
    for path in cwd.glob(values[1]):
        if not path.is_file() or path.is_symlink():
            raise InstallerError(f"FART: arquivo não regular: {path}")
        original = path.read_bytes()
        if b"\0" in original:
            raise InstallerError(f"FART: arquivo binário inesperado: {path}")
        updated, changes = pattern.subn(lambda _match: replacement, original)
        count += changes
        outputs[path] = updated
    return count, outputs


def run_isexec(
    key: str, step: dict[str, Any], args: argparse.Namespace, source: Path,
    target: Path, scratch: Path, prefix: Path, state_path: Path,
    state: dict[str, Any],
) -> None:
    # Some installers repeat DeleteInput through a subsequent cmd /C del.
    # Recognize only a single literal filename, with an exact audited rollback
    # scope; never interpret arbitrary shell syntax as a native deletion.
    if step.get("executable") == "{cmd}" and step.get("parameter_expression"):
        expression = "".join(str(part["value"]) for part in step["parameter_expression"])
        deletion = re.fullmatch(r"/C\s+del\s+([A-Za-z0-9_-][A-Za-z0-9_.-]*)", expression, re.I)
        if deletion and not step.get("cwd_suffix"):
            filename = deletion.group(1)
            root = step.get("cwd", "app")
            if step.get("rollback_paths") != [{"path": filename, "root": root}]:
                raise InstallerError("cmd del: escopo de rollback não comprovado")
            run_delete(
                key, {"type": "delete-file", "path": filename, "path_root": root},
                target, scratch, state_path, state, args.dry_run,
            )
            return
    cwd = resolve_destination(step.get("cwd", "app"), target, scratch)
    if step.get("cwd_suffix"):
        cwd = safe_child(cwd, step["cwd_suffix"])
    if not args.dry_run:
        cwd.mkdir(parents=True, exist_ok=True)
    command = isexec_command(step, args, source, target, scratch, prefix)
    begin_transaction(key, step, target, scratch, state_path, state, args.dry_run)
    environment = {**os.environ, "WINEPREFIX": str(prefix), "WINEDEBUG": "-all"}
    try:
        if str(step.get("executable", "")).replace("\\", "/").rsplit("/", 1)[-1].casefold() == "fart.exe" and not args.dry_run:
            parameters = expand_plan_constants(
                str(step["parameters"]), source, target, scratch, prefix, args.wine
            )
            count, outputs = fart_expected_outputs(parameters, cwd)
            print(f"[FART] {count} substituições esperadas; retorno={count & 255}")
            run_process(
                command, cwd, state_path, state, False, environment,
                success_codes=(count & 255,),
            )
            for path, expected in outputs.items():
                if path.read_bytes() != expected:
                    raise InstallerError(f"FART: pós-condição divergente: {path}")
        else:
            run_process(command, cwd, state_path, state, args.dry_run, environment)
    except BaseException:
        if not args.dry_run:
            restore_transaction(key, target, scratch, state_path, state)
        raise
    if not args.dry_run:
        state["transactions"][key]["status"] = "committed"
        atomic_json(state_path, state)


def run_delete(
    key: str, step: dict[str, Any], target: Path, scratch: Path,
    state_path: Path, state: dict[str, Any], dry_run: bool,
) -> None:
    root = resolve_destination(step.get("path_root", "app"), target, scratch)
    path = safe_child(root, step["path"])
    expected_directory = step["type"] == "delete-tree"
    print(f"[QUARENTENA] {path}")
    if dry_run:
        return
    if path.exists() and path.is_dir() != expected_directory:
        raise InstallerError(f"tipo inesperado para remoção: {path}")
    quarantine = scratch / "transactions" / key.replace(":", "-") / "deleted"
    if quarantine.exists():
        if path.exists():
            raise InstallerError(f"origem e quarentena coexistem: {path}")
        return
    record = {
        "kind": "delete", "status": "committed", "entries": [],
        "root": str(quarantine.parent), "started_at": time.time(),
    }
    if path.exists():
        quarantine.parent.mkdir(parents=True, exist_ok=True)
        os.replace(path, quarantine)
        record["entries"].append({
            "path": str(path), "existed": True, "backup": str(quarantine),
        })
    state.setdefault("transactions", {})[key] = record
    atomic_json(state_path, state)


def run_copy(step: dict[str, Any], target: Path, scratch: Path, dry_run: bool) -> None:
    source_root = resolve_destination(step.get("source_root", "scratch"), target, scratch)
    destination_root = resolve_destination(step.get("destination_root", "app"), target, scratch)
    source = safe_child(source_root, step["source"])
    destination = safe_child(destination_root, step["destination"])
    print(f"[COPY] {source} -> {destination}")
    if dry_run:
        return
    if not source.is_file():
        raise InstallerError(f"arquivo de pós-processamento ausente: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if step.get("delete_source"):
        source.unlink()


def run_manifest_merge(
    key: str, step: dict[str, Any], args: argparse.Namespace, target: Path,
    scratch: Path, state_path: Path, state: dict[str, Any],
) -> None:
    """Compile the known FitGirl addon merge natively, preserving originals."""
    if (
        step.get("embedded_command", "").strip().casefold()
        != "copy /b fitgirl.md5+*.addon&&del *.addon"
        or step.get("cwd") != "app" or step.get("cwd_suffix") != "_Redist"
        or step.get("rollback_paths") != [{"root": "app", "path": "_Redist"}]
    ):
        raise InstallerError("combinação de manifestos não comprovada")
    print("[MANIFESTOS] combinar base e addons presentes, preservando originais")
    if args.dry_run:
        return
    parts = manifests.manifest_parts(
        scratch / "setup-payload/app/_Redist", target, state.get("components", []),
        safe_child=safe_child,
    )
    base = parts[0]
    begin_transaction(key, step, target, scratch, state_path, state, False)
    try:
        preserve_verifier(target, scratch, False)
        destination = target / "_Redist"
        shutil.copy2(base, destination / "fitgirl.base.md5")
        manifests.write_combined_manifest(parts, destination)
    except BaseException:
        restore_transaction(key, target, scratch, state_path, state)
        raise
    state["transactions"][key]["status"] = "committed"
    atomic_json(state_path, state)


def preserve_verifier(
    target: Path, scratch: Path, dry_run: bool,
    quicksfv_x64: Path | None = None,
    preserve_existing_manifest: bool = False,
) -> None:
    """Keep FitGirl's original verifier beside its relative-path manifests."""
    if quicksfv_x64 is not None:
        quicksfv_x64 = quicksfv_x64.resolve()
        if not quicksfv_x64.is_file():
            raise InstallerError(f"QuickSFV x64 externo ausente: {quicksfv_x64}")
        if pe_machine(quicksfv_x64) != 0x8664:
            raise InstallerError(f"QuickSFV x64 externo não é PE32+ x86-64: {quicksfv_x64}")
    source_dir = scratch / "setup-payload" / "app" / "_Redist"
    if not source_dir.is_dir():
        print("[AVISO] payload _Redist ausente; verificador original não foi preservado")
        return
    selected = [
        path for path in source_dir.iterdir()
        if path.is_file() and (
            path.name.casefold() in {"quicksfv.exe", "quicksfv.ini", "fitgirl.md5"}
            or path.suffix.casefold() == ".addon"
        )
    ]
    if not selected:
        print("[AVISO] este setup não contém QuickSFV/manifestos para preservar")
        return
    destination_dir = target / "_Redist"
    for source in sorted(selected, key=lambda path: path.name.casefold()):
        destination = safe_child(destination_dir, source.name)
        if preserve_existing_manifest and source.name.casefold() == "fitgirl.md5" and destination.is_file():
            print(f"[VERIFICADOR] mantendo manifesto combinado validado: {destination}")
            continue
        effective_source = (
            quicksfv_x64
            if source.name.casefold() == "quicksfv.exe" and quicksfv_x64 is not None
            else source
        )
        if (
            source.name.casefold() == "quicksfv.exe"
            and quicksfv_x64 is None
            and destination.is_file()
            and pe_machine(source) == 0x014C
            and pe_machine(destination) == 0x8664
        ):
            print(f"[VERIFICADOR] mantendo QuickSFV x64 compatível: {destination}")
            continue
        print(f"[VERIFICADOR] {effective_source} -> {destination}")
        if dry_run:
            continue
        destination_dir.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp-{os.getpid()}")
        try:
            shutil.copy2(effective_source, temporary)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)


def run_verify(
    step: dict[str, Any], args: argparse.Namespace, target: Path, scratch: Path,
    state_path: Path, state: dict[str, Any]
) -> None:
    manifest_root = resolve_destination(step.get("manifest_root", "payload_app"), target, scratch)
    md5_manifest = safe_child(manifest_root, step["manifest"])
    if not args.dry_run and not md5_manifest.is_file():
        raise InstallerError(f"manifesto de integridade ausente: {md5_manifest}")
    verify_root = resolve_destination(step.get("root", "app"), target, scratch)
    verification_state = scratch / "verification" / f"{step.get('id', 'files')}.json"
    command = command_prefix(args) + [
        sys.executable, str(ROOT / "src/fitgirl_installer/verify.py"),
        "--root", str(verify_root), "--manifest", str(md5_manifest),
        "--state", str(verification_state),
    ]
    run_process(command, ROOT, state_path, state, args.dry_run)


def inspect(args: argparse.Namespace) -> int:
    source = args.source.resolve()
    setup = discover_setup(source)
    setup_hash = sha256(setup)
    print(f"setup.exe: {setup}")
    print(f"SHA-256:   {setup_hash}")
    try:
        path, manifest = find_manifest(setup_hash, args.manifest)
    except InstallerError as error:
        print(f"Plano:     não reconhecido ({error})")
        print("Volumes:")
        for archive in sorted(source.glob("fg-*.bin")):
            print(f"  - {archive.name} ({archive.stat().st_size} bytes)")
        return 1
    print(f"Plano:     {path}")
    print(f"Jogo:      {manifest.get('name', 'desconhecido')}")
    print("Componentes:")
    for name, data in manifest.get("components", {}).items():
        availability = data.get("available_if")
        available = not availability or (source / availability).is_file()
        print(f"  - {name}: {data.get('description', '')} [disponível={str(available).lower()}]")
    print("Etapas:")
    for index, step in enumerate(manifest.get("steps", []), 1):
        item = step.get("archive", step.get("script", step.get("executable", step.get("manifest", ""))))
        destination = step.get("destination", step.get("cwd", step.get("root", "")))
        print(f"  {index}. {step.get('type')} {item} -> {destination}")
    return 0


def _step_handlers(
    args: argparse.Namespace, manifest: dict[str, Any], source: Path, target: Path,
    scratch: Path, prefix: Path, state_path: Path, state: dict[str, Any],
) -> dict[str, Any]:
    """Adapt each step type to the function that runs it, as install() did inline."""

    def extract(run: installer.StepRun) -> None:
        run_extract(
            run.step, args, source, target, scratch, prefix, state_path, state,
            run.global_base, run.global_weight,
            bool(manifest.get("temporary_payload_files")),
        )

    def delete(run: installer.StepRun) -> None:
        run_delete(run.key, run.step, target, scratch, state_path, state, args.dry_run)

    return {
        "extract": extract,
        "batch": lambda run: run_batch(run.step, args, target, scratch, prefix, state_path, state),
        "exec": lambda run: run_exec(run.step, args, target, scratch, prefix, state_path, state),
        "isexec": lambda run: run_isexec(
            run.key, run.step, args, source, target, scratch, prefix, state_path, state,
        ),
        "delete-file": delete,
        "delete-tree": delete,
        "copy": lambda run: run_copy(run.step, target, scratch, args.dry_run),
        "merge-manifests": lambda run: run_manifest_merge(
            run.key, run.step, args, target, scratch, state_path, state,
        ),
        "ini-write": lambda run: run_ini_write(
            run.step, args, source, target, scratch, prefix, state_path, state,
        ),
        "verify": lambda run: run_verify(run.step, args, target, scratch, state_path, state),
    }


def _install_services() -> installer.InstallServices:
    """Bind the coordination to this module's helpers, looked up at call time."""
    return installer.InstallServices(
        save_state=atomic_json, validate_runtime_order=validate_runtime_order,
        record_runtime_completion=record_runtime_completion,
        recover_incomplete_transactions=recover_incomplete_transactions,
        ensure_wine_prefix=ensure_wine_prefix, discover_setup=discover_setup,
        materialize_temporary_payload=materialize_temporary_payload,
        materialize_application_payload=materialize_application_payload,
        component_label=_component_label, resolve_destination=resolve_destination,
        safe_child=safe_child, preserve_verifier=preserve_verifier,
        write_integration_report=write_integration_report,
        finalize_transactions=finalize_transactions, error_type=InstallerError,
    )


def install(args: argparse.Namespace) -> int:
    source, target, scratch, prefix = map(Path.resolve, (args.source, args.target, args.scratch, args.prefix))
    validate_external_game_target(target, prefix)
    setup_hash = sha256(discover_setup(source))
    manifest_path, manifest = find_manifest(setup_hash, args.manifest)
    if args.interactive:
        interactive_requested, interactive_disabled = prompt_components(manifest, source)
        args.component.extend(interactive_requested)
        args.no_component.extend(interactive_disabled)
    components = parse_components(manifest, source, args.component, args.no_component)
    options = {"use2gb"} if getattr(args, "limit_2gb", False) else set()
    plan_hash = manifest_hash(manifest)
    state_path = scratch / "install-state.json"
    expected = initial_state(setup_hash, plan_hash, source, target, components, args)
    state = journal.resume_or_start(state_path, expected)
    installer.run_installation(
        installer.InstallRequest(
            source=source, target=target, scratch=scratch, prefix=prefix,
            manifest_path=manifest_path, manifest=manifest, components=components,
            options=options, state_path=state_path, state=state, wine=args.wine,
            dry_run=args.dry_run, memory_max=args.memory_max, quicksfv_x64=args.quicksfv_x64,
        ),
        handlers=_step_handlers(args, manifest, source, target, scratch, prefix, state_path, state),
        verify_source=lambda step: verify_archive(step, args, source, state_path, state),
        services=_install_services(),
    )
    return 0


def signal_active(args: argparse.Namespace, requested_signal: signal.Signals) -> int:
    state = load_state(args.scratch.resolve() / "install-state.json")
    active = state.get("active")
    if not active:
        raise InstallerError("não há etapa ativa registrada")
    try:
        os.killpg(int(active["pgid"]), requested_signal)
    except ProcessLookupError as error:
        raise InstallerError("o grupo de processos registrado não existe mais") from error
    print(f"[INFO] sinal {requested_signal.name} enviado ao grupo {active['pgid']}")
    return 0


def status(args: argparse.Namespace) -> int:
    path = args.scratch.resolve() / "install-state.json"
    state = load_state(path)
    print(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


_ENTRYPOINT_EXPORTS = {"_run", "main", "parser", "select_language"}


def __getattr__(name: str) -> Any:
    if name not in _ENTRYPOINT_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    entrypoint = import_module(".main", __name__)
    for exported_name in _ENTRYPOINT_EXPORTS:
        globals()[exported_name] = getattr(entrypoint, exported_name)
    return globals()[name]
