"""Conservative input bounds; codec memory is not a guaranteed global cap."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ResourceLimits:
    cpus: tuple[int, ...]
    total_mib: int
    available_mib: int
    memory_budget_mib: int


def detect_limits() -> ResourceLimits:
    cpus = tuple(sorted(os.sched_getaffinity(0))) if hasattr(os, "sched_getaffinity") else ()
    if not cpus:
        cpus = tuple(range(os.cpu_count() or 1))
    values = {}
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            key, value = line.split(':', 1)
            values[key] = int(value.strip().split()[0]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    total = values.get('MemTotal', 0)
    available = values.get('MemAvailable', total)
    # Respect inherited cgroup hard limits as well as physical memory.
    try:
        row = next(x for x in Path('/proc/self/cgroup').read_text().splitlines() if x.startswith('0::'))
        current = Path('/sys/fs/cgroup') / row[3:].lstrip('/')
        while current.is_relative_to('/sys/fs/cgroup'):
            limit = current / 'memory.max'
            if limit.is_file() and limit.read_text().strip() != 'max':
                maximum = int(limit.read_text().strip()) // 1024**2
                used = int((current / 'memory.current').read_text().strip()) // 1024**2
                total = min(total, maximum)
                available = min(available, max(0, maximum - used))
            if current == Path('/sys/fs/cgroup'):
                break
            current = current.parent
    except (OSError, ValueError, StopIteration):
        pass
    reserve = max(512, total // 10)
    budget = max(0, min(total - reserve, available - reserve))
    return ResourceLimits(cpus, total, available, budget)


def parse_cpu_list(value: str, allowed: tuple[int, ...]) -> set[int]:
    result = set()
    maximum = max(allowed)
    for token in value.split(','):
        parts = token.split('-')
        if not 1 <= len(parts) <= 2 or not all(p.isdecimal() for p in parts):
            raise ValueError('lista de CPUs inválida')
        first, last = int(parts[0]), int(parts[-1])
        if first > last or last > maximum:
            raise ValueError('CPU fora do intervalo disponível')
        result.update(range(first, last + 1))
    if not result or not result.issubset(allowed):
        raise ValueError('CPU não permitida pela afinidade atual')
    return result


def command_prefix(args: Any) -> list[str]:
    """Wrap a codec command with the chosen cgroup memory limits, CPU affinity and nice."""
    command: list[str] = []
    if args.memory_high is not None or args.memory_max is not None:
        command.extend(["systemd-run", "--user", "--scope", "--quiet"])
        if args.memory_high is not None:
            command.extend(["-p", f"MemoryHigh={args.memory_high}M"])
        if args.memory_max is not None:
            command.extend(["-p", f"MemoryMax={args.memory_max}M"])
    if args.cpus:
        command.extend(["taskset", "--cpu-list", args.cpus])
    if args.nice != 0:
        command.extend(["nice", "-n", str(args.nice)])
    return command
