#!/usr/bin/env python3
"""Tests para src/motor_pronosticos.py (cerebro de pronósticos). Sin red."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import motor_pronosticos as mp  # noqa: E402


def _historico():
    return [
        {"home_team": "América", "away_team": "Toluca", "home_goals": 3, "away_goals": 0},
        {"home_team": "América", "away_team": "Atlas", "home_goals": 2, "away_goals": 1},
        {"home_team": "Toluca", "away_team": "Atlas", "home_goals": 1, "away_goals": 1},
        {"home_team": "Toluca", "away_team": "América", "home_goals": 0, "away_goals": 2},
        {"home_team": "Atlas", "away_team": "América", "home_goals": 0, "away_goals": 3},
        {"home_team": "Atlas", "away_team": "Toluca", "home_goals": 1, "away_goals": 1},
    ]


class TestGenerar(unittest.TestCase):
    def test_genera_pronosticos(self):
        fixtures = [{"home_team": "América", "away_team": "Toluca", "fecha": "2026-07-18"}]
        res = mp.generar_pronosticos(fixtures=fixtures, resultados=_historico())
        self.assertEqual(res["total_pronosticos"], 1)
        p = res["pronosticos"][0]
        self.assertIn("pick_1x2", p)
        self.assertIn("no_perder_local_pct", p)
        self.assertEqual(res["decision"], "INFORMATIVO / REVISIÓN HUMANA")

    def test_equipo_desconocido_se_omite(self):
        fixtures = [{"home_team": "Equipo Inventado", "away_team": "Otro Raro", "fecha": "x"}]
        res = mp.generar_pronosticos(fixtures=fixtures, resultados=_historico())
        self.assertEqual(res["total_pronosticos"], 0)

    def test_sin_resultados_no_revienta(self):
        res = mp.generar_pronosticos(fixtures=[{"home_team": "A", "away_team": "B"}], resultados=[])
        self.assertEqual(res["total_pronosticos"], 0)

    def test_no_perder_es_suma_coherente(self):
        fixtures = [{"home_team": "América", "away_team": "Toluca", "fecha": "x"}]
        p = mp.generar_pronosticos(fixtures=fixtures, resultados=_historico())["pronosticos"][0]
        self.assertAlmostEqual(
            p["no_perder_local_pct"], round(p["prob_local_pct"] + p["prob_empate_pct"], 2), places=1
        )


class TestSurvivor(unittest.TestCase):
    def _pronos(self):
        return [
            {"local": "América", "visitante": "Toluca", "no_perder_local_pct": 85.0,
             "no_perder_visitante_pct": 40.0},
            {"local": "Atlas", "visitante": "Pumas", "no_perder_local_pct": 55.0,
             "no_perder_visitante_pct": 60.0},
        ]

    def test_elige_mayor_no_perder(self):
        pick = mp.mejor_pick_survivor(self._pronos())
        self.assertEqual(pick["equipo"], "América")
        self.assertEqual(pick["no_perder_pct"], 85.0)

    def test_excluye_usados(self):
        pick = mp.mejor_pick_survivor(self._pronos(), equipos_usados=["América"])
        # Excluido América -> el siguiente mejor es Pumas (60) como visitante.
        self.assertEqual(pick["equipo"], "Pumas")

    def test_sin_candidatos(self):
        self.assertIsNone(mp.mejor_pick_survivor([]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
