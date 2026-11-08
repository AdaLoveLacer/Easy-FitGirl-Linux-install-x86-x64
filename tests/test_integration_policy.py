import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fitgirl_installer.verification.integration import integration_report, write_integration_report


class IntegrationPolicyTests(unittest.TestCase):
    def test_inventory_never_promotes_redistributables_to_game_candidates(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "Game"
            (target / "_Redist/DirectX").mkdir(parents=True)
            (target / "bin").mkdir()
            (target / "Game.exe").write_bytes(b"game" * 100)
            (target / "bin/helper.exe").write_bytes(b"helper")
            (target / "_Redist/DirectX/DXSETUP.exe").write_bytes(b"dx")
            (target / "settings.reg").write_text("REGEDIT4\n")
            report = integration_report(target)
            self.assertEqual(report["game_executable_candidates"][0], "Game.exe")
            self.assertNotIn("_Redist/DirectX/DXSETUP.exe", report["game_executable_candidates"])
            self.assertEqual(report["redistributables"], ["_Redist/DirectX/DXSETUP.exe"])
            self.assertEqual(report["registry_files"], ["settings.reg"])
            self.assertEqual(report["policy"]["private_wine"], "codec_abi_only_never_game_runner")

    def test_report_is_written_outside_the_game_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "Game"
            target.mkdir()
            (target / "Game.exe").write_bytes(b"game")
            output = root / "scratch/integration-report.json"
            write_integration_report(target, output)
            self.assertTrue(output.is_file())
            self.assertFalse((target / "integration-report.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
