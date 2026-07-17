#!/usr/bin/env python3
"""Tests para src/altitud.py (factor de altitud). Sin red."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import altitud as alt  # noqa: E402


class TestFactorAltitud(unittest.TestCase):
    def test_gran_diferencia_da_factor_positivo(self):
        # Toluca (2660) recibe a Mazatlán (10): diferencia enorme -> boost.
        f = alt.factor_altitud("Toluca", "Mazatlán")
        self.assertGreater(f, 0.0)
        self.assertLessEqual(f, alt.CAP_ALTITUD)

    def test_misma_altura_sin_factor(self):
        # Toluca (2660) vs Pumas (2280): diferencia < umbral -> 0.
        self.assertEqual(alt.factor_altitud("Toluca", "Pumas"), 0.0)

    def test_equipo_desconocido_sin_factor(self):
        self.assertEqual(alt.factor_altitud("Equipo Fantasma", "Toluca"), 0.0)

    def test_visitante_de_altura_no_boost(self):
        # Mazatlán (10) recibe a Toluca (2660): el LOCAL es el de baja altura -> 0.
        self.assertEqual(alt.factor_altitud("Mazatlán", "Toluca"), 0.0)


class TestAplicarAltitud(unittest.TestCase):
    def test_sube_prob_local_cuando_aplica(self):
        pron = {
            "local": "Toluca",
            "visitante": "Mazatlán",
            "lambda_local": 1.5,
            "lambda_visitante": 1.2,
            "prob_local_pct": 45.0,
            "prob_empate_pct": 27.0,
            "prob_visitante_pct": 28.0,
        }
        out = alt.aplicar_altitud(pron)
        self.assertGreater(out["prob_local_pct"], 45.0)
        self.assertIn("ajuste_altitud", out)
        self.assertAlmostEqual(
            out["prob_local_pct"] + out["prob_empate_pct"] + out["prob_visitante_pct"], 100.0, places=1
        )

    def test_sin_aplicar_no_cambia(self):
        pron = {
            "local": "Toluca",
            "visitante": "Pumas",
            "lambda_local": 1.4,
            "lambda_visitante": 1.3,
            "prob_local_pct": 40.0,
            "prob_empate_pct": 30.0,
            "prob_visitante_pct": 30.0,
        }
        out = alt.aplicar_altitud(pron)
        self.assertNotIn("ajuste_altitud", out)
        self.assertEqual(out["prob_local_pct"], 40.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
