#!/usr/bin/env python3

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fitgirl_installer import cli as CLI  # noqa: E402
from fitgirl_installer.planning import analyzer, audit, isdone_catalog, planner  # noqa: E402


KNOWN = isdone_catalog.CATALOG[
    "c652b4b564b3c85c399155cbb45c6fb5a9f56f074e566bfd20f01da6e0412c74"
]


def proven(**overrides):
    arguments = {
        "issues": [], "provenance_complete": True, "binary_disassembly_verified": True,
        "coverage": {"complete": True}, "isdone_version": KNOWN,
        "semantic_guards": {
            "all_recognized_actions_covered_by_proven_event_guard": True,
            "checkbox_conditions": {"ini_write_sites": [{"condition": {"proven": True}}]},
            "component_selection": {"isarc_extract_calls": [{"index_matches_selection_bit": True}]},
        },
        "success": {"order_proven": True},
        "steps": [{"type": "isexec", "rollback_paths": []}, {"type": "extract"}],
    }
    arguments.update(overrides)
    return audit.automatic_acceptance(**arguments)


class AcceptancePolicyTests(unittest.TestCase):
    def test_every_proof_accepts_the_plan(self):
        acceptance = proven()
        self.assertTrue(acceptance["automatic"])
        self.assertEqual(acceptance["policy"], "isdone-catalog-v1")
        self.assertEqual(acceptance["isdone"], KNOWN.label)
        self.assertTrue(all(acceptance["requirements"].values()))

    def test_each_missing_proof_keeps_the_plan_for_review(self):
        cases = {
            "no_audit_issues": {"issues": [{"kind": "action_sequence"}]},
            "provenance_complete": {"provenance_complete": False},
            "disassembly_reproduced_from_compiled_code": {"binary_disassembly_verified": False},
            "every_action_planned": {"coverage": {"complete": False}},
            "isdone_build_catalogued": {"isdone_version": None},
            "actions_under_proven_event_guard": {"semantic_guards": {
                "all_recognized_actions_covered_by_proven_event_guard": False,
            }},
            "checkbox_conditions_proven": {"semantic_guards": {
                "all_recognized_actions_covered_by_proven_event_guard": True,
                "checkbox_conditions": {"ini_write_sites": [{"condition": {"proven": False}}]},
            }},
            "components_match_selection_bits": {"semantic_guards": {
                "all_recognized_actions_covered_by_proven_event_guard": True,
                "component_selection": {"isarc_extract_calls": [{"index_matches_selection_bit": False}]},
            }},
            "order_proven_on_success_path": {"success": {"order_proven": False}},
            "every_program_has_rollback_scope": {"steps": [{"type": "isexec"}]},
        }
        for requirement, override in cases.items():
            with self.subTest(requirement=requirement):
                acceptance = proven(**override)
                self.assertFalse(acceptance["automatic"])
                self.assertFalse(acceptance["requirements"][requirement])


class PlanStateTests(unittest.TestCase):
    def test_accepted_plan_stops_being_a_draft(self):
        candidate = {"draft": True, "review_required": True}
        analyzer.apply_semantic_blockers(candidate, {"acceptance": proven()})
        self.assertFalse(candidate["draft"])
        self.assertFalse(candidate["review_required"])
        self.assertTrue(candidate["acceptance"]["automatic"])

    def test_plan_that_loses_its_proof_returns_to_review(self):
        candidate = {"draft": False, "review_required": False, "acceptance": proven()}
        analyzer.apply_semantic_blockers(candidate, {"acceptance": proven(isdone_version=None)})
        self.assertTrue(candidate["draft"])
        self.assertTrue(candidate["review_required"])
        self.assertNotIn("acceptance", candidate)

    def test_plan_accepted_by_a_reviewer_is_left_alone(self):
        candidate = {"draft": False, "review_required": False}
        analyzer.apply_semantic_blockers(candidate, {"acceptance": proven(isdone_version=None)})
        self.assertFalse(candidate["draft"])
        self.assertFalse(candidate["review_required"])

    def test_blocker_always_wins(self):
        candidate = {"draft": True, "review_required": True}
        report = {
            "acceptance": proven(),
            "semantic_guards": {"critical_external_effects": [{
                "kind": "write", "call_address": "0x1", "blocks_audit_acceptance": True,
            }]},
        }
        analyzer.apply_semantic_blockers(candidate, report)
        self.assertTrue(candidate["draft"])
        self.assertIn("semantic_blockers", candidate)


