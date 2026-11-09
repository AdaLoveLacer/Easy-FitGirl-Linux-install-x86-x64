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

    def test_marker_and_message_body_are_both_localized(self):
        self.assertEqual(
            translations.translate("[PULA] 003:c: condição de componente não satisfeita"),
            "[SKIP] 003:c: component condition not satisfied",
        )
        self.assertEqual(
            translations.translate("[VALIDA] calculando MD5 de fg-01.bin..."),
            "[VALIDATE] Calculating MD5 of fg-01.bin...",
        )
        self.assertEqual(
            translations.translate("[ERRO] não há etapa ativa registrada"),
            "[ERROR] No active step is recorded",
        )
        self.assertEqual(
            translations.translate("[ERRO] o grupo de processos registrado não existe mais"),
            "[ERROR] The recorded process group no longer exists",
        )

    def test_unknown_message_body_keeps_the_english_marker(self):
        self.assertEqual(translations.translate("[FALHOU] algo inesperado"), "[FAILED] algo inesperado")

    def test_whole_line_pattern_still_wins_over_the_marker_split(self):
        self.assertEqual(
            translations.translate("[FALHOU] data/x.pak: esperado=aa obtido=bb"),
            "[FAILED] data/x.pak: expected=aa got=bb",
        )
        self.assertEqual(
            translations.translate("[AVISO] este setup não contém QuickSFV/manifestos para preservar"),
            "[WARNING] This setup has no QuickSFV/manifests to preserve",
        )

    def test_memory_range_uses_the_english_connector(self):
        self.assertEqual(
            translations.translate("[ERRO] --srep-memory deve ficar entre 128 e 7000 MiB nesta máquina"),
            "[ERROR] --srep-memory must be between 128 and 7000 MiB on this machine",
        )
        self.assertEqual(
            translations.translate("--bzip3-threads deve ficar entre 1 e 16"),
            "--bzip3-threads must be between 1 and 16",
        )
        self.assertEqual(
            translations.translate("--memory-high deve ficar entre 512 e 7000 MiB nesta máquina"),
            "--memory-high must be between 512 and 7000 MiB on this machine",
        )
        self.assertEqual(
            translations.translate("--memory-max deve ficar entre 512 e 7000 MiB nesta máquina"),
            "--memory-max must be between 512 and 7000 MiB on this machine",
        )

    def test_execution_order_divergence_message_is_localized(self):
        self.assertEqual(
            translations.translate(
                "[ERRO] divergência na ordem de execução detectada: "
                "o rastro registra uma etapa fora da ordem do plano\n"
                "A instalação foi interrompida antes de iniciar outra etapa. "
                "Diagnóstico: /scratch/reports/runtime-divergence-1-2.json\n"
                "Se puder, envie esse relatório ao suporte para ajudar a corrigir o problema."
            ),
            "[ERROR] Execution order divergence detected: "
            "the trace records a step out of the plan's order\n"
            "The installation stopped before starting another step. "
            "Diagnostic report: /scratch/reports/runtime-divergence-1-2.json\n"
            "If you can, send this report to support to help fix the problem.",
        )


if __name__ == "__main__":
    unittest.main()
