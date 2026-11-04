#!/usr/bin/env python3
"""Build a reviewable manifest draft from innounp ISS + IFPS disassembly."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


ASSIGN_STRING = re.compile(r'assign\s+\S+,\s+"([^"]*)"', re.IGNORECASE)
ARCHIVE = re.compile(r"^\{src\}\\(.+\.bin)$", re.IGNORECASE)
LOGICAL_PATH = re.compile(r"^\{(app|tmp)\}\\?(.*)$", re.IGNORECASE)
LINE_ADDRESS = re.compile(r"^\s*(0x[0-9a-fA-F]+)")
INSTRUCTION_LINE = re.compile(r"^\s*(0x[0-9a-fA-F]+)\s{2}(\S+)(?:\s+(.*?))?\s*$")
STRING_OPERAND = re.compile(r'^\S+,\s+"(.*)"$')
INTEGER_OPERAND = re.compile(r"^(\S+),\s+(-?\d+)(?:[iu]\d+)?$")
ISDONE_EXPORT = re.compile(
    r"^dll:files:ISDone\.dll!(ISArcExtract|ISExec)$", re.IGNORECASE
)
PLAN_COMPILER_VERSION = 11
FILESYSTEM_ACTIONS = {"deletefile": "delete-file", "deltree": "delete-tree"}
MUTATING_CALLS = {**FILESYSTEM_ACTIONS, "setinistring": "ini-write"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def md5_catalog(source: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in source.rglob("*.md5"):
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            match = re.match(r"^([0-9a-fA-F]{32})\s+[* ](?:\.\.[\\/])?(.+)$", line.strip())
            if match:
                result[Path(match.group(2).replace("\\", "/")).name.lower()] = match.group(1).lower()
    return result


def nearest_logical(
    strings: list[tuple[int, str, str | None]], line_number: int, window: int = 45
) -> tuple[str, str] | None:
    for index, value, _address in reversed(strings):
        if index >= line_number or line_number - index > window:
            continue
        match = LOGICAL_PATH.match(value)
        if match:
            return match.group(1).lower(), match.group(2).replace("\\", "/").rstrip("/")
    return None


def infer_component(archive: str, components: dict[str, dict[str, Any]]) -> str | None:
    normalized = re.sub(r"[^a-z0-9]", "", archive.lower())
    ranked = []
    for name in components:
        token = re.sub(r"[^a-z0-9]", "", name.lower())
        if token and token in normalized:
            ranked.append((len(token), name))
    if "4k" in normalized and "vid4k" in components:
        return "vid4k"
    return max(ranked)[1] if ranked else None


def _instruction_rows(lines: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for order, line in enumerate(lines):
        match = INSTRUCTION_LINE.match(line)
        if not match:
            continue
        rows.append({
            "order": order,
            "address": match.group(1).lower(),
            "opcode": match.group(2).lower(),
            "operands": match.group(3) or "",
        })
    return rows


def _frame_for_call(rows: list[dict[str, Any]], call_index: int) -> list[dict[str, Any]]:
    start = call_index
    while start >= 0:
        row = rows[start]
        if row["opcode"] == "assign" and row["operands"].startswith("s+15, "):
            return rows[start:call_index + 1]
        start -= 1
    return rows[max(0, call_index - 80):call_index + 1]


def _frame_strings(frame: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in frame:
        if row["opcode"] not in {"assign", "calc.add"}:
            continue
        match = STRING_OPERAND.match(row["operands"])
        if match:
            destination = row["operands"].split(",", 1)[0]
            result.append({
                "address": row["address"],
                "operation": row["opcode"],
                "destination": destination,
                "value": match.group(1),
            })
    return result


def _logical(value: str) -> tuple[str, str] | None:
    match = re.match(r"^\{(app|tmp|src)\}\\?(.*)$", value, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).lower(), match.group(2).replace("\\", "/").rstrip("/")


def _integer_argument(frame: list[dict[str, Any]], variable: str) -> int | None:
    value: int | None = None
    for row in frame:
        if row["opcode"] != "assign":
            continue
        match = INTEGER_OPERAND.match(row["operands"])
        if match and match.group(1) == variable:
            value = int(match.group(2))
    return value


def _string_argument(strings: list[dict[str, Any]], variable: str) -> str | None:
    value: str | None = None
    for item in strings:
        if item["operation"] == "assign" and item["destination"] == variable:
            value = item["value"]
    return value


def checkbox_symbols(lines: list[str]) -> dict[str, str]:
    """Link global checkbox variables to their custom-message caption key."""
    rows = _instruction_rows(lines)
    result: dict[str, str] = {}
    for index, row in enumerate(rows):
        if row["opcode"] != "set-ptr":
            continue
        global_match = re.search(r":=\s+@(g#\d+)$", row["operands"])
        if not global_match:
            continue
        window = rows[index + 1:index + 81]
        caption_call = next(
            (position for position, candidate in enumerate(window)
             if candidate["opcode"] == "call"
             and candidate["operands"] == "class:TCHECKBOX|CAPTION@|"),
            None,
        )
        if caption_call is None:
            continue
        for candidate in window[:caption_call]:
            if candidate["opcode"] != "assign":
                continue
            string = STRING_OPERAND.match(candidate["operands"])
            if string and re.fullmatch(r"\{cm:[^}]+\}", string.group(1), re.IGNORECASE):
                result[global_match.group(1)] = string.group(1)[4:-1]
                break
    return result


def _ini_step(
    rows: list[dict[str, Any]], call_index: int, checkbox_names: dict[str, str]
) -> dict[str, Any] | None:
    call = rows[call_index]
    start = call_index - 1
    while start >= 0:
        row = rows[start]
        if row["opcode"] == "call" and row["operands"].casefold() == "setinistring":
            start += 1
            break
        start -= 1
    frame = rows[max(0, start):call_index + 1]
    strings = _frame_strings(frame)
    filename_position = next(
        (index for index, item in enumerate(strings)
         if item["value"].casefold().endswith(".ini") and _logical(item["value"])),
        None,
    )
    if filename_position is None:
        return None
    arguments = strings[filename_position:]
    if len(arguments) < 4:
        return None
    filename, value, key, section_name = arguments[-4:]
    logical = _logical(filename["value"])
    if logical is None:
        return None
    condition: dict[str, Any] | None = None
    for row in reversed(frame[:frame.index(next(
        item for item in frame if item["address"] == filename["address"]
    ))]):
        if row["opcode"] != "flag-goto":
            continue
        target = re.search(r"0x[0-9a-fA-F]+", row["operands"])
        if not target or int(target.group(), 16) <= int(call["address"], 16):
            continue
        branch_position = frame.index(row)
        checkbox_position = next(
            (position for position in range(branch_position - 1, max(-1, branch_position - 10), -1)
             if frame[position]["opcode"] == "call"
             and frame[position]["operands"] == "class:TCHECKBOX|CHECKED|"),
            None,
        )
        if checkbox_position is None:
            continue
        source = next(
            (candidate["operands"].split(",", 1)[1].strip()
             for candidate in reversed(frame[:checkbox_position])
             if candidate["opcode"] == "assign"
             and candidate["operands"].startswith("s+15, g#")),
            None,
        )
        condition = {
            "kind": "checkbox-checked",
            "source": source,
            "option": checkbox_names.get(source or ""),
            "branch_address": row["address"],
            "skip_target": target.group().lower(),
            "when_checked": True,
            "proven": source is not None,
        }
        break
    return {
        "id": "ini-" + re.sub(
            r"[^a-z0-9]+", "-", f"{section_name['value']}-{key['value']}"
        ).strip("-").lower(),
        "type": "ini-write",
        "description": (
            f"Definir [{section_name['value']}] {key['value']} em {filename['value']}"
        ),
        "file_root": logical[0],
        "file": logical[1],
        "section": section_name["value"],
        "key": key["value"],
        "value": value["value"],
        "condition": condition,
        "bytecode": {
            "argument_address": filename["address"],
            "call_address": call["address"],
            "export": "SETINISTRING",
        },
        "_order": call["order"],
    }


def _isarc_step(
    frame: list[dict[str, Any]], strings: list[dict[str, Any]], call: dict[str, Any],
    md5s: dict[str, str],
) -> dict[str, Any] | None:
    archive_item = next(
        (item for item in reversed(strings)
         if re.search(r"\.(?:bin|fgpack)$", item["value"], re.IGNORECASE)),
        None,
    )
    if archive_item is None or _logical(archive_item["value"]) is None:
        return None
    archive_root, archive_path = _logical(archive_item["value"]) or ("", "")
    destination_item = next(
        (item for item in reversed(strings[:strings.index(archive_item)])
         if _logical(item["value"]) and item["value"].endswith("\\")),
        None,
    )
    destination = _logical(destination_item["value"]) if destination_item else None
    archive_name = Path(archive_path).name
    base_id = re.sub(r"[^a-z0-9]+", "-", archive_name.lower()).strip("-")
    step: dict[str, Any] = {
        "id": base_id,
        "type": "extract",
        "description": f"Extrair {archive_name}",
        "archive": archive_path,
        "destination": destination[0] if destination else "REVIEW",
        "cur_component": _integer_argument(frame, "s+24"),
        "bytecode": {
            "argument_address": archive_item["address"],
            "call_address": call["address"],
            "export": "ISArcExtract",
        },
        "_order": call["order"],
    }
    if destination and destination[1]:
        step["destination_suffix"] = destination[1]
    if archive_root != "src":
        step["archive_root"] = archive_root
    expected_md5 = md5s.get(archive_name.lower())
    if expected_md5:
        step["md5"] = expected_md5
    delete_assignments = []
    for row in frame:
        if row["opcode"] != "assign":
            continue
        match = INTEGER_OPERAND.match(row["operands"])
        if match and match.group(1) == "s+19":
            delete_assignments.append(int(match.group(2)))
    if delete_assignments and delete_assignments[-1] != 0:
        step["delete_archive_after"] = True
    extracted_path = _string_argument(strings, "s+20")
    step["isarc_arguments"] = {
        "cur_component": step["cur_component"],
        "pct_of_total": _integer_argument(frame, "s+23"),
        "input": archive_item["value"],
        "output": destination_item["value"] if destination_item else None,
        "extracted_path": extracted_path,
        "delete_input": bool(delete_assignments[-1]) if delete_assignments else None,
        "extract_pcf": bool(_integer_argument(frame, "s+15")),
    }
    if extracted_path:
        step["archive_path_filter"] = extracted_path
    return step


def _isexec_step(
    frame: list[dict[str, Any]], strings: list[dict[str, Any]], call: dict[str, Any],
) -> dict[str, Any] | None:
    executable_item = next(
        (item for item in reversed(strings)
         if item["operation"] == "assign" and item["destination"] == "s+21"),
        None,
    )
    if executable_item is None:
        return None
    executable = executable_item["value"]
    description_item = next(
        (item for item in strings
         if item["operation"] == "assign" and item["destination"] == "s+16"),
        None,
    )
    cwd_item = next(
        (item for item in strings
         if item["operation"] == "assign" and _logical(item["value"])
         and item["value"].endswith("\\")),
        None,
    )
    direct_parameters_item = next(
        (item for item in strings
         if item["operation"] == "assign" and item["destination"] == "s+20"),
        None,
    )
    raw_expression = [
        {"operation": item["operation"], "value": item["value"],
         "address": item["address"]}
        for item in strings
        if item["destination"] == "s+19" and item["value"] != executable
    ]
    embedded = next(
        (item for item in strings
         if item["operation"] == "assign" and item["destination"] == "s+22"),
        None,
    )
    is_command_shell = executable.casefold() == "{cmd}"
    direct_parameters = None if is_command_shell else (
        direct_parameters_item["value"] if direct_parameters_item else None
    )
    parameter_expression: list[dict[str, Any]] = []
    if is_command_shell:
        for position, part in enumerate(raw_expression):
            parameter_expression.append(part)
            if position == 0 and embedded:
                parameter_expression.append({
                    "operation": "expanded_quoted",
                    "value": embedded["value"],
                    "address": embedded["address"],
                })
    identity = embedded["value"] if executable.casefold() == "{cmd}" and embedded else executable
    base_id = re.sub(r"[^a-z0-9]+", "-", Path(identity.replace("\\", "/")).name.lower()).strip("-")
    step: dict[str, Any] = {
        "id": base_id,
        "type": "isexec",
        "description": description_item["value"] if description_item else f"Executar {identity}",
        "executable": executable,
        "parameters": direct_parameters,
        "cur_component": _integer_argument(frame, "s+22"),
        "bytecode": {
            "argument_address": executable_item["address"],
            "call_address": call["address"],
            "export": "ISExec",
        },
        "_order": call["order"],
    }
    if cwd_item:
        cwd = _logical(cwd_item["value"])
        if cwd:
            step["cwd"] = cwd[0]
            if cwd[1]:
                step["cwd_suffix"] = cwd[1]
    if embedded:
        step["embedded_command"] = embedded["value"]
    if parameter_expression:
        step["parameter_expression"] = parameter_expression
    executable_name = Path(identity.replace("\\", "/")).name.casefold()
    if executable_name == "fnr.exe":
        step["rollback_paths"] = [{"root": "tmp", "path": "arc.ini"}]
    elif executable_name == "flushfilecache.exe":
        step["rollback_paths"] = []
    elif executable_name == "x.exe" and description_item:
        patched = description_item["value"].replace("\\", "/")
        step["rollback_paths"] = [
            {"root": "app", "path": patched},
            {"root": "app", "path": patched + ".x"},
            {"root": "app", "path": patched + "_"},
        ]
    elif executable_name == "fart.exe":
        extension = "*.bat" if "*.bat" in (direct_parameters or "").casefold() else "*.txt"
        suffix = step.get("cwd_suffix", "")
        step["rollback_paths"] = [{
            "root": step.get("cwd", "tmp"),
            "path": f"{suffix}/{extension}" if suffix else extension,
            "glob": True,
        }]
    elif executable_name.endswith((".bat", ".cmd")):
        # A recovered batch program is arbitrary code. Snapshot its complete
        # working tree unless a later analyzer proves a narrower write set.
        step["rollback_paths"] = [{"root": step.get("cwd", "app"), "path": "."}]
    elif executable_name == "x5n.exe":
        # x5n's '-f . ... .' syntax permits mutation anywhere below {app}.
        step["rollback_paths"] = [{"root": "app", "path": "."}]
    elif executable.casefold() == "{cmd}" and embedded:
        if embedded["value"].strip().casefold() == "copy /b fitgirl.md5+*.addon&&del *.addon":
            if step.get("cwd") == "app" and step.get("cwd_suffix") == "_Redist":
                step["type"] = "merge-manifests"
                step["rollback_paths"] = [{"root": "app", "path": "_Redist"}]
        delete_match = re.fullmatch(
            r"\s*del\s+(.+?)\s*", embedded["value"], flags=re.IGNORECASE
        )
        if delete_match:
            step["rollback_paths"] = [{
                "root": step.get("cwd", "app"),
                "path": delete_match.group(1).strip('"').replace("\\", "/"),
            }]
    step["isexec_arguments"] = {
        "cur_component": step["cur_component"],
        "pct_of_total": _integer_argument(frame, "s+21"),
        "specified_process_time": _integer_argument(frame, "s+20"),
        "executable": executable,
        "parameters": step["parameters"],
        "target_dir": cwd_item["value"] if cwd_item else None,
        "output": description_item["value"] if description_item else None,
        "show": bool(_integer_argument(frame, "s+15")),
    }
    return step


def named_isdone_steps(
    lines: list[str], components: dict[str, dict[str, Any]], md5s: dict[str, str],
    checkbox_names: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Recover every ISArcExtract/ISExec action from enriched disassembly."""
    rows = _instruction_rows(lines)
    result: list[dict[str, Any]] = []
    for index, call in enumerate(rows):
        if call["opcode"] != "call":
            continue
        exported = ISDONE_EXPORT.match(call["operands"])
        if not exported:
            continue
        frame = _frame_for_call(rows, index)
        strings = _frame_strings(frame)
        if exported.group(1).casefold() == "isarcextract":
            step = _isarc_step(frame, strings, call, md5s)
        else:
            step = _isexec_step(frame, strings, call)
        if step:
            if step["type"] == "extract":
                component = infer_component(Path(step["archive"]).name, components)
                if component:
                    step["if_component"] = component
                    components[component].setdefault("available_if", Path(step["archive"]).name)
            result.append(step)
    for index, call in enumerate(rows):
        if call["opcode"] == "call" and call["operands"].casefold() == "setinistring":
            step = _ini_step(rows, index, checkbox_names or {})
            if step:
                result.append(step)
    for index, call in enumerate(rows):
        kind = FILESYSTEM_ACTIONS.get(
            call["operands"].casefold() if call["opcode"] == "call" else ""
        )
        if not kind:
            continue
        candidates = _frame_strings(rows[max(0, index - 25):index + 1])
        path_item = next(
            (item for item in reversed(candidates) if _logical(item["value"])),
            None,
        )
        if path_item is None:
            continue
        logical = _logical(path_item["value"])
        if logical is None:
            continue
        base_id = re.sub(
            r"[^a-z0-9]+", "-", Path(logical[1]).name.lower()
        ).strip("-") or kind
        result.append({
            "id": f"{kind}-{base_id}",
            "type": kind,
            "description": (
                f"Remover arquivo {path_item['value']}" if kind == "delete-file"
                else f"Remover diretório {path_item['value']}"
            ),
            "path_root": logical[0],
            "path": logical[1],
            "bytecode": {
                "argument_address": path_item["address"],
                "call_address": call["address"],
                "export": call["operands"],
            },
            "_order": call["order"],
        })
    result.sort(key=lambda step: step["_order"])
    occurrences: dict[str, int] = {}
    for step in result:
        base_id = step["id"]
        occurrences[base_id] = occurrences.get(base_id, 0) + 1
        if occurrences[base_id] > 1:
            step["id"] = f"{base_id}-{occurrences[base_id]}"
    return result


