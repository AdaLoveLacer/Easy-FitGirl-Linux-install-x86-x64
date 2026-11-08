"""Read setup metadata from an extracted ISS script."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class AnalysisPaths:
    """Locations of the cached evidence for one setup hash."""

    cache_root: Path
    analysis: Path
    extracted: Path
    iss: Path
    compiled: Path
    disassembly: Path
    control_flow: Path
    manifest: Path


def analysis_paths(setup_hash: str) -> AnalysisPaths:
    """Resolve where the analysis cache of a setup lives (honours XDG_CACHE_HOME)."""
    cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    analysis = cache_root / "fitgirl-installer" / "plans" / setup_hash
    extracted = analysis / "innounp"
    return AnalysisPaths(
        cache_root=cache_root,
        analysis=analysis,
        extracted=extracted,
        iss=extracted / "install_script.iss",
        compiled=extracted / "embedded" / "CompiledCode.bin",
        disassembly=analysis / "CompiledCode.disassembly.txt",
        control_flow=analysis / "control-flow.json",
        manifest=analysis / "manifest.draft.json",
    )


def discover_setup(source: Path, *, error_type: type[RuntimeError]) -> Path:
    """Find the unique setup executable in a repack directory."""
    matches = [path for path in source.iterdir() if path.name.lower() == "setup.exe"]
    if len(matches) != 1:
        raise error_type(f"esperado um setup.exe em {source}; encontrados: {len(matches)}")
    return matches[0]


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


def discover_analysis_tool(
    environment: str, bundled_name: str, command: str, *,
    root: Path, pe_machine: Callable[[Path], int | None],
) -> Path | None:
    configured = os.environ.get(environment)
    candidates = [Path(configured).expanduser()] if configured else []
    candidates.append(root / "libexec" / bundled_name)
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    candidates.append(data_home / "fitgirl-installer" / "tools" / bundled_name)
    system = shutil.which(command)
    if system:
        candidates.append(Path(system))
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file() and (pe_machine(resolved) is not None or os.access(resolved, os.X_OK)):
            return resolved
    return None


def require_analysis_tools(
    *, find_tool: Callable[[str, str, str], Path | None],
    error_type: type[RuntimeError],
) -> tuple[Path, Path]:
    """Find both tools required for analysis or report which are missing."""
    innounp = find_tool("FITGIRL_INNOUNP", "innounp.exe", "innounp")
    disassembler = find_tool(
        "FITGIRL_IFPS_DISASSEMBLER", "pascalscript", "pascalscript"
    )
    missing = []
    if innounp is None:
        missing.append("innounp (FITGIRL_INNOUNP)")
    if disassembler is None:
        missing.append("disassembler IFPS (FITGIRL_IFPS_DISASSEMBLER)")
    if missing:
        raise error_type(
            "setup desconhecido e ferramentas de análise ausentes: " + ", ".join(missing)
        )
    return innounp, disassembler


def apply_semantic_blockers(candidate: dict[str, Any], report: dict[str, Any]) -> None:
    """Apply critical audit findings to the generated manifest."""
    blockers = [
        f"{effect['kind']} em {effect['call_address']}: {effect.get('detail', 'efeito externo crítico não modelado')}"
        for effect in report.get("semantic_guards", {}).get("critical_external_effects", [])
        if effect.get("blocks_audit_acceptance") is True
    ]
    if blockers:
        candidate["semantic_blockers"] = blockers
        candidate["draft"] = True
        candidate["review_required"] = True
    else:
        candidate.pop("semantic_blockers", None)
    acceptance = report.get("acceptance") or {}
    if acceptance.get("automatic") is True and not blockers:
        candidate["draft"] = False
        candidate["review_required"] = False
        candidate["acceptance"] = acceptance
    elif candidate.pop("acceptance", None) is not None:
        # A plan accepted automatically that no longer proves everything goes
        # back to review; a plan a reviewer accepted by hand is left as it is.
        candidate["draft"] = True
        candidate["review_required"] = True


def isdone_fingerprint(setup: Path, analysis: Path, *, innoextract: Path) -> str | None:
    """SHA-256 of the setup's ISDone.dll, extracted without running the installer."""
    destination = analysis / "isdone"
    shutil.rmtree(destination, ignore_errors=True)
    destination.mkdir(parents=True)
    try:
        subprocess.run(
            [str(innoextract), "--silent", "--output-dir", str(destination),
             "--include", "tmp/ISDone.dll", str(setup)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    found = [path for path in destination.rglob("*") if path.is_file() and path.name.casefold() == "isdone.dll"]
    if len(found) != 1:
        return None
    return hashlib.sha256(found[0].read_bytes()).hexdigest()


def refresh_analysis_audit(
    candidate: dict[str, Any], iss: Path, disassembly: Path, compiled: Path,
    analysis: Path, manifest_path: Path, *,
    write_audit: Callable[..., dict[str, Any]],
    find_tool: Callable[[str, str, str], Path | None],
    save_json: Callable[[Path, dict[str, Any]], None],
    fingerprint_isdone: Callable[[], str | None] | None = None,
) -> None:
    """Refresh the audit and persist the resulting manifest."""
    recorded = candidate.setdefault("analysis", {})
    if fingerprint_isdone is not None and not recorded.get("isdone_sha256"):
        recorded["isdone_sha256"] = fingerprint_isdone()
    report = write_audit(
        candidate, iss, disassembly, compiled, analysis / "plan-audit.json",
        disassembler=find_tool(
            "FITGIRL_IFPS_DISASSEMBLER", "pascalscript", "pascalscript"
        ),
    )
    apply_semantic_blockers(candidate, report)
    save_json(manifest_path, candidate)


def disassemble_compiled_code(
    disassembler: Path, compiled: Path, disassembly: Path, analysis: Path, *,
    error_type: type[RuntimeError],
) -> None:
    """Write disassembly and retain diagnostic output for failed analysis."""
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
        raise error_type(f"disassembler IFPS excedeu 120 s; veja {analysis}") from error
    if completed.returncode != 0 or not disassembly.is_file() or disassembly.stat().st_size == 0:
        raise error_type(f"disassembler IFPS falhou; veja {disassembly_log}")


def extract_setup_evidence(
    command: list[str], environment: dict[str, str], analysis: Path,
    iss: Path, compiled: Path, *, error_type: type[RuntimeError],
) -> None:
    """Run innounp and retain its log and extracted evidence."""
    extract_log = analysis / "innounp.log"
    try:
        completed = subprocess.run(
            command, env=environment, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=300, check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise error_type(f"innounp excedeu 300 s; evidência mantida em {analysis}") from error
    extract_log.write_text(completed.stdout or "", encoding="utf-8")
    if completed.returncode != 0 or not iss.is_file() or not compiled.is_file():
        raise error_type(
            f"innounp não produziu ISS/CompiledCode.bin; veja {extract_log}"
        )


def prepare_innounp_command(
    innounp: Path, extracted: Path, setup: Path, cache_root: Path, *,
    pe_machine: Callable[[Path], int | None], discover_wine: Callable[[], list[Path]],
    wine_z_path: Callable[[Path], str], error_type: type[RuntimeError],
) -> tuple[list[str], dict[str, str]]:
    """Prepare the native or Wine invocation used to extract setup evidence."""
    if pe_machine(innounp) is not None:
        wines = discover_wine()
        if not wines:
            raise error_type("innounp é PE, mas nenhum Wine foi encontrado para a análise")
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
    return command, environment


def inspect_analysis_cache(
    manifest_path: Path, disassembly: Path, control_flow: Path, *,
    read_json: Callable[[Path], dict[str, Any]], sha256: Callable[[Path], str],
    compiler_version: int, schema_version: int,
) -> tuple[dict[str, Any], bool, bool, bool]:
    """Read cached metadata and report which analysis artifacts are current."""
    cached_manifest = read_json(manifest_path) if manifest_path.is_file() else {}
    disassembly_current = (
        disassembly.is_file()
        and cached_manifest.get("analysis", {}).get("disassembly_sha256")
        == sha256(disassembly)
    )
    compiler_current = cached_manifest.get("compiler_version") == compiler_version
    control_flow_current = (
        control_flow.is_file()
        and read_json(control_flow).get("schema") == schema_version
    )
    return cached_manifest, disassembly_current, compiler_current, control_flow_current


def build_analysis_metadata(
    iss: Path, compiled: Path, disassembly: Path, control_flow: Path,
    cfg: dict[str, Any], *, sha256: Callable[[Path], str],
) -> dict[str, Any]:
    """Collect the artifact hashes and control-flow totals for a plan."""
    return {
        "iss_sha256": sha256(iss),
        "compiled_code_sha256": sha256(compiled),
        "disassembly_sha256": sha256(disassembly),
        "control_flow_sha256": sha256(control_flow),
        "control_flow_totals": cfg["totals"],
    }


@dataclass(frozen=True)
class AnalysisServices:
    """Collaborators the analysis needs from the rest of the installer."""

    read_json: Callable[[Path], dict[str, Any]]
    save_json: Callable[[Path, dict[str, Any]], None]
    sha256: Callable[[Path], str]
    write_cfg: Callable[[Path, Path], dict[str, Any]]
    write_manifest: Callable[..., dict[str, Any]]
    write_audit: Callable[..., dict[str, Any]]
    find_tool: Callable[[str, str, str], Path | None]
    pe_machine: Callable[[Path], int | None]
    discover_wine: Callable[[], list[Path]]
    wine_z_path: Callable[[Path], str]
    compiler_version: int
    schema_version: int
    error_type: type[RuntimeError]
    fingerprint_isdone: Callable[[Path, Path], str | None] | None = None


def generate_manifest_draft(
    source: Path, setup: Path, setup_hash: str, *, services: AnalysisServices,
) -> tuple[Path, dict[str, Any]]:
    """Analyze an unknown setup without executing it and cache all review evidence."""
    paths = analysis_paths(setup_hash)
    cache_root, analysis, extracted = paths.cache_root, paths.analysis, paths.extracted
    iss, compiled, disassembly = paths.iss, paths.compiled, paths.disassembly
    control_flow, manifest_path = paths.control_flow, paths.manifest

    def refresh_audit(manifest: dict[str, Any]) -> None:
        refresh_analysis_audit(
            manifest, iss, disassembly, compiled, analysis, manifest_path,
            write_audit=services.write_audit, find_tool=services.find_tool,
            save_json=services.save_json,
            fingerprint_isdone=(
                None if services.fingerprint_isdone is None
                else lambda: services.fingerprint_isdone(setup, analysis)
            ),
        )

    cached_manifest, disassembly_current, compiler_current, control_flow_current = (
        inspect_analysis_cache(
            manifest_path, disassembly, control_flow, read_json=services.read_json,
            sha256=services.sha256, compiler_version=services.compiler_version,
            schema_version=services.schema_version,
        )
    )
    if (
        manifest_path.is_file() and iss.is_file() and compiled.is_file()
        and disassembly.is_file() and control_flow_current and disassembly_current
        and compiler_current
    ):
        manifest = cached_manifest
        if setup_hash in manifest.get("setup_sha256", []):
            refresh_audit(manifest)
            return manifest_path, manifest
    if (
        manifest_path.is_file() and iss.is_file() and compiled.is_file()
        and disassembly.is_file()
        and (not control_flow_current or not disassembly_current or not compiler_current)
    ):
        previous_manifest = cached_manifest
        if setup_hash in previous_manifest.get("setup_sha256", []):
            cfg = services.write_cfg(disassembly, control_flow)
            manifest = services.write_manifest(iss, disassembly, setup, source, manifest_path)
            manifest["analysis"] = previous_manifest.get("analysis", {})
            manifest.setdefault("analysis", {}).update(build_analysis_metadata(
                iss, compiled, disassembly, control_flow, cfg, sha256=services.sha256,
            ))
            current_disassembler = services.find_tool(
                "FITGIRL_IFPS_DISASSEMBLER", "pascalscript", "pascalscript"
            )
            if current_disassembler is not None:
                manifest["analysis"]["ifps_disassembler_sha256"] = services.sha256(
                    current_disassembler
                )
            services.save_json(manifest_path, manifest)
            refresh_audit(manifest)
            return manifest_path, manifest

    innounp, disassembler = require_analysis_tools(
        find_tool=services.find_tool, error_type=services.error_type,
    )

    analysis.mkdir(parents=True, exist_ok=True)
    extracted.mkdir(parents=True, exist_ok=True)
    command, environment = prepare_innounp_command(
        innounp, extracted, setup, cache_root, pe_machine=services.pe_machine,
        discover_wine=services.discover_wine, wine_z_path=services.wine_z_path,
        error_type=services.error_type,
    )
    extract_setup_evidence(
        command, environment, analysis, iss, compiled, error_type=services.error_type,
    )

    disassemble_compiled_code(
        disassembler, compiled, disassembly, analysis, error_type=services.error_type,
    )

    cfg = services.write_cfg(disassembly, control_flow)
    manifest = services.write_manifest(iss, disassembly, setup, source, manifest_path)
    manifest["analysis"] = {
        **build_analysis_metadata(
            iss, compiled, disassembly, control_flow, cfg, sha256=services.sha256,
        ),
        "innounp_sha256": services.sha256(innounp),
        "ifps_disassembler_sha256": services.sha256(disassembler),
    }
    services.save_json(manifest_path, manifest)
    refresh_audit(manifest)
    return manifest_path, manifest
