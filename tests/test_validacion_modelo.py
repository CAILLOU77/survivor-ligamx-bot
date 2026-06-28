#!/usr/bin/env python3
"""Tests para src/validacion_modelo.py (backtesting del modelo). Sin red."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import validacion_modelo as vm  # noqa: E402


class TestResultado1x2(unittest.TestCase):
    def test_local(self):
        self.assertEqual(vm._resultado_1x2(2, 0), 1)

    def test_empate(self):
        self.assertEqual(vm._resultado_1x2(1, 1), 2)

    def test_visita(self):
        self.assertEqual(vm._resultado_1x2(0, 3), 3)


def _liga(n_repeticiones=4):
    # Liga sintética con fechas crecientes; Fuerte casi siempre gana.
    base = [
        ("Fuerte", "Debil", 3, 0), ("Medio", "Debil", 2, 1),
        ("Debil", "Medio", 0, 2), ("Fuerte", "Medio", 2, 0),
        ("Medio", "Fuerte", 0, 1), ("Debil", "Fuerte", 0, 3),
    ]
    out = []
    dia = 1
    for _ in range(n_repeticiones):
        for h, a, hg, ag in base:
            out.append({"home_team": h, "away_team": a, "home_goals": hg,
                        "away_goals": ag, "fecha": f"2026-02-{dia:02d}"})
            dia += 1
    return out


class TestEvaluarModelo(unittest.TestCase):
    def test_datos_insuficientes(self):
        r = vm.evaluar_modelo([{"home_team": "A", "away_team": "B",
                                "home_goals": 1, "away_goals": 0, "fecha": "2026-01-01"}])
        self.assertEqual(r["n_evaluados"], 0)

    def test_evalua_y_reporta_metricas(self):
        r = vm.evaluar_modelo(_liga(), fraccion_test=0.3)
        self.assertGreater(r["n_evaluados"], 0)
        for k in ("accuracy", "brier_promedio", "baseline_local", "mejor_que_baseline"):
            self.assertIn(k, r)
        self.assertTrue(0.0 <= r["accuracy"] <= 1.0)
        self.assertEqual(r["decision"], "INFORMATIVO / REVISIÓN HUMANA")

    def test_no_entrena_con_futuro(self):
        # El train debe ser menor al total (no usa todo para entrenar).
        datos = _liga()
        r = vm.evaluar_modelo(datos, fraccion_test=0.3)
        self.assertLess(r["n_train"], len(datos))


if __name__ == "__main__":
    unittest.main(verbosity=2)
