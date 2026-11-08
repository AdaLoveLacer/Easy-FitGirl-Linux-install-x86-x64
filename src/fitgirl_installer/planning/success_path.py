"""What the compiled script does when every installer action succeeds.

The native installer runs each planned action and stops at the first failure,
keeping its journal for a resume. On every run that finishes, therefore, each
ISDone action and mutating call of the script returned success. This module
interprets ``CurStepChanged`` for each Inno Setup step under exactly that
assumption and proves two properties the native plan relies on:

* order: no reachable backward edge, so every path runs the actions in
  increasing address order, which is the order of the plan;
* failure-only calls: a guarded call such as ``Exec2({uninstallexe})`` is never
  reached, tracking the global flag that guards it across the step events.

Values the interpretation cannot decide stay unknown and keep both branches,
so an unprovable script is reported as unproven, never as proven.
"""

from __future__ import annotations

import re
from collections import deque
from pathlib import Path
from typing import Any

from . import planner, script_flow


SETUP_STEPS = ((0, "ssPreInstall"), (1, "ssInstall"), (2, "ssPostInstall"), (3, "ssDone"))
STATE_LIMIT = 200_000
BOOLEAN_LITERAL = re.compile(r"^([01])(?:[iu]\d+)?$")
EVENT_COMPARISON = re.compile(r"^(\S+)\s*:=\s*s-1\s*=\s*(\d+)(?:[iu]\d+)?$")
CONDITIONAL = re.compile(r"^(\S+)\s+goto\s+0x[0-9a-fA-F]+$")
UNINSTALLER = "{uninstallexe}"


def is_action(instruction: script_flow.Instruction) -> bool:
    """A call the native plan executes, so it returns success on a finished run."""
    return instruction.opcode == "call" and (
        planner.ISDONE_EXPORT.match(instruction.operands) is not None
        or instruction.operands.casefold() in planner.MUTATING_CALLS
    )


def _succeeds(instruction: script_flow.Instruction, successful_exports: frozenset[str]) -> bool:
    """Whether the call returns success on a finished run of the original installer."""
    if is_action(instruction):
        return True
    library, _, export = instruction.operands.partition("!")
    return (
        script_flow.is_dll_call(library, "files:ISDone.dll")
        and export.casefold() in successful_exports
    )


def _destination(instruction: script_flow.Instruction) -> str | None:
    if instruction.opcode in {"assign", "bool-not"} or instruction.opcode.startswith(("calc.", "cmp.")):
        target = instruction.operands.split(":=", 1)[0].split(",", 1)[0].strip()
        return target or None
    return None


def _value(operand: str, values: dict[str, bool]) -> bool | None:
    literal = BOOLEAN_LITERAL.match(operand.strip())
    if literal:
        return literal.group(1) == "1"
    return values.get(operand.strip())


def _step(
    instruction: script_flow.Instruction, values: dict[str, bool], event: int,
    depth: int, references: tuple[str, ...],
    successful_exports: frozenset[str] = frozenset(),
) -> tuple[dict[str, bool], int, tuple[str, ...]]:
    """Apply one instruction to the known booleans.

    IFPS addresses the slot created by the n-th push of a procedure as ``s+n``;
    a push therefore creates a fresh ``s+depth`` and a pop discards it. A call
    may write every variable passed by reference since the previous call; the
    last one holds the result, which is true for a planned action.
    """
    values = dict(values)
    opcode, operands = instruction.opcode, instruction.operands.strip()
    if opcode in {"push-temp", "push", "push-ref"}:
        depth += 1
        values.pop(f"s+{depth}", None)
        if opcode == "push-ref":
            references = (*references, operands)
        return values, depth, references
    if opcode == "pop":
        values.pop(f"s+{depth}", None)
        return values, depth - 1, references
    if opcode == "call":
        for name in references:
            values.pop(name, None)
        if references and _succeeds(instruction, successful_exports):
            values[references[-1]] = True
        return values, depth, ()
    if opcode == "cmp.eq":
        match = EVENT_COMPARISON.match(operands)
        destination = _destination(instruction)
        if match:
            values[match.group(1)] = event == int(match.group(2))
        elif destination:
            values.pop(destination, None)
    elif opcode == "assign":
        destination, _, source = operands.partition(",")
        known = _value(source, values)
        if known is None:
            values.pop(destination.strip(), None)
        else:
            values[destination.strip()] = known
    elif opcode == "bool-not":
        name = operands.strip()
        if name in values:
            values[name] = not values[name]
    elif opcode in {"calc.and", "calc.or"}:
        destination, _, source = operands.partition(",")
        left, right = values.get(destination.strip()), _value(source, values)
        if opcode == "calc.and":
            result = False if left is False or right is False else (
                True if left and right else None
            )
        else:
            result = True if left or right else (
                False if left is False and right is False else None
            )
        if result is None:
            values.pop(destination.strip(), None)
        else:
            values[destination.strip()] = result
    else:
        destination = _destination(instruction)
        if destination:
            values.pop(destination, None)
    return values, depth, references


