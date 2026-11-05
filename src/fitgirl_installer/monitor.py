#!/usr/bin/env python3
"""Monitor actual extraction progress instead of trusting process existence."""

import argparse
from collections import deque
import os
import shutil
import signal
import sys
import textwrap
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fitgirl_installer import translations


def is_codec_process(argv0: str) -> bool:
    name = argv0.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    name = name.removesuffix(".exe")
    return name.startswith("cls-") or name in {
        "unarc-helper", "bzip3", "precomp", "precompx", "x5", "x5n",
        "rz", "rzw", "razor", "xtool", "fgpack", "fsb", "mpz", "x", "x2", "x6",
    }


def proc_stats(archive: Path, prefix: Path | None = None):
    ticks = read_bytes = write_bytes = 0
    rss_kib = pss_kib = 0
    source_pos = -1
    source_positions = {}
    affinity = set()
    matched = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            argv0 = (entry / "cmdline").read_bytes().split(b"\0", 1)[0].decode(errors="replace")
            if not is_codec_process(argv0):
                continue
            if prefix is not None:
                expected = b"WINEPREFIX=" + os.fsencode(prefix)
                if expected not in (entry / "environ").read_bytes().split(b"\0"):
                    continue
            stat = (entry / "stat").read_text().split()
            ticks += int(stat[13]) + int(stat[14])
            status = {}
            for line in (entry / "status").read_text().splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    status[key] = value.strip()
            rss_kib += int(status.get("VmRSS", "0 kB").split()[0])
            affinity.add(status.get("Cpus_allowed_list", "?"))
            try:
                rollup = {
                    key: value.strip()
                    for key, value in (
                        line.split(":", 1) for line in (entry / "smaps_rollup").read_text().splitlines()
                        if ":" in line
                    )
                }
                pss_kib += int(rollup.get("Pss", "0 kB").split()[0])
            except (OSError, ValueError, IndexError):
                pass
            io = {}
            for line in (entry / "io").read_text().splitlines():
                key, value = line.split(":", 1)
                io[key] = int(value.strip())
            read_bytes += io.get("read_bytes", 0)
            write_bytes += io.get("write_bytes", 0)
            process_name = argv0.replace("\\", "/").rsplit("/", 1)[-1]
            matched.append(f"{entry.name}:{stat[2]}:{process_name}")
            process_position = -1
            for fd in (entry / "fd").iterdir():
                try:
                    if Path(os.readlink(fd)).name != archive.name:
                        continue
                    info = (entry / "fdinfo" / fd.name).read_text()
                    pos = next(int(x.split()[1]) for x in info.splitlines() if x.startswith("pos:"))
                    process_position = max(process_position, pos)
                except (OSError, StopIteration, ValueError):
                    pass
            if process_position >= 0:
                source_positions[entry.name] = process_position
                source_pos = max(source_pos, process_position)
        except (OSError, ValueError, IndexError):
            pass
    return (
        ticks, read_bytes, write_bytes, source_pos, matched,
        source_positions, rss_kib, pss_kib, sorted(affinity),
    )


def reread_processes(previous: dict[str, int], current: dict[str, int]) -> list[str]:
    """Report surviving workers that moved backwards in the source archive."""
    return sorted(pid for pid, position in current.items() if pid in previous and position < previous[pid])


def cpu_list_count(value: str) -> int | None:
    try:
        cpus = set()
        for token in value.split(","):
            bounds = token.split("-")
            if len(bounds) not in {1, 2}:
                return None
            first, last = int(bounds[0]), int(bounds[-1])
            if first > last:
                return None
            cpus.update(range(first, last + 1))
        return len(cpus) or None
    except ValueError:
        return None


def tree_size(root: Path):
    total = files = 0
    try:
        for base, _, names in os.walk(root):
            for name in names:
                try:
                    total += os.path.getsize(os.path.join(base, name))
                    files += 1
                except OSError:
                    pass
    except OSError:
        pass
    return total, files


def progress_bar(position: int, total: int, width: int = 30) -> str:
    if position < 0 or total <= 0:
        return f"[{'-' * width}]   ?.?%"
    # The file descriptor can reach EOF before filters flush and FreeArc returns.
    # Reserve 100% for the orchestrator's confirmed successful completion.
    percentage = min(99.9, position / total * 100.0)
    filled = min(width, int(percentage * width / 100))
    return f"[{'#' * filled}{'-' * (width - filled)}] {percentage:5.1f}% aprox."


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    raise AssertionError("unreachable")


def compact_status(
    archive: Path, position: int, total: int, global_progress: float,
    phase: str, eta: str, state: str, output_size: int, files: int,
) -> str:
    progress = progress_bar(position, total, width=8).split("]", 1)[0] + "]"
    if state.startswith("SEM AVANCO"):
        seconds = state.removeprefix("SEM AVANCO ").split("s", 1)[0]
        activity = f"sem avanço {seconds}s"
    else:
        activity = "ativo"
    if "CPU OCUPADA" in state:
        activity = "CPU sem avanço" if state.startswith("SEM AVANCO") else "CPU ocupada"
    if "RELEITURA INTERNA" in state:
        activity += " · releitura"
    line = (
        f"{progress} {global_progress:3.0f}% · {archive.name} · {phase.casefold()} · {activity} · "
        f"ETA {eta} · {human_size(output_size)} · {files} arq"
    )
    width = max(24, shutil.get_terminal_size((80, 24)).columns - 1)
    return textwrap.shorten(line, width=width, placeholder="…")


