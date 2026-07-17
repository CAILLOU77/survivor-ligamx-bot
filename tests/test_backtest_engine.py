#!/usr/bin/env python3
"""Tests para src/backtest_engine.py (validación honesta, sin inventar). Sin red."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import backtest_engine as be  # noqa: E402


class TestRunBacktest(unittest.TestCase):
    def test_usa_validacion_real_no_random(self):
        datos = {"fuente": "ESPN", "resultados": [{"x": 1}]}
        validacion = {
            "accuracy": 0.49,
            "brier_promedio": 0.63,
            "baseline_local": 0.45,
            "mejor_que_baseline": True,
            "n_evaluados": 100,
        }
        with (
            mock.patch.object(be.fuentes_datos, "obtener_resultados", return_value=datos) as m_datos,
            mock.patch.object(be.validacion_modelo, "evaluar_modelo", return_value=dict(validacion)) as m_eval,
        ):
            r = be.run_backtest()
        m_datos.assert_called_once()
        m_eval.assert_called_once()
        self.assertEqual(r["accuracy"], 0.49)
        self.assertEqual(r["fuente_datos"], "ESPN")
        self.assertIn("nota", r)

    def test_no_importa_random(self):
        # Garantía anti-regresión: el motor ya no debe fabricar resultados.
        import inspect

        fuente = inspect.getsource(be)
        self.assertNotIn("import random", fuente)
        self.assertNotIn("random.random(", fuente)


if __name__ == "__main__":
    unittest.main(verbosity=2)
