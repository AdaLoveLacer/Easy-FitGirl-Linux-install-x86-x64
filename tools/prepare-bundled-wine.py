#!/usr/bin/env python3
"""Verify and stage the complete codec runtime for the single-file build."""

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fitgirl_installer.platform.runtime import digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    metadata = ROOT / "resources/wine-runtime.json"
    config = json.loads(metadata.read_text())
    if not args.archive.is_file() or digest(args.archive) != config["archive_sha256"]:
        raise SystemExit("Wine a incorporar ausente ou SHA-256 divergente; build recusado")
    args.destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.archive, args.destination / config["archive"])
    shutil.copy2(metadata, args.destination / metadata.name)
    print(f"Wine completo incorporado: {config['version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
