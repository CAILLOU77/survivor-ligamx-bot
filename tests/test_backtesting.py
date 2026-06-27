#!/usr/bin/env python3
"""Tests para src/backtesting.py (ROI, Win Rate, Brier, distribución VIG)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import backtesting as bt  # noqa: E402


class TestGanancia(unittest.TestCase):
    def test_gana(self):
        self.assertAlmostEqual(bt.ganancia_apuesta(2.5, True), 1.5)

    def test_pierde(self):
        self.assertAlmostEqual(bt.ganancia_apuesta(2.5, False), -1.0)

    def test_cuota_invalida(self):
        with self.assertRaises(ValueError):
            bt.ganancia_apuesta(1.0, True)


class TestRoiWinRate(unittest.TestCase):
    def test_roi_positivo(self):
        # 1 gana a 3.0 (+2), 1 pierde (-1) -> neto +1 en 2 apuestas -> ROI 0.5
        apuestas = [{"odds": 3.0, "gano": True}, {"odds": 2.0, "gano": False}]
        self.assertAlmostEqual(bt.roi(apuestas), 0.5)

    def test_win_rate(self):
        apuestas = [{"odds": 2, "gano": True}, {"odds": 2, "gano": False},
                    {"odds": 2, "gano": True}]
        self.assertAlmostEqual(bt.win_rate(apuestas), 2 / 3)

    def test_vacio(self):
        self.assertEqual(bt.roi([]), 0.0)
        self.assertEqual(bt.win_rate([]), 0.0)


class TestBrier(unittest.TestCase):
    def test_perfecto_es_cero(self):
        self.assertAlmostEqual(bt.brier_score([1.0, 0.0, 0.0], 1), 0.0)

    def test_peor_caso(self):
        # Predijo 100% local pero ganó visitante -> 1 + 0 + 1 = 2.0
        self.assertAlmostEqual(bt.brier_score([1.0, 0.0, 0.0], 3), 2.0)

    def test_resultado_invalido(self):
        with self.assertRaises(ValueError):
            bt.brier_score([0.5, 0.3, 0.2], 4)

    def test_promedio(self):
        items = [{"prob": [1.0, 0, 0], "resultado": 1},
                 {"prob": [0, 0, 1.0], "resultado": 3}]
        self.assertAlmostEqual(bt.brier_promedio(items), 0.0)


class TestEstrategiaYEvaluacion(unittest.TestCase):
    def test_estrategia_favorito(self):
        fila = {"true_prob_1": 0.6, "true_prob_2": 0.25, "true_prob_3": 0.15}
        self.assertEqual(bt.estrategia_favorito(fila), 1)

    def test_evaluar_dataset(self):
        filas = [
            {"momio_1": 1.8, "momio_2": 3.5, "momio_3": 4.5,
             "true_prob_1": 0.55, "true_prob_2": 0.25, "true_prob_3": 0.20, "resultado": 1},
            {"momio_1": 2.5, "momio_2": 3.2, "momio_3": 2.8,
             "true_prob_1": 0.40, "true_prob_2": 0.28, "true_prob_3": 0.32, "resultado": 3},
        ]
        r = bt.evaluar_dataset(filas)
        self.assertEqual(r["n_apuestas"], 2)
        self.assertEqual(r["aciertos"], 1)   # acierta el 1o (favorito local gana), falla el 2o
        self.assertIn("roi", r)
        self.assertEqual(r["decision"], "ESPERAR / NO ENVIAR")

    def test_ignora_filas_sin_resultado(self):
        filas = [{"momio_1": 1.8, "momio_2": 3.5, "momio_3": 4.5,
                  "true_prob_1": 0.5, "true_prob_2": 0.3, "true_prob_3": 0.2}]
        r = bt.evaluar_dataset(filas)
        self.assertEqual(r["n_apuestas"], 0)


class TestDistribucionVig(unittest.TestCase):
    def test_histograma(self):
        dist = bt.distribucion_vig([2.0, 4.0, 4.5, 8.0], bins=(0, 3, 5, 7, 10))
        # 2.0->[0,3); 4.0,4.5->[3,5); 8.0->[7,10)
        por_rango = {d["rango"]: d["conteo"] for d in dist}
        self.assertEqual(por_rango["0-3%"], 1)
        self.assertEqual(por_rango["3-5%"], 2)
        self.assertEqual(por_rango["7-10%"], 1)

    def test_incluye_limite_superior(self):
        dist = bt.distribucion_vig([10.0], bins=(0, 5, 10))
        self.assertEqual(dist[-1]["conteo"], 1)


class TestResumenTrend(unittest.TestCase):
    def test_cuenta_direcciones(self):
        filas = [
            {"trend_1": 1, "trend_2": -1, "trend_3": 0},
            {"trend_1": 1, "trend_2": 0, "trend_3": 0},
        ]
        r = bt.resumen_trend(filas)
        self.assertEqual(r["trend_1"]["subio"], 2)
        self.assertEqual(r["trend_2"]["bajo"], 1)
        self.assertEqual(r["trend_3"]["estable"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
