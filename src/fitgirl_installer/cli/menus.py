"""Reusable terminal prompts for the installer CLI."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..platform.resources import parse_cpu_list
from .presentation import _component_label, _wizard_page


@dataclass(frozen=True)
class DestinationMenuServices:
    roots: tuple[Path, ...]
    storage_label: Callable[[Path], str]
    is_writable: Callable[[Path], bool]
    validation_message: Callable[[Path], str | None]


def prompt_components(
    manifest: dict[str, Any], source: Path, *, wizard: bool = False,
) -> tuple[list[str], list[str]]:
    requested: list[str] = []
    disabled: list[str] = []
    if wizard:
        _wizard_page(2, "Conteúdo", ["Escolha os idiomas e opcionais. Enter mantém o padrão."])
    else:
        print("Conteúdo e opcionais:")
    skipped_redists = []
    for name, data in manifest.get("components", {}).items():
        if name.casefold() == "directx" or name.casefold().startswith("vc_"):
            skipped_redists.append(_component_label(name, data))
            disabled.append(name)
            continue
        availability = data.get("available_if")
        if availability and not (source / availability).is_file():
            print(f"  {_component_label(name, data)}: indisponível (arquivo ausente)")
            disabled.append(name)
            continue
        if data.get("required"):
            print(f"  {_component_label(name, data)} — obrigatório")
            requested.append(name)
            continue
        default = bool(data.get("default", False))
        marker = "S/n" if default else "s/N"
        label = _component_label(name, data)
        while True:
            answer = input(f"  Incluir {label}? [{marker}] ").strip().lower()
            if not answer:
                answer = "s" if default else "n"
            if answer in {"s", "sim", "y", "yes"}:
                requested.append(name)
                break
            if answer in {"n", "não", "nao", "no"}:
                disabled.append(name)
                break
            print("  Digite s ou n.")
    if skipped_redists:
        print("  Redistribuíveis mantidos sem executar: " + ", ".join(skipped_redists))
    return requested, disabled


def prompt_destination(
    game_name: str, *, services: DestinationMenuServices,
    wizard: bool = False, details: list[str] | None = None,
) -> Path:
    roots = services.roots
    if wizard:
        _wizard_page(1, "Destino", details or ["Escolha onde instalar. A pasta será criada após a confirmação."])
    if roots:
        if not wizard:
            print("\nOnde instalar? (fora do prefixo Wine)")
        for index, root in enumerate(roots, 1):
            probe = root
            while not probe.exists() and probe != probe.parent:
                probe = probe.parent
            try:
                free_gib = shutil.disk_usage(probe).free / (1024 ** 3)
                free_text = f" ({free_gib:.1f} GiB livres)"
            except OSError:
                free_text = ""
            storage = services.storage_label(root).replace(", ", " · ")
            warning = " · sem permissão" if not services.is_writable(root) else ""
            print(f"  {index}. {root / game_name}{free_text} · {storage}{warning}")
        print(f"  {len(roots) + 1}. Escolher outro caminho")
        while True:
            answer = input("Destino (número ou caminho) [1]: ").strip()
            if not answer:
                target = (roots[0] / game_name).resolve()
            elif answer.isdigit() and 1 <= int(answer) <= len(roots):
                target = (roots[int(answer) - 1] / game_name).resolve()
            elif answer == str(len(roots) + 1):
                target = prompt_path("Caminho completo da pasta do jogo")
            elif answer.isdigit():
                print("Opção inválida.")
                continue
            else:
                target = Path(answer).expanduser().resolve()
            message = services.validation_message(target)
            if message is not None:
                print(f"Destino indisponível: {message}")
                continue
            return target
    return prompt_path("Caminho completo da pasta do jogo")


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
