"""Reusable terminal prompts for the installer CLI."""

from __future__ import annotations

from pathlib import Path

from ..resource_limits import parse_cpu_list


def prompt_yes_no(message: str, default: bool = False) -> bool:
    marker = "S/n" if default else "s/N"
    while True:
        answer = input(f"{message} [{marker}] ").strip().casefold()
        if not answer:
            return default
        if answer in {"s", "sim", "y", "yes"}:
            return True
        if answer in {"n", "não", "nao", "no"}:
            return False
        print("Digite s ou n.")


def prompt_path(message: str, default: Path | None = None) -> Path:
    suffix = f" [{default}]" if default is not None else ""
    while True:
        answer = input(f"{message}{suffix}: ").strip()
        if not answer and default is not None:
            return default.expanduser().resolve()
        if answer:
            return Path(answer).expanduser().resolve()
        print("Informe um caminho.")


def prompt_positive_int(
    message: str, default: int | None = None, *, minimum: int = 1,
    maximum: int | None = None,
) -> int | None:
    suffix = f" [{default}]" if default is not None else " [automático]"
    while True:
        answer = input(f"{message}{suffix}: ").strip()
        if not answer:
            return default
        try:
            value = int(answer)
        except ValueError:
            print("Informe um número inteiro.")
            continue
        if value >= minimum and (maximum is None or value <= maximum):
            return value
        print(f"Use um valor entre {minimum} e {maximum}." if maximum is not None else f"O mínimo é {minimum}.")


def prompt_cpu_list(allowed: tuple[int, ...]) -> str | None:
    example = f"{allowed[0]}-{allowed[-1]}" if len(allowed) > 1 else str(allowed[0])
    while True:
        answer = input(f"CPUs permitidas para todo o trabalho [{example} = todas]: ").strip()
        if not answer:
            return None
        try:
            selected = parse_cpu_list(answer, allowed)
            if selected == set(allowed):
                return None
            return answer
        except ValueError as error:
            print(f"Valor inválido: {error}. Use, por exemplo, 0-3 ou 0,2.")
