#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fitgirl_installer.platform import resources  # noqa: E402


def limits(**values):
    base = {"memory_high": None, "memory_max": None, "cpus": None, "nice": 0}
    base.update(values)
    return SimpleNamespace(**base)


class CommandPrefixTests(unittest.TestCase):
    def test_automatic_resources_add_nothing(self):
        self.assertEqual(resources.command_prefix(limits()), [])

    def test_all_limits_wrap_in_cgroup_then_affinity_then_nice(self):
        self.assertEqual(
            resources.command_prefix(limits(memory_high=600, memory_max=700, cpus="0-1", nice=5)),
            [
                "systemd-run", "--user", "--scope", "--quiet",
                "-p", "MemoryHigh=600M", "-p", "MemoryMax=700M",
                "taskset", "--cpu-list", "0-1", "nice", "-n", "5",
            ],
        )

    def test_only_hard_memory_cap_still_uses_a_scope(self):
        self.assertEqual(
            resources.command_prefix(limits(memory_max=768)),
            ["systemd-run", "--user", "--scope", "--quiet", "-p", "MemoryMax=768M"],
        )


if __name__ == "__main__":
    unittest.main()
