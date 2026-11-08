"""Provision the pinned, private codec Wine without touching system Wine."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import platform
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath


class RuntimeErrorDetail(RuntimeError):
    pass


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def ensure_bundled_wine(root: Path) -> Path | None:
    metadata = root / "libexec/wine-runtime.json"
    if not metadata.is_file():
        return None
    config = json.loads(metadata.read_text(encoding="utf-8"))
    if config.get("schema") != 1:
        raise RuntimeErrorDetail("metadados do Wine interno não suportados")
    if platform.system() != "Linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise RuntimeErrorDetail("este Wine interno requer Linux x86-64")
    archive_name = str(config["archive"])
    archive_root = str(config["archive_root"])
    for name in (archive_name, archive_root):
        if not name or name in {".", ".."} or PurePosixPath(name).name != name or "\\" in name:
            raise RuntimeErrorDetail("nome inválido nos metadados do runtime")
    checksum = str(config["archive_sha256"])
    if len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum):
        raise RuntimeErrorDetail("SHA-256 inválido nos metadados do runtime")
    archive = metadata.parent / archive_name
    data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    runtimes = data / "fitgirl-installer/runtimes"
    runtimes.mkdir(parents=True, exist_ok=True)
    destination = runtimes / ("wine-" + checksum[:16])
    executable = destination / "bin/wine"
    marker = destination / ".fitgirl-runtime.json"

    def ready() -> bool:
        try:
            return (
                marker.is_file()
                and json.loads(marker.read_text()).get("archive_sha256") == checksum
                and executable.is_file() and os.access(executable, os.X_OK)
                and digest(executable) == config["executable_sha256"]
            )
        except (OSError, ValueError):
            return False

    with (runtimes / (destination.name + ".lock")).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if ready():
            return executable
        if destination.exists():
            raise RuntimeErrorDetail(
                f"runtime privado incompleto ou alterado em {destination}; "
                "não será sobrescrito automaticamente"
            )
        if not archive.is_file() or digest(archive) != checksum:
            raise RuntimeErrorDetail("arquivo do Wine interno ausente ou com SHA-256 inválido")
        if not hasattr(tarfile, "data_filter"):
            raise RuntimeErrorDetail("a extração segura do Wine interno requer Python com tarfile.data_filter (Python 3.12+)")
        if shutil.disk_usage(runtimes).free < int(config["unpacked_bytes"]) + 64 * 1024**2:
            raise RuntimeErrorDetail("espaço insuficiente para preparar o Wine privado (aproximadamente 850 MiB)")
        print(f"[RUNTIME] preparando Wine privado {config['version']} (primeira execução)", flush=True)
        staging = Path(tempfile.mkdtemp(prefix=".wine-stage-", dir=runtimes))
        try:
            with tarfile.open(archive, "r:xz") as stream:
                members = stream.getmembers()
                for member in members:
                    name = PurePosixPath(member.name)
                    if name.is_absolute() or ".." in name.parts or not name.parts or name.parts[0] != archive_root:
                        raise RuntimeErrorDetail("caminho inesperado no arquivo do Wine")
                stream.extractall(staging, members=members, filter="data")
            extracted = staging / archive_root
            candidate = extracted / "bin/wine"
            if not candidate.is_file() or not os.access(candidate, os.X_OK) or digest(candidate) != config["executable_sha256"]:
                raise RuntimeErrorDetail("Wine extraído não corresponde ao executável validado")
            (extracted / marker.name).write_text(
                json.dumps({"archive_sha256": checksum, "version": config["version"]}) + "\n",
                encoding="utf-8",
            )
            os.replace(extracted, destination)
        finally:
            shutil.rmtree(staging)
        return executable