def _global_writes(procedures: list[script_flow.Procedure], name: str) -> list[dict[str, Any]]:
    writes = []
    for procedure in procedures:
        for instruction in procedure.instructions:
            written = _destination(instruction) == name
            by_reference = (
                instruction.opcode == "push-ref" and instruction.operands.strip() == name
            )
            if written or by_reference:
                value = None
                if instruction.opcode == "assign":
                    value = _value(instruction.operands.partition(",")[2], {})
                writes.append({
                    "procedure": procedure.name,
                    "address": f"0x{instruction.address:x}",
                    "opcode": instruction.opcode,
                    "value": value,
                })
    return writes


def _uninstaller_calls(
    disassembly: Path, callback: script_flow.Procedure,
) -> list[dict[str, Any]]:
    rows = planner._instruction_rows(
        disassembly.read_text(encoding="utf-8", errors="replace").splitlines()
    )
    addresses = {instruction.address for instruction in callback.instructions}
    calls = []
    for position, row in enumerate(rows):
        if (
            row["opcode"] != "call"
            or int(row["address"], 16) not in addresses
            or not script_flow.is_dll_call(row["operands"].split("!")[0], "files:ISDone.dll")
            or not row["operands"].casefold().endswith("!exec2")
        ):
            continue
        literals = [item["value"] for item in planner._frame_strings(planner._frame_for_call(rows, position))]
        if any(UNINSTALLER in value.casefold() for value in literals):
            calls.append({"address": int(row["address"], 16), "literals": literals})
    return calls


def _guard_flag(callback: script_flow.Procedure, call_address: int) -> str | None:
    """The global combined into the condition right before a guarded call."""
    candidates = [
        instruction for instruction in callback.instructions
        if instruction.address < call_address and instruction.opcode == "calc.and"
    ]
    for instruction in reversed(candidates[-1:]):
        source = instruction.operands.partition(",")[2].strip()
        if source.startswith("g#"):
            return source
    return None