def action_coverage(lines: list[str], steps: list[dict[str, Any]]) -> dict[str, Any]:
    expected: list[dict[str, str]] = []
    for row in _instruction_rows(lines):
        if row["opcode"] != "call":
            continue
        exported = ISDONE_EXPORT.match(row["operands"])
        if exported:
            expected.append({"address": row["address"], "export": exported.group(1)})
        elif row["operands"].casefold() in MUTATING_CALLS:
            expected.append({"address": row["address"], "export": row["operands"]})
    planned = [
        {
            "address": step["bytecode"]["call_address"],
            "export": step["bytecode"]["export"],
        }
        for step in steps if (
            step.get("bytecode", {}).get("export", "").casefold()
            in {"isarcextract", "isexec", *MUTATING_CALLS}
        )
    ]
    expected_keys = {(item["address"], item["export"].casefold()) for item in expected}
    planned_keys = {(item["address"], item["export"].casefold()) for item in planned}
    return {
        "relevant_calls": len(expected),
        "planned_actions": len(planned),
        "missing": [item for item in expected
                    if (item["address"], item["export"].casefold()) not in planned_keys],
        "unexpected": [item for item in planned
                       if (item["address"], item["export"].casefold()) not in expected_keys],
        "complete": expected_keys == planned_keys and len(expected) == len(planned),
    }


