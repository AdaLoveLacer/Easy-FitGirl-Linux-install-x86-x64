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

from fitgirl_installer.models import InstallerError  # noqa: E402
from fitgirl_installer.verification import checksums  # noqa: E402


class ChecksumTests(unittest.TestCase):
    def test_known_digests_of_a_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "data.bin"
            path.write_bytes(b"abc")
            self.assertEqual(checksums.md5(path), "900150983cd24fb0d6963f7d28e17f72")
            self.assertEqual(checksums.file_hash(path, "md5"), "900150983cd24fb0d6963f7d28e17f72")
            self.assertEqual(
                checksums.sha256(path),
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            )

    def test_empty_file_digests(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "empty.bin"
            path.write_bytes(b"")
            self.assertEqual(checksums.md5(path), "d41d8cd98f00b204e9800998ecf8427e")
            self.assertEqual(
                checksums.file_hash(path),
                "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            )


class VerifyArchiveTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.source = Path(self._temporary.name)
        self.volume = self.source / "fg-01.bin"
        self.volume.write_bytes(b"abc")
        self.saved = []

    def tearDown(self):
        self._temporary.cleanup()

    def verify(self, step, state, dry_run=False):
        output = io.StringIO()
        with redirect_stdout(output):
            result = checksums.verify_archive(
                step, self.source, self.source / "state.json", state, dry_run,
                safe_child=lambda root, relative: root / relative,
                save_state=lambda path, value: self.saved.append(json.dumps(value, sort_keys=True)),
            )
        return result, output.getvalue()

    def test_valid_volume_is_hashed_once_and_recorded(self):
        step = {"archive": "fg-01.bin", "md5": "900150983CD24FB0D6963F7D28E17F72"}
        state = {}
        result, output = self.verify(step, state)
        self.assertEqual(result, self.volume)
        self.assertIn("[VALIDA] calculando MD5 de fg-01.bin...", output)
        self.assertEqual(state["verified"]["fg-01.bin"]["md5"], step["md5"])
        self.assertEqual(len(self.saved), 1)
        _, output = self.verify(step, state)
        self.assertEqual(output, "")
        self.assertEqual(len(self.saved), 1)

    def test_changed_volume_is_rejected_without_recording(self):
        state = {}
        with self.assertRaisesRegex(InstallerError, "MD5 inválido em fg-01.bin"):
            self.verify({"archive": "fg-01.bin", "md5": "0" * 32}, state)
        self.assertEqual(state, {"verified": {}})
        self.assertEqual(self.saved, [])

    def test_missing_volume_and_dry_run(self):
        with self.assertRaisesRegex(InstallerError, "volume ausente"):
            self.verify({"archive": "fg-02.bin", "md5": "0" * 32}, {})
        _, output = self.verify({"archive": "fg-01.bin", "md5": "0" * 32}, {}, dry_run=True)
        self.assertEqual(output, f"[VALIDA] MD5 fg-01.bin: {'0' * 32}\n")
        self.assertEqual(self.saved, [])

    def test_volume_without_md5_is_returned_unchecked(self):
        result, output = self.verify({"archive": "fg-01.bin"}, {})
        self.assertEqual((result, output, self.saved), (self.volume, "", []))


if __name__ == "__main__":
    unittest.main()
