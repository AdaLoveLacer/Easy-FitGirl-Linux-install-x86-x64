#!/usr/bin/env python3
"""Bundle innoextract's non-core shared libraries for standalone builds."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path


_BUNDLED = re.compile(r"^lib(?:boost_[^ ]+|z|bz2|zstd)\.so(?:\.|$)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()

    result = subprocess.run(
        ["ldd", str(args.binary)], text=True, capture_output=True, check=False
    )
    if result.returncode != 0:
        raise SystemExit(f"ldd falhou para {args.binary}: {result.stderr.strip()}")

    libraries: dict[str, Path] = {}
    missing: list[str] = []
    for line in result.stdout.splitlines():
        match = re.match(r"\s*(\S+)\s+=>\s+(\S+)", line)
        if not match:
            continue
        name, path_text = match.groups()
        if path_text == "not":
            missing.append(name)
            continue
        if _BUNDLED.match(name):
            path = Path(path_text)
            if not path.is_file():
                missing.append(name)
                continue
            libraries[name] = path.resolve()

    if missing:
        raise SystemExit("dependências ausentes do innoextract: " + ", ".join(missing))
    if not any(name.startswith("libboost_") for name in libraries):
        raise SystemExit("nenhuma dependência Boost dinâmica encontrada no innoextract")

    args.destination.mkdir(parents=True, exist_ok=True)
    for name, source in sorted(libraries.items()):
        shutil.copy2(source, args.destination / name)
        print(f"Incluída dependência privada: {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
