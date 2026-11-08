import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fitgirl_installer import translations


class InteractiveLocalizationTests(unittest.TestCase):
    def setUp(self):
        self.previous = translations.activate("en")

    def tearDown(self):
        translations.restore(self.previous)

    def test_destination_page_is_localized(self):
        self.assertEqual(translations.translate("Etapa 1 de 4  |  Destino"), "Step 1 of 4  |  Destination")
        self.assertEqual(translations.translate("Origem: Mirage 7"), "Source: Mirage 7")
        self.assertEqual(translations.translate("Arquivos compactados: 899.97 MiB"), "Compressed files: 899.97 MiB")
        self.assertEqual(translations.translate("Espaço declarado pelo instalador: 2.33 GiB"), "Installer-declared space: 2.33 GiB")
        self.assertEqual(translations.translate("  7. Escolher outro caminho"), "  7. Choose another path")

    def test_component_prompt_uses_english_and_english_yes_no_markers(self):
        self.assertEqual(translations.translate("  Incluir Inglês? [s/N] "), "  Include English? [y/N] ")


if __name__ == "__main__":
    unittest.main()
