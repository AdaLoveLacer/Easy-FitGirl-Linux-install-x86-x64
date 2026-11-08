#!/usr/bin/env python3

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fitgirl_installer import cli as CLI  # noqa: E402
from fitgirl_installer.planning import script_flow as IFPS_IR  # noqa: E402
from fitgirl_installer.planning import planner as PLANNER  # noqa: E402


class PlanGeneratorTests(unittest.TestCase):
    def test_setup_discovery_requires_one_case_insensitive_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            with self.assertRaisesRegex(CLI.InstallerError, "encontrados: 0"):
                CLI.discover_setup(source)
            setup = source / "SETUP.EXE"
            setup.write_bytes(b"synthetic")
            self.assertEqual(CLI.discover_setup(source), setup)
            (source / "setup.exe").write_bytes(b"other")
            with self.assertRaisesRegex(CLI.InstallerError, "encontrados: 2"):
                CLI.discover_setup(source)

    def test_iss_components_combine_descriptions_and_defaults(self):
        with tempfile.TemporaryDirectory() as temporary:
            iss = Path(temporary) / "install_script.iss"
            iss.write_text(
                '[Components]\n'
                'Name: "base"; Description: "Русский"; Types: "compact"\n'
                'Name: "base"; Description: "English"; Types: "full"\n'
                'Name: "extra"; Types: "custom"\n'
                'Name: "optional"; Description: "Optional"; Types: "compact"\n'
                '[Files]\nName: "ignored"; Types: "full"\n',
                encoding="utf-8",
            )
            self.assertEqual(PLANNER.components_from_iss(iss), {
                "base": {"description": "English", "default": True},
                "extra": {"description": "extra", "default": True},
                "optional": {"description": "Optional", "default": False},
            })

    def test_native_manifest_merge_preserves_addons_and_rolls_back(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scratch, target = root / "scratch", root / "target"
            source = scratch / "setup-payload/app/_Redist"
            source.mkdir(parents=True)
            target.mkdir()
            (target / "main.bin").write_bytes(b"main")
            (target / "bonus.bin").write_bytes(b"bonus")
            base = "a" * 32 + " *main.bin\r\n"
            addon = "b" * 32 + " *bonus.bin\r\n"
            (source / "fitgirl.md5").write_bytes(base.encode())
            (source / "bonus.addon").write_bytes(addon.encode())
            step = {
                "embedded_command": "copy /b fitgirl.md5+*.addon&&del *.addon",
                "cwd": "app", "cwd_suffix": "_Redist",
                "rollback_paths": [{"root": "app", "path": "_Redist"}],
            }
            args = type("Args", (), {"dry_run": False})()
            state = {"completed": {}, "components": ["bonus"]}
            path = scratch / "install-state.json"
            CLI.run_manifest_merge("merge", step, args, target, scratch, path, state)
            merged = target / "_Redist/fitgirl.md5"
            self.assertEqual(merged.read_bytes(), (base + addon).encode())
            self.assertEqual((source / "fitgirl.md5").read_bytes(), base.encode())
            self.assertTrue((target / "_Redist/bonus.addon").exists())
            self.assertEqual((target / "_Redist/fitgirl.base.md5").read_bytes(), base.encode())
            CLI.preserve_verifier(target, scratch, False, preserve_existing_manifest=True)
            self.assertEqual(merged.read_bytes(), (base + addon).encode())
            CLI.restore_transaction("merge", target, scratch, path, state)
            self.assertFalse((target / "_Redist").exists())
            (target / "bonus.bin").unlink()
            with self.assertRaisesRegex(CLI.InstallerError, "addon incompleto"):
                CLI.run_manifest_merge("missing", step, args, target, scratch, path, state)

    def test_analysis_tools_discovered_in_persistent_user_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tool = root / "data/fitgirl-installer/tools/pascalscript"
            tool.parent.mkdir(parents=True)
            tool.write_text("#!/bin/sh\nexit 0\n")
            tool.chmod(0o755)
            with patch.dict(os.environ, {"XDG_DATA_HOME": str(root / "data")}, clear=True), patch.object(CLI, "ROOT", root), patch.object(CLI.shutil, "which", return_value=None):
                self.assertEqual(CLI.discover_analysis_tool("TEST_TOOL", "pascalscript", "pascalscript"), tool)

    def test_analysis_tool_discovery_respects_candidate_priority(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            configured = root / "configured"
            bundled = root / "libexec" / "pascalscript"
            user = root / "data" / "fitgirl-installer" / "tools" / "pascalscript"
            system = root / "system"
            candidates = (configured, bundled, user, system)
            for candidate in candidates:
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.write_text("#!/bin/sh\nexit 0\n")
                candidate.chmod(0o755)
            environment = {"TEST_TOOL": str(configured), "XDG_DATA_HOME": str(root / "data")}
            with patch.dict(os.environ, environment), patch.object(CLI, "ROOT", root), patch.object(CLI.shutil, "which", return_value=str(system)):
                for expected in candidates:
                    self.assertEqual(CLI.discover_analysis_tool("TEST_TOOL", "pascalscript", "pascalscript"), expected)
                    expected.chmod(0o644)
                self.assertIsNone(CLI.discover_analysis_tool("TEST_TOOL", "pascalscript", "pascalscript"))

    def test_missing_analysis_tools_are_reported_before_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tool = root / "tool"
            cases = (
                (
                    None, None, "innounp (FITGIRL_INNOUNP), "
                    "disassembler IFPS (FITGIRL_IFPS_DISASSEMBLER)",
                ),
                (None, tool, "innounp (FITGIRL_INNOUNP)"),
                (tool, None, "disassembler IFPS (FITGIRL_IFPS_DISASSEMBLER)"),
            )
            for innounp, disassembler, expected in cases:
                with self.subTest(innounp=innounp, disassembler=disassembler):
                    with (
                        patch.dict(os.environ, {"XDG_CACHE_HOME": str(root / "cache")}),
                        patch.object(CLI, "discover_analysis_tool", side_effect=[innounp, disassembler]),
                        patch.object(CLI.subprocess, "run", side_effect=AssertionError("must not execute")),
                        self.assertRaises(CLI.InstallerError) as raised,
                    ):
                        CLI.generate_manifest_draft(root, root / "setup.exe", "missing")
                    self.assertEqual(
                        str(raised.exception),
                        "setup desconhecido e ferramentas de análise ausentes: " + expected,
                    )

    def test_cached_analysis_refreshes_semantic_blockers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            setup_hash = "cached-setup"
            analysis = root / "fitgirl-installer" / "plans" / setup_hash
            iss = analysis / "innounp" / "install_script.iss"
            compiled = analysis / "innounp" / "embedded" / "CompiledCode.bin"
            disassembly = analysis / "CompiledCode.disassembly.txt"
            control_flow = analysis / "control-flow.json"
            manifest_path = analysis / "manifest.draft.json"
            compiled.parent.mkdir(parents=True)
            iss.write_text("[Setup]\n")
            compiled.write_bytes(b"compiled")
            disassembly.write_text("disassembly")
            cases = (
                (True, None), (False, None), (True, "compiler"),
                (True, "disassembly"), (True, "schema"),
            )
            for blocked, stale in cases:
                with self.subTest(blocked=blocked, stale=stale):
                    control_flow.write_text(json.dumps({
                        "schema": CLI.IFPS_IR_SCHEMA_VERSION - int(stale == "schema"),
                    }))
                    manifest = {
                        "setup_sha256": [setup_hash],
                        "compiler_version": CLI.PLAN_COMPILER_VERSION - int(stale == "compiler"),
                        "analysis": {
                            "disassembly_sha256": (
                                "outdated" if stale == "disassembly" else CLI.sha256(disassembly)
                            ),
                            "existing_metadata": "preserved",
                        },
                        "semantic_blockers": ["old blocker"],
                        "draft": False,
                        "review_required": False,
                    }
                    manifest_path.write_text(json.dumps(manifest))
                    effect = {
                        "kind": "write", "call_address": "0x10",
                        "blocks_audit_acceptance": blocked,
                    }
                    report = {"semantic_guards": {"critical_external_effects": [effect]}}
                    regenerated = {
                        "setup_sha256": [setup_hash], "semantic_blockers": ["old blocker"],
                        "draft": False, "review_required": False,
                    }
                    with (
                        patch.dict(os.environ, {"XDG_CACHE_HOME": str(root)}),
                        patch.object(CLI, "discover_analysis_tool", return_value=None),
                        patch.object(CLI, "write_audit", return_value=report) as write_audit,
                        patch.object(CLI, "write_cfg_report", return_value={"totals": {}}) as write_cfg,
                        patch.object(CLI, "write_manifest", return_value=regenerated) as write_manifest,
                    ):
                        path, result = CLI.generate_manifest_draft(root, root / "setup.exe", setup_hash)
                    self.assertEqual(path, manifest_path)
                    if blocked:
                        self.assertEqual(result["semantic_blockers"], [
                            "write em 0x10: efeito externo crítico não modelado",
                        ])
                        self.assertTrue(result["draft"])
                        self.assertTrue(result["review_required"])
                    else:
                        self.assertNotIn("semantic_blockers", result)
                        self.assertFalse(result["draft"])
                        self.assertFalse(result["review_required"])
                    self.assertEqual(json.loads(manifest_path.read_text()), result)
                    write_audit.assert_called_once_with(
                        result, iss, disassembly, compiled, analysis / "plan-audit.json",
                        disassembler=None,
                    )
                    self.assertEqual(write_cfg.call_count, int(stale is not None))
                    self.assertEqual(write_manifest.call_count, int(stale is not None))
                    if stale is not None:
                        self.assertEqual(result["analysis"], {
                            "existing_metadata": "preserved",
                            "iss_sha256": CLI.sha256(iss),
                            "compiled_code_sha256": CLI.sha256(compiled),
                            "disassembly_sha256": CLI.sha256(disassembly),
                            "control_flow_sha256": CLI.sha256(control_flow),
                            "control_flow_totals": {},
                            # The synthetic setup carries no ISDone.dll.
                            "isdone_sha256": None,
                        })

    def test_disassembler_failure_preserves_analysis_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            innounp = root / "fake-innounp"
            disassembler = root / "fake-pascalscript"
            for scenario in ("nonzero", "empty", "timeout"):
                with self.subTest(scenario=scenario):
                    analysis = root / "cache" / "fitgirl-installer" / "plans" / scenario
                    extracted = analysis / "innounp"
                    compiled = extracted / "embedded" / "CompiledCode.bin"
                    compiled.parent.mkdir(parents=True)
                    (extracted / "install_script.iss").write_text("[Setup]\n")
                    compiled.write_bytes(b"compiled")
                    first = CLI.subprocess.CompletedProcess(
                        [str(innounp)], 0, stdout="innounp log",
                    )
                    if scenario == "timeout":
                        second = CLI.subprocess.TimeoutExpired([str(disassembler)], 120)
                        message = "disassembler IFPS excedeu 120 s"
                    else:
                        second = CLI.subprocess.CompletedProcess(
                            [str(disassembler)], int(scenario == "nonzero"),
                        )
                        message = "disassembler IFPS falhou"
                    with (
                        patch.dict(os.environ, {"XDG_CACHE_HOME": str(root / "cache")}),
                        patch.object(CLI, "discover_analysis_tool", side_effect=[innounp, disassembler]),
                        patch.object(CLI.subprocess, "run", side_effect=[first, second]),
                        self.assertRaisesRegex(CLI.InstallerError, message),
                    ):
                        CLI.generate_manifest_draft(root, root / "setup.exe", scenario)
                    self.assertEqual((analysis / "innounp.log").read_text(), "innounp log")
                    self.assertTrue((analysis / "pascalscript.stderr.log").is_file())
                    self.assertTrue(compiled.is_file())

    def test_innounp_failure_preserves_analysis_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            innounp = root / "fake-innounp"
            disassembler = root / "fake-pascalscript"
            for scenario in ("nonzero", "missing_iss", "missing_compiled", "timeout"):
                with self.subTest(scenario=scenario):
                    analysis = root / "cache" / "fitgirl-installer" / "plans" / scenario
                    extracted = analysis / "innounp"
                    compiled = extracted / "embedded" / "CompiledCode.bin"
                    compiled.parent.mkdir(parents=True)
                    if scenario != "missing_iss":
                        (extracted / "install_script.iss").write_text("[Setup]\n")
                    if scenario != "missing_compiled":
                        compiled.write_bytes(b"compiled")
                    if scenario == "timeout":
                        result = CLI.subprocess.TimeoutExpired([str(innounp)], 300)
                        message = "innounp excedeu 300 s"
                    else:
                        result = CLI.subprocess.CompletedProcess(
                            [str(innounp)], int(scenario == "nonzero"), stdout="innounp log",
                        )
                        message = "innounp não produziu ISS/CompiledCode.bin"
                    with (
                        patch.dict(os.environ, {"XDG_CACHE_HOME": str(root / "cache")}),
                        patch.object(CLI, "discover_analysis_tool", side_effect=[innounp, disassembler]),
                        patch.object(CLI.subprocess, "run", side_effect=[result]),
                        self.assertRaisesRegex(CLI.InstallerError, message),
                    ):
                        CLI.generate_manifest_draft(root, root / "setup.exe", scenario)
                    log = analysis / "innounp.log"
                    if scenario == "timeout":
                        self.assertFalse(log.exists())
                    else:
                        self.assertEqual(log.read_text(), "innounp log")
                    self.assertFalse((analysis / "CompiledCode.disassembly.txt").exists())

    def test_innounp_command_for_native_and_pe_tools(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            innounp = root / "innounp"
            disassembler = root / "pascalscript"
            wine = root / "wine"
            setup = root / "setup.exe"
            for scenario in ("native", "pe_default", "pe_custom", "pe_missing"):
                with self.subTest(scenario=scenario):
                    cache = root / "cache" / scenario
                    environment = {"XDG_CACHE_HOME": str(cache)}
                    if scenario == "pe_custom":
                        environment.update({
                            "FITGIRL_ANALYSIS_PREFIX": str(root / "custom-prefix"),
                            "WINEDEBUG": "+warn", "WINEDLLOVERRIDES": "custom=n",
                        })
                    is_pe = scenario != "native"
                    wines = [] if scenario == "pe_missing" else [wine]
                    timeout = CLI.subprocess.TimeoutExpired([str(innounp)], 300)
                    with (
                        patch.dict(os.environ, environment, clear=True),
                        patch.object(CLI, "discover_analysis_tool", side_effect=[innounp, disassembler]),
                        patch.object(CLI, "pe_machine", return_value=0x14C if is_pe else None),
                        patch.object(CLI, "discover_wine", return_value=wines) as discover_wine,
                        patch.object(CLI.subprocess, "run", side_effect=timeout) as run,
                    ):
                        message = (
                            "nenhum Wine foi encontrado" if scenario == "pe_missing"
                            else "innounp excedeu 300 s"
                        )
                        with self.assertRaisesRegex(CLI.InstallerError, message):
                            CLI.generate_manifest_draft(root, setup, scenario)
                    self.assertEqual(discover_wine.call_count, int(is_pe))
                    if scenario == "pe_missing":
                        run.assert_not_called()
                        continue
                    extracted = cache / "fitgirl-installer" / "plans" / scenario / "innounp"
                    command = run.call_args.args[0]
                    actual_env = run.call_args.kwargs["env"]
                    if is_pe:
                        win_extracted = "Z:" + str(extracted.resolve()).replace("/", "\\")
                        win_setup = "Z:" + str(setup.resolve()).replace("/", "\\")
                        expected = [
                            str(wine), str(innounp), "-x", "-b", "-q", "-m", "-y",
                            f"-d{win_extracted}", win_setup,
                        ]
                        prefix = (
                            root / "custom-prefix" if scenario == "pe_custom"
                            else cache / "fitgirl-installer" / "analysis-wine-prefix"
                        )
                        environment.update({
                            "WINEPREFIX": str(prefix.resolve()),
                            "WINEDEBUG": environment.get("WINEDEBUG", "-all"),
                            "WINEDLLOVERRIDES": environment.get("WINEDLLOVERRIDES", "mscoree,mshtml="),
                        })
                    else:
                        expected = [
                            str(innounp), "-x", "-b", "-q", "-m", "-y",
                            f"-d{extracted}", str(setup),
                        ]
                    self.assertEqual(
                        command, expected + ["install_script.iss", "embedded\\CompiledCode.bin"],
                    )
                    self.assertEqual(actual_env, environment)

    def test_literal_cmd_del_is_idempotent_and_reversible(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target, scratch = root / "target", root / "scratch"
            target.mkdir()
            scratch.mkdir()
            state_path = scratch / "install-state.json"
            state = {"completed": {}, "active": None}
            args = type("Args", (), {"dry_run": False})()
            step = {
                "executable": "{cmd}", "cwd": "app",
                "parameter_expression": [
                    {"operation": "assign", "value": "/C "},
                    {"operation": "expanded_quoted", "value": "del inner.fgpack"},
                    {"operation": "calc.add", "value": ""},
                ],
                "rollback_paths": [{"path": "inner.fgpack", "root": "app"}],
            }
            path = target / "inner.fgpack"
            path.write_bytes(b"archive")
            CLI.run_isexec("delete", step, args, root, target, scratch, root, state_path, state)
            self.assertFalse(path.exists())
            CLI.restore_transaction("delete", target, scratch, state_path, state)
            self.assertEqual(path.read_bytes(), b"archive")
            path.unlink()
            CLI.run_isexec("absent", step, args, root, target, scratch, root, state_path, state)
            self.assertEqual(state["transactions"]["absent"]["status"], "committed")
            step["rollback_paths"] = []
            with self.assertRaisesRegex(CLI.InstallerError, "escopo"):
                CLI.run_isexec("invalid", step, args, root, target, scratch, root, state_path, state)

    def test_ifps_cfg_builds_blocks_branches_and_internal_calls(self):
        disassembly = """\
===== proc #1 =====
MAINPROC  bytecode @0x100 (64 bytes, 6 instructions)
  0x100  assign      s+1, 1u8
  0x105  if not      s+1 goto 0x120
  0x110  call        HELPER
  0x115  goto        0x130
  0x120  assign      s+2, 0u8
  0x130  ret

===== proc #2 =====
HELPER  bytecode @0x200 (1 bytes, 1 instructions)
  0x200  ret
"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "compiled.txt"
            path.write_text(disassembly)
            report = IFPS_IR.cfg_report(path)

        self.assertEqual(report["totals"], {
            "procedures": 2, "instructions": 7, "blocks": 5, "edges": 3
        })
        main = report["procedures"][0]
        self.assertEqual(
            main["blocks"][0]["successors"],
            [
                {"target": "0x110", "kind": "branch-false"},
            ],
        )
        self.assertEqual(main["calls"][0]["internal_index"], 2)
        self.assertEqual(main["unresolved_targets"], [])

    def test_ifps_cfg_preserves_try_edges_and_unresolved_targets(self):
        disassembly = """\
===== proc #3 =====
WITHERROR  bytecode @0x300 (64 bytes, 5 instructions)
  0x300  try         finally=0x320 except=- finally2=- end=0x330
  0x310  goto        0x999
  0x320  end-try     (finally)
  0x325  goto        0x330
  0x330  ret
"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "compiled.txt"
            path.write_text(disassembly)
            procedure = IFPS_IR.parse_disassembly(path)[0]
            cfg = IFPS_IR.build_cfg(procedure)

        self.assertEqual(
            [(edge.target, edge.kind) for edge in cfg.blocks[0].successors],
            [(0x320, "try-finally"), (0x330, "try-end"), (0x310, "fallthrough")],
        )
        self.assertEqual(cfg.unresolved_targets[0]["target"], "0x999")

    def test_ifps_recovers_constant_condition_without_guessing_branch_polarity(self):
        disassembly = """\
===== proc #4 =====
CONDITIONS  bytecode @0x400 (64 bytes, 7 instructions)
  0x400  assign      s+2, "text\\eng"
  0x410  push-ref    s+1
  0x415  call        ISCOMPONENTSELECTED
  0x420  pop
  0x421  set-flag    not s+1
  0x428  pop
  0x429  flag-goto   0x440
  0x440  ret
"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "compiled.txt"
            path.write_text(disassembly)
            procedure = IFPS_IR.cfg_report(path)["procedures"][0]

        condition = procedure["constant_conditions"][0]
        self.assertEqual(condition["api"], "ISCOMPONENTSELECTED")
        self.assertEqual(condition["constant_argument"], "text\\eng")
        self.assertTrue(condition["proven"])
        self.assertEqual(condition["result_variable"], "s+1")
        self.assertEqual(condition["branch"]["flag_expression"], "not s+1")
        self.assertFalse(condition["branch"]["when_api_result"])
        self.assertEqual(condition["branch"]["targets"], ["0x440"])

    def test_ifps_proves_component_bitmask_and_isdone_consumer(self):
        disassembly = """\
===== proc #5 =====
BITMASK  bytecode @0x500 (128 bytes, 13 instructions)
  0x500  assign      s+1, 0i32
  0x510  assign      s+4, 1i32
  0x520  assign      s+14, "text\\eng"
  0x530  push-ref    s+13
  0x535  call        ISCOMPONENTSELECTED
  0x540  pop
  0x541  set-flag    not s+13
  0x548  pop
  0x549  flag-goto   0x560
  0x550  calc.add   s+1, s+4
  0x560  calc.mul   s+4, 2i32
  0x570  assign      s+20, s+1
  0x580  call        dll:files:ISDone.dll
  0x590  ret
"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "compiled.txt"
            path.write_text(disassembly)
            procedure = IFPS_IR.cfg_report(path)["procedures"][0]

        bitmask = procedure["component_bitmask"]
        self.assertTrue(bitmask["proven"])
        self.assertEqual(bitmask["components"], [{
            "component": "text\\eng",
            "bit": 1,
            "condition_call": "0x535",
            "add_address": "0x550",
            "join_address": "0x560",
        }])
        self.assertEqual(bitmask["consumer_assignment"], "0x570")
        self.assertEqual(bitmask["consumer_call"], "0x580")

    def test_repeated_archive_calls_are_preserved_in_order(self):
        disassembly = """\
CURSTEPCHANGED  bytecode
  assign      s+1, "{app}\\"
  assign      s+2, "{src}\\fg-05.bin"
  call        dll:files:ISDone.dll
  assign      s+1, "{app}\\"
  assign      s+2, "{src}\\fg-05.bin"
  call        dll:files:ISDone.dll
"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "compiled.txt"
            path.write_text(disassembly)
            steps = PLANNER.steps_from_disassembly(
                path, {}, {"fg-05.bin": "a" * 32}
            )

        self.assertEqual([step["archive"] for step in steps], ["fg-05.bin", "fg-05.bin"])
        self.assertEqual([step["id"] for step in steps], ["fg-05-bin", "fg-05-bin-2"])
        self.assertEqual([step["destination"] for step in steps], ["app", "app"])

    def test_plan_steps_are_linked_to_bytecode_addresses(self):
        disassembly = """\
CURSTEPCHANGED  bytecode
  0x500  assign      s+1, "{app}\\"
  0x510  assign      s+2, "{src}\\fg-01.bin"
  0x520  call        dll:files:ISDone.dll
"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "compiled.txt"
            path.write_text(disassembly)
            step = PLANNER.steps_from_disassembly(path, {}, {})[0]

        self.assertEqual(step["bytecode"], {
            "argument_address": "0x510", "call_address": "0x520"
        })

    def test_named_isdone_exports_recover_extract_exec_and_inner_archive(self):
        disassembly = """\
CURSTEPCHANGED  bytecode
  0x500  assign      s+15, 0u8
  0x510  assign      s+18, "{app}\\temp-fitgirl\\"
  0x520  assign      s+19, "{tmp}\\arc.ini"
  0x530  assign      s+18, "{tmp}\\unarc.dll"
  0x540  assign      s+19, 0u8
  0x550  assign      s+20, ""
  0x560  assign      s+23, "{app}\\"
  0x570  assign      s+24, "{src}\\fg-01.bin"
  0x574  assign      s+23, 0i32
  0x578  assign      s+24, 0i32
  0x580  call        dll:files:ISDone.dll!ISArcExtract
  0x600  assign      s+15, 0u8
  0x610  assign      s+16, "Patching data..."
  0x620  assign      s+20, "{app}\\"
  0x630  assign      s+19, "/C "
  0x640  assign      s+22, "{tmp}\\x5n.exe"
  0x650  calc.add   s+19, " -s-2g -f . new.x5n .&&del new.x5n"
  0x660  assign      s+21, "{cmd}"
  0x664  assign      s+20, 0i32
  0x668  assign      s+21, 0i32
  0x66c  assign      s+22, 0i32
  0x670  call        dll:files:ISDone.dll!ISExec
  0x700  assign      s+15, 0u8
  0x710  assign      s+18, "{app}\\temp-fitgirl\\"
  0x720  assign      s+19, "{tmp}\\arc.ini"
  0x730  assign      s+18, "{tmp}\\unarc.dll"
  0x740  assign      s+19, 1u8
  0x750  assign      s+20, ""
  0x760  assign      s+23, "{app}\\"
  0x770  assign      s+24, "{app}\\inner.fgpack"
  0x774  assign      s+23, 0i32
  0x778  assign      s+24, 0i32
  0x780  call        dll:files:ISDone.dll!ISArcExtract
  0x790  assign      s+16, "{tmp}\\work\\fart.exe"
  0x7a0  call        DELETEFILE
"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "compiled.txt"
            path.write_text(disassembly)
            steps = PLANNER.steps_from_disassembly(path, {}, {})

        self.assertEqual(
            [step["type"] for step in steps],
            ["extract", "isexec", "extract", "delete-file"],
        )
        self.assertEqual(steps[0]["archive"], "fg-01.bin")
        self.assertEqual(steps[0]["bytecode"]["export"], "ISArcExtract")
        self.assertEqual(steps[1]["executable"], "{cmd}")
        self.assertEqual(steps[1]["embedded_command"], "{tmp}\\x5n.exe")
        self.assertEqual(steps[1]["cur_component"], 0)
        self.assertEqual(steps[2]["archive_root"], "app")
        self.assertEqual(steps[2]["archive"], "inner.fgpack")
        self.assertTrue(steps[2]["delete_archive_after"])
        self.assertEqual(steps[2]["isarc_arguments"]["cur_component"], 0)
        self.assertEqual(steps[3]["path"], "work/fart.exe")
        coverage = PLANNER.action_coverage(disassembly.splitlines(), steps)
        self.assertTrue(coverage["complete"])
        self.assertEqual(coverage["relevant_calls"], 4)

    def test_bitmask_accepts_enriched_isdone_init_name(self):
        disassembly = """\
===== proc #5 =====
BITMASK  bytecode @0x500 (128 bytes, 13 instructions)
  0x500  assign      s+1, 0i32
  0x510  assign      s+4, 1i32
  0x520  assign      s+14, "text\\eng"
  0x530  push-ref    s+13
  0x535  call        ISCOMPONENTSELECTED
  0x540  pop
  0x541  set-flag    not s+13
  0x548  pop
  0x549  flag-goto   0x560
  0x550  calc.add   s+1, s+4
  0x560  calc.mul   s+4, 2i32
  0x570  assign      s+20, s+1
  0x580  call        dll:files:ISDone.dll!ISDoneInit
  0x590  ret
"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "compiled.txt"
            path.write_text(disassembly)
            bitmask = IFPS_IR.cfg_report(path)["procedures"][0]["component_bitmask"]

        self.assertTrue(bitmask["proven"])
        self.assertEqual(bitmask["consumer_call"], "0x580")

    def test_set_ini_string_recovers_arguments_and_checkbox_condition(self):
        disassembly = """\
CURSTEPCHANGED  bytecode
  0x800  assign      s+16, "{tmp}\\CLS.ini"
  0x810  assign      s+17, "{app}"
  0x820  assign      s+17, "TempPath"
  0x830  assign      s+18, "Srep"
  0x840  call        SETINISTRING
  0x850  assign      s+15, g#10
  0x860  call        class:TCHECKBOX|CHECKED|
  0x870  set-flag    not s+14
  0x880  flag-goto   0x900
  0x890  assign      s+16, "{tmp}\\arc.ini"
  0x8a0  assign      s+16, "bzip3.exe -dc"
  0x8b0  assign      s+17, "unpackcmd"
  0x8c0  assign      s+18, "External compressor:bz3"
  0x8d0  call        SETINISTRING
  0x900  ret
"""
        steps = PLANNER.named_isdone_steps(disassembly.splitlines(), {}, {})
        ini_steps = [step for step in steps if step["type"] == "ini-write"]

        self.assertEqual(len(ini_steps), 2)
        self.assertEqual(
            (ini_steps[0]["file"], ini_steps[0]["section"], ini_steps[0]["key"], ini_steps[0]["value"]),
            ("CLS.ini", "Srep", "TempPath", "{app}"),
        )
        self.assertIsNone(ini_steps[0]["condition"])
        self.assertEqual(ini_steps[1]["condition"]["source"], "g#10")
        self.assertTrue(ini_steps[1]["condition"]["when_checked"])
        self.assertTrue(ini_steps[1]["condition"]["proven"])

    def test_checkbox_symbol_is_recovered_from_caption_message(self):
        disassembly = """\
  0x100  set-ptr     s+2 := @g#10
  0x110  assign      s+4, "{cm:use2gb}"
  0x120  call        EXPANDCONSTANT
  0x130  call        class:TCHECKBOX|CAPTION@|
"""
        self.assertEqual(PLANNER.checkbox_symbols(disassembly.splitlines()), {"g#10": "use2gb"})

    def test_extract_temporary_file_inventory_is_casefolded_and_audited(self):
        disassembly = """\
===== proc #1 =====
FIRST  bytecode @0x100 (32 bytes, 2 instructions)
  0x100  assign      s+1, "Bass.dll"
  0x110  call        EXTRACTTEMPORARYFILE
===== proc #2 =====
SECOND  bytecode @0x200 (32 bytes, 2 instructions)
  0x200  assign      s+1, "BASS.dll"
  0x210  call        EXTRACTTEMPORARYFILE
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            code = root / "compiled.txt"
            code.write_text(disassembly)
            iss = root / "install_script.iss"
            iss.write_text('[Files]\nSource: "{tmp}\\BASS.dll"; DestDir: "{tmp}"; Flags: dontcopy\n')
            files, coverage = PLANNER.temporary_payload_files(code, iss)

        self.assertEqual(len(files), 1)
        self.assertEqual(len(files[0]["calls"]), 2)
        self.assertTrue(files[0]["present_in_iss"])
        self.assertEqual(coverage["relevant_calls"], 2)
        self.assertTrue(coverage["complete"])

    def test_application_payload_ignores_commented_entries(self):
        with tempfile.TemporaryDirectory() as temporary:
            iss = Path(temporary) / "install_script.iss"
            iss.write_text(
                """[Files]
; Source: "{app}\\_Redist\\optional.exe"; DestDir: "{app}\\_Redist"; Components: optional
Source: "{app}\\_Redist\\QuickSFV.EXE"; DestDir: "{app}\\_Redist"; Flags: ignoreversion
Source: "{app}\\_Redist\\fitgirl.md5"; DestDir: "{app}\\_Redist"; Flags: ignoreversion
"""
            )
            files, coverage = PLANNER.application_payload_files(iss)

        self.assertEqual(
            [item["path"] for item in files],
            ["_Redist/QuickSFV.EXE", "_Redist/fitgirl.md5"],
        )
        self.assertEqual(coverage["active_entries"], 2)
        self.assertTrue(coverage["complete"])

    def test_temporary_payload_is_atomic_hashed_and_resumable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scratch = root / "scratch"
            setup = root / "setup.exe"
            setup.write_bytes(b"setup")
            counter = root / "counter"
            fake = root / "fake-innoextract"
            fake.write_text(
                """#!/usr/bin/env python3
import sys
from pathlib import Path
args = sys.argv[1:]
output = Path(args[args.index('--output-dir') + 1])
includes = [args[index + 1] for index, value in enumerate(args) if value == '--include']
counter = Path(__file__).with_name('counter')
counter.write_text(str(int(counter.read_text()) + 1) if counter.exists() else '1')
for item in includes:
    target = output / item
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b'[S]\\r\\nK=old\\r\\n' if Path(item).name == 'b.ini' else ('payload:' + Path(item).name).encode())
""",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            manifest = {"temporary_payload_files": [{"name": "A.dll"}, {"name": "b.ini"}]}
            state = {"setup_sha256": "a" * 64, "active": None}
            state_path = scratch / "install-state.json"
            scratch.mkdir()
            CLI.atomic_json(state_path, state)

            CLI.materialize_temporary_payload(
                manifest, setup, scratch, state_path, state, False, fake
            )
            destination = scratch / "setup-payload" / "tmp"
            self.assertEqual(counter.read_text(), "1")
            self.assertEqual({path.name for path in destination.iterdir()}, {"A.dll", "b.ini"})
            self.assertEqual(len(state["payload"]["files"]), 2)

            args = type("Args", (), {"wine": Path("/bin/true"), "dry_run": False})()
            CLI.run_ini_write(
                {
                    "file_root": "tmp", "file": "b.ini", "section": "S",
                    "key": "K", "value": "new",
                },
                args, root, Path("/mnt/test-target"), scratch, root / "prefix",
                state_path, state,
            )
            CLI.materialize_temporary_payload(
                manifest, setup, scratch, state_path, state, False, fake
            )
            self.assertEqual(counter.read_text(), "1")
            self.assertIn(b"K=new", (destination / "b.ini").read_bytes())

            (destination / "auxiliary.txt").write_text("archive output")
            CLI.materialize_temporary_payload(
                manifest, setup, scratch, state_path, state, False, fake
            )
            self.assertEqual(counter.read_text(), "1")

            state["completed"] = {"001:ini-write": {}}
            (destination / "A.dll").write_bytes(b"tampered")
            with self.assertRaisesRegex(CLI.InstallerError, "reconstrução automática recusada"):
                CLI.materialize_temporary_payload(
                    manifest, setup, scratch, state_path, state, False, fake
                )
            self.assertTrue((destination / "auxiliary.txt").exists())
            state["completed"] = {}

            (destination / "A.dll").write_bytes(b"tampered")
            CLI.materialize_temporary_payload(
                manifest, setup, scratch, state_path, state, False, fake
            )
            self.assertEqual(counter.read_text(), "2")
            self.assertTrue(any(path.name.startswith("tmp.stale-") for path in destination.parent.iterdir()))

            CLI.materialize_temporary_payload(
                manifest, setup, scratch, state_path, state, False, fake
            )
            self.assertEqual(counter.read_text(), "2")

    def test_fart_expected_count_and_whole_word_postconditions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "commands.txt"
            path.write_bytes(b"fitgirl2-path\r\n" * 8153 + b"xfitgirl2-path\r\n")
            count, outputs = CLI.fart_expected_outputs(
                '-w *.txt fitgirl2-path "W:\\My Temp"', root
            )
            self.assertEqual(count, 8153)
            self.assertEqual(count & 255, 217)
            self.assertEqual(
                outputs[path], b"W:\\My Temp\r\n" * 8153 + b"xfitgirl2-path\r\n"
            )
            self.assertIn(b"fitgirl2-path", path.read_bytes())
            with self.assertRaises(CLI.InstallerError):
                CLI.fart_expected_outputs('-r *.txt find replace', root)

    def test_ini_write_is_atomic_idempotent_and_preserves_crlf(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "CLS.ini"
            path.write_bytes(b"[Srep]\r\nMemory=60%-2048m\r\n\r\n[magic]\r\nBufsize=512k\r\n")

            self.assertTrue(CLI.set_ini_value(path, "srep", "memory", "512m"))
            self.assertFalse(CLI.set_ini_value(path, "Srep", "Memory", "512m"))
            self.assertTrue(CLI.set_ini_value(path, "new", "Key", "Value"))
            result = path.read_bytes()

        self.assertIn(b"Memory=512m\r\n", result)
        self.assertIn(b"[new]\r\nKey=Value\r\n", result)
        self.assertEqual(result.count(b"\n"), result.count(b"\r\n"))

    def test_application_payload_is_materialized_and_resumed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scratch = root / "scratch"
            scratch.mkdir()
            setup = root / "setup.exe"
            setup.write_bytes(b"setup")
            counter = root / "app-counter"
            fake = root / "fake-innoextract"
            fake.write_text(
                """#!/usr/bin/env python3
import sys
from pathlib import Path
args=sys.argv[1:]
output=Path(args[args.index('--output-dir')+1])
counter=Path(__file__).with_name('app-counter')
counter.write_text(str(int(counter.read_text())+1) if counter.exists() else '1')
for index,value in enumerate(args):
    if value == '--include':
        target=output/args[index+1]
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(target.name)
""",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            manifest = {"application_payload_files": [
                {"path": "_Redist/QuickSFV.EXE"},
                {"path": "_Redist/fitgirl.md5"},
            ]}
            state = {"setup_sha256": "a" * 64, "active": None}
            state_path = scratch / "install-state.json"
            CLI.atomic_json(state_path, state)

            CLI.materialize_application_payload(
                manifest, setup, scratch, state_path, state, False, fake
            )
            CLI.materialize_application_payload(
                manifest, setup, scratch, state_path, state, False, fake
            )

            destination = scratch / "setup-payload/app/_Redist"
            self.assertEqual(counter.read_text(), "1")
            self.assertEqual(
                {path.name for path in destination.iterdir()},
                {"QuickSFV.EXE", "fitgirl.md5"},
            )
            self.assertEqual(len(state["payload"]["app_files"]), 2)

    def test_use2gb_condition_is_safe_by_default(self):
        step = {"condition": {"option": "use2gb", "proven": True}}
        self.assertFalse(CLI.enabled(step, set()))
        self.assertTrue(CLI.enabled(step, set(), {"use2gb"}))

    def test_windows_argv_preserves_quoted_paths(self):
        self.assertEqual(
            CLI.windows_argv('-w *.txt fitgirl-path "W:\\Games\\My Game"'),
            ["-w", "*.txt", "fitgirl-path", "W:\\Games\\My Game"],
        )

    def test_cmd_isexec_preserves_expanded_quotes(self):
        args = type("Args", (), {
            "wine": Path("/usr/bin/wine"), "cpus": None, "nice": 0,
            "memory_high": None, "memory_max": None,
        })()
        step = {
            "executable": "{cmd}",
            "parameter_expression": [
                {"operation": "assign", "value": "/C "},
                {"operation": "expanded_quoted", "value": "{tmp}\\x.exe"},
                {"operation": "calc.add", "value": " -f data.bin"},
            ],
        }
        command = CLI.isexec_command(
            step, args, Path("/mnt/source"), Path("/mnt/My Game"),
            Path("/mnt/My Scratch"), Path("/mnt/prefix"),
        )

        self.assertEqual(command[2:5], ["/d", "/s", "/c"])
        self.assertEqual(
            command[5:],
            ["W:\\My Scratch\\setup-payload\\tmp\\x.exe", "-f", "data.bin"],
        )

    def test_isexec_failure_restores_declared_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            scratch = root / "scratch"
            target.mkdir()
            scratch.mkdir()
            mutable = target / "data.bin"
            mutable.write_bytes(b"original")
            fake_wine = root / "wine"
            fake_wine.write_text(
                "#!/usr/bin/env python3\n"
                "import os,pathlib\n"
                "pathlib.Path(os.environ['MUTATE_PATH']).write_bytes(b'changed')\n"
                "raise SystemExit(9)\n"
            )
            fake_wine.chmod(0o755)
            state = {"completed": {}, "active": None}
            state_path = scratch / "install-state.json"
            CLI.atomic_json(state_path, state)
            args = type("Args", (), {
                "wine": fake_wine, "dry_run": False, "cpus": None,
                "nice": 0, "memory_high": None, "memory_max": None,
            })()
            step = {
                "type": "isexec", "executable": "C:\\mutator.exe",
                "parameters": "", "cwd": "app",
                "rollback_paths": [{"root": "app", "path": "data.bin"}],
            }
            old = os.environ.get("MUTATE_PATH")
            os.environ["MUTATE_PATH"] = str(mutable)
            try:
                with self.assertRaises(CLI.InstallerError):
                    CLI.run_isexec(
                        "001:mutate", step, args, root, target, scratch,
                        root / "prefix", state_path, state,
                    )
            finally:
                if old is None:
                    os.environ.pop("MUTATE_PATH", None)
                else:
                    os.environ["MUTATE_PATH"] = old

            self.assertEqual(mutable.read_bytes(), b"original")
            self.assertEqual(
                state["transactions"]["001:mutate"]["status"], "rolled-back"
            )

    def test_delete_uses_reversible_quarantine(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            scratch = root / "scratch"
            target.mkdir()
            scratch.mkdir()
            deleted = target / "temp-fitgirl"
            deleted.mkdir()
            (deleted / "partial.bin").write_bytes(b"partial")
            state = {"completed": {}, "active": None}
            state_path = scratch / "install-state.json"
            CLI.atomic_json(state_path, state)
            step = {
                "type": "delete-tree", "path_root": "app",
                "path": "temp-fitgirl",
            }

            CLI.run_delete(
                "001:delete", step, target, scratch, state_path, state, False
            )
            self.assertFalse(deleted.exists())
            CLI.restore_transaction(
                "001:delete", target, scratch, state_path, state
            )
            self.assertEqual((deleted / "partial.bin").read_bytes(), b"partial")

    def test_rollback_rejects_missing_or_unconfined_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            scratch = root / "scratch"
            target.mkdir()
            scratch.mkdir()
            sentinel = target / "sentinel"
            sentinel.write_text("keep")
            state = {"completed": {}, "transactions": {
                "bad": {
                    "status": "committed",
                    "entries": [{"path": str(sentinel), "existed": False}],
                }
            }}
            state_path = scratch / "install-state.json"
            CLI.atomic_json(state_path, state)

            with self.assertRaises(CLI.InstallerError):
                CLI.restore_transaction(
                    "bad", target, scratch, state_path, state
                )

            self.assertEqual(sentinel.read_text(), "keep")

    def test_resume_rolls_back_isexec_not_marked_completed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            scratch = root / "scratch"
            target.mkdir()
            scratch.mkdir()
            mutable = target / "data.bin"
            mutable.write_bytes(b"original")
            state = {"completed": {}, "transactions": {}, "active": None}
            state_path = scratch / "install-state.json"
            CLI.atomic_json(state_path, state)
            step = {
                "rollback_paths": [{"root": "app", "path": "data.bin"}]
            }
            CLI.begin_transaction(
                "001:mutate", step, target, scratch, state_path, state, False
            )
            mutable.write_bytes(b"partial")
            state["transactions"]["001:mutate"]["status"] = "committed"
            CLI.atomic_json(state_path, state)

            CLI.recover_incomplete_transactions(
                target, scratch, state_path, state
            )

            self.assertEqual(mutable.read_bytes(), b"original")
            self.assertEqual(
                state["transactions"]["001:mutate"]["status"], "rolled-back"
            )

    def test_finalize_discards_only_confined_transaction_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scratch = root / "scratch"
            quarantine = scratch / "transactions/001-delete/deleted"
            quarantine.mkdir(parents=True)
            (quarantine / "obsolete.bin").write_bytes(b"obsolete")
            state = {"transactions": {
                "001:delete": {
                    "kind": "delete", "status": "committed",
                    "root": str(quarantine.parent), "entries": [],
                }
            }}
            state_path = scratch / "install-state.json"
            CLI.atomic_json(state_path, state)

            CLI.finalize_transactions(scratch, state_path, state)

            self.assertFalse(quarantine.parent.exists())
            self.assertEqual(state["transactions"], {})

    def test_unknown_setup_generates_auditable_refused_draft(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "Example [FitGirl Repack]"
            source.mkdir()
            setup = source / "setup.exe"
            setup.write_bytes(b"not-a-pe-test-setup")
            (source / "fg-01.bin").write_bytes(b"archive")
            (source / "fitgirl.md5").write_text(
                f"{'a' * 32} *fg-01.bin\n", encoding="utf-8"
            )

            innounp = root / "fake-innounp"
            innounp.write_text(
                """#!/usr/bin/env python3
import sys
from pathlib import Path
destination = Path(next(arg[2:] for arg in sys.argv if arg.startswith('-d')))
(destination / 'embedded').mkdir(parents=True, exist_ok=True)
(destination / 'install_script.iss').write_text('[Components]\\nName: "base"; Description: "Base"; Types: full\\nfitgirl.md5\\n')
(destination / 'embedded' / 'CompiledCode.bin').write_bytes(b'IFPS-test')
""",
                encoding="utf-8",
            )
            innounp.chmod(0o755)
            disassembler = root / "fake-pascalscript"
            disassembler.write_text(
                """#!/usr/bin/env python3
print('CURSTEPCHANGED  bytecode')
print('  assign      s+1, "{app}\\\\"')
print('  assign      s+2, "{src}\\\\fg-01.bin"')
print('  call        dll:files:ISDone.dll')
""",
                encoding="utf-8",
            )
            disassembler.chmod(0o755)

            environment = {
                "XDG_CACHE_HOME": str(root / "cache"),
                "FITGIRL_INNOUNP": str(innounp),
                "FITGIRL_IFPS_DISASSEMBLER": str(disassembler),
            }
            with patch.dict(os.environ, environment, clear=False):
                path, manifest = CLI.generate_manifest_draft(
                    source, setup, CLI.sha256(setup)
                )

            self.assertTrue(path.is_file())
            self.assertTrue(manifest["draft"])
            self.assertTrue(manifest["review_required"])
            self.assertEqual(manifest["steps"][0]["archive"], "fg-01.bin")
            analysis = path.parent
            control_flow = analysis / "control-flow.json"
            self.assertEqual(manifest["analysis"], {
                "iss_sha256": CLI.sha256(analysis / "innounp/install_script.iss"),
                "compiled_code_sha256": CLI.sha256(analysis / "innounp/embedded/CompiledCode.bin"),
                "disassembly_sha256": CLI.sha256(analysis / "CompiledCode.disassembly.txt"),
                "control_flow_sha256": CLI.sha256(control_flow),
                "control_flow_totals": json.loads(control_flow.read_text())["totals"],
                "innounp_sha256": CLI.sha256(innounp),
                "ifps_disassembler_sha256": CLI.sha256(disassembler),
                # The synthetic setup carries no ISDone.dll.
                "isdone_sha256": None,
            })

    def test_pe_analysis_tool_does_not_need_posix_execute_bit(self):
        with tempfile.TemporaryDirectory() as temporary:
            tool = Path(temporary) / "innounp.exe"
            image = bytearray(256)
            image[0:2] = b"MZ"
            image[0x3C:0x40] = (128).to_bytes(4, "little")
            image[128:132] = b"PE\0\0"
            image[132:134] = (0x14C).to_bytes(2, "little")
            tool.write_bytes(image)
            tool.chmod(0o644)
            with patch.dict(os.environ, {"FITGIRL_INNOUNP": str(tool)}):
                self.assertEqual(
                    CLI.discover_analysis_tool(
                        "FITGIRL_INNOUNP", "missing.exe", "missing-innounp"
                    ),
                    tool,
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
