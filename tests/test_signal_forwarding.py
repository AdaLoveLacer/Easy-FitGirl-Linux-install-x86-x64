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
from fitgirl_installer.models import InstallerError  # noqa: E402
from fitgirl_installer.platform import processes  # noqa: E402


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


class ProcessControlTests(unittest.TestCase):
    def test_run_process_journals_the_child_and_checks_its_exit_code(self):
        saved = []
        state = {}
        save = lambda path, value: saved.append(dict(value))  # noqa: E731
        with redirect_stdout(io.StringIO()):
            processes.run_process(
                [sys.executable, "-c", "raise SystemExit(3)"], Path.cwd(), Path("state.json"),
                state, False, success_codes=(3,), save_state=save,
            )
            with self.assertRaisesRegex(InstallerError, "etapa encerrou com código 3"):
                processes.run_process(
                    [sys.executable, "-c", "raise SystemExit(3)"], Path.cwd(), Path("state.json"),
                    state, False, save_state=save,
                )
        self.assertIsNotNone(saved[0]["active"])
        self.assertIsNone(saved[1]["active"])
        self.assertIsNone(state["active"])

    def test_signal_active_group_requires_a_live_journaled_group(self):
        with self.assertRaisesRegex(InstallerError, "não há etapa ativa registrada"):
            processes.signal_active_group({"active": None}, signal.SIGSTOP)
        process = sleeper()
        try:
            output = io.StringIO()
            with redirect_stdout(output):
                processes.signal_active_group({"active": {"pgid": process.pid}}, signal.SIGCONT)
            self.assertIn(f"sinal SIGCONT enviado ao grupo {process.pid}", output.getvalue())
        finally:
            process.kill()
            process.wait()
        with self.assertRaisesRegex(InstallerError, "não existe mais"):
            processes.signal_active_group({"active": {"pgid": process.pid}}, signal.SIGCONT)


if __name__ == "__main__":
    unittest.main()
