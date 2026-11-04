import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fitgirl_installer import cli, planner


class SizeInfoTests(unittest.TestCase):
    def test_packed_size_counts_only_setup_and_local_volumes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, size in (("setup.exe", 10), ("fg-01.bin", 20), ("FG-OPTIONAL.BIN", 30), ("readme.txt", 99)):
                (root / name).write_bytes(b"x" * size)
            self.assertEqual(cli.repack_size(root), 60)
            manifest = {"steps": [
                {"type": "extract", "archive": "fg-01.bin"},
                {"type": "extract", "archive": "fg-01.bin"},
                {"type": "extract", "archive": "FG-OPTIONAL.BIN", "if_component": "bonus"},
                {"type": "extract", "archive": "inner.fgpack", "archive_root": "app"},
            ]}
            self.assertEqual(cli.selected_repack_size(root, manifest, set()), 30)
            self.assertEqual(cli.selected_repack_size(root, manifest, {"bonus"}), 60)
            (root / "fg-01.bin").unlink()
            self.assertIsNone(cli.selected_repack_size(root, manifest, set()))

    def test_extra_disk_space_metadata_is_positive_literal_in_setup_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "script.iss"
            path.write_text("[Setup]\nExtraDiskSpaceRequired=6635000000\n[Components]\n")
            value = planner.disk_space_from_iss(path)
            self.assertEqual(value["extra_required_bytes"], 6635000000)
            self.assertFalse(value["selection_specific"])
            for text in (
                "[Files]\nExtraDiskSpaceRequired=123\n",
                "[Setup]\nExtraDiskSpaceRequired=-1\n",
                "[Setup]\nExtraDiskSpaceRequired={code:GetSize}\n",
                "[Setup]\nExtraDiskSpaceRequired=0\n",
                "[Setup]\nExtraDiskSpaceRequired=1\nExtraDiskSpaceRequired=2\n",
            ):
                path.write_text(text)
                self.assertIsNone(planner.disk_space_from_iss(path))

    def test_legacy_plan_can_read_existing_cache_without_starting_tools(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            iss = root / "fitgirl-installer/plans/testhash/innounp/install_script.iss"
            iss.parent.mkdir(parents=True)
            iss.write_text("[Setup]\nExtraDiskSpaceRequired=4096\n")
            with patch.dict("os.environ", {"XDG_CACHE_HOME": str(root)}), patch.object(cli.subprocess, "run", side_effect=AssertionError("no tool execution")):
                self.assertEqual(cli.declared_disk_space({}, root / "manifest.json", "testhash"), 4096)
                self.assertIsNone(cli.declared_disk_space({}, root / "manifest.json", "absent"))

    def test_size_format_uses_binary_units_and_portuguese_decimal(self):
        self.assertEqual(cli.format_size(1024**3), "1,00 GiB")
        self.assertEqual(cli.format_size(1536), "1,50 KiB")
