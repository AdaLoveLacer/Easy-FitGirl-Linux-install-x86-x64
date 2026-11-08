#!/usr/bin/env python3

import io
import os
import signal
import subprocess
import sys
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fitgirl_installer import cli as CLI  # noqa: E402


def sleeper() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True,
    )


class SignalForwardingTests(unittest.TestCase):
    """A signal around a journaled child must reach its group and never be lost."""

    def setUp(self):
        self.previous = signal.getsignal(signal.SIGINT)

    def tearDown(self):
        self.assertIs(signal.getsignal(signal.SIGINT), self.previous)

    def test_signal_before_the_child_starts_is_forwarded_once_it_exists(self):
        output = io.StringIO()
        with redirect_stdout(output), CLI.forwarding_signals() as forwarder:
            signal.raise_signal(signal.SIGINT)
            process = sleeper()
            forwarder.attach(process)
            self.assertEqual(process.wait(timeout=10), -signal.SIGINT)
        self.assertIn(f"SIGINT recebido; encerrando o grupo ativo {process.pid}", output.getvalue())

    def test_signal_between_journal_and_wait_reaches_the_group(self):
        output = io.StringIO()
        with redirect_stdout(output), CLI.forwarding_signals() as forwarder:
            process = sleeper()
            forwarder.attach(process)
            signal.raise_signal(signal.SIGINT)
            self.assertEqual(process.wait(timeout=10), -signal.SIGINT)
        with self.assertRaises(ProcessLookupError):
            os.killpg(process.pid, 0)

    def test_signal_after_the_child_ended_is_delivered_when_forwarding_stops(self):
        reached_end_of_block = False
        with self.assertRaises(KeyboardInterrupt):
            with CLI.forwarding_signals() as forwarder:
                process = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
                forwarder.attach(process)
                process.wait(timeout=10)
                signal.raise_signal(signal.SIGINT)
                time.sleep(0.01)
                reached_end_of_block = True
        self.assertTrue(reached_end_of_block)


if __name__ == "__main__":
    unittest.main()
