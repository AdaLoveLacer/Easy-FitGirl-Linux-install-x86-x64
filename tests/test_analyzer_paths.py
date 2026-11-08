#!/usr/bin/env python3

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fitgirl_installer.planning import analyzer  # noqa: E402


class AnalysisPathsTests(unittest.TestCase):
    def test_paths_follow_xdg_cache_home(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(os.environ, {"XDG_CACHE_HOME": temporary}):
                paths = analyzer.analysis_paths("abc123")
            base = Path(temporary) / "fitgirl-installer" / "plans" / "abc123"
            self.assertEqual(paths.cache_root, Path(temporary))
            self.assertEqual(paths.analysis, base)
            self.assertEqual(paths.iss, base / "innounp" / "install_script.iss")
            self.assertEqual(paths.compiled, base / "innounp" / "embedded" / "CompiledCode.bin")
            self.assertEqual(paths.disassembly, base / "CompiledCode.disassembly.txt")
            self.assertEqual(paths.control_flow, base / "control-flow.json")
            self.assertEqual(paths.manifest, base / "manifest.draft.json")

    def test_default_cache_is_under_home(self):
        environment = {key: value for key, value in os.environ.items() if key != "XDG_CACHE_HOME"}
        with patch.dict(os.environ, environment, clear=True):
            paths = analyzer.analysis_paths("h")
        self.assertEqual(paths.cache_root, Path.home() / ".cache")


if __name__ == "__main__":
    unittest.main(verbosity=2)
