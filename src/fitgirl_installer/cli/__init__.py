#!/usr/bin/env python3
"""Interactive standalone installer for FitGirl repacks on Linux."""

from __future__ import annotations

import argparse
import functools
import hashlib
import fcntl
from importlib import import_module
import json
import os
import re
import shutil
import shlex
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from ..ifps_ir import SCHEMA_VERSION as IFPS_IR_SCHEMA_VERSION, write_cfg_report
from ..compatibility import compatibility_error, report_json
from ..integration import write_integration_report
from ..planner import PLAN_COMPILER_VERSION, write_manifest
from ..planning import analyzer
from ..planning.analyzer import disk_space_from_iss
from ..plan_audit import write_audit
from ..runtime import RuntimeErrorDetail, ensure_bundled_wine
from ..resource_limits import detect_limits, parse_cpu_list
from .presentation import _wizard_page, _component_label, format_size
from . import menus
from .menus import (
    DestinationMenuServices, prompt_components, prompt_yes_no, prompt_path,
    prompt_positive_int, prompt_cpu_list,
)


ROOT = Path(__file__).resolve().parents[3]
MANIFEST_DIR = ROOT / "manifests"
STATE_VERSION = 1


class InstallerError(RuntimeError):
    pass


def file_hash(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256(path: Path) -> str:
    return file_hash(path, "sha256")


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


def atomic_json(path: Path, value: dict[str, Any]) -> None:
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
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InstallerError(f"não foi possível ler {path}: {error}") from error
    if not isinstance(value, dict):
        raise InstallerError(f"objeto JSON esperado em {path}")
    return value


def load_state(path: Path) -> dict[str, Any]:
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


def discover_setup(source: Path) -> Path:
    matches = [path for path in source.iterdir() if path.name.lower() == "setup.exe"]
    if len(matches) != 1:
        raise InstallerError(f"esperado um setup.exe em {source}; encontrados: {len(matches)}")
    return matches[0]


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
    candidates: list[Path] = []
    configured = os.environ.get("FITGIRL_WINE_BIN")
    if configured:
        selected = Path(configured).expanduser().resolve()
        if not selected.is_file() or not os.access(selected, os.X_OK):
            raise InstallerError(f"override de desenvolvimento FITGIRL_WINE_BIN inválido: {selected}")
        return [selected]
    try:
        bundled = ensure_bundled_wine(ROOT)
    except RuntimeErrorDetail as error:
        raise InstallerError(str(error)) from error
    if bundled is not None:
        return [bundled]
    mnt = Path("/mnt")
    if mnt.is_dir():
        candidates.extend(sorted(mnt.glob("*/Tools/fitgirl-wine/*/bin/wine")))
    system_wine = shutil.which("wine")
    if system_wine:
        candidates.append(Path(system_wine))
    steam_roots = [
        Path.home() / ".steam/root", Path.home() / ".steam/steam",
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "Steam",
        Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
    ]
    for steam in steam_roots:
        for pattern in (
            "compatibilitytools.d/*/files/bin/wine", "compatibilitytools.d/*/dist/bin/wine",
            "steamapps/common/Proton*/files/bin/wine", "steamapps/common/Proton*/dist/bin/wine",
        ):
            candidates.extend(sorted(steam.glob(pattern)))
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen and resolved.is_file() and os.access(resolved, os.X_OK):
            seen.add(resolved)
            unique.append(resolved)
    return unique


def select_codec_runtime() -> Path:
    """No technical runtime prompt in the normal extraction workflow."""
    candidates = discover_wine()
    for wine in candidates:
        try:
            result = subprocess.run(
                [str(wine), "--version"], text=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=10, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            return wine
    raise InstallerError(
        "nenhum Wine/Proton utilizável foi encontrado. Instale Wine/Proton "
        "compatível ou configure FITGIRL_WINE_BIN para um executável existente"
    )


def discover_analysis_tool(environment: str, bundled_name: str, command: str) -> Path | None:
    return analyzer.discover_analysis_tool(
        environment, bundled_name, command, root=ROOT, pe_machine=pe_machine,
    )


def wine_z_path(path: Path) -> str:
    return "Z:" + str(path.resolve()).replace("/", "\\")


def _refresh_analysis_audit(
    candidate: dict[str, Any], iss: Path, disassembly: Path, compiled: Path,
    analysis: Path, manifest_path: Path,
) -> None:
    report = write_audit(
        candidate, iss, disassembly, compiled, analysis / "plan-audit.json",
        disassembler=discover_analysis_tool(
            "FITGIRL_IFPS_DISASSEMBLER", "pascalscript", "pascalscript"
        ),
    )
    analyzer.apply_semantic_blockers(candidate, report)
    atomic_json(manifest_path, candidate)


def generate_manifest_draft(source: Path, setup: Path, setup_hash: str) -> tuple[Path, dict[str, Any]]:
    """Analyze an unknown setup without executing it and cache all review evidence."""
    cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    analysis = cache_root / "fitgirl-installer" / "plans" / setup_hash
    extracted = analysis / "innounp"
    iss = extracted / "install_script.iss"
    compiled = extracted / "embedded" / "CompiledCode.bin"
    disassembly = analysis / "CompiledCode.disassembly.txt"
    control_flow = analysis / "control-flow.json"
    manifest_path = analysis / "manifest.draft.json"

    cached_manifest = load_json(manifest_path) if manifest_path.is_file() else {}
    disassembly_current = (
        disassembly.is_file()
        and cached_manifest.get("analysis", {}).get("disassembly_sha256")
        == sha256(disassembly)
    )
    compiler_current = cached_manifest.get("compiler_version") == PLAN_COMPILER_VERSION
    control_flow_current = (
        control_flow.is_file()
        and load_json(control_flow).get("schema") == IFPS_IR_SCHEMA_VERSION
    )
    if (
        manifest_path.is_file() and iss.is_file() and compiled.is_file()
        and disassembly.is_file() and control_flow_current and disassembly_current
        and compiler_current
    ):
        manifest = cached_manifest
        if setup_hash in manifest.get("setup_sha256", []):
            _refresh_analysis_audit(
                manifest, iss, disassembly, compiled, analysis, manifest_path,
            )
            return manifest_path, manifest
    if (
        manifest_path.is_file() and iss.is_file() and compiled.is_file()
        and disassembly.is_file()
        and (not control_flow_current or not disassembly_current or not compiler_current)
    ):
        previous_manifest = cached_manifest
        if setup_hash in previous_manifest.get("setup_sha256", []):
            cfg = write_cfg_report(disassembly, control_flow)
            manifest = write_manifest(iss, disassembly, setup, source, manifest_path)
            manifest["analysis"] = previous_manifest.get("analysis", {})
            manifest.setdefault("analysis", {}).update({
                "iss_sha256": sha256(iss),
                "compiled_code_sha256": sha256(compiled),
                "disassembly_sha256": sha256(disassembly),
                "control_flow_sha256": sha256(control_flow),
                "control_flow_totals": cfg["totals"],
            })
            current_disassembler = discover_analysis_tool(
                "FITGIRL_IFPS_DISASSEMBLER", "pascalscript", "pascalscript"
            )
            if current_disassembler is not None:
                manifest["analysis"]["ifps_disassembler_sha256"] = sha256(current_disassembler)
            atomic_json(manifest_path, manifest)
            _refresh_analysis_audit(
                manifest, iss, disassembly, compiled, analysis, manifest_path,
            )
            return manifest_path, manifest

    innounp = discover_analysis_tool("FITGIRL_INNOUNP", "innounp.exe", "innounp")
    disassembler = discover_analysis_tool(
        "FITGIRL_IFPS_DISASSEMBLER", "pascalscript", "pascalscript"
    )
    missing = []
    if innounp is None:
        missing.append("innounp (FITGIRL_INNOUNP)")
    if disassembler is None:
        missing.append("disassembler IFPS (FITGIRL_IFPS_DISASSEMBLER)")
    if missing:
        raise InstallerError(
            "setup desconhecido e ferramentas de análise ausentes: " + ", ".join(missing)
        )

    analysis.mkdir(parents=True, exist_ok=True)
    extracted.mkdir(parents=True, exist_ok=True)
    extract_log = analysis / "innounp.log"
    if pe_machine(innounp) is not None:
        wines = discover_wine()
        if not wines:
            raise InstallerError("innounp é PE, mas nenhum Wine foi encontrado para a análise")
        wine = wines[0]
        prefix = Path(
            os.environ.get(
                "FITGIRL_ANALYSIS_PREFIX",
                cache_root / "fitgirl-installer" / "analysis-wine-prefix",
            )
        ).expanduser().resolve()
        command = [
            str(wine), str(innounp), "-x", "-b", "-q", "-m", "-y",
            f"-d{wine_z_path(extracted)}", wine_z_path(setup),
            "install_script.iss", "embedded\\CompiledCode.bin",
        ]
        environment = os.environ.copy()
        environment.update({
            "WINEPREFIX": str(prefix),
            "WINEDEBUG": environment.get("WINEDEBUG", "-all"),
            "WINEDLLOVERRIDES": environment.get("WINEDLLOVERRIDES", "mscoree,mshtml="),
        })
    else:
        command = [
            str(innounp), "-x", "-b", "-q", "-m", "-y", f"-d{extracted}",
            str(setup), "install_script.iss", "embedded\\CompiledCode.bin",
        ]
        environment = os.environ.copy()
    try:
        completed = subprocess.run(
            command, env=environment, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=300, check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise InstallerError(f"innounp excedeu 300 s; evidência mantida em {analysis}") from error
    extract_log.write_text(completed.stdout or "", encoding="utf-8")
    if completed.returncode != 0 or not iss.is_file() or not compiled.is_file():
        raise InstallerError(
            f"innounp não produziu ISS/CompiledCode.bin; veja {extract_log}"
        )

    disassembly_log = analysis / "pascalscript.stderr.log"
    try:
        with disassembly.open("w", encoding="utf-8") as output, disassembly_log.open(
            "w", encoding="utf-8"
        ) as errors:
            completed = subprocess.run(
                [str(disassembler), str(compiled)], stdout=output, stderr=errors,
                text=True, timeout=120, check=False,
            )
    except subprocess.TimeoutExpired as error:
        raise InstallerError(f"disassembler IFPS excedeu 120 s; veja {analysis}") from error
    if completed.returncode != 0 or not disassembly.is_file() or disassembly.stat().st_size == 0:
        raise InstallerError(f"disassembler IFPS falhou; veja {disassembly_log}")

    cfg = write_cfg_report(disassembly, control_flow)
    manifest = write_manifest(iss, disassembly, setup, source, manifest_path)
    manifest["analysis"] = {
        "iss_sha256": sha256(iss),
        "compiled_code_sha256": sha256(compiled),
        "disassembly_sha256": sha256(disassembly),
        "control_flow_sha256": sha256(control_flow),
        "control_flow_totals": cfg["totals"],
        "innounp_sha256": sha256(innounp),
        "ifps_disassembler_sha256": sha256(disassembler),
    }
    atomic_json(manifest_path, manifest)
    _refresh_analysis_audit(
        manifest, iss, disassembly, compiled, analysis, manifest_path,
    )
    return manifest_path, manifest


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


def enabled(
    step: dict[str, Any], components: set[str], options: set[str] | None = None
) -> bool:
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
    return f"{index:03d}:{step.get('id', step.get('archive', step.get('type', 'step')))}"


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
        expected_key = planned[len(completed_positions)][2] if len(completed_positions) < len(planned) else None
        later = next(key for key in completed_keys if positions[key] >= len(completed_positions))
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
    state.setdefault("completed", {})[key] = {"finished_at": time.time()}
    state.setdefault("execution_trace", []).append({
        "event": "completed", "step": key, "index": index,
        "type": step.get("type"), "recorded_at": time.time(),
    })
    atomic_json(scratch / "install-state.json", state)


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


def _payload_snapshot(
    directory: Path, expected: set[str], *, allow_extra: bool = False,
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
    directory: Path, expected: set[str]
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
    innoextract: Path | None = None,
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
        current = _payload_snapshot(destination, expected, allow_extra=True)
        if current == recorded:
            print(f"[OK] payload temporário: {len(expected)} arquivos já validados")
            return
        print("[AVISO] payload temporário divergiu do journal; será preservado e reconstruído")
        if state.get("completed"):
            raise InstallerError(
                "payload temporário divergiu após etapas concluídas; "
                "reconstrução automática recusada para preservar mutações e auxiliares"
            )
    tool = (innoextract or ROOT / "libexec/innoextract").resolve()
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
            process = subprocess.Popen(
                command, stdout=output, stderr=subprocess.STDOUT,
                text=True, start_new_session=True,
            )
            state["active"] = {
                "pid": process.pid, "pgid": process.pid, "command": command,
                "started_at": time.time(), "kind": "payload",
            }
            atomic_json(state_path, state)
            returncode = wait_process(process, state_path, state)
        if returncode:
            raise InstallerError(
                f"innoextract encerrou com código {returncode}; veja {log} e {staging_root}"
            )
        snapshot = _payload_snapshot(staging_tmp, expected)
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
    innoextract: Path | None = None,
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
        current = _payload_tree_snapshot(destination, set(recorded) if legacy_required else expected)
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
            _payload_tree_snapshot(destination, actual)
            if legacy_required.issubset(actual) and allowed else None
        )
        if snapshot is not None:
            state.setdefault("payload", {})["app_files"] = snapshot
            state["payload"]["app_materialized_at"] = time.time()
            atomic_json(state_path, state)
            print(f"[OK] payload legado de aplicação adotado e validado: {len(snapshot)} arquivos")
            return
    tool = (innoextract or ROOT / "libexec/innoextract").resolve()
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
            process = subprocess.Popen(
                command, stdout=output, stderr=subprocess.STDOUT,
                text=True, start_new_session=True,
            )
            state["active"] = {
                "pid": process.pid, "pgid": process.pid, "command": command,
                "started_at": time.time(), "kind": "payload-app",
            }
            atomic_json(state_path, state)
            returncode = wait_process(process, state_path, state)
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
            snapshot = _payload_tree_snapshot(staging_app, actual) if legacy_required.issubset(actual) and allowed else None
        else:
            snapshot = _payload_tree_snapshot(staging_app, expected)
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
    process = subprocess.Popen(command, cwd=cwd, env=environment, start_new_session=True)
    state["active"] = {"pid": process.pid, "pgid": process.pid, "command": command, "started_at": time.time()}
    atomic_json(state_path, state)
    returncode = wait_process(process, state_path, state)
    if returncode not in success_codes:
        raise InstallerError(f"etapa encerrou com código {returncode}")


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
    archive_root = step.get("archive_root")
    if archive_root:
        archive = safe_child(resolve_destination(archive_root, target, scratch), step["archive"])
        if not archive.is_file() and not args.dry_run:
            raise InstallerError(f"arquivo intermediário ausente: {archive}")
        archive_arguments = ["--archive-path", str(archive)]
    else:
        archive = verify_archive(step, args, source, state_path, state)
        archive_arguments = ["--archive", archive.name]
    destination = resolve_destination(step.get("destination", "app"), target, scratch)
    if step.get("destination_suffix"):
        destination = safe_child(destination, step["destination_suffix"])
    command = command_prefix(args) + [
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
        archive_workdir = safe_child(target, step["archive_workdir"])
        command.extend(["--archive-workdir", str(archive_workdir)])
    for pattern in step.get("filters", []):
        command.extend(["--include", str(pattern)])
    run_process(command, ROOT, state_path, state, args.dry_run)
    if step.get("delete_archive_after") and not args.dry_run:
        archive.unlink(missing_ok=True)


def verify_archive(
    step: dict[str, Any], args: argparse.Namespace, source: Path,
    state_path: Path, state: dict[str, Any]
) -> Path:
    archive = safe_child(source, step["archive"])
    if not archive.is_file():
        raise InstallerError(f"volume ausente: {archive}")
    expected_md5 = step.get("md5")
    archive_stat = archive.stat()
    identity = {"size": archive_stat.st_size, "mtime_ns": archive_stat.st_mtime_ns, "md5": expected_md5}
    if expected_md5 and state.setdefault("verified", {}).get(archive.name) != identity:
        if args.dry_run:
            print(f"[VALIDA] MD5 {archive.name}: {expected_md5}")
        else:
            print(f"[VALIDA] calculando MD5 de {archive.name}...")
            actual_md5 = file_hash(archive, "md5")
            if actual_md5.lower() != expected_md5.lower():
                raise InstallerError(
                    f"MD5 inválido em {archive.name}: esperado {expected_md5}, obtido {actual_md5}"
                )
            state["verified"][archive.name] = identity
            atomic_json(state_path, state)
    return archive


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
    process = subprocess.Popen(command, cwd=cwd, env=environment, start_new_session=True)
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


def clone_path(source: Path, destination: Path) -> None:
    """Create an independent backup, preferring a copy-on-write reflink."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink():
        destination.symlink_to(os.readlink(source))
        return
    if source.is_dir():
        destination.mkdir()
        for child in source.iterdir():
            clone_path(child, destination / child.name)
        shutil.copystat(source, destination, follow_symlinks=False)
        return
    with source.open("rb") as input_handle, destination.open("xb") as output_handle:
        try:
            fcntl.ioctl(output_handle.fileno(), 0x40049409, input_handle.fileno())
        except OSError:
            input_handle.seek(0)
            shutil.copyfileobj(input_handle, output_handle, 8 * 1024 * 1024)
    shutil.copystat(source, destination, follow_symlinks=False)


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
    if "rollback_paths" not in step:
        raise InstallerError(f"{key}: ISExec sem rollback_paths comprovados")
    paths = transaction_paths(step, target, scratch)
    print(f"[TRANSAÇÃO] {key}: {len(paths)} caminhos mutáveis")
    if dry_run:
        return
    record_root = scratch / "transactions" / key.replace(":", "-")
    if record_root.exists():
        raise InstallerError(f"transação anterior não resolvida: {record_root}")
    entries: list[dict[str, Any]] = []
    for index, path in enumerate(paths):
        entry: dict[str, Any] = {
            "path": str(path), "existed": os.path.lexists(path),
        }
        if os.path.lexists(path):
            backup = record_root / f"{index:06d}"
            clone_path(path, backup)
            entry["backup"] = str(backup)
        entries.append(entry)
    state.setdefault("transactions", {})[key] = {
        "kind": "isexec", "status": "prepared", "entries": entries,
        "root": str(record_root),
        "started_at": time.time(),
    }
    atomic_json(state_path, state)


def restore_transaction(
    key: str, target: Path, scratch: Path,
    state_path: Path, state: dict[str, Any],
) -> None:
    record = state.get("transactions", {}).get(key)
    if not record or record.get("status") == "rolled-back":
        return
    record_root_value = record.get("root")
    if not record_root_value:
        raise InstallerError(f"transação {key} sem raiz de backup")
    transactions_root = (scratch / "transactions").resolve()
    record_root = Path(record_root_value).resolve()
    try:
        record_root.relative_to(transactions_root)
    except ValueError as error:
        raise InstallerError(
            f"raiz de transação fora do scratch: {record_root}"
        ) from error
    allowed_roots = (target.resolve(), scratch.resolve())
    for entry in reversed(record["entries"]):
        path = Path(entry["path"])
        resolved = path.resolve()
        if not any(
            resolved == root or root in resolved.parents for root in allowed_roots
        ):
            raise InstallerError(f"rollback recusou caminho não confinado: {path}")
        if entry["existed"]:
            backup = Path(entry["backup"]).resolve()
            try:
                backup.relative_to(record_root)
            except ValueError as error:
                raise InstallerError(
                    f"backup de transação fora da quarentena: {backup}"
                ) from error
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
        if entry["existed"]:
            path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(backup, path)
    record["status"] = "rolled-back"
    if record_root.is_dir():
        shutil.rmtree(record_root)
    state.get("completed", {}).pop(key, None)
    atomic_json(state_path, state)
    print(f"[ROLLBACK] {key} restaurado")


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


def recover_incomplete_transactions(
    target: Path, scratch: Path, state_path: Path, state: dict[str, Any]
) -> None:
    """Undo an ISExec that did not reach the completed-step journal entry."""
    for key, record in list(state.get("transactions", {}).items()):
        if record.get("kind") != "isexec" or key in state.get("completed", {}):
            continue
        if record.get("status") in {"prepared", "committed"}:
            print(f"[RECUPERAÇÃO] rollback da etapa incompleta {key}")
            restore_transaction(key, target, scratch, state_path, state)


def finalize_transactions(
    scratch: Path, state_path: Path, state: dict[str, Any]
) -> None:
    """Discard rollback data only after every installation step succeeded."""
    transactions_root = (scratch / "transactions").resolve()
    for key, record in state.get("transactions", {}).items():
        root_value = record.get("root")
        if not root_value:
            raise InstallerError(f"transação {key} sem raiz durante finalização")
        root = Path(root_value).resolve()
        try:
            root.relative_to(transactions_root)
        except ValueError as error:
            raise InstallerError(
                f"finalização recusou raiz fora do scratch: {root}"
            ) from error
        if root.is_dir():
            shutil.rmtree(root)
    state["transactions"] = {}
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
    from ..verify import parse_manifest

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
    source = scratch / "setup-payload/app/_Redist"
    base = source / "fitgirl.md5"
    if not base.is_file():
        raise InstallerError(f"manifesto base ausente: {base}")
    parts = [base]
    seen = dict((relative.casefold(), digest) for digest, relative in parse_manifest(base))
    for addon in sorted(source.glob("*.addon"), key=lambda p: p.name.casefold()):
        rows = parse_manifest(addon)
        present = [safe_child(target, relative).is_file() for _, relative in rows]
        if rows and not any(present) and addon.stem not in state.get("components", []):
            print(f"[MANIFESTOS] addon inativo: {addon.name}")
            continue
        if not all(present):
            raise InstallerError(f"addon incompleto: {addon.name}")
        for digest, relative in rows:
            previous = seen.setdefault(relative.casefold(), digest)
            if previous != digest:
                raise InstallerError(f"hashes conflitantes nos manifestos: {relative}")
        parts.append(addon)
    begin_transaction(key, step, target, scratch, state_path, state, False)
    try:
        preserve_verifier(target, scratch, False)
        destination = target / "_Redist"
        shutil.copy2(base, destination / "fitgirl.base.md5")
        content = b"".join(p.read_bytes().rstrip(b"\r\n") + b"\r\n" for p in parts)
        temporary = destination / f".fitgirl.md5.merge-{os.getpid()}"
        try:
            with temporary.open("wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            parse_manifest(temporary)
            os.replace(temporary, destination / "fitgirl.md5")
        finally:
            temporary.unlink(missing_ok=True)
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


def initial_state(setup_hash: str, plan_hash: str, source: Path, target: Path, components: set[str], args: argparse.Namespace) -> dict[str, Any]:
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
    immutable = ("version", "setup_sha256", "manifest_sha256", "source", "target", "components", "settings")
    differences = [key for key in immutable if state.get(key) != expected.get(key)]
    if differences:
        raise InstallerError(
            "o journal pertence a outro plano/opções (" + ", ".join(differences) + "); "
            "use o mesmo comando ou um scratch diferente"
        )


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
    target.mkdir(parents=True, exist_ok=True)
    scratch.mkdir(parents=True, exist_ok=True)
    atomic_json(state_path, state)
    execution_plan = [
        (index, step, step_key(index, step))
        for index, step in enumerate(manifest.get("steps", []), 1)
        if enabled(step, components, options)
    ]
    if not args.dry_run:
        validate_runtime_order(scratch, manifest, state, execution_plan)
    recover_incomplete_transactions(target, scratch, state_path, state)
    if any(
        step.get("type") in {"batch", "exec", "isexec"}
        and enabled(step, components, options)
        for step in manifest.get("steps", [])
    ):
        ensure_wine_prefix(
            args.wine, prefix, scratch, state_path, state, args.dry_run
        )
    if sys.stdout.isatty():
        print("Plano de instalação validado.")
    else:
        print(f"[INFO] plano: {manifest_path}")
    materialize_temporary_payload(
        manifest, discover_setup(source), scratch, state_path, state, args.dry_run
    )
    materialize_application_payload(
        manifest, discover_setup(source), scratch, state_path, state, args.dry_run
    )
    if sys.stdout.isatty():
        labels = [
            _component_label(name, manifest.get("components", {}).get(name, {}))
            for name in sorted(components)
        ]
        print("Conteúdo: " + ", ".join(labels))
    else:
        print(f"[INFO] componentes: {', '.join(sorted(components))}")
    if args.memory_max is not None:
        print("[AVISO] MemoryMax é um teto rígido: ao atingi-lo, o kernel pode matar o stream ativo")
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
            verify_archive(step, args, source, state_path, state)
        if key in state["completed"]:
            if sys.stdout.isatty():
                print(f"Etapa {visible_index}/{len(planned)} já validada; retomando.")
            else:
                print(f"[OK] {key}: já concluída")
            continue
        if not args.dry_run:
            validate_runtime_order(
                scratch, manifest, state, execution_plan,
                current=(index, step, key),
            )
        kind = step.get("type")
        if sys.stdout.isatty():
            print(f"Etapa {visible_index}/{len(planned)}: {step.get('description', key)}")
        else:
            print(f"[ETAPA {index}] {step.get('description', key)}")
        if kind == "extract":
            run_extract(
                step, args, source, target, scratch, prefix, state_path, state,
                global_base, global_weight,
                bool(manifest.get("temporary_payload_files")),
            )
        elif kind == "batch":
            run_batch(step, args, target, scratch, prefix, state_path, state)
        elif kind == "exec":
            run_exec(step, args, target, scratch, prefix, state_path, state)
        elif kind == "isexec":
            run_isexec(
                key, step, args, source, target, scratch, prefix,
                state_path, state,
            )
        elif kind in {"delete-file", "delete-tree"}:
            run_delete(key, step, target, scratch, state_path, state, args.dry_run)
        elif kind == "copy":
            run_copy(step, target, scratch, args.dry_run)
        elif kind == "merge-manifests":
            run_manifest_merge(key, step, args, target, scratch, state_path, state)
        elif kind == "ini-write":
            run_ini_write(
                step, args, source, target, scratch, prefix, state_path, state
            )
        elif kind == "verify":
            run_verify(step, args, target, scratch, state_path, state)
        else:
            raise InstallerError(f"tipo de etapa não suportado: {kind}")
        if not args.dry_run:
            record_runtime_completion(scratch, state, index, step, key)
        finished_weight += weight
        if sys.stdout.isatty():
            print(f"Etapa concluída · {min(100, finished_weight / total_weight * 100):.0f}% geral")
        else:
            print(f"[GLOBAL] {min(99.9, finished_weight / total_weight * 100):5.1f}% confirmado")
    preserve_verifier(
        target, scratch, args.dry_run, args.quicksfv_x64,
        preserve_existing_manifest=any(s.get("type") == "merge-manifests" for _, s, _, _ in planned),
    )
    if not args.dry_run:
        report_path = scratch / "integration-report.json"
        report = write_integration_report(target, report_path)
        print(
            f"[INTEGRAÇÃO] {len(report['game_executable_candidates'])} executáveis candidatos; "
            f"{len(report['redistributables'])} redistribuíveis não executados; relatório: {report_path}"
        )
        finalize_transactions(scratch, state_path, state)
    if sys.stdout.isatty():
        print("Instalação concluída e arquivos verificados." if not args.dry_run else "Simulação concluída.")
    else:
        print(f"[GLOBAL] 100.0% {'simulado' if args.dry_run else 'confirmado'}")
        print(f"[INFO] instalação concluída em {target}" if not args.dry_run else "[INFO] simulação concluída")
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
