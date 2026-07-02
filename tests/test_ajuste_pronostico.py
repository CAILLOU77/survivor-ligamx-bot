#!/usr/bin/env python3
"""Tests de ajuste_pronostico: ajuste moderado y con tope (lineup + H2H)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import ajuste_pronostico as aj  # noqa: E402


def _pron():
    return {
        "local": "América", "visitante": "Toluca",
        "prob_local_pct": 55.0, "prob_empate_pct": 25.0, "prob_visitante_pct": 20.0,
        "goles_esperados_local": 1.8, "goles_esperados_visitante": 1.1,
        "pick_1x2": "Gana Local", "prob_pick_pct": 55.0, "nivel_confianza": "ALTA",
        "no_perder_local_pct": 80.0, "no_perder_visitante_pct": 45.0,
    }


class TestFactorLineup(unittest.TestCase):
    def test_xi_completo_sin_recorte(self):
        self.assertEqual(aj.factor_lineup(100.0), 0.0)

    def test_deficit_con_tope(self):
        # fuerza 50% -> deficit 50 -> 0.5*0.6=0.30 pero CAP=0.15
        self.assertAlmostEqual(aj.factor_lineup(50.0), 0.15)

    def test_deficit_pequeno(self):
        # fuerza 90% -> deficit 10 -> 0.1*0.6=0.06
        self.assertAlmostEqual(aj.factor_lineup(90.0), 0.06)

    def test_none_sin_recorte(self):
        self.assertEqual(aj.factor_lineup(None), 0.0)


class TestSinSenales(unittest.TestCase):
    def test_sin_impacto_ni_h2h_no_ajusta(self):
        r = aj.ajustar_pronostico(_pron())
        self.assertFalse(r["ajuste"]["aplicado"])
        self.assertEqual(r["prob_local_pct"], 55.0)

    def test_xi_no_disponible_no_ajusta(self):
        # impacto vacío -> sin recorte
        r = aj.ajustar_pronostico(_pron(), impacto_equipos={})
        self.assertFalse(r["ajuste"]["aplicado"])


class TestAjusteLineup(unittest.TestCase):
    def test_favorito_debilitado_baja_su_prob(self):
        impacto = {"América": {"fuerza_xi_pct": 60.0}, "Toluca": {"fuerza_xi_pct": 100.0}}
        base = _pron()
        r = aj.ajustar_pronostico(base, impacto_equipos=impacto)
        self.assertTrue(r["ajuste"]["aplicado"])
        # América (local) pierde ataque -> baja su prob de ganar vs base
        self.assertLess(r["prob_local_pct"], base["prob_local_pct"])
        # goles esperados del local recortados
        self.assertLess(r["goles_esperados_local"], base["goles_esperados_local"])

    def test_ajuste_acotado_no_voltea(self):
        # Aun con XI muy incompleto (tope 15%), un favorito claro sigue siendo favorito.
        impacto = {"América": {"fuerza_xi_pct": 0.0}, "Toluca": {"fuerza_xi_pct": 100.0}}
        r = aj.ajustar_pronostico(_pron(), impacto_equipos=impacto)
        self.assertEqual(r["pick_1x2"], "Gana Local")  # no se volteó


class TestAjusteH2H(unittest.TestCase):
    def test_dominio_local_empuja(self):
        h2h = {"team1": {"name": "América", "wins": 6}, "team2": {"name": "Toluca", "wins": 0},
               "played": 8, "draws": 2}
        base = _pron()
        r = aj.ajustar_pronostico(base, h2h=h2h)
        self.assertTrue(r["ajuste"]["aplicado"])
        self.assertGreater(r["prob_local_pct"], base["prob_local_pct"])

    def test_muestra_insuficiente_no_ajusta(self):
        h2h = {"team1": {"name": "América", "wins": 3}, "team2": {"name": "Toluca", "wins": 0},
               "played": 4, "draws": 1}
        r = aj.ajustar_pronostico(_pron(), h2h=h2h)
        self.assertFalse(r["ajuste"]["aplicado"])

    def test_bestia_negra_baja_al_favorito(self):
        # El rival domina históricamente al favorito local -> baja su prob.
        h2h = {"team1": {"name": "América", "wins": 1}, "team2": {"name": "Toluca", "wins": 6},
               "played": 9, "draws": 2}
        base = _pron()
        r = aj.ajustar_pronostico(base, h2h=h2h)
        self.assertLess(r["prob_local_pct"], base["prob_local_pct"])


if __name__ == "__main__":
    unittest.main()
