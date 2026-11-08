"""Conservative consistency audit; not a proof of PascalScript equivalence."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import re
import subprocess
from typing import Any

from . import isdone_catalog, planner, script_flow, success_path


SCHEMA_VERSION = 2
IGNORED_STEP_FIELDS = {"id", "description", "bytecode"}


def _action_at(instruction: script_flow.Instruction) -> bool:
    return instruction.opcode == "call" and (
        planner.ISDONE_EXPORT.match(instruction.operands) is not None
        or instruction.operands.casefold() in planner.MUTATING_CALLS
    )


def _tokens_for_block(
    procedure_name: str,
    block: script_flow.BasicBlock,
    named: set[str],
) -> list[dict[str, Any]]:
    tokens: list[dict[str, Any]] = []
    for instruction in block.instructions:
        if instruction.opcode != "call":
            continue
        if _action_at(instruction):
            tokens.append({
                "kind": "action",
                "value": f"{procedure_name}@0x{instruction.address:x}:{instruction.operands}",
            })
        if instruction.opcode == "call" and instruction.operands.casefold() in named:
            tokens.append({
                "kind": "call",
                "value": instruction.operands.casefold(),
            })

    return tokens


def _cap_variants(
    variants: list[tuple[str, ...]], limit: int,
) -> tuple[list[tuple[str, ...]], bool]:
    ordered = variants[:limit]
    return ordered, len(variants) > limit


def _bounded_block_paths(
    spec: dict[str, Any], seq_limit: int,
) -> tuple[list[list[dict[str, Any]]], bool]:
    """Return bounded block/token sequences, marking visible cycles.

    Loops are not unrolled semantically: repeat visits cap the path and add an
    explicit CYCLE marker. This preserves order evidence without claiming full
    fixpoint semantics.
    """
    def walk_block(
        start: int, stack: tuple[int, ...], acc: list[dict[str, Any]],
    ) -> tuple[list[list[dict[str, Any]]], bool]:
        if start in stack:
            acc = acc + [{"kind": "cycle", "value": f"BLOCK_CYCLE:0x{start:x}"}]
            return [acc], True
        item = spec["blocks"][start]
        block = item["block"]
        acc = acc + item["tokens"]
        if not block.successors:
            return [acc], False
        local: list[list[dict[str, Any]]] = []
        truncated = False
        for edge in block.successors:
            paths, child_truncated = walk_block(edge.target, stack + (start,), acc)
            truncated = truncated or child_truncated
            for path in paths:
                local.append(path)
                if len(local) >= seq_limit:
                    truncated = True
                    break
            if len(local) >= seq_limit:
                break
        return local, truncated

    raw_paths, path_truncated = walk_block(spec["entry"], (), [])
    return raw_paths, path_truncated


def _sequence_digest(sequences: list[tuple[str, ...]]) -> str:
    digest = hashlib.sha256()
    for sequence in sequences:
        digest.update("\0".join(sequence).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _expand_tokens(
    key: str,
    tokens: list[dict[str, Any]],
    expand: Any,
    limit: int,
) -> tuple[list[tuple[str, ...]], bool]:
    variants: list[tuple[str, ...]] = [()]
    truncated = False
    for token in tokens:
        if token["kind"] == "cycle":
            variants = [prefix + (token["value"],) for prefix in variants]
            truncated = True
            variants = variants[:limit]
            continue
        if token["kind"] == "action":
            variants = [prefix + (token["value"],) for prefix in variants]
            variants = variants[:limit]
            truncated = truncated or len(variants) == limit and len({*variants}) < len(variants)
            continue
        expanded, was_truncated = expand(token["value"], key)
        truncated = truncated or was_truncated
        proposed = []
        for prefix in variants:
            for suffix in expanded:
                proposed.append(prefix + suffix)
                if len(proposed) >= limit:
                    truncated = True
                    break
            if len(proposed) >= limit:
                truncated = True
                break
        variants = proposed[:limit]
    unique = sorted(set(variants))
    if len(unique) > limit:
        unique = unique[:limit]
        truncated = True
    return unique, truncated



def interprocedural_action_path_report(
    disassembly: Path, entry_limit: int = 16, sequence_limit: int = 256,
    depth_limit: int = 6, in_procedure_sequence_limit: int = 256,
) -> dict[str, Any]:
    """Enumerate bounded global action orders across direct calls.

    The enumeration is a conservative executable-path analysis, not a proof of
    Pascal semantics. Internal calls are expanded only when the operand is a
    direct name that resolves to a parsed procedure. Loops are represented by
    explicit CYCLE markers and are never unrolled indefinitely.
    """
    parsed = script_flow.parse_disassembly(disassembly)
    named = {procedure.name.casefold() for procedure in parsed}
    frames = {}
    unresolved_total = 0
    for procedure in parsed:
        cfg = script_flow.build_cfg(procedure)
        unresolved_total += len(cfg.unresolved_targets)
        blocks = []
        for block in cfg.blocks:
            tokens = _tokens_for_block(procedure.name, block, named)
            blocks.append({
                "block": block,
                "tokens": tokens,
            })
        frames[procedure.name.casefold()] = {
            "name": procedure.name,
            "blocks": {item["block"].start: item for item in blocks},
            "entry": cfg.blocks[0].start if cfg.blocks else None,
        }

    relevant_roots = []
    preferred = (
        "initializewizard", "curstepchanged", "nextbuttonclick",
        "curpagechanged", "cancelbuttononclick", "shouldskippage",
    )
    for wanted in preferred:
        if wanted in frames:
            relevant_roots.append(wanted)
    relevant_roots.extend(
        key for key in frames
        if key not in relevant_roots and any(
            token["kind"] == "call"
            for frame in frames[key]["blocks"].values()
            for token in frame["tokens"]
        )
    )
    relevant_roots = relevant_roots[:entry_limit]
    summaries: dict[str, tuple[list[tuple[str, ...]], bool]] = {}

    def summarize(
        key: str, stack: tuple[str, ...],
    ) -> tuple[list[tuple[str, ...]], bool]:
        if key in stack:
            return [(f"CYCLE:{key}",)], True
        if len(stack) >= depth_limit:
            return [(f"DEPTH_LIMIT:{key}",)], True
        if key in summaries:
            return summaries[key]
        spec = frames[key]
        if spec["entry"] is None:
            return [()], False
        block_paths, truncated = _bounded_block_paths(spec, in_procedure_sequence_limit)
        results: list[tuple[str, ...]] = []
        next_stack = stack + (key,)

        def expand(callee: str, _caller: str):
            return summarize(callee, next_stack)

        for tokens in block_paths:
            sequences, was_truncated = _expand_tokens(key, tokens, expand, in_procedure_sequence_limit)
            truncated = truncated or was_truncated
            results.extend(sequences)
            if len(results) >= in_procedure_sequence_limit:
                results = results[:in_procedure_sequence_limit]
                truncated = True
                break
        unique = sorted(set(results))
        truncated = truncated or len(unique) > sequence_limit
        summaries[key] = (unique[:sequence_limit], truncated)
        return summaries[key]

    entries = []
    for key in relevant_roots:
        sequences, truncated = summarize(key, ())
        digest = _sequence_digest(sequences)
        entries.append({
            "procedure": frames[key]["name"],
            "sequence_count": len(sequences),
            "sequence_set_sha256": digest,
            "action_sequence_samples": [list(sequence) for sequence in sequences[:8]],
            "truncated": truncated,
        })
    return {
        "schema": 1,
        "entry_limit": entry_limit,
        "sequence_limit": sequence_limit,
        "depth_limit": depth_limit,
        "entries": entries,
        "unresolved_cfg_targets": unresolved_total,
        "all_entries_bounded": True,
        "interprocedural_paths_proven": False,
        "limitations": [
            "Only direct textual calls that resolve to parsed procedures are expanded.",
            "Loops are not unrolled; recursion is reported through explicit CYCLE or DEPTH_LIMIT tokens.",
            "This is bounded executable-path enumeration, not independent proof of Pascal semantics.",
        ],
    }


def action_path_report(disassembly: Path, limit: int = 4096) -> dict[str, Any]:
    """Enumerate intraprocedural action orders without unrolling loops."""
    procedures = []
    for procedure in script_flow.parse_disassembly(disassembly):
        cfg = script_flow.build_cfg(procedure)
        actions = {
            instruction.address: instruction.operands
            for instruction in procedure.instructions
            if instruction.opcode == "call" and (
                planner.ISDONE_EXPORT.match(instruction.operands)
                or instruction.operands.casefold() in planner.MUTATING_CALLS
            )
        }
        if not actions or not cfg.blocks:
            continue
        blocks = {block.start: block for block in cfg.blocks}
        sequences: set[tuple[str, ...]] = set()
        cycles: set[tuple[int, int]] = set()
        truncated = False

        def walk(start: int, stack: tuple[int, ...], sequence: tuple[str, ...]) -> None:
            nonlocal truncated
            if len(sequences) >= limit:
                truncated = True
                return
            if start in stack:
                cycles.add((stack[-1], start))
                return
            block = blocks[start]
            current = sequence + tuple(
                f"0x{instruction.address:x}:{actions[instruction.address]}"
                for instruction in block.instructions if instruction.address in actions
            )
            if not block.successors:
                sequences.add(current)
                return
            next_stack = stack + (start,)
            for edge in block.successors:
                walk(edge.target, next_stack, current)

        walk(cfg.blocks[0].start, (), ())
        ordered_sequences = sorted(sequences)
        sequence_digest = hashlib.sha256()
        for sequence in ordered_sequences:
            sequence_digest.update("\0".join(sequence).encode("utf-8"))
            sequence_digest.update(b"\n")
        procedures.append({
            "procedure": procedure.name,
            "sequence_count": len(sequences),
            "sequence_set_sha256": sequence_digest.hexdigest(),
            "action_sequence_samples": [
                list(sequence) for sequence in ordered_sequences[:8]
            ],
            "cycles": [
                {"from": f"0x{source:x}", "to": f"0x{target:x}"}
                for source, target in sorted(cycles)
            ],
            "truncated": truncated,
            "single_order": len(sequences) == 1 and not cycles and not truncated,
        })
    return {
        "procedures": procedures,
        "all_relevant_procedures_single_order": bool(procedures) and all(
            item["single_order"] for item in procedures
        ),
    }


def semantic_guard_report(disassembly: Path) -> dict[str, Any]:
    """Prove a narrow set of event guards and inventory opaque DLL behavior.

    Event recognition is deliberately restricted to a direct comparison of the
    callback parameter against a literal followed by an inverted flag branch.
    Component-selection bits are reported separately because ISDone.dll is an
    external runtime whose interpretation of CurComponent is not proved here.
    """
    setup_steps = {
        0: "ssPreInstall", 1: "ssInstall", 2: "ssPostInstall", 3: "ssDone",
    }
    procedures = script_flow.parse_disassembly(disassembly)
    callback = next(
        (proc for proc in procedures if proc.name.casefold() == "curstepchanged"),
        None,
    )
    if callback is None:
        return {
            "callback": None,
            "event_guards": [],
            "event_guard_proof_complete": False,
            "unmodeled_external_calls": [],
            "component_selection": None,
            "limitations": ["CurStepChanged was not found."],
        }

    instructions = callback.instructions
    action_sites = [instruction for instruction in instructions if _action_at(instruction)]
    guards: list[dict[str, Any]] = []
    for index, instruction in enumerate(instructions):
        if instruction.opcode != "cmp.eq":
            continue
        match = re.fullmatch(
            r"(\S+)\s*:=\s*(\S+)\s*=\s*(\d+)(?:[iu]\d+)?",
            instruction.operands.strip(),
        )
        if not match:
            continue
        result_variable, parameter, raw_value = match.groups()
        value = int(raw_value)
        set_flag = next(
            (item for item in instructions[index + 1:index + 4]
             if item.opcode == "set-flag"),
            None,
        )
        if not set_flag or set_flag.operands.strip() != f"not {result_variable}":
            continue
        set_flag_index = instructions.index(set_flag, index + 1)
        branch = next(
            (item for item in instructions[set_flag_index + 1:set_flag_index + 4]
             if item.opcode == "flag-goto"),
            None,
        )
        targets = script_flow.control_targets(branch) if branch else []
        if parameter != "s-1" or value not in setup_steps or not targets:
            continue
        skip_target = targets[0][0]
        body_start = (
            instructions[instructions.index(branch) + 1].address
            if instructions.index(branch) + 1 < len(instructions) else None
        )
        guarded = [
            item for item in action_sites
            if body_start is not None and body_start <= item.address < skip_target
        ]
        guards.append({
            "comparison_address": f"0x{instruction.address:x}",
            "parameter": parameter,
            "ordinal": value,
            "event": setup_steps[value],
            "branch_address": f"0x{branch.address:x}",
            "skip_target": f"0x{skip_target:x}",
            "actions_in_true_branch": [
                {"address": f"0x{item.address:x}", "call": item.operands}
                for item in guarded
            ],
            "branch_polarity_proven": True,
        })

    external_calls = []
    rows = planner._instruction_rows(disassembly.read_text(encoding="utf-8", errors="replace").splitlines())
    callback_addresses = {instruction.address for instruction in instructions}
    for position, row in enumerate(rows):
        if (
            row["opcode"] != "call"
            or int(row["address"], 16) not in callback_addresses
            or not row["operands"].casefold().startswith("dll:")
        ):
            continue
        if planner.ISDONE_EXPORT.match(row["operands"]):
            continue
        frame = planner._frame_for_call(rows, position)
        literals = [item["value"] for item in planner._frame_strings(frame)]
        external_calls.append({
            "address": row["address"],
            "procedure": next((proc.name for proc in procedures
                               if proc.entry <= int(row["address"], 16)
                               and (not proc.instructions or int(row["address"], 16) <= proc.instructions[-1].address)), None),
            "call": row["operands"],
            "nearby_string_literals_heuristic": literals,
            "modeled_by_plan_audit": False,
        })

    component_analysis = script_flow.component_bitmask(callback)
    recovered_steps = planner.steps_from_disassembly(disassembly, {}, {})
    component_steps = [
        {
            "archive": step.get("archive"),
            "call_address": step.get("bytecode", {}).get("call_address"),
            "cur_component": step.get("cur_component"),
        }
        for step in recovered_steps
        if step.get("type") == "extract"
    ]
    ini_conditions = [
        {
            "call_address": step.get("bytecode", {}).get("call_address"),
            "file": step.get("file"),
            "section": step.get("section"),
            "key": step.get("key"),
            "condition": step.get("condition"),
        }
        for step in recovered_steps
        if step.get("type") == "ini-write" and step.get("condition") is not None
    ]
    bit_by_name = {
        item["component"].casefold(): item["bit"]
        for item in (component_analysis or {}).get("components", [])
        if item.get("component")
    }
    component_by_bit: dict[int, list[str]] = {}
    for name, bit in bit_by_name.items():
        component_by_bit.setdefault(bit, []).append(name)
    for step in component_steps:
        index = step.get("cur_component")
        step["component_for_matching_bit"] = component_by_bit.get(index, [])
        step["index_matches_selection_bit"] = (
            index == 0 or index in component_by_bit
        )
    critical_external_effects = []
    for call in external_calls:
        literals = [str(value).casefold() for value in call["nearby_string_literals_heuristic"]]
        call_name = call["call"].casefold()
        if (
            "!exec2" in call_name
            and any("{uninstallexe}" in value for value in literals)
            and any("/verysilent" in value for value in literals)
        ):
            critical_external_effects.append({
                "kind": "unmodeled_silent_uninstaller_launch",
                "call_address": call["address"],
                "procedure": call["procedure"],
                "executable_literal": "{uninstallexe}",
                "arguments_literal": "/VERYSILENT",
                "severity": "critical",
                "modeled_by_native_plan": False,
                "blocks_audit_acceptance": True,
                "evidence_basis": "IFPS external-call frame literals; review the exact caller branch before interpreting reachability.",
                "detail": "A conditional silent-uninstaller launch is absent from the native plan and must be resolved before review acceptance.",
            })
        elif "!precompinit" in call_name:
            critical_external_effects.append({
                "kind": "unmodeled_precomp_ini_write",
                "call_address": call["address"],
                "procedure": call["procedure"],
                "severity": "critical",
                "modeled_by_native_plan": False,
                "blocks_audit_acceptance": True,
                "evidence_basis": (
                    "The exact ISDone.dll binary shared by the audited setups calls "
                    "WritePrivateProfileStringA for the Precomp section (Memory and TempPath) "
                    "from PrecompInit; the native action inventory does not model this export."
                ),
                "detail": "PrecompInit writes the Precomp Memory and TempPath keys to CLS.ini; that external configuration change is absent from the native plan.",
            })
        elif "!isdonestop" in call_name:
            critical_external_effects.append({
                "kind": "unmodeled_conditional_records_file_deletion",
                "call_address": call["address"],
                "procedure": call["procedure"],
                "severity": "critical",
                "modeled_by_native_plan": False,
                "blocks_audit_acceptance": True,
                "evidence_basis": (
                    "The exact ISDone.dll binary shared by the audited setups conditionally "
                    "calls DeleteFileA on the records path retained by ISDoneInit; the native "
                    "action inventory does not model this export or prove its guard unreachable."
                ),
                "detail": "ISDoneStop can delete the records.inf path retained by ISDoneInit when its internal cleanup guards pass; the native plan does not model or disprove that deletion.",
            })
    return {
        "callback": callback.name,
        "event_guards": guards,
        "recognized_actions": len(action_sites),
        "all_recognized_actions_covered_by_proven_event_guard": (
            bool(action_sites) and any(
                len(guard["actions_in_true_branch"]) == len(action_sites)
                for guard in guards
            )
        ),
        "component_selection": {
            "bitmask_analysis": component_analysis,
            "isarc_extract_calls": component_steps,
            "external_cur_component_semantics_proven": False,
        },
        "checkbox_conditions": {
            "ini_write_sites": ini_conditions,
            "all_reported_conditions_proven": bool(ini_conditions) and all(
                item["condition"].get("proven") is True for item in ini_conditions
            ),
        },
        "unmodeled_external_calls": external_calls,
        "critical_external_effects": critical_external_effects,
        "limitations": [
            "The event enum mapping uses Inno Setup's TSetupStep declaration and standard zero-based Pascal enum ordinals.",
            "No source or verified contract for ISDone.dll is available in this audit; its component and helper semantics remain opaque.",
            "The report inventories external DLL calls; it does not prove the side effects of calls omitted by the native plan.",
            "A matching ISDone CurComponent index and selection bit is structural evidence only; external ISDone.dll behavior is not executed or independently verified.",
        ],
        "sources": {
            "inno_setup_step_enum": "https://github.com/jrsoftware/issrc/blob/main/Projects/Src/Shared.SetupSteps.pas",
            "inno_curstepchanged_event": "https://jrsoftware.org/ishelp/topic_scriptevents.htm",
            "pascal_enum_ordinals": "https://docwiki.embarcadero.com/RADStudio/Athens/en/Simple_Types",
            "ifps_flag_branch_runtime": "https://github.com/jrsoftware/issrc/blob/main/Components/UniPs/Source/uPSRuntime.pas",
        },
    }


def audit_plan(
    manifest: dict[str, Any], iss: Path, disassembly: Path, compiled: Path,
    reproduced_disassembly: bytes | None = None,
    reproduction_error: str | None = None,
) -> dict[str, Any]:
    """Compare actions/order/arguments to reconstructed IFPS frames and raw calls.

    Re-decoding uses the planner and therefore is a regression cross-check, not
    an independent interpreter. Unknown branches and interprocedural order are
    deliberately not promoted to proven semantics.
    """
    issues: list[dict[str, Any]] = []
    lines = disassembly.read_text(encoding="utf-8", errors="replace").splitlines()
    hashes = {
        "iss_sha256": planner.sha256(iss),
        "disassembly_sha256": planner.sha256(disassembly),
        "compiled_code_sha256": planner.sha256(compiled),
    }
    binary_disassembly_verified = False
    if reproduction_error:
        issues.append({"kind": "compiled_disassembly_failed", "detail": reproduction_error})
    elif reproduced_disassembly is not None:
        binary_disassembly_verified = reproduced_disassembly == disassembly.read_bytes()
        if not binary_disassembly_verified:
            issues.append({
                "kind": "compiled_disassembly_mismatch",
                "expected_sha256": hashes["disassembly_sha256"],
                "actual_sha256": hashlib.sha256(reproduced_disassembly).hexdigest(),
            })
    recorded = manifest.get("analysis", {})
    provenance_complete = True
    for field, actual in hashes.items():
        if not recorded.get(field):
            provenance_complete = False
            issues.append({"kind": "missing_provenance", "field": field})
        elif recorded[field] != actual:
            issues.append({"kind": "source_hash_mismatch", "field": field})

    steps = manifest.get("steps", [])
    needs_verifier = "fitgirl.md5" in iss.read_text(encoding="utf-8", errors="replace").lower()
    if needs_verifier and sum(step.get("type") == "verify" for step in steps) != 1:
        issues.append({"kind": "verification_coverage"})
    coverage = planner.action_coverage(lines, steps)
    if not coverage["complete"]:
        issues.append({"kind": "action_coverage", "details": coverage})
    rows = planner._instruction_rows(lines)
    raw = []
    for row in rows:
        if row["opcode"] != "call":
            continue
        exported = planner.ISDONE_EXPORT.match(row["operands"])
        if exported or row["operands"].casefold() in planner.MUTATING_CALLS:
            raw.append((row["address"].casefold(), (
                exported.group(1) if exported else row["operands"]
            ).casefold()))

    def identity(step: dict[str, Any]) -> tuple[str, str]:
        code = step.get("bytecode", {})
        return str(code.get("call_address", "")).casefold(), str(code.get("export", "")).casefold()

    planned = [identity(step) for step in steps if step.get("bytecode")]
    if planned != raw:
        issues.append({"kind": "action_sequence", "expected": raw, "actual": planned})
    for key, count in Counter(planned).items():
        if count > 1:
            issues.append({"kind": "duplicate_action", "action": key, "count": count})

    # The MD5 catalog is intentionally taken from the candidate: archive digest
    # correctness is a separate check, not evidence supplied by IFPS.
    md5s = {
        str(step["archive"]).lower(): step["md5"]
        for step in steps if step.get("archive") and step.get("md5")
    }
    components = planner.components_from_iss(iss)
    reference = planner.steps_from_disassembly(disassembly, components, md5s)
    expected_by_call = {identity(step): step for step in reference}
    for index, step in enumerate(steps):
        if step.get("type") == "verify" and not step.get("bytecode"):
            if (
                index != len(steps) - 1 or step.get("root") != "app"
                or step.get("manifest_root") != (
                    "app" if any(s.get("type") == "merge-manifests" for s in steps) else "payload_app"
                )
                or step.get("manifest") != "_Redist/fitgirl.md5"
                or "fitgirl.md5" not in iss.read_text(encoding="utf-8", errors="replace").lower()
            ):
                issues.append({"kind": "unproved_verification", "step": index + 1})
            continue
        expected = expected_by_call.get(identity(step))
        if expected is None:
            issues.append({"kind": "unmapped_action", "step": index + 1})
            continue
        fields = (set(step) | set(expected)) - IGNORED_STEP_FIELDS
        for field in sorted(fields):
            if step.get(field) != expected.get(field):
                issues.append({
                    "kind": "argument_or_condition_mismatch", "step": index + 1,
                    "field": field, "expected": expected.get(field), "actual": step.get(field),
                })
    if components != manifest.get("components", {}):
        issues.append({"kind": "components_mismatch"})
    if "disk_space" in manifest and manifest["disk_space"] != planner.disk_space_from_iss(iss):
        issues.append({"kind": "disk_space_mismatch"})
    for inventory, recover in (
        ("temporary_payload_files", lambda: planner.temporary_payload_files(disassembly, iss)[0]),
        ("application_payload_files", lambda: planner.application_payload_files(iss)[0]),
    ):
        if manifest.get(inventory, []) != recover():
            issues.append({"kind": "payload_mismatch", "field": inventory})

    semantic_guards = semantic_guard_report(disassembly)
    isdone_sha256 = recorded.get("isdone_sha256")
    isdone_version = isdone_catalog.version(isdone_sha256)
    success = success_path.success_path_report(
        disassembly, isdone_version.successful_exports if isdone_version else frozenset(),
    )
    semantic_guards["critical_external_effects"] = isdone_catalog.resolve_effects(
        semantic_guards.get("critical_external_effects", []), disassembly, isdone_sha256, success,
    )
    for effect in semantic_guards["critical_external_effects"]:
        if effect.get("blocks_audit_acceptance") is False:
            continue
        issues.append({
            "kind": effect["kind"],
            "call_address": effect["call_address"],
            "procedure": effect["procedure"],
            "detail": effect.get("detail", "An external ISDone.dll effect is absent from the native plan and must be resolved before review acceptance."),
        })

    cfg = script_flow.cfg_report(disassembly)
    action_paths = action_path_report(disassembly)
    if not cfg["totals"]["procedures"] or not cfg["totals"]["instructions"]:
        issues.append({"kind": "unparsed_control_flow"})
    unresolved = [
        {"procedure": proc["name"], **item}
        for proc in cfg["procedures"] for item in proc["unresolved_targets"]
    ]
    if unresolved:
        issues.append({"kind": "unresolved_cfg_targets", "details": unresolved})
    return {
        "schema": SCHEMA_VERSION,
        "status": "MISMATCH" if issues else "MATCH_REVIEW_REQUIRED",
        "consistent": not issues,
        "provenance_complete": provenance_complete,
        "sources": hashes,
        "coverage": coverage,
        "issues": issues,
        "control_flow_totals": cfg["totals"],
        "action_paths": action_paths,
        "semantic_guards": semantic_guards,
        "isdone": {
            "sha256": isdone_sha256,
            "catalogued": isdone_version is not None,
            "label": isdone_version.label if isdone_version else None,
        },
        "success_path": success,
        "interprocedural_action_paths": interprocedural_action_path_report(
            disassembly, entry_limit=4, sequence_limit=64, depth_limit=4,
            in_procedure_sequence_limit=128,
        ),
        "semantic_equivalence_proven": False,
        "binary_disassembly_verified": binary_disassembly_verified,
        "review_required": True,
        "limitations": [
            "Argument reconstruction shares the planner implementation; not an independent interpreter.",
            ("Disassembly was reproduced byte-for-byte from CompiledCode.bin with the configured tool."
             if binary_disassembly_verified else
             "Source hashes bind cached artifacts but reproduction from CompiledCode.bin was not verified."),
            "Instruction order is not proven runtime order across branches, loops or procedures.",
            "Component inference is checked for consistency, not proven for every execution path.",
            "Known event guards are reported separately; external DLL helper and component-index semantics remain unproved.",
            "Archive MD5 values and runtime effects require separate empirical validation.",
        ],
    }


def write_audit(
    manifest: dict[str, Any], iss: Path, disassembly: Path, compiled: Path,
    output: Path, disassembler: Path | None = None,
) -> dict[str, Any]:
    import json

    output.parent.mkdir(parents=True, exist_ok=True)
    reproduced = None
    reproduction_error = None
    temporary = output.parent / f".{output.name}.redissect-{os.getpid()}"
    errors = output.parent / f".{output.name}.redissect-{os.getpid()}.stderr"
    if disassembler is not None:
        try:
            with temporary.open("wb") as stdout, errors.open("wb") as stderr:
                result = subprocess.run(
                    [str(disassembler), str(compiled)], stdout=stdout, stderr=stderr,
                    timeout=120, check=False,
                )
            if result.returncode:
                reproduction_error = f"disassembler encerrou com código {result.returncode}"
            else:
                reproduced = temporary.read_bytes()
        except (OSError, subprocess.TimeoutExpired) as error:
            reproduction_error = str(error)
        finally:
            temporary.unlink(missing_ok=True)
            errors.unlink(missing_ok=True)
    report = audit_plan(
        deepcopy(manifest), iss, disassembly, compiled,
        reproduced_disassembly=reproduced,
        reproduction_error=reproduction_error,
    )
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
