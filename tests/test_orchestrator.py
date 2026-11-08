#!/usr/bin/env python3

import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "fitgirl"
sys.path.insert(0, str(ROOT / "src"))

from fitgirl_installer.platform.resources import detect_limits


def digest(path: Path, algorithm: str) -> str:
    value = hashlib.new(algorithm)
    value.update(path.read_bytes())
    return value.hexdigest()


class OrchestratorIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="fitgirl-test-")
        self.root = Path(self.temporary.name)
        self.source = self.root / "repack"
        self.source.mkdir()
        (self.source / "setup.exe").write_bytes(b"fake-inno-setup")
        for name in ("a.bin", "b.bin", "optional.bin"):
            (self.source / name).write_bytes((name + "-payload").encode())
        self.calls = self.root / "calls.jsonl"
        self.failure_marker = self.root / "failed-once"
        self.backend = self.root / "fake-backend.py"
        self.backend.write_text(textwrap.dedent("""\
            #!/usr/bin/env python3
            import errno, json, os, sys, time
            from pathlib import Path

            archive_option = '--archive' if '--archive' in sys.argv else '--archive-path'
            archive = Path(sys.argv[sys.argv.index(archive_option) + 1]).name
            record = {
                'archive': archive,
                'argv': sys.argv[1:],
                'affinity': sorted(os.sched_getaffinity(0)),
                'nice': os.getpriority(os.PRIO_PROCESS, 0),
            }
            with Path(os.environ['FAKE_CALLS']).open('a') as handle:
                print(json.dumps(record), file=handle)
            if archive == os.environ.get('FAKE_SLEEP_ARCHIVE'):
                time.sleep(float(os.environ.get('FAKE_SLEEP_SECONDS', '60')))
            if archive == os.environ.get('FAKE_ENOSPC_ARCHIVE'):
                raise OSError(errno.ENOSPC, 'No space left on device')
            marker = Path(os.environ['FAKE_FAILURE_MARKER'])
            if archive == 'b.bin' and not marker.exists():
                marker.touch()
                raise SystemExit(9)
        """), encoding="utf-8")
        self.backend.chmod(0o755)
        self.manifest = self.root / "manifest.json"
        self.manifest.write_text(json.dumps({
            "schema": 1,
            "name": "Synthetic repack",
            "setup_sha256": [digest(self.source / "setup.exe", "sha256")],
            "components": {
                "core": {"description": "Core", "default": True, "required": True},
                "optional": {
                    "description": "Optional payload", "default": False,
                    "available_if": "optional.bin"
                }
            },
            "steps": [
                {"id": "a", "type": "extract", "description": "A", "archive": "a.bin", "md5": digest(self.source / "a.bin", "md5"), "destination": "app"},
                {"id": "b", "type": "extract", "description": "B", "archive": "b.bin", "md5": digest(self.source / "b.bin", "md5"), "destination": "app"},
                {"id": "optional", "type": "extract", "description": "Optional", "archive": "optional.bin", "md5": digest(self.source / "optional.bin", "md5"), "destination": "app", "if_component": "optional"}
            ]
        }), encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def environment(self):
        return {
            **os.environ,
            "FAKE_CALLS": str(self.calls),
            "FAKE_FAILURE_MARKER": str(self.failure_marker),
        }

    def installer_command(self, scratch: Path, *extra: str):
        return [
            str(INSTALLER), "install",
            "--source", str(self.source),
            "--target", str(self.root / "target"),
            "--scratch", str(scratch),
            "--manifest", str(self.manifest),
            "--wine", "/bin/true",
            "--prefix", str(self.root / "prefix"),
            "--backend", str(self.backend),
            *extra,
        ]

    def run_installer(self, scratch: Path, *extra: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self.installer_command(scratch, *extra), text=True, input=input_text,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=self.environment(),
        )

    def calls_read(self):
        if not self.calls.exists():
            return []
        return [json.loads(line) for line in self.calls.read_text().splitlines()]

    def test_failure_resume_and_source_corruption_detection(self):
        scratch = self.root / "resume-work"
        first = self.run_installer(scratch)
        self.assertEqual(first.returncode, 2, first.stdout)
        state = json.loads((scratch / "install-state.json").read_text())
        self.assertEqual(set(state["completed"]), {"001:a"})
        self.assertIsNone(state["active"])
        self.assertEqual([call["archive"] for call in self.calls_read()], ["a.bin", "b.bin"])

        second = self.run_installer(scratch)
        self.assertEqual(second.returncode, 0, second.stdout)
        self.assertEqual([call["archive"] for call in self.calls_read()], ["a.bin", "b.bin", "b.bin"])
        state = json.loads((scratch / "install-state.json").read_text())
        self.assertEqual(set(state["completed"]), {"001:a", "002:b"})

        (self.source / "a.bin").write_bytes(b"corrupted")
        corrupted = self.run_installer(scratch)
        self.assertEqual(corrupted.returncode, 2, corrupted.stdout)
        self.assertIn("MD5 inválido", corrupted.stdout)

    def test_component_selection_cpu_affinity_nice_and_memory_forwarding(self):
        self.failure_marker.touch()
        manifest = json.loads(self.manifest.read_text())
        manifest["steps"][0]["destination_suffix"] = "Tools"
        manifest["steps"][0]["filters"] = ["eng"]
        self.manifest.write_text(json.dumps(manifest))
        allowed_cpu = min(os.sched_getaffinity(0))
        parent_nice = os.getpriority(os.PRIO_PROCESS, 0)
        result = self.run_installer(
            self.root / "options-work",
            "--component", "optional",
            "--cpus", str(allowed_cpu),
            "--nice", "5",
            "--srep-memory", "1234",
            "--bzip3-threads", "4",
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        calls = self.calls_read()
        self.assertEqual([call["archive"] for call in calls], ["a.bin", "b.bin", "optional.bin"])
        for call in calls:
            self.assertNotIn("--payload-ready", call["argv"])
            self.assertEqual(call["affinity"], [allowed_cpu])
            self.assertEqual(call["nice"], min(19, parent_nice + 5))
            self.assertIn("--srep-memory", call["argv"])
            self.assertEqual(call["argv"][call["argv"].index("--srep-memory") + 1], "1234")
            self.assertIn("--bzip3-threads", call["argv"])
            self.assertEqual(call["argv"][call["argv"].index("--bzip3-threads") + 1], "4")
            self.assertIn("--global-base", call["argv"])
            self.assertIn("--global-weight", call["argv"])
        self.assertIn("--include", calls[0]["argv"])
        self.assertEqual(calls[0]["argv"][calls[0]["argv"].index("--include") + 1], "eng")
        target_index = calls[0]["argv"].index("-t") + 1
        self.assertEqual(Path(calls[0]["argv"][target_index]).name, "Tools")
        self.assertIn("[GLOBAL] 100.0% confirmado", result.stdout)

    def test_backend_payload_ready_uses_isolated_runtime_copy(self):
        backend_root = self.root / "backend-root"
        libexec = backend_root / "libexec"
        libexec.mkdir(parents=True)
        backend = libexec / "fitgirl-extract"
        backend.write_bytes((ROOT / "libexec/fitgirl-extract").read_bytes())
        backend.chmod(0o755)
        for name in ("unarc", "unarc-helper.exe"):
            helper = libexec / name
            helper.write_text("#!/bin/sh\nexit 0\n")
            helper.chmod(0o755)

        wine_dir = self.root / "fake-wine"
        wine_dir.mkdir()
        wine = wine_dir / "wine"
        wine.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$WINEPREFIX/arguments\"\necho '[FreeArc] final rc=0'\n")
        wine.chmod(0o755)
        winepath = wine_dir / "winepath"
        winepath.write_text("#!/bin/sh\necho 'Z:\\\\runtime'\n")
        winepath.chmod(0o755)

        source = self.root / "backend-source"
        source.mkdir()
        (source / "setup.exe").write_bytes(b"setup")
        (source / "fg-01.bin").write_bytes(b"archive")
        scratch = self.root / "backend-scratch"
        payload = scratch / "setup-payload" / "tmp"
        payload.mkdir(parents=True)
        (payload / "unarc.dll").write_bytes(b"dll")
        (payload / "arc.ini").write_text("threads=fgrplc\n")
        (payload / "CLS.ini").write_text("[Srep]\nMemory=4096m\n")
        prefix = self.root / "backend-prefix"
        (prefix / "dosdevices").mkdir(parents=True)
        (prefix / "system.reg").write_text("ready")
        reserved = self.root / "reserved-drive"
        reserved.mkdir()
        (prefix / "dosdevices/r:").symlink_to(reserved)
        before = {
            path.name: digest(path, "sha256")
            for path in (payload / "arc.ini", payload / "CLS.ini")
        }

        result = subprocess.run([
            str(backend), "-d", str(source), "-t", str(self.root / "backend-target"),
            "-w", str(scratch), "--archive", "fg-01.bin", "--payload-ready",
            "--list-only", "--wine", str(wine), "--prefix", str(prefix),
            "--bzip3-threads", "3", "--srep-memory", "1024",
            "--archive-path-filter", "work",
        ], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("cópia runtime", result.stdout)
        self.assertEqual(
            before,
            {
                path.name: digest(path, "sha256")
                for path in (payload / "arc.ini", payload / "CLS.ini")
            },
        )
        self.assertFalse(list(scratch.glob(".payload-runtime.*")))
        self.assertIn("threads=3", (scratch / "arc.ini").read_text())
        self.assertIn("-apwork", (prefix / "arguments").read_text().splitlines())
        self.assertIn("-wS:\\", (prefix / "arguments").read_text().splitlines())
        self.assertEqual((prefix / "dosdevices/r:").resolve(), reserved)
        self.assertEqual((prefix / "dosdevices/s:").resolve(), scratch)

    def test_archive_path_filter_is_forwarded_by_plan(self):
        self.failure_marker.touch()
        manifest = json.loads(self.manifest.read_text())
        manifest["steps"][0]["archive_path_filter"] = "work"
        self.manifest.write_text(json.dumps(manifest))
        result = self.run_installer(self.root / "filter-work")
        self.assertEqual(result.returncode, 0, result.stdout)
        call = self.calls_read()[0]
        self.assertIn("--archive-path-filter", call["argv"])
        self.assertEqual(
            call["argv"][call["argv"].index("--archive-path-filter") + 1], "work"
        )

    def test_interactive_component_selection(self):
        self.failure_marker.touch()
        result = self.run_installer(self.root / "interactive-work", "--interactive", input_text="s\n")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Incluir Optional payload", result.stdout)
        self.assertEqual(
            [call["archive"] for call in self.calls_read()],
            ["a.bin", "b.bin", "optional.bin"],
        )

    def test_public_entrypoint_needs_only_repack_path(self):
        self.failure_marker.touch()
        environment = self.environment()
        environment.update({
            "FITGIRL_MANIFEST": str(self.manifest),
            "FITGIRL_WINE_BIN": "/bin/true",
            "FITGIRL_GAMES_DIR": str(self.root / "games"),
            "FITGIRL_BACKEND": str(self.backend),
        })
        result = subprocess.run(
            [str(INSTALLER), str(self.source)],
            text=True,
            input="\nn\nn\n\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=environment,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("FITGIRL INSTALLER", result.stdout)
        self.assertIn("Arquivos compactados:", result.stdout)
        self.assertIn("Espaço declarado pelo instalador: não informado", result.stdout)
        self.assertIn("Dados selecionados:", result.stdout)
        self.assertIn("Revisar e iniciar", result.stdout)
        self.assertNotIn("Wine [", result.stdout)
        self.assertIn("Automático (recomendado)", result.stdout)
        self.assertEqual(
            [call["archive"] for call in self.calls_read()],
            ["a.bin", "b.bin"],
        )

    def test_unless_component_skips_fallback_when_optional_is_selected(self):
        self.failure_marker.touch()
        manifest = json.loads(self.manifest.read_text())
        manifest["steps"].append({
            "id": "fallback", "type": "extract", "description": "Fallback",
            "archive": "a.bin", "md5": digest(self.source / "a.bin", "md5"),
            "destination": "app", "unless_component": "optional",
        })
        self.manifest.write_text(json.dumps(manifest))
        result = self.run_installer(
            self.root / "unless-work", "--component", "optional"
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("[PULA] 004:fallback", result.stdout)
        self.assertEqual(
            [call["archive"] for call in self.calls_read()],
            ["a.bin", "b.bin", "optional.bin"],
        )

    def test_exec_step_is_reviewable_in_dry_run(self):
        manifest = json.loads(self.manifest.read_text())
        manifest["steps"] = [{
            "id": "postprocess", "type": "exec", "description": "Postprocess",
            "executable_root": "tmp", "executable": "x5.exe", "cwd": "app",
            "args": ["-s-1g", "000.fgpack", "eng.fgpack.x5", "eng.fgpack"],
            "delete_after": ["eng.fgpack.x5"],
        }]
        self.manifest.write_text(json.dumps(manifest))
        result = self.run_installer(self.root / "exec-work", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("x5.exe", result.stdout)
        self.assertIn("eng.fgpack.x5", result.stdout)

    def test_cgroup_limits_are_explicit_in_dry_run(self):
        limits = detect_limits()
        if limits.memory_budget_mib < 512:
            self.skipTest("host memory budget is below the minimum supported cgroup limit")
        memory_max = max(512, min(1024, limits.memory_budget_mib - 256))
        memory_high = max(512, min(1024, memory_max))
        result = self.run_installer(
            self.root / "cgroup-work", "--dry-run",
            "--memory-high", str(memory_high), "--memory-max", str(memory_max),
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(f"MemoryHigh={memory_high}M", result.stdout)
        self.assertIn(f"MemoryMax={memory_max}M", result.stdout)
        self.assertIn("teto rígido", result.stdout)

    def test_verify_step_dry_run_does_not_require_extracted_manifest(self):
        manifest = json.loads(self.manifest.read_text())
        manifest["steps"] = [{
            "id": "verify", "type": "verify", "description": "Verify",
            "manifest_root": "payload_app", "manifest": "_Redist/fitgirl.md5",
            "root": "app",
        }]
        self.manifest.write_text(json.dumps(manifest))
        result = self.run_installer(self.root / "verify-dry-work", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("fitgirl_installer/verify.py", result.stdout)
        self.assertIn("_Redist/fitgirl.md5", result.stdout)

    def test_generated_archive_is_forwarded_and_deleted_after_success(self):
        self.failure_marker.touch()
        target = self.root / "target"
        target.mkdir()
        generated = target / "eng.fgpack"
        generated.write_bytes(b"generated-archive")
        manifest = json.loads(self.manifest.read_text())
        manifest["steps"] = [{
            "id": "generated", "type": "extract", "description": "Generated",
            "archive_root": "app", "archive": "eng.fgpack", "destination": "app",
            "delete_archive_after": True,
        }]
        self.manifest.write_text(json.dumps(manifest))
        result = self.run_installer(self.root / "generated-work")
        self.assertEqual(result.returncode, 0, result.stdout)
        call = self.calls_read()[0]
        self.assertIn("--archive-path", call["argv"])
        self.assertFalse(generated.exists())

    def test_copy_step_uses_confined_logical_roots(self):
        self.failure_marker.touch()
        scratch = self.root / "copy-work"
        source = scratch / "stage" / "eng" / "steam_api.ini"
        source.parent.mkdir(parents=True)
        source.write_text("Language=english\n")
        manifest = json.loads(self.manifest.read_text())
        manifest["steps"] = [{
            "id": "copy-language", "type": "copy", "description": "Copy",
            "source_root": "scratch", "source": "stage/eng/steam_api.ini",
            "destination_root": "app", "destination": "Tools/steam_api.ini",
        }]
        self.manifest.write_text(json.dumps(manifest))
        result = self.run_installer(scratch)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual((self.root / "target/Tools/steam_api.ini").read_text(), "Language=english\n")

    def test_original_verifier_is_preserved_and_restored(self):
        self.failure_marker.touch()
        scratch = self.root / "verifier-work"
        embedded = scratch / "setup-payload/app/_Redist"
        embedded.mkdir(parents=True)
        (embedded / "QuickSFV.EXE").write_bytes(b"quicksfv")
        (embedded / "QuickSFV.ini").write_text("[settings]\n")
        (embedded / "fitgirl.md5").write_text("manifest\n")
        (embedded / "eng.addon").write_text("addon\n")

        first = self.run_installer(scratch)
        self.assertEqual(first.returncode, 0, first.stdout)
        redist = self.root / "target/_Redist"
        self.assertEqual((redist / "QuickSFV.EXE").read_bytes(), b"quicksfv")
        self.assertEqual((redist / "fitgirl.md5").read_text(), "manifest\n")
        self.assertEqual((redist / "eng.addon").read_text(), "addon\n")

        (redist / "QuickSFV.EXE").unlink()
        resumed = self.run_installer(scratch)
        self.assertEqual(resumed.returncode, 0, resumed.stdout)
        self.assertEqual((redist / "QuickSFV.EXE").read_bytes(), b"quicksfv")

    def test_preserve_verifier_does_not_downgrade_quicksfv_x64(self):
        def fake_pe(machine: int) -> bytes:
            data = bytearray(0x88)
            data[:2] = b"MZ"
            data[0x3C:0x40] = (0x80).to_bytes(4, "little")
            data[0x80:0x84] = b"PE\0\0"
            data[0x84:0x86] = machine.to_bytes(2, "little")
            return bytes(data)

        self.failure_marker.touch()
        target = self.root / "target"
        scratch = self.root / "verifier-x64-work"
        embedded = scratch / "setup-payload/app/_Redist"
        embedded.mkdir(parents=True)
        (embedded / "QuickSFV.EXE").write_bytes(fake_pe(0x014C))
        redist = target / "_Redist"
        redist.mkdir(parents=True)
        x64 = fake_pe(0x8664)
        (redist / "QuickSFV.EXE").write_bytes(x64)

        result = self.run_installer(scratch)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual((redist / "QuickSFV.EXE").read_bytes(), x64)

    def test_external_quicksfv_x64_is_installed_and_x86_is_rejected(self):
        def fake_pe(machine: int) -> bytes:
            data = bytearray(0x88)
            data[:2] = b"MZ"
            data[0x3C:0x40] = (0x80).to_bytes(4, "little")
            data[0x80:0x84] = b"PE\0\0"
            data[0x84:0x86] = machine.to_bytes(2, "little")
            return bytes(data)

        self.failure_marker.touch()
        scratch = self.root / "verifier-override-work"
        embedded = scratch / "setup-payload/app/_Redist"
        embedded.mkdir(parents=True)
        (embedded / "QuickSFV.EXE").write_bytes(fake_pe(0x014C))
        external = self.root / "QuickSFV-x64.exe"
        x64 = fake_pe(0x8664)
        external.write_bytes(x64)

        simulated = self.run_installer(
            scratch, "--quicksfv-x64", str(external), "--dry-run",
        )
        self.assertEqual(simulated.returncode, 0, simulated.stdout)
        self.assertIn(str(external), simulated.stdout)
        self.assertFalse((self.root / "target/_Redist/QuickSFV.EXE").exists())

        installed = self.run_installer(scratch, "--quicksfv-x64", str(external))
        self.assertEqual(installed.returncode, 0, installed.stdout)
        self.assertEqual((self.root / "target/_Redist/QuickSFV.EXE").read_bytes(), x64)

        x86 = self.root / "QuickSFV-x86.exe"
        x86.write_bytes(fake_pe(0x014C))
        rejected = self.run_installer(scratch, "--quicksfv-x64", str(x86))
        self.assertEqual(rejected.returncode, 2, rejected.stdout)
        self.assertIn("não é PE32+ x86-64", rejected.stdout)

    def test_sigkill_leaves_recoverable_journal_and_blocks_concurrent_run(self):
        self.failure_marker.touch()
        scratch = self.root / "crash-work"
        environment = self.environment()
        environment.update({"FAKE_SLEEP_ARCHIVE": "a.bin", "FAKE_SLEEP_SECONDS": "60"})
        orchestrator = subprocess.Popen(
            self.installer_command(scratch), env=environment,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        state_path = scratch / "install-state.json"
        state = None
        for _ in range(100):
            if state_path.exists():
                state = json.loads(state_path.read_text())
                if state.get("active"):
                    break
            time.sleep(0.02)
        self.assertIsNotNone(state)
        self.assertTrue(state["active"])
        active_pgid = int(state["active"]["pgid"])

        os.kill(orchestrator.pid, signal.SIGKILL)
        orchestrator.wait(timeout=5)
        blocked = self.run_installer(scratch)
        self.assertEqual(blocked.returncode, 2, blocked.stdout)
        self.assertIn("a etapa anterior ainda está ativa", blocked.stdout)

        os.killpg(active_pgid, signal.SIGKILL)
        for _ in range(100):
            try:
                os.killpg(active_pgid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.02)
        recovered = self.run_installer(scratch)
        self.assertEqual(recovered.returncode, 0, recovered.stdout)
        self.assertEqual([call["archive"] for call in self.calls_read()], ["a.bin", "a.bin", "b.bin"])

    def test_sigterm_is_forwarded_and_immediate_resume_is_safe(self):
        self.failure_marker.touch()
        scratch = self.root / "sigterm-work"
        environment = self.environment()
        environment.update({"FAKE_SLEEP_ARCHIVE": "a.bin", "FAKE_SLEEP_SECONDS": "60"})
        orchestrator = subprocess.Popen(
            self.installer_command(scratch), env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        state_path = scratch / "install-state.json"
        active_pgid = None
        for _ in range(200):
            if state_path.exists():
                state = json.loads(state_path.read_text())
                if state.get("active"):
                    active_pgid = int(state["active"]["pgid"])
                    break
            time.sleep(0.02)
        self.assertIsNotNone(active_pgid)

        os.kill(orchestrator.pid, signal.SIGTERM)
        output = orchestrator.communicate(timeout=10)[0]
        self.assertEqual(orchestrator.returncode, 2, output)
        self.assertIn("SIGTERM recebido", output)
        state = json.loads(state_path.read_text())
        self.assertIsNone(state["active"])
        with self.assertRaises(ProcessLookupError):
            os.killpg(active_pgid, 0)

        resumed = self.run_installer(scratch)
        self.assertEqual(resumed.returncode, 0, resumed.stdout)

    def test_sigint_is_forwarded_and_immediate_resume_is_safe(self):
        self.failure_marker.touch()
        scratch = self.root / "sigint-work"
        environment = self.environment()
        environment.update({"FAKE_SLEEP_ARCHIVE": "a.bin", "FAKE_SLEEP_SECONDS": "60"})
        orchestrator = subprocess.Popen(
            self.installer_command(scratch), env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        state_path = scratch / "install-state.json"
        active_pgid = None
        for _ in range(200):
            if state_path.exists():
                state = json.loads(state_path.read_text())
                if state.get("active"):
                    active_pgid = int(state["active"]["pgid"])
                    break
            time.sleep(0.02)
        self.assertIsNotNone(active_pgid)
        # The fake backend is Python: a SIGINT during its interpreter startup can
        # land in an importlib weakref callback, where CPython ignores the
        # KeyboardInterrupt. Wait until it has recorded its call and is running.
        for _ in range(200):
            if self.calls.exists() and '"archive": "a.bin"' in self.calls.read_text():
                break
            time.sleep(0.02)

        os.kill(orchestrator.pid, signal.SIGINT)
        output = orchestrator.communicate(timeout=10)[0]
        self.assertEqual(orchestrator.returncode, 2, output)
        self.assertIn("SIGINT recebido", output)
        state = json.loads(state_path.read_text())
        self.assertIsNone(state["active"])
        with self.assertRaises(ProcessLookupError):
            os.killpg(active_pgid, 0)

        resumed = self.run_installer(scratch)
        self.assertEqual(resumed.returncode, 0, resumed.stdout)

    def test_truncated_journal_recovers_from_atomic_backup(self):
        self.failure_marker.touch()
        scratch = self.root / "truncated-work"
        first = self.run_installer(scratch)
        self.assertEqual(first.returncode, 0, first.stdout)
        state_path = scratch / "install-state.json"
        self.assertTrue(state_path.with_name("install-state.json.bak").is_file())
        state_path.write_text('{"version":')

        recovered = self.run_installer(scratch)
        self.assertEqual(recovered.returncode, 0, recovered.stdout)
        self.assertIn("backup restaurado", recovered.stdout)
        self.assertTrue(list(scratch.glob("install-state.json.corrupt-*")))

    def test_no_space_failure_keeps_step_resumable(self):
        self.failure_marker.touch()
        scratch = self.root / "enospc-work"
        environment = self.environment()
        environment["FAKE_ENOSPC_ARCHIVE"] = "a.bin"
        failed = subprocess.run(
            self.installer_command(scratch), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=environment,
        )
        self.assertEqual(failed.returncode, 2, failed.stdout)
        state = json.loads((scratch / "install-state.json").read_text())
        self.assertEqual(state["completed"], {})
        self.assertIsNone(state["active"])

        resumed = self.run_installer(scratch)
        self.assertEqual(resumed.returncode, 0, resumed.stdout)

    def test_read_only_destination_keeps_copy_step_resumable(self):
        self.failure_marker.touch()
        scratch = self.root / "read-only-work"
        source = scratch / "stage/config.ini"
        source.parent.mkdir(parents=True)
        source.write_text("Language=english\n")
        manifest = json.loads(self.manifest.read_text())
        manifest["steps"] = [{
            "id": "copy-config", "type": "copy", "description": "Copy config",
            "source_root": "scratch", "source": "stage/config.ini",
            "destination_root": "app", "destination": "config.ini",
        }]
        self.manifest.write_text(json.dumps(manifest))
        target = self.root / "target"
        target.mkdir()
        target.chmod(0o500)
        try:
            failed = self.run_installer(scratch)
            self.assertEqual(failed.returncode, 2, failed.stdout)
            state = json.loads((scratch / "install-state.json").read_text())
            self.assertEqual(state["completed"], {})
            self.assertFalse((target / "config.ini").exists())
        finally:
            target.chmod(0o700)

        resumed = self.run_installer(scratch)
        self.assertEqual(resumed.returncode, 0, resumed.stdout)
        self.assertEqual((target / "config.ini").read_text(), "Language=english\n")

    def test_final_verification_is_a_transactional_step(self):
        self.failure_marker.touch()
        scratch = self.root / "verify-step-work"
        target = self.root / "target"
        target.mkdir(exist_ok=True)
        (target / "installed.bin").write_bytes(b"installed")
        embedded = scratch / "setup-payload/app/_Redist"
        embedded.mkdir(parents=True)
        (embedded / "fitgirl.md5").write_text(
            f"{hashlib.md5(b'installed').hexdigest()} *..\\installed.bin\n",
            encoding="utf-8",
        )
        manifest = json.loads(self.manifest.read_text())
        manifest["steps"].append({
            "id": "verify", "type": "verify", "description": "Verify",
            "manifest_root": "payload_app", "manifest": "_Redist/fitgirl.md5", "root": "app",
        })
        self.manifest.write_text(json.dumps(manifest))
        result = self.run_installer(scratch)
        self.assertEqual(result.returncode, 0, result.stdout)
        state = json.loads((scratch / "install-state.json").read_text())
        self.assertIn("004:verify", state["completed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
