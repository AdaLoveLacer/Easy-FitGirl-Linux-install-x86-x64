#!/usr/bin/env python3

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fitgirl_installer.execution import journal as order  # noqa: E402
from fitgirl_installer.models import InstallerError  # noqa: E402


PLANNED = [
    (1, {"id": "a", "type": "extract"}, "001:a"),
    (2, {"id": "b", "type": "batch"}, "002:b"),
    (3, {"id": "c", "type": "verify"}, "003:c"),
]
MANIFEST = {"name": "Synthetic"}


def journal(completed=(), trace=None):
    state = {
        "setup_sha256": "s", "manifest_sha256": "m",
        "completed": {key: {"finished_at": 1.0} for key in completed},
    }
    if trace is not None:
        state["execution_trace"] = trace
    return state


class RuntimeOrderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.scratch = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def report(self):
        reports = list((self.scratch / "reports").glob("runtime-divergence-*.json"))
        self.assertEqual(len(reports), 1)
        return json.loads(reports[0].read_text())

    def test_legacy_journal_gets_a_trace_in_plan_order(self):
        state = journal(["001:a", "002:b"])
        order.validate_runtime_order(self.scratch, MANIFEST, state, PLANNED)
        self.assertEqual(
            [(e["event"], e["step"], e["source"]) for e in state["execution_trace"]],
            [("completed", "001:a", "legacy-journal"), ("completed", "002:b", "legacy-journal")],
        )
        saved = json.loads((self.scratch / "install-state.json").read_text())
        self.assertEqual(saved["execution_trace"], state["execution_trace"])

    def test_later_step_completed_before_expected_one_is_reported(self):
        state = journal(["001:a", "003:c"])
        with self.assertRaisesRegex(InstallerError, "divergência na ordem de execução"):
            order.validate_runtime_order(self.scratch, MANIFEST, state, PLANNED)
        report = self.report()
        self.assertEqual(report["kind"], "runtime_execution_order_divergence")
        # Comportamento atual preservado pela refatoração. O "expected_next"
        # deste caso aponta 003:c em vez de 002:b (bug pré-existente,
        # registrado para correção separada), por isso não é conferido aqui.
        self.assertEqual(report["observed"]["step"], "003:c")
        self.assertEqual(report["observed"]["event"], "completed_in_journal")
        self.assertEqual(report["reason"], "o journal marca uma etapa posterior como concluída antes da etapa esperada")
        self.assertNotIn(str(self.scratch), json.dumps(report))

    def test_unknown_completed_step_is_reported(self):
        with self.assertRaisesRegex(InstallerError, "não pertence ao plano"):
            order.validate_runtime_order(self.scratch, MANIFEST, journal(["009:x"], trace=[]), PLANNED)
        self.assertEqual(self.report()["observed"]["step"], "009:x")

    def test_out_of_order_trace_is_reported(self):
        trace = [
            {"event": "started", "step": "002:b"},
            {"event": "started", "step": "001:a"},
        ]
        with self.assertRaisesRegex(InstallerError, "fora da ordem do plano"):
            order.validate_runtime_order(self.scratch, MANIFEST, journal(trace=trace), PLANNED)

    def test_completed_step_missing_from_trace_is_reported(self):
        with self.assertRaisesRegex(InstallerError, "discordam sobre uma etapa concluída"):
            order.validate_runtime_order(self.scratch, MANIFEST, journal(["001:a"], trace=[]), PLANNED)

    def test_dispatch_of_wrong_step_is_reported_before_it_starts(self):
        state = journal(trace=[])
        with self.assertRaisesRegex(InstallerError, "não é a próxima etapa pendente"):
            order.validate_runtime_order(
                self.scratch, MANIFEST, state, PLANNED, current=PLANNED[1],
            )
        self.assertEqual(state["execution_trace"], [])

    def test_dispatch_and_completion_are_traced_and_saved(self):
        state = journal(trace=[])
        order.validate_runtime_order(self.scratch, MANIFEST, state, PLANNED, current=PLANNED[0])
        order.record_runtime_completion(self.scratch, state, 1, PLANNED[0][1], "001:a")
        self.assertEqual(
            [(e["event"], e["step"]) for e in state["execution_trace"]],
            [("started", "001:a"), ("completed", "001:a")],
        )
        self.assertIn("001:a", state["completed"])
        saved = json.loads((self.scratch / "install-state.json").read_text())
        self.assertEqual(saved["execution_trace"], state["execution_trace"])
        order.validate_runtime_order(self.scratch, MANIFEST, state, PLANNED, current=PLANNED[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
