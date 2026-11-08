#!/usr/bin/env python3
"""Audit a candidate plan against cached ISS, IFPS bytes and disassembly."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fitgirl_installer.planning.audit import write_audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "iss", "disassembly", "compiled", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--disassembler", type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    report = write_audit(
        manifest, args.iss, args.disassembly, args.compiled, args.output,
        disassembler=args.disassembler,
    )
    print(f"{report['status']}: {len(report['issues'])} divergências")
    print(f"Relatório: {args.output}")
    print("Revisão obrigatória: consistência não comprova equivalência semântica.")
    return 0 if report["consistent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
