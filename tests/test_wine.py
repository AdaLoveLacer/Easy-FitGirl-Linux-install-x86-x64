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
from fitgirl_installer.platform.runtime import RuntimeErrorDetail  # noqa: E402


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


class WinePathTests(unittest.TestCase):
    def test_drive_c_and_mnt_paths_are_mapped_without_running_wine(self):
        never = Path("/nonexistent/bin/wine")
        prefix = Path("/srv/fitgirl-prefix")
        self.assertEqual(
            wine.wine_path(prefix / "drive_c/Program Files/x.exe", prefix, never),
            "C:\\Program Files\\x.exe",
        )
        self.assertEqual(wine.wine_path(Path("/mnt/Games/a b/x.bat"), prefix, never), "W:\\Games\\a b\\x.bat")
        self.assertEqual(wine.wine_z_path(Path("/srv/repack/setup.exe")), "Z:\\srv\\repack\\setup.exe")

    def test_other_paths_use_winepath_and_its_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake = executable(root / "bin/wine", 'printf "Z:\\\\converted\\r\\n"')
            self.assertEqual(wine.wine_path(root / "file.txt", root / "prefix", fake), "Z:\\converted")
            failing = executable(root / "bad/wine", "exit 3")
            with self.assertRaisesRegex(InstallerError, "winepath não converteu"):
                wine.wine_path(root / "file.txt", root / "prefix", failing)


class EnsureWinePrefixTests(unittest.TestCase):
    def test_new_prefix_is_booted_and_w_drive_points_to_mnt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            calls = []
            wine.ensure_wine_prefix(
                Path("/opt/wine/bin/wine"), root / "prefix", root / "scratch",
                root / "state.json", {}, False,
                run_process=lambda *call: calls.append(call), working_directory=Path("/code"),
            )
            command, cwd, _, _, dry_run, environment = calls[0]
            self.assertEqual(command, ["/opt/wine/bin/wine", "wineboot.exe", "-i"])
            self.assertEqual((cwd, dry_run), (Path("/code"), False))
            self.assertEqual(environment["WINEDLLOVERRIDES"], "mscoree,mshtml=")
            self.assertEqual(os.readlink(root / "prefix/dosdevices/w:"), "/mnt")

    def test_existing_prefix_is_not_booted_and_dry_run_changes_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            prefix = Path(temporary) / "prefix"
            prefix.mkdir()
            (prefix / "system.reg").write_text("")
            calls = []
            wine.ensure_wine_prefix(
                Path("/opt/wine/bin/wine"), prefix, Path(temporary), Path(temporary) / "s.json",
                {}, True, run_process=lambda *call: calls.append(call), working_directory=Path("/code"),
            )
            self.assertEqual(calls, [])
            self.assertFalse((prefix / "dosdevices").exists())


if __name__ == "__main__":
    unittest.main()
