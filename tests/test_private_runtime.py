import hashlib
import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fitgirl_installer import cli
from fitgirl_installer.platform import runtime


class PrivateRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = self.root / "package"
        self.libexec = self.package / "libexec"
        self.libexec.mkdir(parents=True)
        self.wine = b"#!/bin/sh\necho wine-test\n"
        self.archive = self.libexec / "wine.tar.xz"
        self.make_archive()
        self.environment = patch.dict(os.environ, {"XDG_DATA_HOME": str(self.root / "data")})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def make_archive(self, unsafe=False):
        with tarfile.open(self.archive, "w:xz") as stream:
            info = tarfile.TarInfo("wine-test/bin/wine")
            info.mode = 0o755
            info.size = len(self.wine)
            stream.addfile(info, io.BytesIO(self.wine))
            if unsafe:
                info = tarfile.TarInfo("../escaped")
                info.size = 1
                stream.addfile(info, io.BytesIO(b"x"))
        self.config = {
            "schema": 1, "version": "test", "archive": self.archive.name,
            "archive_root": "wine-test", "archive_sha256": runtime.digest(self.archive),
            "executable_sha256": hashlib.sha256(self.wine).hexdigest(), "unpacked_bytes": 100,
        }
        (self.libexec / "wine-runtime.json").write_text(json.dumps(self.config))

    def test_first_run_and_cache_reuse_without_system_wine(self):
        wine = runtime.ensure_bundled_wine(self.package)
        self.assertEqual(wine.read_bytes(), self.wine)
        self.assertTrue(os.access(wine, os.X_OK))
        self.assertTrue(wine.is_relative_to(self.root / "data"))
        self.archive.unlink()
        self.assertEqual(runtime.ensure_bundled_wine(self.package), wine)

    def test_corrupted_archive_is_refused(self):
        self.archive.write_bytes(b"broken")
        with self.assertRaisesRegex(runtime.RuntimeErrorDetail, "SHA-256"):
            runtime.ensure_bundled_wine(self.package)
        self.assertFalse(list((self.root / "data").rglob("bin/wine")))

    def test_existing_altered_runtime_is_not_overwritten(self):
        wine = runtime.ensure_bundled_wine(self.package)
        wine.write_bytes(b"user change")
        with self.assertRaisesRegex(runtime.RuntimeErrorDetail, "não será sobrescrito"):
            runtime.ensure_bundled_wine(self.package)
        self.assertEqual(wine.read_bytes(), b"user change")

    def test_archive_path_escape_is_refused_and_staging_cleaned(self):
        self.make_archive(unsafe=True)
        with self.assertRaisesRegex(runtime.RuntimeErrorDetail, "caminho inesperado"):
            runtime.ensure_bundled_wine(self.package)
        self.assertFalse(list((self.root / "data").rglob("escaped")))
        self.assertFalse(list((self.root / "data").rglob(".wine-stage-*")))

    def test_unsupported_architecture_is_refused(self):
        with patch.object(runtime.platform, "machine", return_value="aarch64"):
            with self.assertRaisesRegex(runtime.RuntimeErrorDetail, "x86-64"):
                runtime.ensure_bundled_wine(self.package)


class PortableMenuTests(unittest.TestCase):
    def test_two_generic_destinations_without_mount_dependencies(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            with patch.object(cli.Path, "home", return_value=home), patch.dict(os.environ, {}, clear=True), patch.object(cli, "local_mounts", return_value=[]):
                self.assertEqual(cli.discover_game_roots(), [home / "Games"])

    def test_every_distinct_local_drive_gets_a_games_candidate(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            mounts = [
                {"target": "/", "source": "/dev/nvme0n1p2[/@]"},
                {"target": "/mnt/A", "source": "/dev/sda1"},
                {"target": "/mnt/A-sub", "source": "/dev/sda1"},
                {"target": "/mnt/B", "source": "/dev/sdb1"},
            ]
            with patch.object(cli.Path, "home", return_value=home), patch.dict(os.environ, {}, clear=True), patch.object(cli, "local_mounts", return_value=mounts):
                self.assertEqual(cli.discover_game_roots(), [home / "Games", Path("/mnt/A/Games"), Path("/mnt/B/Games")])

    def test_cpu_list_parser_rejects_unavailable_processors(self):
        from fitgirl_installer.platform.resources import parse_cpu_list
        self.assertEqual(parse_cpu_list("0-2,4", (0, 1, 2, 4)), {0, 1, 2, 4})
        with self.assertRaises(ValueError):
            parse_cpu_list("0-8", (0, 1, 2, 3))

    def test_custom_destination_is_exact_and_has_no_implicit_game_suffix(self):
        with tempfile.TemporaryDirectory() as temporary:
            custom = Path(temporary) / "My chosen folder"
            with patch.object(cli, "discover_game_roots", return_value=[Path(temporary) / "Games", Path(temporary) / "other"]), patch("builtins.input", side_effect=["3", str(custom)]):
                self.assertEqual(cli.prompt_destination("Game"), custom)
            self.assertFalse(custom.exists())

    def test_sibling_custom_destinations_have_distinct_resume_ids(self):
        first = cli.target_work_id(Path("/games/Mirage 7"), "a" * 64)
        second = cli.target_work_id(Path("/games/Mirage 7 test"), "a" * 64)
        self.assertEqual(first, "mirage-7")
        self.assertEqual(second, "mirage-7-test")
        self.assertNotEqual(first, second)

    def test_destination_inside_prefix_or_its_symlink_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prefix = root / "prefix"
            (prefix / "dosdevices").mkdir(parents=True)
            (prefix / "system.reg").write_text("Wine")
            alias = root / "alias"
            alias.symlink_to(prefix, target_is_directory=True)
            for destination in (prefix / "drive_c/Game", alias / "Game"):
                with self.assertRaises(cli.InstallerError):
                    cli.validate_external_game_target(destination)
            cli.validate_external_game_target(root / "Games/Game", prefix)

    def test_missing_runtime_exits_before_prompting_or_analyzing_setup(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "discover_wine", return_value=[]), patch("builtins.input", side_effect=AssertionError("must not prompt")), patch.object(cli, "generate_manifest_draft", side_effect=AssertionError("must not analyze")):
            with self.assertRaisesRegex(cli.InstallerError, "nenhum Wine/Proton"):
                cli.interactive_install(Path(temporary))

    def test_proton_wine_is_discovered_without_running_proton_launcher(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            wine = home / ".local/share/Steam/compatibilitytools.d/GE-Proton/files/bin/wine"
            wine.parent.mkdir(parents=True)
            wine.write_text("#!/bin/sh\nexit 0\n")
            wine.chmod(0o755)
            with patch.object(cli.Path, "home", return_value=home), patch.dict(os.environ, {}, clear=True), patch.object(cli, "ensure_bundled_wine", return_value=None):
                self.assertIn(wine, cli.discover_wine())
