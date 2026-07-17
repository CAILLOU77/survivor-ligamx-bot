#!/usr/bin/env python3
"""Tests para src/routers/api_ligamx.py (API pública unificada de Liga MX).

Llaman a las funciones de endpoint directamente, con el histórico y el
calendario inyectados (sin red, sin servidor).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

import fastapi

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import importlib

api = importlib.import_module("routers.api_ligamx")


def _fake_resultados():
    # Mini-histórico: América y Guadalajara con varios enfrentamientos.
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
            {
                "fecha": "2025-03-10",
                "home_team": "Guadalajara",
                "away_team": "América",
                "home_goals": 0,
                "away_goals": 0,
            },
            {"fecha": "2024-11-05", "home_team": "América", "away_team": "Toluca", "home_goals": 3, "away_goals": 0},
            {
                "fecha": "2024-10-01",
                "home_team": "Toluca",
                "away_team": "Guadalajara",
                "home_goals": 1,
                "away_goals": 1,
            },
            {
                "fecha": "2024-09-01",
                "home_team": "Guadalajara",
                "away_team": "Toluca",
                "home_goals": 2,
                "away_goals": 0,
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
                {"home_team": "Toluca", "away_team": "Atlante"},
            ],
        },
        {
            "jornada": 2,
            "fecha_inicio": "2026-07-21",
            "fecha_fin": "2026-07-26",
            "partidos": [
                {"home_team": "Guadalajara", "away_team": "Toluca"},
                {"home_team": "Atlante", "away_team": "América"},
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
        self.assertIn("endpoints", r)
        self.assertEqual(r["decision"], "INFORMATIVO / REVISIÓN HUMANA")

    def test_equipos_lista_y_modelo(self):
        r = api.equipos()
        nombres = {e["equipo"] for e in r["equipos"]}
        self.assertIn("América", nombres)
        self.assertIn("Atlante", nombres)
        # Atlante no tiene histórico => sin modelo; América sí.
        modelo = {e["equipo"]: e["tiene_modelo"] for e in r["equipos"]}
        self.assertFalse(modelo["Atlante"])
        self.assertTrue(modelo["América"])

    def test_calendario_completo(self):
        r = api.calendario_completo()
        self.assertEqual(r["jornadas_total"], 2)
        self.assertEqual(r["jornadas"][0]["jornada"], 1)

    def test_calendario_jornada_con_predicciones(self):
        r = api.calendario_jornada(1, predicciones=True)
        self.assertEqual(r["jornada"], 1)
        # América vs Guadalajara: ambos con modelo => predicción presente.
        ag = next(p for p in r["partidos"] if p["home_team"] == "América")
        self.assertIsNotNone(ag["prediccion"])
        # Toluca vs Atlante: Atlante sin modelo => predicción None.
        ta = next(p for p in r["partidos"] if p["away_team"] == "Atlante")
        self.assertIsNone(ta["prediccion"])

    def test_calendario_jornada_inexistente(self):
        with self.assertRaises(fastapi.HTTPException) as ctx:
            api.calendario_jornada(99)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_equipo_detalle_y_alias(self):
        # Alias "chivas" -> Guadalajara.
        r = api.equipo_detalle("chivas")
        self.assertEqual(r["equipo"], "Guadalajara")
        self.assertTrue(r["tiene_modelo"])
        self.assertEqual(r["partidos_calendario"], 2)

    def test_equipo_sin_acento(self):
        r = api.equipo_detalle("america")
        self.assertEqual(r["equipo"], "América")

    def test_equipo_no_encontrado(self):
        with self.assertRaises(fastapi.HTTPException) as ctx:
            api.equipo_detalle("Barcelona")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_h2h_historico_y_modelo(self):
        r = api.head_to_head(local="america", visitante="chivas")
        self.assertEqual(r["local"], "América")
        self.assertEqual(r["visitante"], "Guadalajara")
        hist = r["historico"]
        self.assertEqual(hist["partidos"], 2)
        self.assertEqual(hist["victorias_América"], 1)
        self.assertEqual(hist["victorias_Guadalajara"], 0)
        self.assertEqual(hist["empates"], 1)
        self.assertIsNotNone(r["prediccion_modelo"])

    def test_h2h_mismo_equipo(self):
        with self.assertRaises(fastapi.HTTPException) as ctx:
            api.head_to_head(local="america", visitante="aguilas")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_h2h_equipo_inexistente(self):
        with self.assertRaises(fastapi.HTTPException) as ctx:
            api.head_to_head(local="america", visitante="real madrid")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_resultados(self):
        r = api.resultados(meses=2)
        self.assertEqual(r["total"], 5)
        self.assertEqual(r["fuente"], "ESPN (test)")

    def test_jornada_actual_pretemporada(self):
        r = api.jornada_actual(fecha="2026-07-01")
        self.assertEqual(r["estado"], "pretemporada")
        self.assertIsNone(r["jornada_actual"])
        self.assertEqual(r["jornada_proxima"], 1)
        self.assertEqual(r["jornada_objetivo"]["jornada"], 1)
        self.assertEqual(r["dias_para_proxima"], 15)

    def test_jornada_actual_en_curso(self):
        r = api.jornada_actual(fecha="2026-07-17")
        self.assertEqual(r["estado"], "en_curso")
        self.assertEqual(r["jornada_actual"], 1)
        self.assertEqual(r["jornada_objetivo"]["jornada"], 1)

    def test_jornada_actual_entre_jornadas(self):
        r = api.jornada_actual(fecha="2026-07-20")
        self.assertEqual(r["estado"], "entre_jornadas")
        self.assertIsNone(r["jornada_actual"])
        self.assertEqual(r["ultima_jugada"], 1)
        self.assertEqual(r["jornada_objetivo"]["jornada"], 2)

    def test_jornada_actual_terminada(self):
        r = api.jornada_actual(fecha="2026-12-01")
        self.assertEqual(r["estado"], "temporada_terminada")
        self.assertEqual(r["ultima_jugada"], 2)
        self.assertIsNone(r["jornada_objetivo"])

    def test_jornada_actual_con_predicciones(self):
        r = api.jornada_actual(fecha="2026-07-17", predicciones=True)
        partidos = r["jornada_objetivo"]["partidos"]
        ag = next(p for p in partidos if p["home_team"] == "América")
        self.assertIn("prediccion", ag)
        self.assertIsNotNone(ag["prediccion"])

    def test_jornada_actual_fecha_invalida(self):
        with self.assertRaises(fastapi.HTTPException) as ctx:
            api.jornada_actual(fecha="no-es-fecha")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_cache_evita_recalcular(self):
        with mock.patch.object(api.fuentes_mod, "obtener_resultados", return_value=_fake_resultados()) as m:
            api._CACHE["fuerzas"] = None
            api._CACHE["ts"] = None
            api.equipos()
            api.equipos()
            self.assertEqual(m.call_count, 1)  # 2a vez usa caché


if __name__ == "__main__":
    unittest.main(verbosity=2)
