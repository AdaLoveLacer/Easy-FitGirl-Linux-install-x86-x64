"""Read setup metadata from an extracted ISS script."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable


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


def refresh_analysis_audit(
    candidate: dict[str, Any], iss: Path, disassembly: Path, compiled: Path,
    analysis: Path, manifest_path: Path, *,
    write_audit: Callable[..., dict[str, Any]],
    find_tool: Callable[[str, str, str], Path | None],
    save_json: Callable[[Path, dict[str, Any]], None],
) -> None:
    """Refresh the audit and persist the resulting manifest."""
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
