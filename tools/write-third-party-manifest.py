#!/usr/bin/env python3
"""Write hashes for non-system ELF/PE payloads in a staged release runtime."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
output = Path(sys.argv[2])
license_by_prefix = {
    "libboost_": "BSL-1.0",
    "liblzma": "0BSD (XZ Utils core); corresponding source included",
    "libz.so": "Zlib",
    "libbz2": "bzip2 BSD",
    "libzstd": "BSD-3-Clause (alternative GPL-2.0-only)",
}
items = []
for path in sorted((root / "libexec").iterdir()):
    if not path.is_file() or path.name == "fitgirl-extract":
        continue
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if path.name == "innoextract":
        license_name, origin = "Zlib", "dscharrer/innoextract commit 6e9e34e"
    elif path.name == "unarc":
        license_name, origin = "GPL-2.0", "xredor/unarc commit adc333d"
    elif path.name == "unarc-helper.exe":
        license_name, origin = "Project source", "src/unarc_helper.c"
    elif path.name.startswith("liblzma.so"):
        license_name = "0BSD (XZ Utils core); see bundled COPYING files"
        origin = "XZ Utils 5.8.4 source release; built by tools/build-liblzma.sh"
    else:
        license_name = next(
            (value for prefix, value in license_by_prefix.items() if path.name.startswith(prefix)),
            "system runtime; see host distribution license notices",
        )
        origin = "shared dependency resolved from release builder"
    items.append({
        "path": f"libexec/{path.name}",
        "size_bytes": path.stat().st_size,
        "sha256": digest,
        "license": license_name,
        "origin": origin,
    })
output.write_text(json.dumps({"schema": 1, "files": items}, indent=2) + "\n", encoding="utf-8")
