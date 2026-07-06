#!/usr/bin/env python3
"""Tests para comparador_mercado.mezclar_pronosticos_con_mercado. Sin red."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import comparador_mercado as cm  # noqa: E402


def _pron():
    return [{
        "local": "América", "visitante": "Toluca",
        "prob_local_pct": 50.0, "prob_empate_pct": 25.0, "prob_visitante_pct": 25.0,
        "no_perder_local_pct": 75.0, "no_perder_visitante_pct": 50.0,
        "pick_1x2": "Gana Local", "prob_over_pct": 55.0,
    }]


class TestMezcla(unittest.TestCase):
    def test_mezcla_mueve_hacia_mercado(self):
        clave = cm._clave_partido("América", "Toluca")
        # Local MUY favorito en el mercado (momio bajo).
        momios = {clave: {"ml": {"local": 1.2, "empate": 6.0, "visita": 12.0}}}
        out = cm.mezclar_pronosticos_con_mercado(_pron(), momios=momios, peso_modelo=0.0)
        p = out[0]
        # Solo mercado: prob_local sube muy por encima del 50% del modelo.
        self.assertGreater(p["prob_local_pct"], 60.0)
        self.assertAlmostEqual(
            p["prob_local_pct"] + p["prob_empate_pct"] + p["prob_visitante_pct"],
            100.0, places=1)
        # no-perder coherente con las probs mezcladas.
        self.assertAlmostEqual(p["no_perder_local_pct"],
                               p["prob_local_pct"] + p["prob_empate_pct"], places=2)
        self.assertIn("mezcla_mercado", p)

    def test_mitad_y_mitad_queda_entre_modelo_y_mercado(self):
        clave = cm._clave_partido("América", "Toluca")
        momios = {clave: {"ml": {"local": 1.2, "empate": 6.0, "visita": 12.0}}}
        out = cm.mezclar_pronosticos_con_mercado(_pron(), momios=momios, peso_modelo=0.5)
        # Con 50/50, prob_local queda entre el modelo (50) y el mercado (~77).
        self.assertGreater(out[0]["prob_local_pct"], 50.0)
        self.assertLess(out[0]["prob_local_pct"], 77.0)

    def test_sin_momios_no_cambia(self):
        out = cm.mezclar_pronosticos_con_mercado(_pron(), momios={}, peso_modelo=0.5)
        self.assertEqual(out[0]["prob_local_pct"], 50.0)
        self.assertNotIn("mezcla_mercado", out[0])

    def test_partido_sin_mercado_se_queda_igual(self):
        clave = cm._clave_partido("Otro", "Equipo")
        momios = {clave: {"ml": {"local": 1.5, "empate": 4.0, "visita": 6.0}}}
        out = cm.mezclar_pronosticos_con_mercado(_pron(), momios=momios, peso_modelo=0.5)
        # El partido América-Toluca no tiene momios en el dict -> sin cambio.
        self.assertEqual(out[0]["prob_local_pct"], 50.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