def success_path_report(
    disassembly: Path, successful_exports: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Interpret CurStepChanged for every setup step assuming every action succeeds.

    ``successful_exports`` names further ISDone exports, in lower case, whose
    boolean result means success for the exact DLL in use; that knowledge comes
    from the catalog of analysed DLL versions, never from the script.
    """
    procedures = script_flow.parse_disassembly(disassembly)
    callback = next(
        (procedure for procedure in procedures if procedure.name.casefold() == "curstepchanged"),
        None,
    )
    if callback is None:
        return {"callback_found": False, "order_proven": False, "uninstaller_launch_unreachable": False,
                "limitations": ["CurStepChanged was not found."]}
    cfg = script_flow.build_cfg(callback)
    blocks = {block.start: block for block in cfg.blocks}
    first = cfg.blocks[0].start if cfg.blocks else None
    uninstaller = _uninstaller_calls(disassembly, callback)
    flags = sorted({_guard_flag(callback, call["address"]) or "" for call in uninstaller})
    flag = flags[0] if len(flags) == 1 and flags[0] else None
    flag_writes = _global_writes(procedures, flag) if flag else []
    outside_writes = [item for item in flag_writes if item["procedure"] != callback.name]
    flag_model_sound = bool(flag) and all(
        item["opcode"] == "assign" and item["value"] is not None for item in flag_writes
    )
    initial: bool | None = None
    if flag_model_sound and outside_writes:
        initial_values = {item["value"] for item in outside_writes}
        initial = initial_values.pop() if len(initial_values) == 1 else None

    events = []
    back_edges: set[tuple[int, int]] = set()
    reached_uninstaller: list[dict[str, Any]] = []
    actions_by_event: dict[str, int] = {}
    entry_flag = initial
    exhausted = False
    for event, name in SETUP_STEPS:
        start_values: dict[str, bool] = {}
        if flag and entry_flag is not None:
            start_values[flag] = entry_flag
        queue = deque(
            [(first, 0, (), tuple(sorted(start_values.items())))]
        ) if first is not None else deque()
        seen: set[tuple[Any, ...]] = set()
        exit_flags: set[bool | None] = set()
        actions: set[int] = set()
        while queue:
            if len(seen) > STATE_LIMIT:
                exhausted = True
                break
            state = queue.popleft()
            if state in seen:
                continue
            seen.add(state)
            start, depth, references, frozen = state
            block = blocks[start]
            values = dict(frozen)
            condition: bool | None = None
            for instruction in block.instructions:
                if instruction.opcode == "call":
                    if is_action(instruction):
                        actions.add(instruction.address)
                    if any(call["address"] == instruction.address for call in uninstaller):
                        reached_uninstaller.append({
                            "event": name, "address": f"0x{instruction.address:x}",
                            "flag_value": values.get(flag) if flag else None,
                        })
                if instruction.opcode == "set-flag":
                    negated = instruction.operands.startswith("not ")
                    operand = instruction.operands[4:] if negated else instruction.operands
                    known = values.get(operand.strip())
                    condition = None if known is None else (not known if negated else known)
                values, depth, references = _step(
                    instruction, values, event, depth, references, successful_exports,
                )
            terminator = block.instructions[-1]
            if terminator.opcode in {"if", "if not"}:
                match = CONDITIONAL.match(terminator.operands.strip())
                known = values.get(match.group(1)) if match else None
                condition = None if known is None else (not known if terminator.opcode == "if not" else known)
            successors = block.successors
            if terminator.opcode in {"flag-goto", "if", "if not"} and condition is not None:
                wanted = "branch-true" if condition else "branch-false"
                successors = [edge for edge in successors if edge.kind == wanted]
            if terminator.opcode == "ret" or not successors:
                exit_flags.add(values.get(flag) if flag else None)
            frozen_values = tuple(sorted(values.items()))
            for edge in successors:
                if edge.target <= start:
                    back_edges.add((start, edge.target))
                successor = (edge.target, depth, references, frozen_values)
                if successor not in seen:
                    queue.append(successor)
        events.append({"event": name, "states": len(seen), "actions_reached": len(actions)})
        actions_by_event[name] = len(actions)
        entry_flag = exit_flags.pop() if len(exit_flags) == 1 else None
        if exhausted:
            break

    action_events = [name for name, count in actions_by_event.items() if count]
    order_proven = not exhausted and not back_edges and len(action_events) <= 1
    uninstaller_proven = (
        not exhausted and flag_model_sound and bool(uninstaller) and not reached_uninstaller
    )
    return {
        "callback_found": True,
        "assumption": "every ISDone action and mutating call returns success, as on any finished native run",
        "successful_exports": sorted(successful_exports),
        "events": events,
        "state_limit_reached": exhausted,
        "reachable_back_edges": [f"0x{source:x}->0x{target:x}" for source, target in sorted(back_edges)],
        "action_events": action_events,
        "order_proven": order_proven,
        "uninstaller_calls": [f"0x{call['address']:x}" for call in uninstaller],
        "uninstaller_guard_flag": flag,
        "uninstaller_guard_flag_writes": flag_writes,
        "uninstaller_guard_initial_value": initial,
        "uninstaller_reached": reached_uninstaller,
        "uninstaller_launch_unreachable": uninstaller_proven,
    }
