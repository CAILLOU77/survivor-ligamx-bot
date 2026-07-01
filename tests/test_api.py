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
from fastapi.testclient import TestClient  # noqa: E402


class TestApi(unittest.TestCase):
    def setUp(self):
        apimod.API_KEY = "testkey"  # asegura auth activa en el test
        self.client = TestClient(apimod.app)

    def test_health_ok(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("status"), "ok")

    def test_stats_sin_key_403(self):
        self.assertEqual(self.client.get("/stats").status_code, 403)

    def test_stats_con_key(self):
        with mock.patch.object(apimod, "get_metrics", return_value={"total_picks": 0}):
            r = self.client.get("/stats", headers={"X-API-Key": "testkey"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("total_picks", r.json())

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
        with mock.patch("src.database.add_equipo_usado", return_value=True), \
             mock.patch("src.database.get_equipos_usados", return_value=["Toluca"]):
            r = self.client.post("/survivor/usados", params={"equipo": "Toluca"},
                                 headers={"X-API-Key": "testkey"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["agregado"])

    def test_usados_post_sin_equipo_400(self):
        r = self.client.post("/survivor/usados", params={"equipo": "  "},
                             headers={"X-API-Key": "testkey"})
        self.assertEqual(r.status_code, 400)

    def test_webhook_otro_chat_no_actua(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_CHAT_ID": "111"}, clear=False):
            with mock.patch("src.telegram_pronosticos.enviar_mensaje") as menv:
                r = self.client.post("/telegram/webhook",
                                     json={"message": {"chat": {"id": 999}, "text": "/usados"}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"ok": True})
        menv.assert_not_called()

    def test_webhook_dueno_responde(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_CHAT_ID": "111", "TELEGRAM_WEBHOOK_SECRET": ""}, clear=False):
            with mock.patch("src.telegram_pronosticos.enviar_mensaje") as menv, \
                 mock.patch("src.telegram_webhook.responder", return_value="ok") as mresp:
                r = self.client.post("/telegram/webhook",
                                     json={"message": {"chat": {"id": 111}, "text": "/usados"}})
        self.assertEqual(r.status_code, 200)
        mresp.assert_called_once()
        menv.assert_called_once()

    def test_webhook_secreto_invalido_403(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_WEBHOOK_SECRET": "s3cr3t"}, clear=False):
            r = self.client.post("/telegram/webhook",
                                 json={"message": {"chat": {"id": 111}, "text": "/usados"}},
                                 headers={"X-Telegram-Bot-Api-Secret-Token": "malo"})
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
