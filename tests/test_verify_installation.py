import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "src/fitgirl_installer/verify.py"


def md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


class VerifyInstallationTests(unittest.TestCase):
    def test_mismatch_missing_cache_and_repair(self):
        with tempfile.TemporaryDirectory(prefix="fitgirl-verify-") as temporary:
            root = Path(temporary)
            (root / "good.bin").write_bytes(b"good")
            (root / "bad.bin").write_bytes(b"bad")
            manifest = root / "fitgirl.md5"
            manifest.write_text(
                f"{md5(b'good')} *..\\good.bin\n"
                f"{md5(b'repaired')} *..\\bad.bin\n"
                f"{md5(b'missing')} *..\\missing.bin\n",
                encoding="utf-8",
            )
            state = root / "state.json"
            command = [
                sys.executable, str(VERIFIER), "--root", str(root),
                "--manifest", str(manifest), "--state", str(state), "--present-only",
            ]
            failed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertEqual(failed.returncode, 1, failed.stdout)
            self.assertIn('"mismatch": 1', failed.stdout)
            cached = json.loads(state.read_text())
            self.assertEqual(set(cached["files"]), {"good.bin", "bad.bin"})

            (root / "bad.bin").write_bytes(b"repaired")
            repaired = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertEqual(repaired.returncode, 0, repaired.stdout)
            self.assertIn('"ok": 2', repaired.stdout)
            self.assertIn('"missing": 1', repaired.stdout)

            complete_required = subprocess.run(command[:-1], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertEqual(complete_required.returncode, 2, complete_required.stdout)


    def test_script_does_not_let_the_platform_package_shadow_the_standard_module(self):
        # Emulate `python3 verify.py`: Python puts the script's directory first.
        probe = (
            "import runpy, sys; "
            f"sys.path.insert(0, {str(VERIFIER.parent)!r}); "
            f"runpy.run_path({str(VERIFIER)!r}, run_name='probe'); "
            "import platform; print(platform.__file__)"
        )
        result = subprocess.run([sys.executable, "-c", probe], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("fitgirl_installer", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