def archive_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def global_percentage(local_position: int, local_total: int, base: float, weight: float) -> float:
    if local_position < 0 or local_total <= 0:
        return min(99.9, max(0.0, base * 100.0))
    local_fraction = min(0.999, max(0.0, local_position / local_total))
    return min(99.9, max(0.0, (base + weight * local_fraction) * 100.0))


def moving_eta(samples: deque[tuple[float, int]], total: int) -> str:
    if len(samples) < 2 or total <= 0:
        return "?"
    started_at, started_position = samples[0]
    ended_at, ended_position = samples[-1]
    elapsed = ended_at - started_at
    advanced = ended_position - started_position
    if elapsed <= 0 or advanced <= 0 or ended_position >= total:
        return "?"
    seconds = int((total - ended_position) / (advanced / elapsed))
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def calibrated_eta(
    position: int,
    total: int,
    samples: deque[tuple[float, int]],
    workers_active: bool,
) -> tuple[str, str]:
    """Do not turn compressed-input completion into an extraction ETA.

    Solid archives may be fully read well before SREP/XTool finish producing
    output. Once the input is effectively exhausted, no generic remaining-work
    denominator exists, so an honest unknown ETA is more useful than 0 seconds.
    """
    if workers_active and total > 0 and position >= int(total * 0.995):
        return "?", "PÓS-LEITURA"
    return moving_eta(samples, total), "LEITURA"


def effective_position(position: int, samples: deque[tuple[float, int]]) -> int:
    if position >= 0:
        return max(position, samples[-1][1] if samples else 0)
    return samples[-1][1] if samples else -1


def main():
    translations.activate(os.environ.get("FITGIRL_LANGUAGE", "pt"))
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--stop-file", required=True, type=Path)
    parser.add_argument("--interval", type=int, default=20)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--global-base", type=float, default=0.0)
    parser.add_argument("--global-weight", type=float, default=1.0)
    parser.add_argument("--prefix", type=Path)
    args = parser.parse_args()

    stopping = False

    def request_stop(_signal: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    hz = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
    host_cpus = os.cpu_count() or 1
    previous = proc_stats(args.archive, args.prefix)
    previous_size, _ = tree_size(args.target)
    stagnant = 0
    peak_rss_kib = peak_pss_kib = 0
    positions: deque[tuple[float, int]] = deque(maxlen=8)
    while not stopping and not args.stop_file.exists():
        time.sleep(args.interval)
        if stopping or args.stop_file.exists():
            break
        current = proc_stats(args.archive, args.prefix)
        peak_rss_kib = max(peak_rss_kib, current[6])
        peak_pss_kib = max(peak_pss_kib, current[7])
        size, files = tree_size(args.target)
        cpu_one_core = max(0.0, (current[0] - previous[0]) / hz / args.interval * 100)
        allowed_counts = [cpu_list_count(value) for value in current[8]]
        effective_cpus = min((value for value in allowed_counts if value), default=host_cpus)
        cpu_total = cpu_one_core / effective_cpus
        # Processes can exit between samples, reducing the aggregate counters.
        # Treat that as zero delta instead of reporting impossible negative I/O.
        dr = max(0, current[1] - previous[1])
        dw = max(0, current[2] - previous[2])
        ds = size - previous_size
        moved = dr > 0 or dw > 0 or ds > 0 or current[3] != previous[3]
        stagnant = 0 if moved else stagnant + args.interval
        state = "ATIVO" if moved else f"SEM AVANCO {stagnant}s"
        rereads = reread_processes(previous[5], current[5])
        if rereads:
            state += f" | RELEITURA INTERNA pid={','.join(rereads)}"
        if not moved and cpu_one_core >= 10:
            state += " (CPU OCUPADA; progresso não comprovado)"
        total = archive_size(args.archive)
        display_position = effective_position(current[3], positions)
        if current[3] >= 0:
            positions.append((time.monotonic(), display_position))
        eta, phase = calibrated_eta(
            display_position, total, positions, bool(current[4])
        )
        global_progress = global_percentage(
            display_position, total, args.global_base, args.global_weight
        )
        progress = progress_bar(display_position, total)
        source_state = " | ORIGEM INDISPONÍVEL" if total <= 0 else ""
        message = (
            f"[MONITOR] entrada={progress} global={global_progress:5.1f}% "
            f"fase={phase} ETA={eta} {state} "
            f"| CPU 1-core={cpu_one_core:.1f}% total={cpu_total:.1f}% "
            f"| IO read={dr} write={dw} | input-pos={current[3]} "
            f"| RAM rss={current[6] // 1024}MiB pss={current[7] // 1024}MiB "
            f"pico-rss={peak_rss_kib // 1024}MiB pico-pss={peak_pss_kib // 1024}MiB "
            f"cpus={','.join(current[8]) or '?'} "
            f"| output={size} (+{ds}) files={files} | proc={','.join(current[4]) or 'nenhum'}"
            f"{source_state}"
        )
        if sys.stdout.isatty():
            display = compact_status(
                args.archive, display_position, total, global_progress,
                phase, eta, state, size, files,
            )
            print(f"\r\033[2K{display}", end="", flush=True)
        else:
            print(message, flush=True)
        if args.log:
            with args.log.open("a", encoding="utf-8") as log:
                print(message, file=log, flush=True)
        previous, previous_size = current, size
    if sys.stdout.isatty():
        print(flush=True)


if __name__ == "__main__":
    main()
