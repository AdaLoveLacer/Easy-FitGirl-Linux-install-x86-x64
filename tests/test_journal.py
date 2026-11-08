#!/usr/bin/env python3

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fitgirl_installer.execution import journal  # noqa: E402
from fitgirl_installer.models import InstallerError  # noqa: E402


class JournalFileTests(unittest.TestCase):
    def test_atomic_json_keeps_previous_version_as_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            journal.atomic_json(path, {"v": 1})
            self.assertFalse(path.with_name("state.json.bak").exists())
            journal.atomic_json(path, {"v": 2})
            self.assertEqual(json.loads(path.read_text()), {"v": 2})
            self.assertEqual(json.loads(path.with_name("state.json.bak").read_text()), {"v": 1})
            self.assertEqual(sorted(p.name for p in Path(temporary).iterdir()), ["state.json", "state.json.bak"])

    def test_load_json_rejects_unreadable_and_non_object(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "x.json"
            path.write_text("[1]")
            with self.assertRaisesRegex(InstallerError, "objeto JSON esperado"):
                journal.load_json(path)
            path.write_text("{")
            with self.assertRaisesRegex(InstallerError, "não foi possível ler"):
                journal.load_json(path)

    def test_load_state_restores_backup_and_preserves_corrupt_journal(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "install-state.json"
            journal.atomic_json(path, {"completed": {}})
            journal.atomic_json(path, {"completed": {"001:a": {}}})
            path.write_text("{corrupt")
            with redirect_stdout(io.StringIO()) as output:
                state = journal.load_state(path)
            self.assertEqual(state, {"completed": {}})
            self.assertEqual(json.loads(path.read_text()), {"completed": {}})
            self.assertEqual(len(list(Path(temporary).glob("install-state.json.corrupt-*"))), 1)
            self.assertIn("backup restaurado", output.getvalue())

    def test_load_state_without_backup_reports_original_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "install-state.json"
            path.write_text("{corrupt")
            with self.assertRaisesRegex(InstallerError, "não foi possível ler"):
                journal.load_state(path)


class ResumeTests(unittest.TestCase):
    def expected(self, **changes):
        state = {
            "version": journal.STATE_VERSION, "setup_sha256": "s", "manifest_sha256": "m",
            "source": "/src", "target": "/dst", "components": ["core"], "settings": {},
            "completed": {}, "verified": {}, "active": None, "created_at": 0,
        }
        state.update(changes)
        return state

    def test_missing_journal_starts_from_expected_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            expected = self.expected()
            self.assertIs(journal.resume_or_start(Path(temporary) / "s.json", expected), expected)

    def test_journal_for_other_plan_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "s.json"
            journal.atomic_json(path, self.expected(manifest_sha256="other"))
            with self.assertRaisesRegex(InstallerError, r"outro plano/opções \(manifest_sha256\)"):
                journal.resume_or_start(path, self.expected())

    def test_dead_active_step_is_cleared_and_completed_steps_kept(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "s.json"
            journal.atomic_json(path, self.expected(
                completed={"001:a": {}}, active={"pgid": 2 ** 22 + 12345},
            ))
            with redirect_stdout(io.StringIO()) as output:
                state = journal.resume_or_start(path, self.expected())
            self.assertIsNone(state["active"])
            self.assertEqual(state["completed"], {"001:a": {}})
            self.assertIn("não está mais ativa", output.getvalue())

    def test_live_active_step_blocks_a_concurrent_run(self):
        import os
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "s.json"
            journal.atomic_json(path, self.expected(active={"pgid": os.getpgrp()}))
            with self.assertRaisesRegex(InstallerError, "ainda está ativa"):
                journal.resume_or_start(path, self.expected())

    def test_initial_state_records_only_given_optional_limits(self):
        from types import SimpleNamespace
        args = SimpleNamespace(srep_memory="1g", cpus=None, nice=5, limit_2gb=True,
                               bzip3_threads=None, memory_high="2G", memory_max=None)
        state = journal.initial_state("s", "m", Path("/src"), Path("/dst"), {"b", "a"}, args)
        self.assertEqual(state["components"], ["a", "b"])
        self.assertEqual(state["settings"], {
            "srep_memory": "1g", "cpus": None, "nice": 5, "limit_2gb": True, "memory_high": "2G",
        })
        self.assertEqual((state["completed"], state["active"]), ({}, None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
