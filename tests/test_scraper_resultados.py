#!/usr/bin/env python3
"""Tests para src/scraper_resultados.py. Sin red: _get/requests mockeados; archivos en tempdir."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import scraper_resultados as sr  # noqa: E402


class TestGenerarConclusion(unittest.TestCase):
    def test_victoria_local(self):
        out = sr._generar_conclusion("América", "Toluca", 2, 0, [], [])
        self.assertIn("Victoria de América", out)
        self.assertIn("2-0", out)

    def test_victoria_visitante(self):
        out = sr._generar_conclusion("América", "Toluca", 0, 1, [], [])
        self.assertIn("Victoria de Toluca", out)

    def test_empate(self):
        out = sr._generar_conclusion("América", "Toluca", 1, 1, [], [])
        self.assertIn("Empate 1-1", out)

    def test_goles_tarjetas_expulsiones(self):
        eventos = [
            "⚽ América — Gol 1",
            "⚽ Toluca — Gol 1",
            "🟨 Toluca — Amarilla",
            "🟥 Toluca — Roja",
        ]
        out = sr._generar_conclusion("América", "Toluca", 2, 1, eventos, [])
        self.assertIn("Goles (2)", out)
        self.assertIn("Tarjetas (2)", out)  # 🟨 y 🟥 cuentan como tarjetas
        self.assertIn("Expulsiones", out)

    def test_fuentes_web(self):
        out = sr._generar_conclusion("A", "B", 1, 0, [], [{"titulo": "t", "fuente": "f"}])
        self.assertIn("Fuentes consultadas", out)


class TestGetPost(unittest.TestCase):
    def test_get_200_devuelve_json(self):
        fake = mock.Mock(status_code=200)
        fake.json.return_value = {"a": 1}
        with mock.patch.object(sr, "requests") as rq:
            rq.get.return_value = fake
            self.assertEqual(sr._get("http://x"), {"a": 1})

    def test_get_no_200_devuelve_none(self):
        with mock.patch.object(sr, "requests") as rq:
            rq.get.return_value = mock.Mock(status_code=500)
            self.assertIsNone(sr._get("http://x"))

    def test_get_sin_requests_devuelve_none(self):
        with mock.patch.object(sr, "requests", None):
            self.assertIsNone(sr._get("http://x"))

    def test_post_200_devuelve_texto(self):
        with mock.patch.object(sr, "requests") as rq:
            rq.post.return_value = mock.Mock(status_code=200, text="ok")
            self.assertEqual(sr._post("http://x"), "ok")


def _espn_sample(estado="STATUS_FULL_TIME", hg="2", ag="1"):
    return {
        "events": [
            {
                "id": "1",
                "date": "2026-07-16T20:00Z",
                "status": {"type": {"name": estado}},
                "competitions": [
                    {
                        "competitors": [
                            {"homeAway": "home", "team": {"displayName": "América"}, "score": hg},
                            {"homeAway": "away", "team": {"displayName": "Toluca"}, "score": ag},
                        ]
                    }
                ],
            }
        ]
    }


class TestObtenerPartidosEspn(unittest.TestCase):
    def test_parsea_partido_finalizado(self):
        with mock.patch.object(sr, "_get", return_value=_espn_sample()):
            partidos = sr.obtener_partidos_espn("20260716", delta_dias=0)
        self.assertEqual(len(partidos), 1)
        p = partidos[0]
        self.assertEqual(p["home_team"], "América")
        self.assertEqual(p["away_team"], "Toluca")
        self.assertEqual(p["home_goals"], 2)
        self.assertEqual(p["away_goals"], 1)
        self.assertEqual(p["fuente"], "espn")

    def test_sin_datos_devuelve_vacio(self):
        with mock.patch.object(sr, "_get", return_value=None):
            self.assertEqual(sr.obtener_partidos_espn("20260716", delta_dias=0), [])

    def test_ignora_no_finalizados(self):
        with mock.patch.object(sr, "_get", return_value=_espn_sample(estado="STATUS_IN_PROGRESS")):
            self.assertEqual(sr.obtener_partidos_espn("20260716", delta_dias=0), [])


class TestGuardarCargar(unittest.TestCase):
    def test_roundtrip_guardar_cargar(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "res.json")
            with mock.patch.object(sr, "RESULTADOS_PATH", path):
                sr.guardar_resultados({"x": 1, "lista": [1, 2]})
                self.assertTrue(os.path.exists(path))
                data = sr.cargar_resultados()
            self.assertEqual(data, {"x": 1, "lista": [1, 2]})

    def test_cargar_sin_archivo_devuelve_vacio(self):
        with mock.patch.object(sr, "RESULTADOS_PATH", "/tmp/no_existe_xyz_123.json"):
            self.assertEqual(sr.cargar_resultados(), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
