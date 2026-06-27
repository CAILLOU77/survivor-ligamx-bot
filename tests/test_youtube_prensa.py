#!/usr/bin/env python3
"""
Tests para src/youtube_prensa.py.

No hacen red real: requests.get está mockeado. Cubren relevancia, parseo por
fecha, búsqueda y errores, y que el resumen conserva ESPERAR / NO ENVIAR sin
imprimir secretos.
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import youtube_prensa as yp  # noqa: E402


def _fake_response(status=200, items=None):
    resp = mock.Mock()
    resp.status_code = status
    resp.json.return_value = {"items": items or []}
    return resp


def _item(video_id, titulo, canal, publicado_iso):
    return {
        "id": {"videoId": video_id},
        "snippet": {"title": titulo, "channelTitle": canal, "publishedAt": publicado_iso},
    }


class TestHabilitado(unittest.TestCase):
    def test_default_false(self):
        os.environ["YOUTUBE_ENABLED"] = "false"
        self.assertFalse(yp.youtube_habilitado())

    def test_true(self):
        os.environ["YOUTUBE_ENABLED"] = "true"
        self.assertTrue(yp.youtube_habilitado())


class TestRelevancia(unittest.TestCase):
    def test_relevante(self):
        self.assertTrue(yp._es_relevante("Conferencia de prensa de Cruz Azul"))
        self.assertTrue(yp._es_relevante("RUEDA DE PRENSA previa al clásico"))
        self.assertTrue(yp._es_relevante("Declaraciones del técnico"))

    def test_no_relevante(self):
        self.assertFalse(yp._es_relevante("Gol de último minuto vs Toluca"))
        self.assertFalse(yp._es_relevante("Resumen de la jornada"))


class TestParseoRespuesta(unittest.TestCase):
    def _cutoff(self):
        return datetime.now(timezone.utc) - timedelta(hours=24)

    def test_filtra_por_fecha(self):
        reciente = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        viejo = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
        data = {"items": [
            _item("a", "Conferencia de prensa América", "TUDN", reciente),
            _item("b", "Conferencia de prensa Pumas", "ESPN", viejo),
        ]}
        regs = yp._parsear_respuesta(data, self._cutoff())
        ids = {r["video_id"] for r in regs}
        self.assertIn("a", ids)
        self.assertNotIn("b", ids)

    def test_filtra_por_relevancia(self):
        reciente = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        data = {"items": [
            _item("a", "Conferencia de prensa Tigres", "Canal", reciente),
            _item("b", "Mejores goles de la fecha", "Canal", reciente),
        ]}
        regs = yp._parsear_respuesta(data, self._cutoff(), solo_relevantes=True)
        self.assertEqual([r["video_id"] for r in regs], ["a"])

    def test_construye_link(self):
        reciente = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        data = {"items": [_item("xyz", "Conferencia de prensa", "C", reciente)]}
        regs = yp._parsear_respuesta(data, self._cutoff())
        self.assertEqual(regs[0]["link"], "https://www.youtube.com/watch?v=xyz")

    def test_item_invalido_se_ignora(self):
        regs = yp._parsear_respuesta({"items": [{}, "ruido"]}, self._cutoff())
        self.assertEqual(regs, [])


class TestBuscarConferencias(unittest.TestCase):
    def setUp(self):
        os.environ["YOUTUBE_API_KEY"] = "dummy_key"

    @mock.patch("youtube_prensa.requests.get")
    def test_busca_y_devuelve(self, mock_get):
        reciente = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        mock_get.return_value = _fake_response(
            items=[_item("a", "Conferencia de prensa Chivas", "TUDN", reciente)]
        )
        regs = yp.buscar_conferencias()
        self.assertEqual(len(regs), 1)
        self.assertEqual(regs[0]["canal"], "TUDN")

    @mock.patch("youtube_prensa.requests.get")
    def test_http_error_lanza(self, mock_get):
        mock_get.return_value = _fake_response(status=403)
        with self.assertRaises(RuntimeError):
            yp.buscar_conferencias()

    def test_sin_api_key_lanza(self):
        os.environ["YOUTUBE_API_KEY"] = ""
        with self.assertRaises(RuntimeError):
            yp.buscar_conferencias()

    def test_sin_requests_lanza(self):
        original = yp.requests
        try:
            yp.requests = None
            with self.assertRaises(RuntimeError):
                yp.buscar_conferencias()
        finally:
            yp.requests = original


class TestResumen(unittest.TestCase):
    def test_resumen_mantiene_esperar(self):
        regs = [{
            "fuente": "YouTube", "titulo": "Conferencia X", "canal": "TUDN",
            "publicado": "2026-07-16T10:00:00+00:00", "video_id": "a",
            "link": "https://www.youtube.com/watch?v=a",
        }]
        out = yp.resumen_conferencias(regs)
        self.assertIn("ESPERAR / NO ENVIAR", out)
        self.assertNotIn("CERRAR", out)

    def test_resumen_vacio(self):
        out = yp.resumen_conferencias([])
        self.assertIn("Sin conferencias", out)
        self.assertIn("ESPERAR / NO ENVIAR", out)

    def test_resumen_sin_secretos(self):
        os.environ["YOUTUBE_API_KEY"] = "SUPER_SECRETO_123"
        out = yp.resumen_conferencias([])
        self.assertNotIn("SUPER_SECRETO_123", out)
        self.assertNotIn("YOUTUBE_API_KEY", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
