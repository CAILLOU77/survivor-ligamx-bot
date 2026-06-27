#!/usr/bin/env python3
"""Tests para scripts/dashboard_odds.py (contexto + HTML/TXT)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "scripts"), str(ROOT / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import dashboard_odds as dash  # noqa: E402


def _filas():
    return [
        {"timestamp": "t1", "id_mercado": "evt1", "momio_1": "1.8", "momio_2": "3.5",
         "momio_3": "4.5", "true_prob_1": "0.55", "true_prob_2": "0.25",
         "true_prob_3": "0.20", "vig_pct": "6.3", "trend_1": "0", "trend_2": "0", "trend_3": "0"},
        {"timestamp": "t2", "id_mercado": "evt1", "momio_1": "2.0", "momio_2": "3.2",
         "momio_3": "4.0", "true_prob_1": "0.50", "true_prob_2": "0.27",
         "true_prob_3": "0.23", "vig_pct": "3.1", "trend_1": "1", "trend_2": "-1", "trend_3": "-1"},
    ]


class TestLatest(unittest.TestCase):
    def test_ultimo_por_mercado(self):
        ult = dash.latest_por_mercado(_filas())
        self.assertEqual(len(ult), 1)
        self.assertEqual(ult[0]["timestamp"], "t2")


class TestContexto(unittest.TestCase):
    def test_contexto_basico(self):
        ctx = dash.construir_contexto(_filas())
        self.assertEqual(ctx["total_filas"], 2)
        self.assertIn("vig_dist", ctx)
        self.assertIn("trend", ctx)
        self.assertIsNone(ctx["backtest"])

    def test_contexto_con_backtest(self):
        ctx = dash.construir_contexto(_filas(), resultados={"evt1": 1})
        self.assertIsNotNone(ctx["backtest"])
        self.assertEqual(ctx["backtest"]["n_apuestas"], 1)


class TestRender(unittest.TestCase):
    def test_html_valido(self):
        html = dash.construir_html(dash.construir_contexto(_filas()))
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("Dashboard de Momios", html)
        self.assertIn("ESPERAR / NO ENVIAR", html)

    def test_texto_mantiene_esperar(self):
        txt = dash.construir_texto(dash.construir_contexto(_filas()))
        self.assertIn("ESPERAR / NO ENVIAR", txt)
        self.assertNotIn("CERRAR", txt)

    def test_texto_incluye_backtest(self):
        ctx = dash.construir_contexto(_filas(), resultados={"evt1": 1})
        txt = dash.construir_texto(ctx)
        self.assertIn("Backtesting", txt)
        self.assertIn("ROI", txt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
