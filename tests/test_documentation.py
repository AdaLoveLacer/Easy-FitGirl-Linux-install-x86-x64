#!/usr/bin/env python3

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DocumentationTests(unittest.TestCase):
    def test_licenses_command_lists_every_bundled_component(self):
        """Quem baixa só o arquivo único recebe os avisos por este comando."""
        result = subprocess.run(
            [str(ROOT / "fitgirl"), "licenses"], cwd=ROOT, text=True,
            env={"FITGIRL_LANGUAGE": "pt", "PATH": "/usr/bin:/bin"},
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("0BSD", result.stdout)
        esperados = json.loads((ROOT / "third_party/components.json").read_text())
        nomes = esperados if isinstance(esperados, list) else esperados.get("components", [])
        for componente in nomes:
            arquivo = componente.get("license_file") if isinstance(componente, dict) else None
            if arquivo:
                self.assertIn(arquivo, result.stdout, f"aviso ausente: {arquivo}")

    def test_standalone_build_stages_the_notices(self):
        """O arquivo único precisa carregar LICENSE e LICENSES/ no payload."""
        script = (ROOT / "tools/build-standalone.sh").read_text()
        self.assertIn('cp "$ROOT/LICENSE" "$STAGE/LICENSE"', script)
        self.assertIn('third_party/licenses/', script)

    def test_operational_docs_match_canonical_status(self):
        result = subprocess.run(
            [str(ROOT / "tools/sync-docs.py"), "--check"],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        self.assertEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()
