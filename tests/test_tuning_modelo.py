#!/usr/bin/env python3
"""Tests para src/tuning_modelo.py (afinación de hiperparámetros). Sin red."""
from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import tuning_modelo as tm  # noqa: E402


def _historico(n=200):
    """Liga sintética con estructura estable para que el tuning corra."""
    import random
    random.seed(7)
    equipos = ["A", "B", "C", "D", "E", "F"]
    out = []
    d0 = date(2023, 1, 7)
    for i in range(n):
        h, a = random.sample(equipos, 2)
        # A y B fuertes de local; el resto parejo.
        hg = random.choice([2, 3, 1]) if h in ("A", "B") else random.choice([0, 1, 2])
        ag = random.choice([0, 1]) if h in ("A", "B") else random.choice([0, 1, 2])
        out.append({"home_team": h, "away_team": a, "home_goals": hg,
                    "away_goals": ag, "fecha": (d0 + timedelta(days=3 * i)).isoformat()})
    return out


class TestTuning(unittest.TestCase):
    def test_estructura(self):
        r = tm.tunear_hiperparametros(
            _historico(200),
            grid_half=(365.0,), grid_shrink=(4.0,), grid_rho=(-0.10,),
        )
        for k in ("actuales", "sugeridos", "brier_holdout_actual",
                  "brier_holdout_sugerido", "aplicar", "decision"):
            self.assertIn(k, r)
        self.assertIn("half_life_dias", r["sugeridos"])

    def test_datos_insuficientes(self):
        r = tm.tunear_hiperparametros(_historico(20))
        self.assertIn("mensaje", r)

    def test_brier_conjunto_devuelve_valor(self):
        h = _historico(120)
        br, n = tm._brier_conjunto(h[:80], h[80:], 365.0, 4.0, -0.10)
        self.assertIsNotNone(br)
        self.assertGreater(n, 0)
        self.assertGreater(br, 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
