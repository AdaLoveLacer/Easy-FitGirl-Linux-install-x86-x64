#!/usr/bin/env python3

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fitgirl_installer.planning import analyzer, isdone_catalog  # noqa: E402


KNOWN = "c652b4b564b3c85c399155cbb45c6fb5a9f56f074e566bfd20f01da6e0412c74"
EFFECTS = [
    {"kind": "unmodeled_precomp_ini_write", "blocks_audit_acceptance": True},
    {"kind": "unmodeled_conditional_records_file_deletion", "blocks_audit_acceptance": True},
    {"kind": "unmodeled_silent_uninstaller_launch", "blocks_audit_acceptance": True},
]


def script(records: str) -> str:
    return f"""===== proc #1 =====
CURSTEPCHANGED  bytecode @0x100 (0 bytes, 0 instructions)
  0x100  assign      s+15, "{records}"
  0x101  call        dll:files:ISDone.dll!ISDoneInit
  0x102  assign      s+15, "{{app}}"
  0x103  assign      s+16, 256i32
  0x104  call        dll:files:ISDone.dll!PrecompInit
  0x105  ret
"""


class ResolveEffectsTests(unittest.TestCase):
    def resolve(self, records: str, isdone: str | None, unreachable: bool):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "CompiledCode.disassembly.txt"
            path.write_text(script(records), encoding="utf-8")
            return isdone_catalog.resolve_effects(
                EFFECTS, path, isdone, {"uninstaller_launch_unreachable": unreachable,
                                        "uninstaller_guard_flag": "g#29"},
            )

    def blocking(self, effects):
        return [effect["kind"] for effect in effects if effect["blocks_audit_acceptance"]]

    def test_catalogued_dll_with_proofs_lifts_every_effect(self):
        effects = self.resolve("{src}\\records.inf", KNOWN, True)
        self.assertEqual(self.blocking(effects), [])
        self.assertEqual(
            [effect["resolution"]["rule"] for effect in effects],
            ["codec_resource_tuning", "deletion_outside_installation", "failure_path_only"],
        )
        self.assertEqual(effects[1]["resolution"]["records_paths"], ["{src}\\records.inf"])
        self.assertTrue(all(effect["resolution"]["evidence"] for effect in effects))

    def test_unknown_dll_keeps_every_effect_blocked(self):
        for isdone in (None, "0" * 64):
            effects = self.resolve("{src}\\records.inf", isdone, True)
            self.assertEqual(len(self.blocking(effects)), 3)
            self.assertIn("not in the catalog", effects[0]["unresolved_reason"])

    def test_records_file_inside_the_installation_stays_blocked(self):
        effects = self.resolve("{app}\\records.inf", KNOWN, True)
        self.assertEqual(self.blocking(effects), ["unmodeled_conditional_records_file_deletion"])

    def test_uninstaller_needs_the_success_path_proof(self):
        effects = self.resolve("{src}\\records.inf", KNOWN, False)
        self.assertEqual(self.blocking(effects), ["unmodeled_silent_uninstaller_launch"])


class IsdoneFingerprintTests(unittest.TestCase):
    def test_hashes_the_extracted_dll_and_tolerates_a_missing_one(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tool = root / "fake-innoextract"
            tool.write_text(
                "#!/usr/bin/env python3\n"
                "import sys\nfrom pathlib import Path\n"
                "args = sys.argv[1:]\n"
                "out = Path(args[args.index('--output-dir') + 1])\n"
                "if Path(args[-1]).name == 'with-dll.exe':\n"
                "    (out / 'tmp').mkdir(parents=True)\n"
                "    (out / 'tmp' / 'isdone.dll').write_bytes(b'dll')\n",
                encoding="utf-8",
            )
            tool.chmod(0o755)
            self.assertEqual(
                analyzer.isdone_fingerprint(root / "with-dll.exe", root / "a", innoextract=tool),
                hashlib.sha256(b"dll").hexdigest(),
            )
            self.assertIsNone(
                analyzer.isdone_fingerprint(root / "without.exe", root / "b", innoextract=tool)
            )


if __name__ == "__main__":
    unittest.main()
