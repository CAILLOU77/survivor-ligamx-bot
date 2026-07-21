#!/usr/bin/env python3
"""Tests para src/routers/cron_router.py (endpoint /cron/backtest con auth). Sin red ni BD."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = str(Path(__file__).resolve().parents[1])
SRC = str(Path(__file__).resolve().parents[1] / "src")
for p in (SRC, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("RATE_LIMIT_ENABLED", "false")  # el limiter no estorba en tests

import src.auth as authmod  # noqa: E402
from src.routers import cron_router  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(cron_router.router)
    return app


class TestCronBacktestAuth(unittest.TestCase):
    def setUp(self):
        authmod.API_KEY = "testkey"
        self.client = TestClient(_app())

    def tearDown(self):
        authmod.API_KEY = "testkey"

    def test_sin_key_devuelve_403(self):
        self.assertEqual(self.client.post("/cron/backtest").status_code, 403)

    def test_key_invalida_devuelve_403(self):
        r = self.client.post("/cron/backtest", headers={"X-API-Key": "wrong"})
        self.assertEqual(r.status_code, 403)

    def test_api_key_no_configurada_devuelve_503(self):
        authmod.API_KEY = ""
        r = self.client.post("/cron/backtest", headers={"X-API-Key": "x"})
        self.assertEqual(r.status_code, 503)
        self.assertIn("no configurada", r.json().get("detail", ""))

    def test_con_key_ejecuta_backtest(self):
        # run_backtest mockeado; el bloque de settle falla controladamente (sin red).
        with mock.patch.object(cron_router, "run_backtest", return_value={"ok": True}), \
             mock.patch("fuentes_datos.obtener_resultados", side_effect=RuntimeError("sin red en tests"), create=True):
            r = self.client.post("/cron/backtest", headers={"X-API-Key": "testkey"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["validacion"], {"ok": True})
        self.assertIn("settle_error", body)  # el settle cayó en el except, no tumbó el endpoint


if __name__ == "__main__":
    unittest.main(verbosity=2)
