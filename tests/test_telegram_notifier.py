#!/usr/bin/env python3
"""Pruebas del cliente asíncrono de pronósticos, sin acceso a la red."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock

import httpx

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import telegram_notifier as tn  # noqa: E402


class _FakeClient:
    """Cliente httpx asíncrono configurable para la consulta a la API."""

    def __init__(self, get_resp=None, get_error: Exception | None = None):
        self._get_resp = get_resp
        self._get_error = get_error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url):
        if self._get_error is not None:
            raise self._get_error
        return self._get_resp


def _respuesta(data):
    respuesta = mock.Mock()
    respuesta.json.return_value = data
    respuesta.raise_for_status.return_value = None
    return respuesta


class TestNotifyPredicciones(unittest.TestCase):
    def test_sin_credenciales_no_envia(self):
        with (
            mock.patch.object(tn, "TELEGRAM_TOKEN", None),
            mock.patch.object(tn, "CHAT_ID", None),
            mock.patch.object(tn.telegram_pronosticos, "enviar_mensaje") as enviar,
        ):
            self.assertFalse(asyncio.run(tn.notify_predicciones()))
        enviar.assert_not_called()

    def test_sin_pronosticos_no_envia(self):
        fake = _FakeClient(get_resp=_respuesta({"pronosticos": []}))
        with (
            mock.patch.object(tn, "TELEGRAM_TOKEN", "tok"),
            mock.patch.object(tn, "CHAT_ID", "chat"),
            mock.patch.object(tn.httpx, "AsyncClient", lambda *args, **kwargs: fake),
            mock.patch.object(tn.telegram_pronosticos, "enviar_mensaje") as enviar,
        ):
            self.assertFalse(asyncio.run(tn.notify_predicciones()))
        enviar.assert_not_called()

    def test_formato_invalido_no_envia(self):
        fake = _FakeClient(get_resp=_respuesta(["no", "es", "objeto"]))
        with (
            mock.patch.object(tn, "TELEGRAM_TOKEN", "tok"),
            mock.patch.object(tn, "CHAT_ID", "chat"),
            mock.patch.object(tn.httpx, "AsyncClient", lambda *args, **kwargs: fake),
            mock.patch.object(tn.telegram_pronosticos, "enviar_mensaje") as enviar,
        ):
            self.assertFalse(asyncio.run(tn.notify_predicciones()))
        enviar.assert_not_called()

    def test_con_pronosticos_usa_entrega_comun_idempotente(self):
        data = {"pronosticos": [{"local": "A", "visitante": "B"}], "total_pronosticos": 1}
        fake = _FakeClient(get_resp=_respuesta(data))
        with (
            mock.patch.object(tn, "TELEGRAM_TOKEN", "tok"),
            mock.patch.object(tn, "CHAT_ID", "chat"),
            mock.patch.object(tn.httpx, "AsyncClient", lambda *args, **kwargs: fake),
            mock.patch.object(tn.telegram_pronosticos, "construir_mensaje", return_value="<b>msg</b>"),
            mock.patch.object(tn.telegram_pronosticos, "enviar_mensaje", return_value=True) as enviar,
        ):
            self.assertTrue(asyncio.run(tn.notify_predicciones()))

        enviar.assert_called_once()
        self.assertEqual(enviar.call_args.args[0], "<b>msg</b>")
        self.assertTrue(enviar.call_args.kwargs["idempotency_key"].startswith("notifier:predicciones:"))

    def test_mismo_lote_genera_la_misma_llave(self):
        data = {"pronosticos": [{"visitante": "B", "local": "A"}], "total_pronosticos": 1}
        self.assertEqual(tn._clave_predicciones(data), tn._clave_predicciones(dict(data)))

    def test_rechazo_de_entrega_se_reporta_como_fallo(self):
        data = {"pronosticos": [{"local": "A", "visitante": "B"}]}
        fake = _FakeClient(get_resp=_respuesta(data))
        with (
            mock.patch.object(tn, "TELEGRAM_TOKEN", "tok"),
            mock.patch.object(tn, "CHAT_ID", "chat"),
            mock.patch.object(tn.httpx, "AsyncClient", lambda *args, **kwargs: fake),
            mock.patch.object(tn.telegram_pronosticos, "construir_mensaje", return_value="msg"),
            mock.patch.object(tn.telegram_pronosticos, "enviar_mensaje", return_value=False),
        ):
            self.assertFalse(asyncio.run(tn.notify_predicciones()))

    def test_timeout_no_expone_el_token(self):
        fake = _FakeClient(get_error=httpx.ReadTimeout("url con tok-super-secreto"))
        with (
            mock.patch.object(tn, "TELEGRAM_TOKEN", "tok-super-secreto"),
            mock.patch.object(tn, "CHAT_ID", "chat"),
            mock.patch.object(tn.httpx, "AsyncClient", lambda *args, **kwargs: fake),
            mock.patch("builtins.print") as imprimir,
        ):
            self.assertFalse(asyncio.run(tn.notify_predicciones()))

        salida = " ".join(str(arg) for llamada in imprimir.call_args_list for arg in llamada.args)
        self.assertNotIn("tok-super-secreto", salida)
        self.assertIn("ReadTimeout", salida)


if __name__ == "__main__":
    unittest.main(verbosity=2)
