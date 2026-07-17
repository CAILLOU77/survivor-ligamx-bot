from pathlib import Path
import importlib.util
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "final_security_gate.py"
SPEC = importlib.util.spec_from_file_location("final_security_gate", MODULE_PATH)
final_security_gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = final_security_gate
assert SPEC.loader is not None
SPEC.loader.exec_module(final_security_gate)


class FinalSecurityGateTests(unittest.TestCase):
    def test_allows_esperar_no_enviar_marker(self):
        result = final_security_gate.validate_report_text("Reporte final\nDecisión operativa: ESPERAR / NO ENVIAR\n")

        self.assertTrue(result.ok)
        self.assertEqual(result.exit_code, 0)

    def test_allows_ready_for_full_audit_no_auto_send_marker(self):
        result = final_security_gate.validate_report_text("Estado: READY_FOR_FULL_AUDIT / NO ENVIAR AUTOMÁTICO\n")

        self.assertTrue(result.ok)
        self.assertEqual(result.exit_code, 0)

    def test_blocks_report_without_safe_marker(self):
        result = final_security_gate.validate_report_text("Reporte final sin etiqueta operativa segura.")

        self.assertFalse(result.ok)
        self.assertEqual(result.exit_code, 2)

    def test_blocks_forbidden_close_signal_even_with_safe_marker(self):
        result = final_security_gate.validate_report_text(
            "Decisión operativa: ESPERAR / NO ENVIAR\nError peligroso: CERRAR pick."
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.exit_code, 3)

    def test_allows_negated_no_cerrar_context(self):
        result = final_security_gate.validate_report_text(
            "Decisión operativa: ESPERAR / NO ENVIAR\nControl: NO CERRAR pick automáticamente."
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.exit_code, 0)

    def test_allows_negated_no_enviar_pick_context(self):
        result = final_security_gate.validate_report_text(
            "Decisión operativa: ESPERAR / NO ENVIAR\nControl: NO ENVIAR PICK automáticamente."
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.exit_code, 0)

    def test_blocks_forbidden_enviar_pick_signal(self):
        result = final_security_gate.validate_report_text(
            "Decisión operativa: ESPERAR / NO ENVIAR\nTexto peligroso: ENVIAR PICK."
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.exit_code, 3)

    def test_blocks_betting_signal_even_with_safe_marker(self):
        result = final_security_gate.validate_report_text(
            "Decisión operativa: ESPERAR / NO ENVIAR\nTexto peligroso: apostar."
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.exit_code, 3)

    def test_missing_report_file_returns_no_send(self):
        missing_path = Path(tempfile.gettempdir()) / "missing_survivor_report_final.txt"
        if missing_path.exists():
            missing_path.unlink()

        result = final_security_gate.validate_report_file(missing_path)

        self.assertFalse(result.ok)
        self.assertEqual(result.exit_code, 1)


if __name__ == "__main__":
    unittest.main()
