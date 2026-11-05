#!/usr/bin/env python3
"""Interactive standalone installer for FitGirl repacks on Linux."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

from .. import i18n
from . import (
    InstallerError,
    ROOT,
    compatibility_error,
    detect_limits,
    install,
    inspect,
    interactive_install,
    parse_cpu_list,
    prompt_path,
    report_json,
    signal_active,
    status,
)


def parser() -> argparse.ArgumentParser:
    main = argparse.ArgumentParser(description=__doc__)
    subparsers = main.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help=i18n.translate("verificar requisitos deste Linux"))
    inspect_parser = subparsers.add_parser("inspect", help=i18n.translate("identificar setup, opções e plano"))
    inspect_parser.add_argument("--source", type=Path, default=Path.cwd())
    inspect_parser.add_argument("--manifest", type=Path)
    inspect_parser.set_defaults(handler=inspect)

    install_parser = subparsers.add_parser("install", help=i18n.translate("executar ou retomar o plano"))
    install_parser.add_argument("--source", type=Path, default=Path.cwd())
    install_parser.add_argument("--target", type=Path, required=True)
    install_parser.add_argument("--scratch", type=Path, required=True)
    install_parser.add_argument("--manifest", type=Path)
    install_parser.add_argument("--wine", type=Path, required=True)
    install_parser.add_argument("--prefix", type=Path, required=True)
    install_parser.add_argument("--backend", type=Path, default=ROOT / "libexec/fitgirl-extract", help=argparse.SUPPRESS)
    install_parser.add_argument("--component", action="append", default=[])
    install_parser.add_argument("--no-component", action="append", default=[])
    install_parser.add_argument("--interactive", action="store_true", help=i18n.translate("perguntar componentes no terminal"))
    install_parser.add_argument("--srep-memory", type=int)
    install_parser.add_argument(
        "--limit-2gb", action="store_true",
        help=i18n.translate("aplicar escritas INI condicionadas ao checkbox original use2gb"),
    )
    install_parser.add_argument("--bzip3-threads", type=int, help=i18n.translate("threads para placeholders fgrplc do BZip3"))
    install_parser.add_argument("--memory-high", type=int, help=i18n.translate("limiar cgroup v2 suave em MiB"))
    install_parser.add_argument("--memory-max", type=int, help=i18n.translate("teto cgroup v2 rígido em MiB (pode causar OOM kill)"))
    install_parser.add_argument("--cpus", help=i18n.translate("lista taskset, por exemplo 0-7 ou 0,2,4,6"))
    install_parser.add_argument("--nice", type=int, choices=range(0, 20), default=0)
    install_parser.add_argument("--monitor-interval", type=int, default=20)
    install_parser.add_argument(
        "--quicksfv-x64", type=Path,
        help="QuickSFV PE32+ x86-64 externo para substituir a edição PE32 do setup",
    )
    install_parser.add_argument("--dry-run", action="store_true")
    install_parser.set_defaults(handler=install)

    for name, handler, help_text in (
        ("status", status, i18n.translate("mostrar o journal")),
        ("pause", lambda args: signal_active(args, signal.SIGSTOP), i18n.translate("pausar o grupo ativo")),
        ("resume", lambda args: signal_active(args, signal.SIGCONT), i18n.translate("retomar o grupo ativo")),
    ):
        action = subparsers.add_parser(name, help=help_text)
        action.add_argument("--scratch", type=Path, required=True)
        action.set_defaults(handler=handler)
    return main


def _run(arguments: list[str]) -> int:
    internal_commands = {"doctor", "inspect", "install", "status", "pause", "resume"}
    if arguments in (["-h"], ["--help"]):
        print("Uso: fitgirl /caminho/do/repack")
        print("\nO menu terminal solicitará destino, componentes e configurações.")
        return 0
    issue = compatibility_error()
    if issue and not (arguments and arguments[0] == "doctor"):
        raise InstallerError(issue)
    if not arguments:
        source = prompt_path("Caminho do repack", Path.cwd())
        return interactive_install(source)
    if arguments[0] not in internal_commands and not arguments[0].startswith("-"):
        if len(arguments) != 1:
            raise InstallerError("use somente: fitgirl /caminho/do/repack")
        return interactive_install(Path(arguments[0]))
    args = parser().parse_args(arguments)
    if args.command == "doctor":
        report = json.loads(report_json())
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report["supported"] else 2
    limits = detect_limits()
    if getattr(args, "srep_memory", None) is not None and not 128 <= args.srep_memory <= limits.memory_budget_mib:
        raise InstallerError(f"--srep-memory deve ficar entre 128 e {limits.memory_budget_mib} MiB nesta máquina")
    if getattr(args, "bzip3_threads", None) is not None and not 1 <= args.bzip3_threads <= len(limits.cpus):
        raise InstallerError(f"--bzip3-threads deve ficar entre 1 e {len(limits.cpus)}")
    if getattr(args, "memory_high", None) is not None and not 512 <= args.memory_high <= limits.memory_budget_mib:
        raise InstallerError(f"--memory-high deve ficar entre 512 e {limits.memory_budget_mib} MiB nesta máquina")
    if getattr(args, "memory_max", None) is not None and not 512 <= args.memory_max <= limits.memory_budget_mib:
        raise InstallerError(f"--memory-max deve ficar entre 512 e {limits.memory_budget_mib} MiB nesta máquina")
    if (getattr(args, "memory_high", None) is not None and
            getattr(args, "memory_max", None) is not None and
            args.memory_high > args.memory_max):
        raise InstallerError("--memory-high não pode exceder --memory-max")
    if getattr(args, "cpus", None):
        try:
            parse_cpu_list(args.cpus, limits.cpus)
        except ValueError as error:
            raise InstallerError(f"--cpus inválido: {error}") from error
    return args.handler(args)


def select_language() -> str:
    configured = os.environ.get("FITGIRL_LANGUAGE", "").strip().lower()
    if configured in {"pt", "pt-br", "portuguese", "português", "portugues"}:
        return "pt"
    if configured in {"en", "english", "inglês", "ingles"}:
        return "en"
    while True:
        print("Idioma / Language")
        print("  1. Português (Brasil)")
        print("  2. English")
        answer = input("Escolha / Choose [1]: ").strip().casefold()
        if answer in {"", "1", "pt", "pt-br", "português", "portugues"}:
            return "pt"
        if answer in {"2", "en", "english", "inglês", "ingles"}:
            return "en"
        print("Opção inválida. Digite 1 para português ou 2 para English.")


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    show_help = any(argument in {"-h", "--help"} for argument in arguments)
    language = select_language() if not show_help else os.environ.get("FITGIRL_LANGUAGE", "pt")
    previous = i18n.activate(language)
    try:
        return _run(arguments)
    except (InstallerError, OSError, subprocess.SubprocessError) as error:
        print(f"[ERRO] {error}", file=sys.stderr)
        return 2
    finally:
        i18n.restore(previous)


if __name__ == "__main__":
    raise SystemExit(main())
