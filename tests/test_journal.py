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


if __name__ == "__main__":
    unittest.main(verbosity=2)
