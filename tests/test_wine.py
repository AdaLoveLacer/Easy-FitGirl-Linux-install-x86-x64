#!/usr/bin/env python3

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fitgirl_installer.models import InstallerError  # noqa: E402
from fitgirl_installer.platform import wine  # noqa: E402
from fitgirl_installer.runtime import RuntimeErrorDetail  # noqa: E402


def executable(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(0o755)
    return path


class DiscoverWineTests(unittest.TestCase):
    def test_development_override_wins_and_must_be_executable(self):
        with tempfile.TemporaryDirectory() as temporary:
            override = executable(Path(temporary) / "wine", "exit 0")
            unreachable = lambda root: self.fail("private runtime must not be prepared")  # noqa: E731
            with patch.dict(os.environ, {"FITGIRL_WINE_BIN": str(override)}):
                self.assertEqual(
                    wine.discover_wine(root=Path(temporary), ensure_bundled_wine=unreachable),
                    [override.resolve()],
                )
            override.chmod(0o644)
            with patch.dict(os.environ, {"FITGIRL_WINE_BIN": str(override)}):
                with self.assertRaisesRegex(InstallerError, "FITGIRL_WINE_BIN inválido"):
                    wine.discover_wine(root=Path(temporary), ensure_bundled_wine=unreachable)

    def test_private_runtime_is_preferred_and_its_errors_become_installer_errors(self):
        bundled = Path("/opt/private/bin/wine")
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                wine.discover_wine(root=Path("/code"), ensure_bundled_wine=lambda root: bundled),
                [bundled],
            )

            def broken(root):
                raise RuntimeErrorDetail("SHA-256 inválido nos metadados do runtime")

            with self.assertRaisesRegex(InstallerError, "SHA-256 inválido"):
                wine.discover_wine(root=Path("/code"), ensure_bundled_wine=broken)


class SelectCodecRuntimeTests(unittest.TestCase):
    def test_first_candidate_that_answers_version_is_chosen(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            broken = executable(root / "broken/wine", "exit 1")
            missing = root / "missing/wine"
            working = executable(root / "working/wine", "echo wine-11.0")
            self.assertEqual(
                wine.select_codec_runtime(lambda: [broken, missing, working]), working
            )

    def test_no_usable_candidate_is_refused(self):
        with self.assertRaisesRegex(InstallerError, "nenhum Wine/Proton utilizável"):
            wine.select_codec_runtime(lambda: [])


if __name__ == "__main__":
    unittest.main()
