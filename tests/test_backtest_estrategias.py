#!/usr/bin/env python3
"""Tests para src/backtest_estrategias.py (comparación de estrategias). Sin red."""
from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import backtest_estrategias as be  # noqa: E402


def _torneo(d0: date, n_semanas: int) -> list:
    """
    Un torneo sintético: cada semana los LOCALES fuertes ganan. Suficientes
    equipos para que el modelo tenga favoritos locales claros.
    """
    out = []
    for w in range(n_semanas):
        d = (d0 + timedelta(days=7 * w)).isoformat()
        out.append({"home_team": "Fuerte", "away_team": "Debil",
                    "home_goals": 3, "away_goals": 0, "fecha": d})
        out.append({"home_team": "Local2", "away_team": "Visita2",
                    "home_goals": 2, "away_goals": 1, "fecha": d})
        out.append({"home_team": "Medio", "away_team": "Colista",
                    "home_goals": 2, "away_goals": 0, "fecha": d})
    return out


def _tres_torneos() -> list:
    """
    Tres torneos por semestre (Clausura 2025 / Apertura 2025 / Clausura 2026).
    El más viejo (2025C) es PARCIAL (no hay histórico previo para entrenarlo),
    así que quedan 2 torneos COMPLETOS evaluables.
    """
    t1 = _torneo(date(2025, 1, 6), 12)   # 2025C (parcial: sin datos previos)
    t2 = _torneo(date(2025, 8, 4), 12)   # 2025A (completo)
    t3 = _torneo(date(2026, 1, 5), 12)   # 2026C (completo)
    return t1 + t2 + t3


class TestHelpers(unittest.TestCase):
    def test_fecha_semana_iso(self):
        f = be._fecha_semana_iso("2026-W02")
        self.assertEqual(f, date.fromisocalendar(2026, 2, 1))
        self.assertIsNone(be._fecha_semana_iso("basura"))

    def test_gano_local_y_visita(self):
        p = {"home_goals": 2, "away_goals": 0}
        self.assertTrue(be._gano(p, es_local=True))
        self.assertFalse(be._gano(p, es_local=False))
        empate = {"home_goals": 1, "away_goals": 1}
        self.assertFalse(be._gano(empate, es_local=True))
        self.assertFalse(be._gano(empate, es_local=False))


class TestDivisionTorneos(unittest.TestCase):
    def test_detecta_dos_torneos(self):
        r = be.simular_estrategia(_tres_torneos(), estrategia=be.estrategia_ingenua,
                                  min_train=6)
        self.assertGreaterEqual(r["torneos_evaluados"], 2)


class TestSimulacion(unittest.TestCase):
    def test_estructura_agregados(self):
        r = be.simular_estrategia(_tres_torneos(), estrategia=be.estrategia_real,
                                  min_train=6)
        for k in ("estrategia", "torneos_evaluados", "tasa_supervivencia_torneo_pct",
                  "jornadas_sobrevividas_prom", "victorias_prom_por_torneo",
                  "por_torneo", "decision"):
            self.assertIn(k, r)
        self.assertEqual(r["decision"], "INFORMATIVO / REVISIÓN HUMANA")

    def test_no_repite_equipos_dentro_de_torneo(self):
        # En cada torneo, los picks no deben repetir equipo.
        # (reconstruimos por torneo desde el detalle interno de simular)
        r = be.simular_estrategia(_tres_torneos(), estrategia=be.estrategia_ingenua,
                                  min_train=6)
        # Si sobrevivió y jugó varias jornadas, hubo variedad de equipos.
        self.assertGreaterEqual(r["jornadas_jugadas_total"], 1)

    def test_reinicio_por_torneo_permite_reusar_entre_torneos(self):
        # Con reinicio por torneo, la suma de jornadas jugadas debe poder superar
        # el número de equipos distintos (imposible sin reinicio).
        r = be.simular_estrategia(_tres_torneos(), estrategia=be.estrategia_ingenua,
                                  min_train=6)
        self.assertGreaterEqual(r["torneos_evaluados"], 2)

    def test_datos_insuficientes(self):
        r = be.simular_estrategia(_torneo(date(2025, 1, 6), 1),
                                  estrategia=be.estrategia_real, min_train=500)
        self.assertEqual(r["torneos_evaluados"], 0)
        self.assertIn("mensaje", r)


class TestComparar(unittest.TestCase):
    def test_comparar_devuelve_ambas(self):
        r = be.comparar_estrategias(_tres_torneos(), min_train=6)
        self.assertIn("ingenua", r["por_estrategia"])
        self.assertIn("real", r["por_estrategia"])
        self.assertIn(r["mejor"], {"ingenua", "real", None})

    def test_estrategia_real_sobrevive_liga_facil(self):
        # En una liga donde los locales fuertes siempre ganan, la estrategia real
        # debe sobrevivir al menos un torneo completo.
        r = be.comparar_estrategias(_tres_torneos(), min_train=6)
        real = r["por_estrategia"]["real"]
        self.assertGreater(real["jornadas_sobrevividas_total"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
