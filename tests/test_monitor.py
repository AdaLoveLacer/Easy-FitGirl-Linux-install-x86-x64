import importlib.util
import tempfile
import unittest
from collections import deque
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "src/fitgirl_installer/monitor.py"
SPEC = importlib.util.spec_from_file_location("monitor_extraction", MODULE_PATH)
MONITOR = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MONITOR)


class ProgressBarTests(unittest.TestCase):
    def test_codec_names_include_razor_workers_without_exe(self):
        for name in ("rzw", "rz", "RZW.EXE", "W:\\scratch\\rzw.exe", "/path/CLS-srep_x64.exe", "xtool.exe"):
            with self.subTest(name=name):
                self.assertTrue(MONITOR.is_codec_process(name))
        for name in ("bash", "python3", "start.exe", "not-rzw.exe"):
            with self.subTest(name=name):
                self.assertFalse(MONITOR.is_codec_process(name))

    def test_unknown_progress(self):
        self.assertIn("?.?%", MONITOR.progress_bar(-1, 100))

    def test_half_progress(self):
        self.assertIn("50.0%", MONITOR.progress_bar(50, 100))

    def test_active_monitor_never_claims_one_hundred_percent(self):
        self.assertIn("99.9%", MONITOR.progress_bar(100, 100))
        self.assertNotIn("100.0%", MONITOR.progress_bar(200, 100))

    def test_compact_status_uses_plain_language_and_output_summary(self):
        line = MONITOR.compact_status(
            Path("fg-01.bin"), 50, 100, 49.5, "LEITURA", "2m10s",
            "ATIVO", 1024**3, 80,
        )
        self.assertIn("fg-01.bin", line)
        self.assertIn("leitura", line)
        self.assertIn("ETA 2m10s", line)
        self.assertIn("1.0 GiB", line)
        self.assertIn("80 arq", line)
        self.assertNotIn("CPU 1-core", line)

    def test_disappearing_archive_has_unknown_size_without_traceback(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "disconnected.bin"
            self.assertEqual(MONITOR.archive_size(missing), 0)

    def test_global_progress_is_weighted_and_capped(self):
        self.assertAlmostEqual(MONITOR.global_percentage(50, 100, 0.25, 0.5), 50.0)
        self.assertEqual(MONITOR.global_percentage(100, 100, 0.9, 0.2), 99.9)
        self.assertEqual(MONITOR.global_percentage(-1, 100, 0.25, 0.5), 25.0)

    def test_moving_eta(self):
        samples = deque([(10.0, 100), (20.0, 300)])
        self.assertEqual(MONITOR.moving_eta(samples, 500), "10s")

    def test_post_read_phase_never_claims_zero_eta(self):
        samples = deque([(10.0, 100), (20.0, 999)])
        self.assertEqual(
            MONITOR.calibrated_eta(999, 1000, samples, True),
            ("?", "PÓS-LEITURA"),
        )

    def test_read_phase_keeps_moving_eta(self):
        samples = deque([(10.0, 100), (20.0, 300)])
        self.assertEqual(
            MONITOR.calibrated_eta(300, 500, samples, True),
            ("10s", "LEITURA"),
        )

    def test_last_position_is_retained_after_worker_exits(self):
        samples = deque([(10.0, 300)])
        self.assertEqual(MONITOR.effective_position(-1, samples), 300)

    def test_reread_requires_same_surviving_process_to_move_backwards(self):
        self.assertEqual(MONITOR.reread_processes({"10": 500}, {"10": 200}), ["10"])
        self.assertEqual(MONITOR.reread_processes({"10": 500}, {"11": 200}), [])
        self.assertEqual(MONITOR.reread_processes({"10": 200}, {"10": 500}), [])

    def test_cpu_list_count_handles_ranges_and_sparse_sets(self):
        self.assertEqual(MONITOR.cpu_list_count("0-1"), 2)
        self.assertEqual(MONITOR.cpu_list_count("0-3,8,10-11"), 7)
        self.assertIsNone(MONITOR.cpu_list_count("3-1"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
