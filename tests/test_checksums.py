#!/usr/bin/env python3

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

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


if __name__ == "__main__":
    unittest.main()
