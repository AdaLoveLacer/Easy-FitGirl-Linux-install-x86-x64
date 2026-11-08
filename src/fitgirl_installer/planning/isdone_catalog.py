"""Analysed ISDone.dll versions and how their external effects map to the native plan.

FitGirl repacks share a small number of ISDone.dll builds. What one build does
is proven once, by static analysis of that exact binary, and recorded here by
SHA-256. A setup whose DLL is not catalogued keeps every effect blocked, and a
catalogued effect is only lifted after the check of that setup's own script.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import planner


@dataclass(frozen=True)
class IsdoneVersion:
    label: str
    evidence: str
    successful_exports: frozenset[str]
    precomp_init_section: str
    records_deleted_by_isdonestop: bool


CATALOG: dict[str, IsdoneVersion] = {
    "c652b4b564b3c85c399155cbb45c6fb5a9f56f074e566bfd20f01da6e0412c74": IsdoneVersion(
        label="ISDone.dll c652b4b5 (Star Trucker, Children of Morta, Subnautica and others)",
        evidence="evidence/semantic-guard-audit-2026-11-04.json",
        # Boolean exports whose true result means success; analysed in the
        # binary together with the extraction actions.
        successful_exports=frozenset({"isdoneinit", "precompinit", "filesearchinit", "changelanguage"}),
        # PrecompInit only writes Memory and TempPath of this CLS.ini section.
        precomp_init_section="Precomp",
        # ISDoneStop may delete the records file retained by ISDoneInit.
        records_deleted_by_isdonestop=True,
    ),
}

OUTSIDE_INSTALLATION = ("{src}\\", "{tmp}\\")


def version(isdone_sha256: str | None) -> IsdoneVersion | None:
    return CATALOG.get((isdone_sha256 or "").casefold())


def _call_literals(disassembly: Path, export: str) -> list[list[str]]:
    rows = planner._instruction_rows(
        disassembly.read_text(encoding="utf-8", errors="replace").splitlines()
    )
    return [
        [item["value"] for item in planner._frame_strings(planner._frame_for_call(rows, index))]
        for index, row in enumerate(rows)
        if row["opcode"] == "call"
        and row["operands"].casefold() == f"dll:files:isdone.dll!{export}".casefold()
    ]


def resolve_effects(
    effects: list[dict[str, Any]], disassembly: Path, isdone_sha256: str | None,
    success_path: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Return the effects, lifting each one only when its proof holds for this setup."""
    known = version(isdone_sha256)
    resolved = []
    for effect in effects:
        effect = dict(effect)
        resolution = None
        if known is None:
            effect["unresolved_reason"] = "ISDone.dll version is not in the catalog of analysed builds"
        elif effect["kind"] == "unmodeled_precomp_ini_write":
            resolution = {
                "rule": "codec_resource_tuning",
                "detail": (
                    f"PrecompInit only sets Memory and TempPath of [{known.precomp_init_section}] "
                    "in CLS.ini: the precomp codec's working memory and temporary directory. "
                    "They decide whether decoding fits, never the decoded bytes; a failure "
                    "stops the native run and the final MD5 check covers the output."
                ),
                "arguments": _call_literals(disassembly, "PrecompInit"),
            }
        elif effect["kind"] == "unmodeled_conditional_records_file_deletion":
            paths = [
                value for literals in _call_literals(disassembly, "ISDoneInit")
                for value in literals if value.casefold().endswith("records.inf")
            ]
            if known.records_deleted_by_isdonestop and paths and all(
                value.casefold().startswith(OUTSIDE_INSTALLATION) for value in paths
            ):
                resolution = {
                    "rule": "deletion_outside_installation",
                    "detail": (
                        "ISDoneStop can only delete the records file retained by ISDoneInit, "
                        "which this script places outside {app}; the native run never creates "
                        "it, so omitting the deletion leaves the installed tree unchanged."
                    ),
                    "records_paths": paths,
                }
            else:
                effect["unresolved_reason"] = "records file path is not proven outside {app}"
        elif effect["kind"] == "unmodeled_silent_uninstaller_launch":
            if success_path and success_path.get("uninstaller_launch_unreachable"):
                resolution = {
                    "rule": "failure_path_only",
                    "detail": (
                        "On the success path of every setup step the guard flag is cleared "
                        "before the uninstaller call, which is therefore reached only after a "
                        "failed action; the native run stops at that failure instead."
                    ),
                    "guard_flag": success_path.get("uninstaller_guard_flag"),
                }
            else:
                effect["unresolved_reason"] = "success path does not prove the uninstaller unreachable"
        if resolution:
            effect["resolution"] = {**resolution, "isdone": known.label, "evidence": known.evidence}
            effect["modeled_by_native_plan"] = True
            effect["blocks_audit_acceptance"] = False
        resolved.append(effect)
    return resolved
