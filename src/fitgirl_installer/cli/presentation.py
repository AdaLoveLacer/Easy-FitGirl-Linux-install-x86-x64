"""Terminal presentation helpers for the installer CLI."""

from __future__ import annotations

import sys
from typing import Any

from .. import i18n


def _wizard_page(step: int, title: str, details: list[str] | None = None) -> None:
    """Keep the first-run menu focused, clearing only an interactive terminal."""
    if sys.stdout.isatty():
        sys.stdout.write("\033[2J\033[H")
    print("FITGIRL INSTALLER")
    print(f"Etapa {step} de 4  |  {title}")
    print("─" * 40)
    for detail in details or []:
        print(detail)
    if details:
        print()


def _component_label(name: str, data: dict[str, Any]) -> str:
    key = name.casefold()
    if key == "text":
        return "Arquivos principais"
    if key == "vid4k":
        return "Vídeos em 4K"
    if key.startswith("local\\"):
        language = key.rsplit("\\", 1)[-1]
        return {
            "eng": "Inglês", "rus": "Russo", "esp": "Espanhol",
            "ger": "Alemão", "fra": "Francês", "ita": "Italiano",
            "jap": "Japonês",
        }.get(language, str(data.get("description", name)))
    if key == "directx":
        return "DirectX"
    if key.startswith("vc_"):
        return str(data.get("description", name)).split(" (recognized", 1)[0].replace("Visual C++", "Microsoft Visual C++")
    return str(data.get("description", name))


def format_size(size: int) -> str:
    value = float(size)
    decimal_separator = "." if i18n.LANGUAGE == "en" else ","
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.2f} {unit}".replace(".", decimal_separator)
        value /= 1024
    raise AssertionError("unreachable")
