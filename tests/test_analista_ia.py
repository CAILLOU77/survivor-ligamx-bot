#!/usr/bin/env python3
"""Tests para src/analista_ia.py (capa IA Groq). Sin red: requests mockeado."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import analista_ia as ia  # noqa: E402


def _resp(status=200, content='{"riesgos":[],"sin_senales":true}'):
    r = mock.Mock()
    r.status_code = status
    r.json.return_value = {"choices": [{"message": {"content": content}}]}
    return r


_NEWS = [
    {"titulo": "Toluca: duda de último minuto por lesión de su delantero", "fuente": "365Scores"},
    {"titulo": "América llega completo al clásico", "fuente": "MARCA"},
]


class TestHabilitado(unittest.TestCase):
    def test_sin_key_apagado(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(ia.habilitado())

    def test_con_key_encendido(self):
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "x"}, clear=True):
            self.assertTrue(ia.habilitado())

    def test_lee_key_primary_backup(self):
        with mock.patch.dict(os.environ, {"GROQ_API_KEY_PRIMARY": "p"}, clear=True):
            self.assertEqual(ia._api_key(), "p")

    def test_enabled_false_fuerza_apagado(self):
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "x", "GROQ_ENABLED": "false"}, clear=True):
            self.assertFalse(ia.habilitado())


class TestAnalizar(unittest.TestCase):
    def test_desactivado_sin_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            r = ia.analizar_noticias(["América", "Toluca"], _NEWS)
        self.assertFalse(r["disponible"])

    def test_sin_noticias(self):
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "x"}, clear=True):
            r = ia.analizar_noticias(["América", "Toluca"], [])
        self.assertFalse(r["disponible"])

    def test_extrae_riesgos(self):
        content = (
            '{"riesgos":[{"equipo":"Toluca","tipo":"lesion","jugador":"X",'
            '"resumen":"Duda por lesión","titulo_fuente":"Toluca: duda..."}],'
            '"sin_senales":false}'
        )
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "x"}, clear=True):
            with mock.patch.object(ia.requests, "post", return_value=_resp(content=content)):
                r = ia.analizar_noticias(["América", "Toluca"], _NEWS)
        self.assertTrue(r["disponible"])
        self.assertEqual(len(r["riesgos"]), 1)
        self.assertEqual(r["riesgos"][0]["equipo"], "Toluca")
        self.assertEqual(r["riesgos"][0]["tipo"], "lesion")

    def test_sin_senales(self):
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "x"}, clear=True):
            with mock.patch.object(ia.requests, "post", return_value=_resp()):
                r = ia.analizar_noticias(["América", "Toluca"], _NEWS)
        self.assertTrue(r["disponible"])
        self.assertEqual(r["riesgos"], [])
        self.assertTrue(r["sin_senales"])

    def test_http_error_tolerante(self):
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "x"}, clear=True):
            with mock.patch.object(ia.requests, "post", return_value=_resp(status=500)):
                r = ia.analizar_noticias(["América", "Toluca"], _NEWS)
        self.assertFalse(r["disponible"])

    def test_excepcion_tolerante(self):
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "x"}, clear=True):
            with mock.patch.object(ia.requests, "post", side_effect=Exception("boom")):
                r = ia.analizar_noticias(["América", "Toluca"], _NEWS)
        self.assertFalse(r["disponible"])


if __name__ == "__main__":
    unittest.main()
