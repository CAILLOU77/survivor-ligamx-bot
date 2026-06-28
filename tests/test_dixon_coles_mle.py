#!/usr/bin/env python3
"""Tests para src/dixon_coles_mle.py (Dixon-Coles por MLE). Requiere scipy."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

try:
    import numpy  # noqa: F401
    import scipy  # noqa: F401
    _DEPS = True
except ImportError:  # pragma: no cover
    _DEPS = False

import dixon_coles_mle as dc  # noqa: E402


def _liga_sintetica(repeticiones=6):
    # Fuerte gana casi siempre, Debil pierde casi siempre.
    base = [
        ("Fuerte", "Medio", 3, 0), ("Fuerte", "Debil", 4, 0),
        ("Medio", "Debil", 2, 1), ("Medio", "Fuerte", 0, 2),
        ("Debil", "Fuerte", 0, 3), ("Debil", "Medio", 1, 2),
    ]
    out = []
    dia = 1
    for _ in range(repeticiones):
        for h, a, hg, ag in base:
            out.append({"home_team": h, "away_team": a, "home_goals": hg,
                        "away_goals": ag, "fecha": f"2026-03-{dia:02d}"})
            dia += 1
    return out


@unittest.skipUnless(_DEPS, "numpy/scipy no instalados")
class TestAjuste(unittest.TestCase):
    def test_ajusta_y_devuelve_estructura(self):
        modelo = dc.ajustar_dixon_coles(_liga_sintetica())
        for k in ("equipos", "gamma", "rho", "n_partidos"):
            self.assertIn(k, modelo)
        self.assertIn("fuerte", modelo["equipos"])
        self.assertIn("ataque", modelo["equipos"]["fuerte"])

    def test_equipo_fuerte_mayor_ataque(self):
        modelo = dc.ajustar_dixon_coles(_liga_sintetica())
        self.assertGreater(
            modelo["equipos"]["fuerte"]["ataque"],
            modelo["equipos"]["debil"]["ataque"],
        )

    def test_sin_partidos_lanza(self):
        with self.assertRaises(ValueError):
            dc.ajustar_dixon_coles([])

    def test_goles_esperados_fuerte_vs_debil(self):
        modelo = dc.ajustar_dixon_coles(_liga_sintetica())
        lam, mu = dc.goles_esperados(modelo, "Fuerte", "Debil")
        self.assertGreater(lam, mu)


@unittest.skipUnless(_DEPS, "numpy/scipy no instalados")
class TestPronostico(unittest.TestCase):
    def test_pronostico_completo_y_suma_100(self):
        modelo = dc.ajustar_dixon_coles(_liga_sintetica())
        r = dc.pronostico(modelo, "Fuerte", "Debil")
        for k in ("prob_local_pct", "prob_empate_pct", "prob_visitante_pct",
                  "pick_1x2", "pick_ou", "pick_btts", "marcador_mas_probable"):
            self.assertIn(k, r)
        total = r["prob_local_pct"] + r["prob_empate_pct"] + r["prob_visitante_pct"]
        self.assertAlmostEqual(total, 100.0, places=1)
        self.assertEqual(r["modelo"], "dixon_coles_mle")

    def test_fuerte_es_favorito(self):
        modelo = dc.ajustar_dixon_coles(_liga_sintetica())
        r = dc.pronostico(modelo, "Fuerte", "Debil")
        self.assertEqual(r["pick_1x2"], "Gana Local")

    def test_equipo_desconocido_no_rompe(self):
        modelo = dc.ajustar_dixon_coles(_liga_sintetica())
        r = dc.pronostico(modelo, "Equipo Nuevo", "Otro Nuevo")
        total = r["prob_local_pct"] + r["prob_empate_pct"] + r["prob_visitante_pct"]
        self.assertAlmostEqual(total, 100.0, places=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
