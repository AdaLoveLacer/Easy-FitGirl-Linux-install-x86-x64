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


class PlannedStepRunTests(unittest.TestCase):
    def planned(self):
        return [
            (1, {"id": "a", "type": "extract", "archive": "a.bin"}, "001:a", 3),
            (2, {"id": "b", "type": "batch"}, "002:b", 1),
        ]

    def test_completed_steps_are_resumed_and_weights_reach_handlers(self):
        calls, verified, checked, recorded = [], [], [], []
        state = {"completed": {"001:a": {}}}
        with redirect_stdout(io.StringIO()):
            installer.run_planned_steps(
                self.planned(), state,
                handlers={"batch": calls.append},
                verify_source=lambda step: verified.append(step["id"]),
                check_order=lambda index, step, key: checked.append(key),
                record_completion=lambda index, step, key: recorded.append(key),
                error_type=RuntimeError,
            )
        self.assertEqual(verified, ["a"])
        self.assertEqual(checked, ["002:b"])
        self.assertEqual(recorded, ["002:b"])
        self.assertEqual(len(calls), 1)
        self.assertEqual((calls[0].key, calls[0].global_base, calls[0].global_weight), ("002:b", 0.75, 0.25))

    def test_unknown_step_type_is_refused_before_completion(self):
        recorded = []
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, "não suportado: mystery"):
            installer.run_planned_steps(
                [(1, {"id": "x", "type": "mystery"}, "001:x", 1)], {"completed": {}},
                handlers={}, verify_source=lambda step: None, check_order=None,
                record_completion=lambda *item: recorded.append(item), error_type=RuntimeError,
            )
        self.assertEqual(recorded, [])

    def test_dry_run_skips_order_check_and_recording(self):
        calls = []
        with redirect_stdout(io.StringIO()):
            installer.run_planned_steps(
                self.planned()[1:], {"completed": {}}, handlers={"batch": calls.append},
                verify_source=lambda step: None, check_order=None, record_completion=None,
                error_type=RuntimeError,
            )
        self.assertEqual([run.key for run in calls], ["002:b"])


class FinishInstallationTests(unittest.TestCase):
    def test_real_run_reports_and_finalizes_after_preserving_verifier(self):
        events = []
        output = io.StringIO()
        with redirect_stdout(output):
            installer.finish_installation(
                [(1, {"type": "merge-manifests"}, "001:m", 1)], target=Path("/t"),
                scratch=Path("/s"), state_path=Path("/s/state"), state={}, dry_run=False,
                quicksfv_x64=None,
                preserve_verifier=lambda *a, **k: events.append(("verifier", k)),
                write_integration_report=lambda target, path: events.append(("report", path)) or {
                    "game_executable_candidates": ["a"], "redistributables": [],
                },
                finalize_transactions=lambda *a: events.append(("finalize",)),
            )
        self.assertEqual(
            events,
            [("verifier", {"preserve_existing_manifest": True}),
             ("report", Path("/s/integration-report.json")), ("finalize",)],
        )
        self.assertIn("[INTEGRAÇÃO] 1 executáveis candidatos", output.getvalue())

    def test_dry_run_neither_reports_nor_finalizes(self):
        events = []
        with redirect_stdout(io.StringIO()):
            installer.finish_installation(
                [], target=Path("/t"), scratch=Path("/s"), state_path=Path("/s/state"),
                state={}, dry_run=True, quicksfv_x64=None,
                preserve_verifier=lambda *a, **k: events.append("verifier"),
                write_integration_report=lambda *a: events.append("report"),
                finalize_transactions=lambda *a: events.append("finalize"),
            )
        self.assertEqual(events, ["verifier"])


class RunInstallationTests(unittest.TestCase):
    def run_case(self, steps, dry_run=False):
        events = []
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def record(name):
                return lambda *args, **kwargs: events.append(name)

            services = installer.InstallServices(
                save_state=record("save_state"),
                validate_runtime_order=lambda *a, **k: events.append(
                    "order:" + ("current" if "current" in k else "initial")
                ),
                record_runtime_completion=record("record"),
                recover_incomplete_transactions=record("recover"),
                ensure_wine_prefix=record("wine_prefix"),
                discover_setup=lambda source: source / "setup.exe",
                materialize_temporary_payload=record("tmp_payload"),
                materialize_application_payload=record("app_payload"),
                component_label=lambda name, data: name,
                resolve_destination=resolve, safe_child=child,
                preserve_verifier=record("verifier"),
                write_integration_report=lambda target, path: events.append("report") or {
                    "game_executable_candidates": [], "redistributables": [],
                },
                finalize_transactions=record("finalize"), error_type=RuntimeError,
            )
            request = installer.InstallRequest(
                source=root, target=root / "target", scratch=root / "scratch",
                prefix=root / "prefix", manifest_path=root / "m.json",
                manifest={"steps": steps}, components=set(), options=set(),
                state_path=root / "scratch" / "state.json", state={"completed": {}},
                wine="/bin/true", dry_run=dry_run, memory_max=None, quicksfv_x64=None,
            )
            with redirect_stdout(io.StringIO()):
                installer.run_installation(
                    request, handlers={"batch": record("batch"), "copy": record("copy")},
                    verify_source=record("verify_source"), services=services,
                )
            self.assertTrue(request.target.is_dir() and request.scratch.is_dir())
        return events

    def test_real_run_calls_collaborators_in_order(self):
        self.assertEqual(self.run_case([{"id": "b", "type": "batch"}]), [
            "save_state", "order:initial", "recover", "wine_prefix", "tmp_payload",
            "app_payload", "order:current", "batch", "record", "verifier", "report",
            "finalize",
        ])

    def test_wine_prefix_only_for_steps_that_run_programs(self):
        self.assertNotIn("wine_prefix", self.run_case([{"id": "c", "type": "copy"}]))

    def test_dry_run_skips_order_checks_recording_and_finalization(self):
        self.assertEqual(self.run_case([{"id": "b", "type": "batch"}], dry_run=True), [
            "save_state", "recover", "wine_prefix", "tmp_payload", "app_payload",
            "batch", "verifier",
        ])


if __name__ == "__main__":
    unittest.main(verbosity=2)
