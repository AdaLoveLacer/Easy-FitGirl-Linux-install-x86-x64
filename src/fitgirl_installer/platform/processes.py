"""Child processes of the installer: launch, wait, signals and journaled activity."""

from __future__ import annotations

import contextlib
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from ..models import InstallerError


def run_process(
    command: list[str], cwd: Path, state_path: Path, state: dict[str, Any],
    dry_run: bool, environment: dict[str, str] | None = None,
    success_codes: tuple[int, ...] = (0,), *,
    save_state: Callable[[Path, dict[str, Any]], None],
) -> None:
    """Run a journaled child in its own session and wait for it, forwarding signals."""
    if sys.stdout.isatty():
        print("Executando etapa auxiliar…")
    else:
        print("[EXEC]", shlex.join(command))
    if dry_run:
        return
    with forwarding_signals() as forwarder:
        process = subprocess.Popen(command, cwd=cwd, env=environment, start_new_session=True)
        forwarder.attach(process)
        state["active"] = {"pid": process.pid, "pgid": process.pid, "command": command, "started_at": time.time()}
        save_state(state_path, state)
        returncode = wait_process(process, state_path, state, save_state=save_state)
    if returncode not in success_codes:
        raise InstallerError(f"etapa encerrou com código {returncode}")


class SignalForwarder:
    """Forward SIGINT/SIGTERM to a child's group across its whole journaled life.

    A signal that arrives before the child exists is held and forwarded as
    soon as it starts; one that arrives after the child ended is delivered
    again when the forwarding stops, so an interruption is never lost.
    """

    def __init__(self) -> None:
        self.process: subprocess.Popen[Any] | None = None
        self.pending: list[int] = []
        self.after_exit: list[int] = []

    def __call__(self, requested: int, _frame: Any) -> None:
        if self.process is None:
            self.pending.append(requested)
        elif self.process.poll() is not None:
            self.after_exit.append(requested)
        else:
            self._forward(requested)

    def _forward(self, requested: int) -> None:
        assert self.process is not None
        name = signal.Signals(requested).name
        print(f"[AVISO] {name} recebido; encerrando o grupo ativo {self.process.pid}")
        try:
            os.killpg(self.process.pid, requested)
        except ProcessLookupError:
            pass

    def attach(self, process: subprocess.Popen[Any]) -> None:
        self.process = process
        for requested in self.pending:
            self._forward(requested)
        self.pending.clear()


@contextlib.contextmanager
def forwarding_signals():
    """Install a SignalForwarder before a child starts and keep it until its journal entry is cleared."""
    forwarder = SignalForwarder()
    previous = {
        requested: signal.signal(requested, forwarder)
        for requested in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        yield forwarder
    finally:
        for requested, handler in previous.items():
            signal.signal(requested, handler)
    for requested in forwarder.pending + forwarder.after_exit:
        signal.raise_signal(requested)


def wait_process(
    process: subprocess.Popen[Any], state_path: Path, state: dict[str, Any], *,
    save_state: Callable[[Path, dict[str, Any]], None],
) -> int:
    """Wait for a child, forwarding SIGINT/SIGTERM, then clear it from the journal."""
    previous_handlers: dict[signal.Signals, Any] = {}

    def forward(requested: int, _frame: Any) -> None:
        name = signal.Signals(requested).name
        print(f"[AVISO] {name} recebido; encerrando o grupo ativo {process.pid}")
        try:
            os.killpg(process.pid, requested)
        except ProcessLookupError:
            pass

    for requested in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[requested] = signal.signal(requested, forward)
    try:
        return process.wait()
    finally:
        for requested, previous in previous_handlers.items():
            signal.signal(requested, previous)
        state["active"] = None
        save_state(state_path, state)


def signal_active_group(state: dict[str, Any], requested_signal: signal.Signals) -> None:
    """Send a signal to the process group the journal records as active."""
    active = state.get("active")
    if not active:
        raise InstallerError("não há etapa ativa registrada")
    try:
        os.killpg(int(active["pgid"]), requested_signal)
    except ProcessLookupError as error:
        raise InstallerError("o grupo de processos registrado não existe mais") from error
    print(f"[INFO] sinal {requested_signal.name} enviado ao grupo {active['pgid']}")
