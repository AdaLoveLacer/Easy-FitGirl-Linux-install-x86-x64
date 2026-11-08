#!/usr/bin/env python3

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fitgirl_installer.planning import success_path  # noqa: E402


def script(after_extract: str = "set-flag    not s+1", extra: str = "") -> str:
    """A FitGirl-shaped CurStepChanged: ssInstall arms g#5, ssPostInstall extracts,
    clears g#5 only when the extraction returned true, and launches the
    uninstaller while g#5 is still set."""
    return f"""===== proc #1 =====
CURSTEPCHANGED  bytecode @0x100 (0 bytes, 0 instructions)
  0x100  push-temp   BOOLEAN
  0x101  cmp.eq     s+1 := s-1 = 1u8
  0x102  set-flag    not s+1
  0x103  pop
  0x104  flag-goto   0x110
  0x105  assign      g#5, 1u8
  0x110  push-temp   BOOLEAN
  0x111  cmp.eq     s+1 := s-1 = 2u8
  0x112  set-flag    not s+1
  0x113  pop
  0x114  flag-goto   0x160
  0x115  push-temp   BOOLEAN
  0x116  push-ref    s+1
  0x117  call        dll:files:ISDone.dll!ISArcExtract
  0x118  pop
  0x119  {after_extract}
  0x11a  pop
  0x11b  flag-goto   0x130
  0x11c  assign      g#5, 0u8
{extra}  0x130  push-temp   BOOLEAN
  0x131  cmp.eq     s+1 := s-1 = 2u8
  0x132  calc.and   s+1, g#5
  0x133  set-flag    not s+1
  0x134  pop
  0x135  flag-goto   0x160
  0x136  assign      s+15, "/VERYSILENT"
  0x137  assign      s+16, "{{uninstallexe}}"
  0x138  call        dll:files:ISDone.dll!Exec2
  0x160  ret
"""


class SuccessPathTests(unittest.TestCase):
    def report(self, text: str, exports=frozenset()):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "CompiledCode.disassembly.txt"
            path.write_text(text, encoding="utf-8")
            return success_path.success_path_report(path, exports)

    def test_uninstaller_is_unreachable_when_success_clears_its_flag(self):
        report = self.report(script())
        self.assertEqual(report["uninstaller_guard_flag"], "g#5")
        self.assertEqual(report["uninstaller_calls"], ["0x138"])
        self.assertTrue(report["uninstaller_launch_unreachable"])
        self.assertTrue(report["order_proven"])
        self.assertEqual(report["action_events"], ["ssPostInstall"])

    def test_uninstaller_is_reached_when_success_skips_the_clearing(self):
        report = self.report(script(after_extract="set-flag    s+1"))
        self.assertFalse(report["uninstaller_launch_unreachable"])
        self.assertEqual(
            [(item["event"], item["flag_value"]) for item in report["uninstaller_reached"]],
            [("ssPostInstall", True)],
        )

    def test_unknown_result_keeps_both_branches_and_is_not_proven(self):
        unknown = script().replace(
            "call        dll:files:ISDone.dll!ISArcExtract", "call        DIREXISTS",
        )
        self.assertFalse(self.report(unknown)["uninstaller_launch_unreachable"])

    def test_success_of_an_init_export_requires_catalog_knowledge(self):
        init = script().replace("ISDone.dll!ISArcExtract", "ISDone.dll!ISDoneInit")
        self.assertFalse(self.report(init)["uninstaller_launch_unreachable"])
        self.assertTrue(self.report(init, frozenset({"isdoneinit"}))["uninstaller_launch_unreachable"])

    def test_backward_edge_on_the_success_path_disproves_the_order(self):
        report = self.report(script(extra="  0x11d  goto        0x115\n"))
        self.assertFalse(report["order_proven"])
        self.assertEqual(report["reachable_back_edges"], ["0x11c->0x115"])

    def test_missing_callback_proves_nothing(self):
        report = self.report("===== proc #1 =====\nMAIN  bytecode @0x1 (0 bytes, 0 instructions)\n  0x1  ret\n")
        self.assertFalse(report["order_proven"])
        self.assertFalse(report["uninstaller_launch_unreachable"])


if __name__ == "__main__":
    unittest.main()
