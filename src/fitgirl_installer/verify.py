#!/usr/bin/env python3
"""Verify extracted files against FitGirl's _Redist/fitgirl.md5 manifest."""

from __future__ import annotations

import sys
from pathlib import Path

# Replace this script's own directory, which Python puts first, with src/:
# otherwise the fitgirl_installer/platform package would shadow the standard
# platform module for everything imported here.
sys.path[0] = str(Path(__file__).resolve().parents[1])
from fitgirl_installer.verification.checksums import main


if __name__ == "__main__":
    raise SystemExit(main())
