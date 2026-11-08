import copy
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fitgirl_installer import plan_audit
from fitgirl_installer.planning import planner
from fitgirl_installer.planning import script_flow


class PlanAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.iss = root / "install.iss"
        self.code = root / "CompiledCode.bin"
        self.asm = root / "code.txt"
        self.iss.write_text('[Setup]\nAppName="Synthetic"\n')
        self.code.write_bytes(b"IFPS-synthetic")
        self.asm.write_text('''===== proc #1 =====
CURSTEPCHANGED  bytecode @0x100 (64 bytes, 5 instructions)
  0x100  assign      s+16, "{tmp}\\a.txt"
  0x110  call        DELETEFILE
  0x120  assign      s+16, "{app}\\cache"
  0x130  call        DELTREE
  0x140  ret
''')
        self.manifest = {
            "components": {},
            "steps": planner.steps_from_disassembly(self.asm, {}, {}),
            "analysis": {
                "iss_sha256": planner.sha256(self.iss),
                "compiled_code_sha256": planner.sha256(self.code),
                "disassembly_sha256": planner.sha256(self.asm),
            },
        }

    def audit(self, manifest=None):
        return plan_audit.audit_plan(
            self.manifest if manifest is None else manifest,
            self.iss, self.asm, self.code,
        )

    def kinds(self, manifest=None):
        return {item["kind"] for item in self.audit(manifest)["issues"]}

    def test_cfg_prunes_direct_constant_if_not_back_edge(self):
        self.asm.write_text('''===== proc #1 =====
CURSTEPCHANGED  bytecode @0x100 (48 bytes, 3 instructions)
  0x100  assign      s+13, 1u8
  0x110  if not      s+13 goto 0x100
  0x120  ret
''')
        procedure = script_flow.parse_disassembly(self.asm)[0]
        cfg = script_flow.build_cfg(procedure)
        self.assertEqual(len(cfg.blocks), 2)
        self.assertEqual(
            [(edge.kind, edge.target) for edge in cfg.blocks[0].successors],
            [("branch-false", 0x120)],
        )

    def test_cfg_keeps_unknown_or_nonlocal_condition_edges(self):
        self.asm.write_text('''===== proc #1 =====
CURSTEPCHANGED  bytecode @0x100 (64 bytes, 5 instructions)
  0x100  assign      s+13, 1u8
  0x110  call        MAY_CHANGE_LOCAL
  0x120  if not      s+13 goto 0x100
  0x130  ret
''')
        procedure = script_flow.parse_disassembly(self.asm)[0]
        cfg = script_flow.build_cfg(procedure)
        self.assertEqual(
            {(edge.kind, edge.target) for edge in cfg.blocks[0].successors},
            {("branch-true", 0x100), ("branch-false", 0x130)},
        )

    def test_consistent_plan_still_requires_semantic_review(self):
        before = copy.deepcopy(self.manifest)
        report = self.audit()
        self.assertTrue(report["consistent"], report)
        self.assertEqual(report["status"], "MATCH_REVIEW_REQUIRED")
        self.assertTrue(report["review_required"])
        self.assertFalse(report["semantic_equivalence_proven"])
        self.assertEqual(before, self.manifest)

    def test_omission_and_duplicate_are_rejected(self):
        candidate = copy.deepcopy(self.manifest)
        candidate["steps"].pop()
        self.assertIn("action_coverage", self.kinds(candidate))
        candidate = copy.deepcopy(self.manifest)
        candidate["steps"].append(copy.deepcopy(candidate["steps"][0]))
        self.assertIn("duplicate_action", self.kinds(candidate))

    def test_reordering_is_rejected_even_with_full_coverage(self):
        self.manifest["steps"].reverse()
        report = self.audit()
        self.assertTrue(report["coverage"]["complete"])
        self.assertIn("action_sequence", self.kinds())

    def test_argument_and_condition_tampering_are_rejected(self):
        for field, value in (("path", "other.txt"), ("if_component", "invented"), ("path_root", "app")):
            with self.subTest(field=field):
                candidate = copy.deepcopy(self.manifest)
                candidate["steps"][0][field] = value
                self.assertIn("argument_or_condition_mismatch", self.kinds(candidate))

    def test_missing_or_changed_binary_provenance_is_rejected(self):
        self.code.write_bytes(b"changed")
        self.assertIn("source_hash_mismatch", self.kinds())
        del self.manifest["analysis"]["compiled_code_sha256"]
        self.assertIn("missing_provenance", self.kinds())

    def test_injected_actions_and_payload_are_rejected(self):
        self.manifest["steps"].append({"type": "exec", "executable": "injected.exe"})
        self.manifest["temporary_payload_files"] = [{"name": "injected.dll"}]
        self.assertIn("unmapped_action", self.kinds())
        self.assertIn("payload_mismatch", self.kinds())

    def test_unknown_cfg_target_is_rejected(self):
        self.asm.write_text(self.asm.read_text().replace('  0x140  ret', '  0x140  goto        0x999'))
        self.manifest["analysis"]["disassembly_sha256"] = planner.sha256(self.asm)
        self.assertIn("unresolved_cfg_targets", self.kinds())

    def test_missing_final_verification_is_rejected(self):
        self.iss.write_text('[Files]\nSource: "fitgirl.md5"; DestDir: "{app}\\_Redist"\n')
        self.manifest["analysis"]["iss_sha256"] = planner.sha256(self.iss)
        self.assertIn("verification_coverage", self.kinds())

    def test_compiled_code_is_redissected_and_mismatch_is_rejected(self):
        tool = self.code.parent / "fake-disassembler"
        tool.write_text(textwrap.dedent(f"""\
            #!/usr/bin/env python3
            import sys
            from pathlib import Path
            assert Path(sys.argv[1]).read_bytes() == {self.code.read_bytes()!r}
            sys.stdout.buffer.write({self.asm.read_bytes()!r})
        """))
        tool.chmod(0o755)
        output = self.code.parent / "audit.json"
        report = plan_audit.write_audit(
            self.manifest, self.iss, self.asm, self.code, output,
            disassembler=tool,
        )
        self.assertTrue(report["binary_disassembly_verified"], report)
        tool.write_text("#!/bin/sh\nprintf changed\n")
        tool.chmod(0o755)
        report = plan_audit.write_audit(
            self.manifest, self.iss, self.asm, self.code, output,
            disassembler=tool,
        )
        self.assertIn("compiled_disassembly_mismatch", {x["kind"] for x in report["issues"]})

    def test_action_paths_distinguish_conditional_orders(self):
        self.asm.write_text('''===== proc #1 =====
P  bytecode @0x100 (64 bytes, 5 instructions)
  0x100  if          s+1 goto 0x130
  0x110  call        DELETEFILE
  0x120  goto        0x140
  0x130  call        DELTREE
  0x140  ret
''')
        report = plan_audit.action_path_report(self.asm)
        procedure = report["procedures"][0]
        self.assertEqual(procedure["sequence_count"], 2)
        self.assertFalse(procedure["single_order"])
        self.assertFalse(report["all_relevant_procedures_single_order"])

    def test_interprocedural_paths_expand_direct_calls(self):
        self.asm.write_text('''===== proc #1 =====
INITIALIZEWIZARD  bytecode @0x100 (64 bytes, 4 instructions)
  0x100  call        HELPER
  0x110  ret

===== proc #2 =====
HELPER  bytecode @0x200 (64 bytes, 5 instructions)
  0x200  call        DELETEFILE
  0x210  call        SETINISTRING
  0x220  ret
''')
        report = plan_audit.interprocedural_action_path_report(self.asm)
        entry = next(item for item in report["entries"] if item["procedure"] == "INITIALIZEWIZARD")
        self.assertEqual(entry["sequence_count"], 1)
        self.assertEqual(
            entry["action_sequence_samples"][0],
            ["HELPER@0x200:DELETEFILE", "HELPER@0x210:SETINISTRING"],
        )
        self.assertFalse(report["interprocedural_paths_proven"])
