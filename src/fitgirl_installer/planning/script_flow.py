#!/usr/bin/env python3
"""Parse symbolic IFPS disassembly and build conservative control-flow graphs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PROCEDURE_HEADER = re.compile(r"^===== proc #(\d+) =====$")
PROCEDURE_SIGNATURE = re.compile(
    r"^(\S+)\s+bytecode\s+@(0x[0-9a-fA-F]+)\s+\(\d+ bytes, \d+ instructions\)$"
)
INSTRUCTION = re.compile(r"^\s*(0x[0-9a-fA-F]+)\s{2}(.+?)\s*$")
ADDRESS = re.compile(r"0x[0-9a-fA-F]+")
STRING_ASSIGNMENT = re.compile(r'^\S+,\s+"([^"]*)"$')
CONDITION_APIS = {"iscomponentselected", "fileexists"}
SCHEMA_VERSION = 5


def is_dll_call(callee: str, library: str, function: str | None = None) -> bool:
    """Match enriched DLL references while accepting legacy library-only output."""
    prefix = f"dll:{library}"
    if callee.casefold() == prefix.casefold():
        return function is None
    expected = prefix if function is None else f"{prefix}!{function}"
    return callee.casefold() == expected.casefold()


@dataclass(frozen=True)
class Instruction:
    address: int
    opcode: str
    operands: str
    raw: str


@dataclass
class Procedure:
    index: int
    name: str
    entry: int
    instructions: list[Instruction] = field(default_factory=list)


@dataclass(frozen=True)
class Edge:
    target: int
    kind: str


@dataclass
class BasicBlock:
    start: int
    instructions: list[Instruction]
    successors: list[Edge] = field(default_factory=list)

    @property
    def end(self) -> int:
        return self.instructions[-1].address


@dataclass
class ControlFlowGraph:
    procedure: Procedure
    blocks: list[BasicBlock]
    unresolved_targets: list[dict[str, Any]]


def split_operation(text: str) -> tuple[str, str]:
    if text.startswith("if not "):
        return "if not", text[len("if not "):]
    if text.startswith("if "):
        return "if", text[len("if "):]
    operation, separator, operands = text.partition(" ")
    return operation, operands.lstrip() if separator else ""


def parse_disassembly(path: Path) -> list[Procedure]:
    procedures: list[Procedure] = []
    pending_index: int | None = None
    current: Procedure | None = None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        header = PROCEDURE_HEADER.match(raw)
        if header:
            pending_index = int(header.group(1))
            current = None
            continue
        if pending_index is not None and current is None:
            signature = PROCEDURE_SIGNATURE.match(raw)
            if signature:
                current = Procedure(
                    index=pending_index,
                    name=signature.group(1),
                    entry=int(signature.group(2), 16),
                )
                procedures.append(current)
                pending_index = None
                continue
        instruction = INSTRUCTION.match(raw)
        if instruction and current is not None:
            opcode, operands = split_operation(instruction.group(2))
            current.instructions.append(
                Instruction(
                    address=int(instruction.group(1), 16),
                    opcode=opcode,
                    operands=operands,
                    raw=raw.strip(),
                )
            )
    return procedures


def control_targets(instruction: Instruction) -> list[tuple[int, str]]:
    if instruction.opcode in {"goto", "flag-goto"}:
        match = ADDRESS.search(instruction.operands)
        kind = "jump" if instruction.opcode == "goto" else "branch-true"
        return [(int(match.group(), 16), kind)] if match else []
    if instruction.opcode in {"if", "if not"}:
        match = re.search(r"\bgoto\s+(0x[0-9a-fA-F]+)", instruction.operands)
        return [(int(match.group(1), 16), "branch-true")] if match else []
    if instruction.opcode == "try":
        targets = []
        for label, value in re.findall(
            r"(finally|except|finally2|end)=(0x[0-9a-fA-F]+|-)", instruction.operands
        ):
            if value != "-":
                targets.append((int(value, 16), f"try-{label}"))
        return targets
    return []


def is_control(instruction: Instruction) -> bool:
    return instruction.opcode in {"goto", "flag-goto", "if", "if not", "ret", "try"}


def _constant_conditional_outcome(block: BasicBlock) -> bool | None:
    """Return the branch condition only for an immediately preceding 0/1 assign.

    This deliberately recognizes a tiny, auditable IFPS pattern. It does not
    propagate values across blocks or calls, so unknown conditions keep both
    CFG edges. The returned boolean means the conditional jump is taken.
    """
    terminator = block.instructions[-1]
    if terminator.opcode not in {"if", "if not"} or len(block.instructions) < 2:
        return None
    match = re.match(r"(\S+)\s+goto\s+0x[0-9a-fA-F]+$", terminator.operands.strip())
    assignment = block.instructions[-2]
    if not match or assignment.opcode != "assign":
        return None
    operands = re.fullmatch(r"(\S+),\s+(-?\d+)(?:[iu]\d+)?", assignment.operands)
    if not operands or operands.group(1) != match.group(1):
        return None
    value = int(operands.group(2))
    if value not in {0, 1}:
        return None
    truth = bool(value)
    return not truth if terminator.opcode == "if not" else truth


def build_cfg(procedure: Procedure) -> ControlFlowGraph:
    if not procedure.instructions:
        return ControlFlowGraph(procedure, [], [])
    addresses = {instruction.address for instruction in procedure.instructions}
    leaders = {procedure.instructions[0].address}
    unresolved: list[dict[str, Any]] = []
    for index, instruction in enumerate(procedure.instructions):
        for target, kind in control_targets(instruction):
            if target in addresses:
                leaders.add(target)
            else:
                unresolved.append({
                    "address": f"0x{instruction.address:x}",
                    "target": f"0x{target:x}",
                    "kind": kind,
                })
        if is_control(instruction) and index + 1 < len(procedure.instructions):
            leaders.add(procedure.instructions[index + 1].address)

    blocks: list[BasicBlock] = []
    current: list[Instruction] = []
    for instruction in procedure.instructions:
        if current and instruction.address in leaders:
            blocks.append(BasicBlock(current[0].address, current))
            current = []
        current.append(instruction)
    if current:
        blocks.append(BasicBlock(current[0].address, current))

    block_starts = {block.start for block in blocks}
    for index, block in enumerate(blocks):
        terminator = block.instructions[-1]
        targets = control_targets(terminator)
        for target, kind in targets:
            if target in block_starts:
                block.successors.append(Edge(target, kind))
        has_fallthrough = terminator.opcode not in {"goto", "ret"}
        if has_fallthrough and index + 1 < len(blocks):
            kind = "branch-false" if terminator.opcode in {"flag-goto", "if", "if not"} else "fallthrough"
            block.successors.append(Edge(blocks[index + 1].start, kind))
        outcome = _constant_conditional_outcome(block)
        if outcome is not None:
            selected_kind = "branch-true" if outcome else "branch-false"
            block.successors = [edge for edge in block.successors if edge.kind == selected_kind]
    return ControlFlowGraph(procedure, blocks, unresolved)


def constant_condition_calls(procedure: Procedure) -> list[dict[str, Any]]:
    """Recover constant arguments and nearby raw branch semantics conservatively."""
    result: list[dict[str, Any]] = []
    instructions = procedure.instructions
    for index, instruction in enumerate(instructions):
        if instruction.opcode != "call" or instruction.operands.casefold() not in CONDITION_APIS:
            continue
        literal: str | None = None
        literal_address: int | None = None
        result_variable: str | None = None
        for candidate in reversed(instructions[max(0, index - 12):index]):
            if result_variable is None and candidate.opcode == "push-ref":
                result_variable = candidate.operands
            if candidate.opcode != "assign":
                continue
            match = STRING_ASSIGNMENT.match(candidate.operands)
            if match:
                literal = match.group(1)
                literal_address = candidate.address
                break
        branch: dict[str, Any] | None = None
        flag_expression: str | None = None
        for candidate in instructions[index + 1:index + 9]:
            if candidate.opcode == "set-flag":
                flag_expression = candidate.operands
            if candidate.opcode in {"flag-goto", "if", "if not"}:
                targets = control_targets(candidate)
                branch_when_result: bool | None = None
                if candidate.opcode == "flag-goto" and result_variable:
                    if flag_expression == result_variable:
                        branch_when_result = True
                    elif flag_expression == f"not {result_variable}":
                        branch_when_result = False
                branch = {
                    "address": f"0x{candidate.address:x}",
                    "opcode": candidate.opcode,
                    "flag_expression": flag_expression,
                    "when_api_result": branch_when_result,
                    "targets": [f"0x{target:x}" for target, _ in targets],
                }
                break
        result.append({
            "api": instruction.operands,
            "call_address": f"0x{instruction.address:x}",
            "constant_argument": literal,
            "argument_address": f"0x{literal_address:x}" if literal_address is not None else None,
            "result_variable": result_variable,
            "branch": branch,
            "proven": literal is not None and branch is not None
            and branch["when_api_result"] is not None,
        })
    return result


def integer_literal(value: str) -> int | None:
    match = re.fullmatch(r"(-?\d+)(?:[iu]\d+)?", value)
    return int(match.group(1)) if match else None


def component_bitmask(procedure: Procedure) -> dict[str, Any] | None:
    """Recognize the common selected-component bitmask construction idiom."""
    instructions = procedure.instructions
    by_address = {instruction.address: index for index, instruction in enumerate(instructions)}
    conditions = [
        condition for condition in constant_condition_calls(procedure)
        if condition["api"].casefold() == "iscomponentselected" and condition["proven"]
    ]
    if not conditions:
        return None
    entries: list[dict[str, Any]] = []
    accumulator: str | None = None
    weight_variable: str | None = None
    weight: int | None = None
    last_branch_index = 0
    for condition in conditions:
        branch = condition["branch"]
        branch_index = by_address[int(branch["address"], 16)]
        target = int(branch["targets"][0], 16)
        target_index = by_address.get(target)
        if target_index is None or target_index <= branch_index:
            return None
        additions = [
            item for item in instructions[branch_index + 1:target_index]
            if item.opcode == "calc.add"
        ]
        if len(additions) != 1:
            return None
        add_match = re.fullmatch(r"(\S+),\s*(\S+)", additions[0].operands)
        if not add_match:
            return None
        current_accumulator, current_weight_variable = add_match.groups()
        multiplier = instructions[target_index]
        multiply_match = (
            re.fullmatch(r"(\S+),\s*(\S+)", multiplier.operands)
            if multiplier.opcode == "calc.mul" else None
        )
        if not multiply_match or multiply_match.group(1) != current_weight_variable:
            return None
        if integer_literal(multiply_match.group(2)) != 2:
            return None
        if accumulator is None:
            accumulator = current_accumulator
            weight_variable = current_weight_variable
            initial_values: dict[str, int] = {}
            for candidate in instructions[:branch_index]:
                if candidate.opcode != "assign":
                    continue
                assignment = re.fullmatch(r"(\S+),\s*(\S+)", candidate.operands)
                if assignment:
                    parsed = integer_literal(assignment.group(2))
                    if parsed is not None:
                        initial_values[assignment.group(1)] = parsed
            if initial_values.get(accumulator) != 0 or initial_values.get(weight_variable) != 1:
                return None
            weight = 1
        if current_accumulator != accumulator or current_weight_variable != weight_variable or weight is None:
            return None
        entries.append({
            "component": condition["constant_argument"],
            "bit": weight,
            "condition_call": condition["call_address"],
            "add_address": f"0x{additions[0].address:x}",
            "join_address": f"0x{target:x}",
        })
        weight *= 2
        last_branch_index = target_index

    consumer_assignment: Instruction | None = None
    consumer_call: Instruction | None = None
    for candidate in instructions[last_branch_index + 1:]:
        if consumer_assignment is None and candidate.opcode == "assign":
            assignment = re.fullmatch(r"(\S+),\s*(\S+)", candidate.operands)
            if assignment and assignment.group(2) == accumulator:
                consumer_assignment = candidate
        if candidate.opcode == "call" and (
            is_dll_call(candidate.operands, "files:ISDone.dll", "ISDoneInit")
            or is_dll_call(candidate.operands, "files:ISDone.dll")
        ):
            consumer_call = candidate
            break
    return {
        "accumulator": accumulator,
        "weight_variable": weight_variable,
        "components": entries,
        "consumer_assignment": (
            f"0x{consumer_assignment.address:x}" if consumer_assignment else None
        ),
        "consumer_call": f"0x{consumer_call.address:x}" if consumer_call else None,
        "proven": consumer_assignment is not None and consumer_call is not None,
    }


def cfg_report(path: Path) -> dict[str, Any]:
    procedures = parse_disassembly(path)
    internal_by_name = {procedure.name.casefold(): procedure.index for procedure in procedures}
    result: list[dict[str, Any]] = []
    totals = {"procedures": len(procedures), "instructions": 0, "blocks": 0, "edges": 0}
    for procedure in procedures:
        cfg = build_cfg(procedure)
        calls = []
        for instruction in procedure.instructions:
            if instruction.opcode != "call":
                continue
            callee = instruction.operands
            calls.append({
                "address": f"0x{instruction.address:x}",
                "callee": callee,
                "internal_index": internal_by_name.get(callee.casefold()),
            })
        blocks = [{
            "start": f"0x{block.start:x}",
            "end": f"0x{block.end:x}",
            "successors": [
                {"target": f"0x{edge.target:x}", "kind": edge.kind}
                for edge in block.successors
            ],
        } for block in cfg.blocks]
        totals["instructions"] += len(procedure.instructions)
        totals["blocks"] += len(blocks)
        totals["edges"] += sum(len(block["successors"]) for block in blocks)
        result.append({
            "index": procedure.index,
            "name": procedure.name,
            "entry": f"0x{procedure.entry:x}",
            "instruction_count": len(procedure.instructions),
            "blocks": blocks,
            "calls": calls,
            "constant_conditions": constant_condition_calls(procedure),
            "component_bitmask": component_bitmask(procedure),
            "unresolved_targets": cfg.unresolved_targets,
        })
    return {"schema": SCHEMA_VERSION, "totals": totals, "procedures": result}


def write_cfg_report(disassembly: Path, output: Path) -> dict[str, Any]:
    report = cfg_report(disassembly)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
