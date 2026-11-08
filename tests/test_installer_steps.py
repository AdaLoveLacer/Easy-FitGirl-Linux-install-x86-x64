#!/usr/bin/env python3

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fitgirl_installer.execution import installer  # noqa: E402


def resolve(value: str, target: Path, scratch: Path) -> Path:
    return {"app": target, "scratch": scratch}[value]


def child(root: Path, relative: str) -> Path:
    return root / relative


class StepSelectionTests(unittest.TestCase):
    manifest = {"steps": [
        {"id": "core", "type": "extract", "archive": "core.bin"},
        {"id": "extra", "type": "extract", "archive": "extra.bin", "if_component": "extra"},
        {"id": "patch", "type": "batch"},
        {"type": "verify"},
    ]}

    def test_selected_steps_keep_plan_order_and_keys(self):
        self.assertEqual(
            [key for _, _, key in installer.selected_steps(self.manifest, {"core"}, set())],
            ["001:core", "003:patch", "004:verify"],
        )

    def test_weighted_steps_use_archive_size_and_report_skips(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            (source / "core.bin").write_bytes(b"x" * 10)
            output = io.StringIO()
            with redirect_stdout(output):
                planned = installer.weighted_steps(
                    self.manifest, {"core"}, set(), source=source,
                    target=source / "target", scratch=source / "scratch",
                    resolve_destination=resolve, safe_child=child,
                )
        self.assertEqual(
            [(key, weight) for _, _, key, weight in planned],
            [("001:core", 10), ("003:patch", 1024 * 1024), ("004:verify", 1024 * 1024)],
        )
        self.assertEqual(
            output.getvalue(), "[PULA] 002:extra: condição de componente não satisfeita\n"
        )

    def test_missing_archive_counts_as_one_mebibyte(self):
        with tempfile.TemporaryDirectory() as temporary:
            planned = installer.weighted_steps(
                {"steps": [{"id": "a", "type": "extract", "archive": "a.bin"}]},
                set(), set(), source=Path(temporary), target=Path(temporary),
                scratch=Path(temporary), resolve_destination=resolve, safe_child=child,
            )
        self.assertEqual(planned[0][3], 1024 * 1024)


if __name__ == "__main__":
    unittest.main(verbosity=2)
