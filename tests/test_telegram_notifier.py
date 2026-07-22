#!/usr/bin/env python3
"""Tests para src/telegram_notifier.py (notificador de pronósticos). Sin red: httpx mockeado."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import telegram_notifier as tn  # noqa: E402


class _FakeClient:
    """Cliente httpx asíncrono fake parametrizable."""

    def __init__(self, get_resp=None, post_capture=None):
        self._get_resp = get_resp
        self._post_capture = post_capture

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url):
        return self._get_resp

    async def post(self, url, json=None):
        if self._post_capture is not None:
            self._post_capture["url"] = url
            self._post_capture["json"] = json
        return mock.Mock()


class TestNotifyPredicciones(unittest.TestCase):
    def test_sin_credenciales_no_envia(self):
        with mock.patch.object(tn, "TELEGRAM_TOKEN", None), mock.patch.object(tn, "CHAT_ID", None):
            self.assertIsNone(asyncio.run(tn.notify_predicciones()))

    def test_sin_pronosticos_no_envia(self):
        get_resp = mock.Mock()
        get_resp.json.return_value = {"pronosticos": []}
        get_resp.raise_for_status.return_value = None
        capture = {}
        fake = _FakeClient(get_resp=get_resp, post_capture=capture)
        with mock.patch.object(tn, "TELEGRAM_TOKEN", "tok"), mock.patch.object(tn, "CHAT_ID", "chat"), \
             mock.patch.object(tn.httpx, "AsyncClient", lambda *a, **k: fake):
            asyncio.run(tn.notify_predicciones())
        self.assertNotIn("url", capture)  # nunca se envió a Telegram

    def test_con_pronosticos_envia_a_telegram(self):
        data = {"pronosticos": [{"local": "A", "visitante": "B"}], "total_pronosticos": 1}
        get_resp = mock.Mock()
        get_resp.json.return_value = data
        get_resp.raise_for_status.return_value = None
        capture = {}
        fake = _FakeClient(get_resp=get_resp, post_capture=capture)
        with mock.patch.object(tn, "TELEGRAM_TOKEN", "tok"), mock.patch.object(tn, "CHAT_ID", "chat"), \
             mock.patch.object(tn.httpx, "AsyncClient", lambda *a, **k: fake), \
             mock.patch.object(tn.telegram_pronosticos, "construir_mensaje", return_value="<b>msg</b>"):
            asyncio.run(tn.notify_predicciones())
        self.assertIn("tok", capture["url"])
        self.assertEqual(capture["json"]["chat_id"], "chat")
        self.assertEqual(capture["json"]["text"], "<b>msg</b>")


if __name__ == "__main__":
    unittest.main(verbosity=2)
