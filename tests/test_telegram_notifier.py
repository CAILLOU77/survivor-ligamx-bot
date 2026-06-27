#!/usr/bin/env python3
"""
Tests para src/telegram_notifier.py: división de mensajes y modo --dry-run.

El dry-run valida el reporte con el safety gate y muestra lo que se ENVIARÍA
sin llamar a la red. No modifica la lógica de producción.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "telegram_notifier.py"
SPEC = importlib.util.spec_from_file_location("telegram_notifier", MODULE_PATH)
telegram_notifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = telegram_notifier
assert SPEC.loader is not None
SPEC.loader.exec_module(telegram_notifier)

tn = telegram_notifier


class TestDividirTexto(unittest.TestCase):
    def test_texto_corto_una_parte(self):
        partes = tn.dividir_texto("hola mundo", max_chars=100)
        self.assertEqual(partes, ["hola mundo"])

    def test_texto_largo_se_divide(self):
        texto = "aaaa\nbbbb\ncccc"  # 14 chars
        partes = tn.dividir_texto(texto, max_chars=10)
        self.assertEqual(len(partes), 2)
        self.assertEqual(partes[0], "aaaa\nbbbb")
        self.assertEqual(partes[1], "cccc")

    def test_cada_parte_respeta_maximo(self):
        texto = "\n".join(["linea de prueba"] * 60)
        partes = tn.dividir_texto(texto, max_chars=80)
        self.assertTrue(len(partes) > 1)
        for parte in partes:
            self.assertLessEqual(len(parte), 80)

    def test_reconstruye_contenido(self):
        texto = "\n".join(f"linea {i}" for i in range(40))
        partes = tn.dividir_texto(texto, max_chars=50)
        # Al unir las partes (sin los espacios recortados) se conservan todas las líneas.
        unido = "\n".join(partes)
        for i in range(40):
            self.assertIn(f"linea {i}", unido)


class TestDryRun(unittest.TestCase):
    def _write_report(self, text: str) -> Path:
        handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
        with handle:
            handle.write(text)
        return Path(handle.name)

    def _run(self, report_path: Path, env=None):
        base_env = {"TELEGRAM_BOT_TOKEN": "dummy", "TELEGRAM_CHAT_ID": "dummy"}
        if env is not None:
            base_env = env
        with mock.patch.dict(os.environ, base_env, clear=False):
            argv = ["telegram_notifier.py", "--report", str(report_path), "--dry-run"]
            with mock.patch.object(sys, "argv", argv):
                with mock.patch.object(tn, "enviar_mensaje") as enviar_mock:
                    code = tn.main()
        return code, enviar_mock

    def test_dry_run_no_envia_reporte_seguro(self):
        report = self._write_report(
            "Reporte final\nDecisión operativa: ESPERAR / NO ENVIAR\n"
        )
        code, enviar_mock = self._run(report)
        self.assertEqual(code, 0)
        enviar_mock.assert_not_called()

    def test_dry_run_no_envia_reporte_peligroso(self):
        report = self._write_report(
            "Reporte final\nDecisión operativa: ESPERAR / NO ENVIAR\nCERRAR pick\n"
        )
        code, enviar_mock = self._run(report)
        # El safety gate detecta señal prohibida -> exit 3, pero NO se envía nada.
        self.assertEqual(code, 3)
        enviar_mock.assert_not_called()

    def test_dry_run_funciona_sin_credenciales(self):
        # Sin token/chat_id, el dry-run igual valida y previsualiza (no envía).
        report = self._write_report(
            "Reporte final\nDecisión operativa: ESPERAR / NO ENVIAR\n"
        )
        code, enviar_mock = self._run(
            report, env={"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}
        )
        self.assertEqual(code, 0)
        enviar_mock.assert_not_called()


class TestEnvioNormalSigueFuncionando(unittest.TestCase):
    """Regresión: sin --dry-run, el envío normal sigue intacto."""

    def _write_report(self, text: str) -> Path:
        handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
        with handle:
            handle.write(text)
        return Path(handle.name)

    def test_envio_normal_llama_enviar(self):
        report = self._write_report(
            "Reporte final\nDecisión operativa: ESPERAR / NO ENVIAR\n"
        )
        env = {"TELEGRAM_BOT_TOKEN": "dummy", "TELEGRAM_CHAT_ID": "dummy"}
        with mock.patch.dict(os.environ, env, clear=False):
            argv = ["telegram_notifier.py", "--report", str(report)]
            with mock.patch.object(sys, "argv", argv):
                with mock.patch.object(tn, "enviar_mensaje") as enviar_mock:
                    code = tn.main()
        self.assertEqual(code, 0)
        enviar_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
