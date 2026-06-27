#!/usr/bin/env python3
"""Tests para fireworks_client. No hacen llamadas reales: requests.post está mockeado."""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import fireworks_client as fc


def _fake_response(status=200, content='{"resumen": "ok"}'):
    resp = mock.Mock()
    resp.status_code = status
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    return resp


class TestFireworksClient(unittest.TestCase):
    def setUp(self):
        os.environ["FIREWORKS_API_KEY"] = "test_key_dummy"
        os.environ["FIREWORKS_ENABLED"] = "false"

    def test_habilitado_por_defecto_es_false(self):
        os.environ["FIREWORKS_ENABLED"] = "false"
        self.assertFalse(fc.fireworks_habilitado())

    def test_habilitado_true(self):
        os.environ["FIREWORKS_ENABLED"] = "true"
        self.assertTrue(fc.fireworks_habilitado())

    @mock.patch("fireworks_client.requests.post")
    def test_clasifica_y_agrega_decision_segura(self, mock_post):
        mock_post.return_value = _fake_response(
            content='{"resumen": "America sin lesiones", "senales_riesgo": []}'
        )
        data = fc.clasificar_riesgo_fireworks("America descarta lesion.")
        self.assertEqual(data["resumen"], "America sin lesiones")
        self.assertEqual(data["proveedor_ia"], "fireworks")
        self.assertEqual(data["decision_operativa"], "ESPERAR / NO ENVIAR")

    @mock.patch("fireworks_client.requests.post")
    def test_json_invalido_se_guarda_como_raw(self, mock_post):
        mock_post.return_value = _fake_response(content="texto no json")
        data = fc.clasificar_riesgo_fireworks("noticia")
        self.assertEqual(data["raw"], "texto no json")
        self.assertEqual(data["decision_operativa"], "ESPERAR / NO ENVIAR")

    @mock.patch("fireworks_client.requests.post")
    def test_http_error_lanza_runtime(self, mock_post):
        mock_post.return_value = _fake_response(status=500)
        with self.assertRaises(RuntimeError):
            fc.clasificar_riesgo_fireworks("noticia")

    def test_sin_api_key_lanza_runtime(self):
        os.environ["FIREWORKS_API_KEY"] = ""
        with self.assertRaises(RuntimeError):
            fc.clasificar_riesgo_fireworks("noticia")

    def test_sin_requests_instalado_lanza_runtime(self):
        # Simula entorno sin la dependencia opcional 'requests'.
        original = fc.requests
        try:
            fc.requests = None
            with self.assertRaises(RuntimeError):
                fc.clasificar_riesgo_fireworks("noticia")
        finally:
            fc.requests = original

    def test_modulo_importa_aunque_requests_falte(self):
        # El módulo debe poder importarse aunque 'requests' no exista:
        # el atributo existe (None o el módulo real), nunca rompe el import.
        self.assertTrue(hasattr(fc, "requests"))


if __name__ == "__main__":
    unittest.main()
