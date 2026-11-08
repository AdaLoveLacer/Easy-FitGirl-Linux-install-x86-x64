#!/usr/bin/env python3

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fitgirl_installer.execution import extractor  # noqa: E402
from fitgirl_installer.models import InstallerError  # noqa: E402


def _args(**overrides):
    values = {
        "backend": Path("/opt/backend"), "wine": Path("/usr/bin/wine"),
        "monitor_interval": 10, "srep_memory": None, "bzip3_threads": None,
        "dry_run": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class RunExtractTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.source = self.root / "repack"
        self.target = self.root / "target"
        self.scratch = self.root / "scratch"
        for path in (self.source, self.target, self.scratch):
            path.mkdir()
        self.calls = []
        self.verified = []

    def tearDown(self):
        self._temporary.cleanup()

    def services(self, prefix=()):
        def resolve(value, target, scratch):
            return {"app": target, "scratch": scratch}[value]

        def verify(step):
            self.verified.append(step["archive"])
            return self.source / step["archive"]

        return extractor.ExtractionServices(
            resolve_destination=resolve,
            safe_child=lambda root, relative: root / relative,
            verify_source=verify,
            command_prefix=lambda: list(prefix),
            run_process=lambda *call: self.calls.append(call),
            working_directory=Path("/code"),
        )

    def run_step(self, step, args=None, **keywords):
        extractor.run_extract(
            step, args or _args(), self.source, self.target, self.scratch,
            self.root / "prefix", self.scratch / "state.json", {},
            services=self.services(keywords.pop("prefix", ())), **keywords,
        )

    def test_source_archive_is_verified_and_passed_by_name(self):
        (self.source / "fg-01.bin").write_bytes(b"x")
        self.run_step(
            {"archive": "fg-01.bin", "filters": ["a/*", "b/*"]},
            _args(srep_memory=512, bzip3_threads=4),
            global_base=0.25, global_weight=0.5, payload_ready=True,
            prefix=("taskset", "--cpu-list", "0-1"),
        )
        self.assertEqual(self.verified, ["fg-01.bin"])
        command, cwd, _, _, dry_run = self.calls[0]
        self.assertEqual(cwd, Path("/code"))
        self.assertFalse(dry_run)
        self.assertEqual(command, [
            "taskset", "--cpu-list", "0-1", "/opt/backend",
            "-d", str(self.source), "-t", str(self.target), "-w", str(self.scratch),
            "--archive", "fg-01.bin", "--wine", "/usr/bin/wine",
            "--prefix", str(self.root / "prefix"), "--monitor-interval", "10",
            "--global-base", "0.250000000", "--global-weight", "0.500000000",
            "--payload-ready", "--srep-memory", "512", "--bzip3-threads", "4",
            "--include", "a/*", "--include", "b/*",
        ])

    def test_intermediate_archive_uses_full_path_and_is_deleted_after(self):
        archive = self.scratch / "inner.fgpack"
        archive.write_bytes(b"x")
        self.run_step({
            "archive": "inner.fgpack", "archive_root": "scratch",
            "destination_suffix": "Data", "archive_path_filter": "*.pak",
            "archive_workdir": "work", "delete_archive_after": True,
        })
        self.assertEqual(self.verified, [])
        command = self.calls[0][0]
        self.assertEqual(command[command.index("--archive-path") + 1], str(archive))
        self.assertEqual(command[command.index("-t") + 1], str(self.target / "Data"))
        self.assertEqual(command[command.index("--archive-path-filter") + 1], "*.pak")
        self.assertEqual(command[command.index("--archive-workdir") + 1], str(self.target / "work"))
        self.assertFalse(archive.exists())

    def test_missing_intermediate_archive_stops_before_running(self):
        with self.assertRaisesRegex(InstallerError, "arquivo intermediário ausente"):
            self.run_step({"archive": "missing.fgpack", "archive_root": "scratch"})
        self.assertEqual(self.calls, [])

    def test_dry_run_tolerates_missing_archive_and_keeps_files(self):
        archive = self.scratch / "inner.fgpack"
        self.run_step(
            {"archive": "inner.fgpack", "archive_root": "scratch", "delete_archive_after": True},
            _args(dry_run=True),
        )
        self.assertTrue(self.calls[0][4])
        archive.write_bytes(b"x")
        self.run_step(
            {"archive": "inner.fgpack", "archive_root": "scratch", "delete_archive_after": True},
            _args(dry_run=True),
        )
        self.assertTrue(archive.exists())


if __name__ == "__main__":
    unittest.main()
