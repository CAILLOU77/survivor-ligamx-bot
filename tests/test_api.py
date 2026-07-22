#!/usr/bin/env python3
"""Tests de la capa web (src/api.py) con TestClient. DB/red mockeadas."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

SRC = str(Path(__file__).resolve().parents[1] / "src")
ROOT = str(Path(__file__).resolve().parents[1])
for p in (SRC, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("API_KEY", "testkey")  # antes de importar la app

import src.api as apimod  # noqa: E402
import src.auth as authmod  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class TestApi(unittest.TestCase):
    def setUp(self):
        authmod.API_KEY = "testkey"  # asegura auth activa en el test
        self.client = TestClient(apimod.app)

    def test_health_ok(self):
        with (
            mock.patch("src.database.get_equipos_usados", return_value=[]),
            mock.patch("requests.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("status"), "ok")

    def test_stats_sin_key_403(self):
        self.assertEqual(self.client.get("/stats").status_code, 403)

    def test_stats_con_key(self):
        mock_data = {
            "total_picks": 5,
            "wins": 3,
            "win_rate": 60.0,
            "total_profit": 12.5,
            "accuracy_1x2": 0.6,
            "accuracy_marcador": 0.2,
            "brier_score": 0.25,
            "accuracy_por_jornada": [],
            "latencia_espn_promedio_ms": 450.0,
            "total_predicciones": 5,
            "ultima_actualizacion": "2026-07-17T22:00:00",
        }
        with mock.patch.object(apimod, "get_metrics", return_value=mock_data):
            r = self.client.get("/stats", headers={"X-API-Key": "testkey"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("total_picks", r.json())
        self.assertEqual(r.json()["total_picks"], 5)

    def test_usados_get_publico(self):
        with mock.patch("src.database.get_equipos_usados", return_value=["América"]):
            r = self.client.get("/survivor/usados")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["usados"], ["América"])
        self.assertEqual(r.json()["total"], 1)

    def test_usados_post_sin_key_403(self):
        r = self.client.post("/survivor/usados", params={"equipo": "Toluca"})
        self.assertEqual(r.status_code, 403)

    def test_usados_post_con_key(self):
        with (
            mock.patch("src.database.add_equipo_usado", return_value=True),
            mock.patch("src.database.get_equipos_usados", return_value=["Toluca"]),
        ):
            r = self.client.post("/survivor/usados", params={"equipo": "Toluca"}, headers={"X-API-Key": "testkey"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["agregado"])

    def test_usados_post_sin_equipo_400(self):
        r = self.client.post("/survivor/usados", params={"equipo": "  "}, headers={"X-API-Key": "testkey"})
        self.assertEqual(r.status_code, 400)

    def test_webhook_otro_chat_no_actua(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_CHAT_ID": "111"}, clear=False):
            with mock.patch("src.telegram_pronosticos.enviar_mensaje") as menv:
                r = self.client.post("/telegram/webhook", json={"message": {"chat": {"id": 999}, "text": "/usados"}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"ok": True})
        menv.assert_not_called()

    def test_webhook_dueno_responde(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_CHAT_ID": "111", "TELEGRAM_WEBHOOK_SECRET": ""}, clear=False):
            with (
                mock.patch("src.telegram_pronosticos.enviar_mensaje") as menv,
                mock.patch("src.telegram_webhook.responder", return_value="ok") as mresp,
            ):
                r = self.client.post("/telegram/webhook", json={"message": {"chat": {"id": 111}, "text": "/usados"}})
        self.assertEqual(r.status_code, 200)
        mresp.assert_called_once()
        menv.assert_called_once()

    def test_webhook_secreto_invalido_403(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_WEBHOOK_SECRET": "s3cr3t"}, clear=False):
            r = self.client.post(
                "/telegram/webhook",
                json={"message": {"chat": {"id": 111}, "text": "/usados"}},
                headers={"X-Telegram-Bot-Api-Secret-Token": "malo"},
            )
        self.assertEqual(r.status_code, 403)


class TestAuth(unittest.TestCase):
    def setUp(self):
        authmod.API_KEY = "testkey"
        self.client = TestClient(apimod.app)

    def test_api_key_no_configurada_devuelve_503(self):
        """Si API_KEY='' (no configurada), debe dar 503"""
        authmod.API_KEY = ""
        r = self.client.get("/stats", headers={"X-API-Key": ""})
        self.assertEqual(r.status_code, 503)
        self.assertIn("API_KEY no configurada", r.json().get("detail", ""))
        authmod.API_KEY = "testkey"  # restaurar

    def test_api_key_invalida_devuelve_403(self):
        """Si API_KEY es distinta, debe dar 403"""
        r = self.client.get("/stats", headers={"X-API-Key": "wrong"})
        self.assertEqual(r.status_code, 403)
        self.assertIn("inválida", r.json().get("detail", ""))

    def test_healthcheck_devuelve_dependencias(self):
        """Healthcheck debe incluir campo 'dependencias'"""
        from unittest import mock as _mock

        with (
            _mock.patch("src.database.get_equipos_usados", return_value=[]),
            _mock.patch("requests.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("dependencias", data)
        self.assertIn("base_de_datos", data["dependencias"])
        self.assertIn("espn", data["dependencias"])
        self.assertIn("ligamx_api", data["dependencias"])

    def test_healthcheck_db_fallando_muestra_degradado(self):
        """Si la BD falla, status='degradado'"""
        from unittest import mock as _mock

        with (
            _mock.patch("src.database.get_equipos_usados", side_effect=Exception("DB caída")),
            _mock.patch("requests.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["status"], "degradado")
        self.assertIn("error", data["dependencias"]["base_de_datos"])

    def test_healthcheck_espn_fallando_muestra_degradado(self):
        """Si ESPN falla, status='degradado'"""
        from unittest import mock as _mock

        with (
            _mock.patch("src.database.get_equipos_usados", return_value=[]),
            _mock.patch("requests.get", side_effect=Exception("Timeout")),
        ):
            r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["status"], "degradado")
        self.assertIn("error", data["dependencias"]["espn"])

    def test_healthcheck_espn_5xx_muestra_degradado(self):
        """Si ESPN devuelve 502, status='degradado'"""
        from unittest import mock as _mock

        mock_resp = _mock.MagicMock()
        mock_resp.status_code = 502
        with (
            _mock.patch("src.database.get_equipos_usados", return_value=[]),
            _mock.patch("requests.get", return_value=mock_resp),
        ):
            r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["status"], "degradado")
        self.assertIn("error", data["dependencias"]["espn"])
        self.assertIn("502", data["dependencias"]["espn"])

    def test_healthcheck_ligamxapi_5xx_muestra_degradado(self):
        """Si ligamx-api devuelve 503, status='degradado'"""
        from unittest import mock as _mock

        mock_resp = _mock.MagicMock()
        mock_resp.status_code = 503
        with (
            _mock.patch("src.database.get_equipos_usados", return_value=[]),
            _mock.patch("requests.get", return_value=mock_resp),
        ):
            r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["status"], "degradado")
        self.assertIn("error", data["dependencias"]["ligamx_api"])
        self.assertIn("503", data["dependencias"]["ligamx_api"])

    def test_healthcheck_espn_timeout_muestra_degradado(self):
        """Timeout en ESPN debe dar degradado"""
        from unittest import mock as _mock

        with (
            _mock.patch("src.database.get_equipos_usados", return_value=[]),
            _mock.patch("requests.get", side_effect=Exception("Connection timeout")),
        ):
            r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["status"], "degradado")
        self.assertIn("timeout", data["dependencias"]["espn"].lower())


if __name__ == "__main__":
    unittest.main()
