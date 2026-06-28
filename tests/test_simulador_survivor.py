#!/usr/bin/env python3
"""Tests para src/simulador_survivor.py (backtest del juego Survivor). Sin red."""
from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import simulador_survivor as ss  # noqa: E402


def _liga(n_semanas=8):
    """Liga sintética: una jornada por semana ISO; 'Fuerte' gana siempre de local."""
    out = []
    d0 = date(2026, 1, 6)  # lunes
    for w in range(n_semanas):
        d = (d0 + timedelta(days=7 * w)).isoformat()
        out.append({"home_team": "Fuerte", "away_team": "Debil",
                    "home_goals": 3, "away_goals": 0, "fecha": d})
        out.append({"home_team": "Medio", "away_team": "Otro",
                    "home_goals": 2, "away_goals": 1, "fecha": d})
    return out


class TestHelpers(unittest.TestCase):
    def test_semana_iso(self):
        self.assertEqual(ss._semana_iso("2026-01-06"), "2026-W02")
        self.assertIsNone(ss._semana_iso("basura"))

    def test_agrupar_jornadas_ordenadas(self):
        js = ss.agrupar_jornadas(_liga(3))
        self.assertEqual(len(js), 3)
        semanas = [j["jornada"] for j in js]
        self.assertEqual(semanas, sorted(semanas))

    def test_sobrevive_local_y_visita(self):
        gana_local = {"home_goals": 2, "away_goals": 0}
        self.assertTrue(ss._sobrevive(gana_local, es_local=True))
        self.assertFalse(ss._sobrevive(gana_local, es_local=False))
        empate = {"home_goals": 1, "away_goals": 1}
        self.assertTrue(ss._sobrevive(empate, es_local=True))
        self.assertTrue(ss._sobrevive(empate, es_local=False))


class TestSimulacion(unittest.TestCase):
    def test_estructura_y_juega(self):
        r = ss.simular_temporada(_liga(8), min_train=2)
        for k in ("jornadas_jugadas", "jornadas_sobrevividas", "eliminado_en",
                  "detalle", "decision"):
            self.assertIn(k, r)
        self.assertGreaterEqual(r["jornadas_jugadas"], 1)
        self.assertEqual(r["decision"], "INFORMATIVO / REVISIÓN HUMANA")
        if r["detalle"]:
            d = r["detalle"][0]
            for k in ("jornada", "pick", "condicion", "partido", "sobrevivio"):
                self.assertIn(k, d)

    def test_no_repite_equipos(self):
        r = ss.simular_temporada(_liga(8), min_train=2)
        picks = [d["pick"] for d in r["detalle"]]
        self.assertEqual(len(picks), len(set(picks)))  # nunca repite pick

    def test_datos_insuficientes_no_juega(self):
        r = ss.simular_temporada(_liga(1), min_train=50)
        self.assertEqual(r["jornadas_jugadas"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
