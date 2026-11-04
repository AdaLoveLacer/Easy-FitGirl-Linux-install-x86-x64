#!/usr/bin/env python3
"""Build a reviewable manifest draft from innounp ISS + IFPS disassembly."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fitgirl_installer.planner import write_manifest  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iss", type=Path, required=True)
    parser.add_argument("--disassembly", type=Path, required=True)
    parser.add_argument("--setup", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest = write_manifest(
        args.iss, args.disassembly, args.setup, args.source, args.output
    )
    print(f"rascunho: {args.output}")
    print(f"componentes: {len(manifest['components'])}; etapas: {len(manifest['steps'])}")
    print("REVISÃO OBRIGATÓRIA: valide condições e posição das ações antes de remover draft=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
