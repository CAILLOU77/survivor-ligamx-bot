#!/usr/bin/env python3
"""Tests para src/routers/api_ligamx.py (API pública unificada de Liga MX)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

import fastapi

ROOT = str(Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import src.routers.api_ligamx as api


def _fake_resultados():
    return {
        "fuente": "ESPN (test)",
        "resultados": [
            {
                "fecha": "2025-08-01",
                "home_team": "América",
                "away_team": "Guadalajara",
                "home_goals": 2,
                "away_goals": 1,
            },
        ],
    }


def _fake_calendario():
    return [
        {
            "jornada": 1,
            "fecha_inicio": "2026-07-16",
            "fecha_fin": "2026-07-18",
            "partidos": [
                {"home_team": "América", "away_team": "Guadalajara"},
            ],
        },
    ]


class TestApiLigaMX(unittest.TestCase):
    def setUp(self):
        api._CACHE["datos"] = None
        api._CACHE["fuerzas"] = None
        api._CACHE["ts"] = None
        self.p_res = mock.patch.object(api.fuentes_mod, "obtener_resultados", return_value=_fake_resultados())
        self.p_cal = mock.patch.object(api.plan_mod, "cargar_calendario", return_value=_fake_calendario())
        self.p_res.start()
        self.p_cal.start()

    def tearDown(self):
        self.p_res.stop()
        self.p_cal.stop()

    def test_indice(self):
        r = api.indice()
        self.assertIn("Apertura 2026", r["nombre"])

    def test_equipos(self):
        r = api.equipos()
        self.assertGreaterEqual(r["total"], 1)
        self.assertEqual(r["equipos"][0]["equipo"], "América")

    def test_equipo_detalle(self):
        r = api.equipo_detalle("América")
        self.assertEqual(r["equipo"], "América")
        self.assertIn("calendario", r)

    def test_equipo_no_encontrado(self):
        with self.assertRaises(fastapi.HTTPException) as ctx:
            api.equipo_detalle("Equipo Inexistente")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_h2h_mismo_equipo(self):
        with self.assertRaises(fastapi.HTTPException) as ctx:
            api.head_to_head(local="América", visitante="América")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_h2h_equipo_inexistente(self):
        with self.assertRaises(fastapi.HTTPException) as ctx:
            api.head_to_head(local="América", visitante="Inexistente")
        self.assertEqual(ctx.exception.status_code, 404)

if __name__ == "__main__":
    unittest.main()