def temporary_payload_files(
    disassembly: Path, iss: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Recover every ExtractTemporaryFile dependency across all procedures."""
    from .ifps_ir import parse_disassembly

    calls: list[dict[str, Any]] = []
    for procedure in parse_disassembly(disassembly):
        for index, instruction in enumerate(procedure.instructions):
            if instruction.opcode != "call" or instruction.operands != "EXTRACTTEMPORARYFILE":
                continue
            argument = None
            for candidate in reversed(procedure.instructions[max(0, index - 8):index]):
                if candidate.opcode != "assign":
                    continue
                match = STRING_OPERAND.match(candidate.operands)
                if match:
                    argument = {
                        "name": match.group(1),
                        "procedure": procedure.name,
                        "argument_address": f"0x{candidate.address:x}",
                        "call_address": f"0x{instruction.address:x}",
                    }
                    break
            if argument:
                calls.append(argument)
    iss_sources = {
        Path((field(line, "Source") or "").replace("\\", "/")).name.casefold()
        for line in section(
            iss.read_text(encoding="utf-8", errors="replace").splitlines(), "Files"
        )
        if field(line, "Source")
    }
    by_name: dict[str, dict[str, Any]] = {}
    for call in calls:
        key = call["name"].casefold()
        item = by_name.setdefault(key, {
            "name": call["name"],
            "destination": "tmp",
            "present_in_iss": key in iss_sources,
            "calls": [],
        })
        item["calls"].append({key: value for key, value in call.items() if key != "name"})
    files = list(by_name.values())
    missing_arguments = len(calls) - sum(len(item["calls"]) for item in files)
    coverage = {
        "relevant_calls": sum(
            1 for procedure in parse_disassembly(disassembly)
            for instruction in procedure.instructions
            if instruction.opcode == "call" and instruction.operands == "EXTRACTTEMPORARYFILE"
        ),
        "planned_calls": len(calls),
        "unique_files": len(files),
        "missing_arguments": missing_arguments,
        "missing_from_iss": [item["name"] for item in files if not item["present_in_iss"]],
    }
    coverage["complete"] = (
        coverage["relevant_calls"] == coverage["planned_calls"]
        and missing_arguments == 0 and not coverage["missing_from_iss"]
    )
    return files, coverage


def application_payload_files(iss: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Recover active setup files whose destination belongs to {app}."""
    result: list[dict[str, Any]] = []
    lines = section(
        iss.read_text(encoding="utf-8", errors="replace").splitlines(), "Files"
    )
    for line in lines:
        if line.lstrip().startswith(";"):
            continue
        source = field(line, "Source")
        if not source:
            continue
        logical = _logical(source)
        if not logical or logical[0] != "app" or not logical[1]:
            continue
        result.append({
            "path": logical[1],
            "source": source,
            "destination": "app",
            "components": (field(line, "Components") or "").split(),
            "flags": (field(line, "Flags") or "").split(),
        })
    unique = {item["path"].casefold() for item in result}
    coverage = {
        "active_entries": len(result),
        "unique_files": len(unique),
        "duplicates": len(result) - len(unique),
        "complete": len(result) == len(unique),
    }
    return result, coverage


def steps_from_disassembly(
    path: Path, components: dict[str, dict[str, Any]], md5s: dict[str, str]
) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    names = checkbox_symbols(lines)
    start = next((index for index, line in enumerate(lines) if line.startswith("CURSTEPCHANGED ")), 0)
    lines = lines[start:]
    named_steps = named_isdone_steps(lines, components, md5s, names)
    if named_steps:
        named_steps.sort(key=lambda step: step["_order"])
        for step in named_steps:
            step.pop("_order")
        return named_steps
    strings: list[tuple[int, str, str | None]] = []
    for index, line in enumerate(lines):
        match = ASSIGN_STRING.search(line)
        if match:
            address = LINE_ADDRESS.match(line)
            strings.append((index, match.group(1), address.group(1).lower() if address else None))

    steps: list[dict[str, Any]] = []
    archive_occurrences: dict[str, int] = {}
    for index, value, address in strings:
        match = ARCHIVE.match(value)
        if not match:
            continue
        archive = Path(match.group(1).replace("\\", "/")).name
        following = "\n".join(lines[index:index + 28])
        if "call        dll:files:ISDone.dll" not in following:
            continue
        destination = nearest_logical(strings, index)
        archive_key = archive.lower()
        archive_occurrences[archive_key] = archive_occurrences.get(archive_key, 0) + 1
        occurrence = archive_occurrences[archive_key]
        base_id = re.sub(r"[^a-z0-9]+", "-", archive_key).strip("-")
        step: dict[str, Any] = {
            "id": base_id if occurrence == 1 else f"{base_id}-{occurrence}",
            "type": "extract",
            "description": f"Extrair {archive}",
            "archive": archive,
            "destination": destination[0] if destination else "REVIEW",
            "_order": index,
        }
        expected_md5 = md5s.get(archive.lower())
        if expected_md5:
            step["md5"] = expected_md5
        call = next(
            (LINE_ADDRESS.match(line) for line in lines[index:index + 28]
             if "call        dll:files:ISDone.dll" in line),
            None,
        )
        if address or (call and call.group(1)):
            step["bytecode"] = {
                "argument_address": address,
                "call_address": call.group(1).lower() if call else None,
            }
        component = infer_component(archive, components)
        if component:
            step["if_component"] = component
            components[component].setdefault("available_if", archive)
        elif "optional" in archive.lower() or "selective" in archive.lower():
            step["condition_review_required"] = True
        steps.append(step)

    seen_scripts: set[str] = set()
    for index, value, address in strings:
        logical = LOGICAL_PATH.match(value)
        if not logical or not logical.group(2).lower().endswith((".bat", ".cmd")):
            continue
        script = Path(logical.group(2).replace("\\", "/")).name
        if script.lower() in seen_scripts:
            continue
        following = "\n".join(lines[index:index + 48])
        if "call        dll:files:ISDone.dll" not in following:
            continue
        cwd = nearest_logical(strings, index)
        step = {
            "id": re.sub(r"[^a-z0-9]+", "-", script.lower()).strip("-"),
            "type": "batch",
            "description": f"Executar {script}",
            "script_root": logical.group(1).lower(),
            "script": script,
            "cwd": "app",
            "_order": index,
        }
        if cwd and cwd[0] == "app" and cwd[1]:
            step["cwd_suffix"] = cwd[1]
        call = next(
            (LINE_ADDRESS.match(line) for line in lines[index:index + 48]
             if "call        dll:files:ISDone.dll" in line),
            None,
        )
        if address or (call and call.group(1)):
            step["bytecode"] = {
                "argument_address": address,
                "call_address": call.group(1).lower() if call else None,
            }
        steps.append(step)
        seen_scripts.add(script.lower())

    steps.sort(key=lambda step: step["_order"])
    for step in steps:
        step.pop("_order")
    return steps


def build_manifest(iss: Path, disassembly: Path, setup: Path, source: Path) -> dict[str, Any]:
    components = components_from_iss(iss)
    steps = steps_from_disassembly(disassembly, components, md5_catalog(source))
    disassembly_lines = disassembly.read_text(encoding="utf-8", errors="replace").splitlines()
    coverage = action_coverage(disassembly_lines, steps)
    payload_files, payload_coverage = temporary_payload_files(disassembly, iss)
    app_files, app_coverage = application_payload_files(iss)
    if "fitgirl.md5" in iss.read_text(encoding="utf-8", errors="replace").lower():
        steps.append({
            "id": "verify-game-files",
            "type": "verify",
            "description": "Validar instalação contra _Redist/fitgirl.md5",
            "manifest_root": "app" if any(s["type"] == "merge-manifests" for s in steps) else "payload_app",
            "manifest": "_Redist/fitgirl.md5",
            "root": "app",
        })
    return {
        "schema": 1,
        "compiler_version": PLAN_COMPILER_VERSION,
        "draft": True,
        "review_required": True,
        "name": setup.parent.name,
        "setup_sha256": [sha256(setup)],
        "components": components,
        "steps": steps,
        "action_coverage": coverage,
        "temporary_payload_files": payload_files,
        "temporary_payload_coverage": payload_coverage,
        "application_payload_files": app_files,
        "application_payload_coverage": app_coverage,
        "disk_space": disk_space_from_iss(iss),
    }


def write_manifest(
    iss: Path, disassembly: Path, setup: Path, source: Path, output: Path
) -> dict[str, Any]:
    manifest = build_manifest(iss, disassembly, setup, source)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest
