#!/usr/bin/env python3
"""Render and verify operational documentation from one canonical status file."""

from __future__ import annotations

import argparse
import ast
import difflib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "status/project-status.json"
PENDING = ROOT / "docs/PENDENCIAS.md"
VALIDATION = ROOT / "docs/VALIDATION.md"
BEGIN = "<!-- BEGIN GENERATED:PROJECT_STATUS -->"
END = "<!-- END GENERATED:PROJECT_STATUS -->"


def test_count() -> int:
    total = 0
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        total += sum(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
            for node in ast.walk(tree)
        )
    return total


def load_status() -> dict:
    data = json.loads(STATUS.read_text(encoding="utf-8"))
    if data.get("schema") != 1:
        raise SystemExit("schema de status não suportado")
    return data


def verdict_block(data: dict, tests: int) -> str:
    rows = [
        BEGIN,
        "",
        f"Fonte canônica: [`status/project-status.json`](../status/project-status.json).  ",
        f"Suíte automatizada descoberta: **{tests}/{tests} testes**.",
        "",
        "| Requisito | Estado | Veredito |",
        "|---|---:|---|",
    ]
    rows.extend(f"| {name} | {state} | {text} |" for name, state, text in data["verdicts"])
    rows.extend(["", END])
    return "\n".join(rows)


def pending_document(data: dict, tests: int) -> str:
    lines = [
        "# Pendências operacionais",
        "",
        "> ARQUIVO GERADO. Não edite diretamente. Atualize",
        "> `status/project-status.json` e execute `./tools/sync-docs.py --write`.",
        "",
        f"Última atualização declarada: {data['updated_on']}  ",
        f"Suíte automatizada descoberta: **{tests}/{tests} testes**.",
        "",
    ]
    for index, stream in enumerate(data["workstreams"], 1):
        lines.extend([
            f"## {index}. {stream['title']}",
            "",
            f"Estado: **{stream['status']}**",
            "",
        ])
        for done, text in stream["items"]:
            lines.append(f"- [{'x' if done else ' '}] {text}")
        lines.append("")
    lines.extend(["## Baseline validado", ""])
    lines.extend(f"- {item}" for item in data["baselines"])
    lines.append("")
    return "\n".join(lines)


def replace_generated(text: str, block: str) -> str:
    if BEGIN not in text or END not in text:
        heading = "## Veredito atual"
        start = text.index(heading) + len(heading)
        next_heading = text.index("\n## ", start)
        return text[:start] + "\n\n" + block + "\n" + text[next_heading:]
    prefix, rest = text.split(BEGIN, 1)
    _, suffix = rest.split(END, 1)
    return prefix + block + suffix


def expected_files() -> dict[Path, str]:
    data = load_status()
    tests = test_count()
    validation = replace_generated(
        VALIDATION.read_text(encoding="utf-8"), verdict_block(data, tests)
    )
    return {
        PENDING: pending_document(data, tests),
        VALIDATION: validation,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="atualizar documentos gerados")
    mode.add_argument("--check", action="store_true", help="falhar se documentos estiverem obsoletos")
    args = parser.parse_args()

    stale = False
    for path, expected in expected_files().items():
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current == expected:
            continue
        if args.write:
            path.write_text(expected, encoding="utf-8")
            print(f"[ATUALIZADO] {path.relative_to(ROOT)}")
            continue
        stale = True
        print(f"[DESATUALIZADO] {path.relative_to(ROOT)}")
        print("".join(difflib.unified_diff(
            current.splitlines(True), expected.splitlines(True),
            fromfile=str(path), tofile="gerado",
        )))
    if stale:
        print("Execute: ./tools/sync-docs.py --write")
        return 1
    print("[OK] documentação operacional sincronizada")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