class WizardTests(unittest.TestCase):
    def run_wizard(self, manifest):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            (source / "setup.exe").write_bytes(b"setup")
            plan = source / "plan.json"
            reached = []
            output = io.StringIO()
            with (
                patch.object(CLI, "select_codec_runtime", return_value=Path("/bin/true")),
                patch.object(CLI, "generate_manifest_draft", return_value=(plan, manifest)),
                patch.object(CLI, "prompt_destination", side_effect=lambda *a, **k: reached.append("destination") or source / "game"),
                patch.object(CLI, "prompt_components", side_effect=AssertionError("stop")),
                redirect_stdout(output),
            ):
                try:
                    CLI.interactive_install(source)
                except AssertionError:
                    pass
            return reached, output.getvalue()

    def test_accepted_generated_plan_continues_to_the_wizard(self):
        reached, output = self.run_wizard({
            "name": "Game", "draft": False, "review_required": False,
            "acceptance": proven(), "steps": [{"type": "extract"}] * 3, "components": {},
        })
        self.assertEqual(reached, ["destination"])
        self.assertIn("plano automático aceito: 3 etapas", output)

    def test_unaccepted_generated_plan_is_still_refused(self):
        with self.assertRaisesRegex(CLI.InstallerError, "instalação recusada"):
            with tempfile.TemporaryDirectory() as temporary, patch.object(
                CLI, "select_codec_runtime", return_value=Path("/bin/true"),
            ), patch.object(CLI, "generate_manifest_draft", return_value=(
                Path(temporary) / "plan.json", {"draft": True, "review_required": True, "steps": []},
            )), redirect_stdout(io.StringIO()):
                (Path(temporary) / "setup.exe").write_bytes(b"setup")
                CLI.interactive_install(Path(temporary))


class CommandWriteScopeTests(unittest.TestCase):
    """Rollback scope inferred from a FitGirl post-processing command line."""

    @staticmethod
    def expression(*parts):
        result = [{"operation": "assign", "value": "/C "}]
        for part in parts:
            if part.startswith("!"):
                result.append({"operation": "expanded_quoted", "value": part[1:]})
            else:
                result.append({"operation": "calc.add", "value": part})
        return result

    def scope(self, *parts):
        found = planner.command_write_scope(self.expression(*parts), "app", "Data")
        return None if found is None else [item["path"] for item in found]

    def test_named_operands_of_payload_tools_and_builtins_are_snapshotted(self):
        self.assertEqual(
            self.scope("!{tmp}\\x2.exe", " 01.fgpack 01.fgpack.x2&&del 01.fgpack.x2"),
            ["Data/01.fgpack", "Data/01.fgpack.x2"],
        )
        self.assertEqual(
            self.scope("!{tmp}\\x5.exe", " -s-1g a.fgpack a.x5 a_&&del a.x5&&move a_ a.fgpack"),
            ["Data/a.fgpack", "Data/a.x5", "Data/a_"],
        )
        self.assertEqual(
            self.scope("copy /b nul+re\\*.fgu re_chunk.fga&&rd /q /s re"),
            ["Data/re_chunk.fga", "Data/re"],
        )

    def test_anything_outside_the_simple_shape_has_no_scope(self):
        for parts in (
            ("!{tmp}\\x2.exe", " a.bin b.bin | more"),
            ("!{tmp}\\x2.exe", " ..\\a.bin b"),
            ("!{tmp}\\x2.exe", " C:\\a.bin b"),
            ("!{tmp}\\x2.exe", " a.bin %TEMP%\\b"),
            ("format c:",),
            ("!{tmp}\\x2.exe", ' "unterminated'),
        ):
            with self.subTest(parts=parts):
                self.assertIsNone(self.scope(*parts))


if __name__ == "__main__":
    unittest.main()
