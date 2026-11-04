import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fitgirl_installer import i18n


class InteractiveLocalizationTests(unittest.TestCase):
    def setUp(self):
        self.previous = i18n.activate("en")

    def tearDown(self):
        i18n.restore(self.previous)

    def test_destination_page_is_localized(self):
        self.assertEqual(i18n.translate("Etapa 1 de 4  |  Destino"), "Step 1 of 4  |  Destination")
        self.assertEqual(i18n.translate("Origem: Mirage 7"), "Source: Mirage 7")
        self.assertEqual(i18n.translate("Arquivos compactados: 899.97 MiB"), "Compressed files: 899.97 MiB")
        self.assertEqual(i18n.translate("Espaço declarado pelo instalador: 2.33 GiB"), "Installer-declared space: 2.33 GiB")
        self.assertEqual(i18n.translate("  7. Escolher outro caminho"), "  7. Choose another path")

    def test_component_prompt_uses_english_and_english_yes_no_markers(self):
        self.assertEqual(i18n.translate("  Incluir Inglês? [s/N] "), "  Include English? [y/N] ")


if __name__ == "__main__":
    unittest.main()
