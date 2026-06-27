#!/usr/bin/env python3
"""Tests para src/poisson_model.py (modelo Poisson / Dixon-Coles)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import poisson_model as pm  # noqa: E402


class TestPoissonPMF(unittest.TestCase):
    def test_pmf_conocido(self):
        # P(X=0; lam=1) = e^-1 ≈ 0.3679
        self.assertAlmostEqual(pm._pois_pmf(0, 1.0), 0.367879, places=5)

    def test_lambda_cero(self):
        self.assertEqual(pm._pois_pmf(0, 0.0), 1.0)
        self.assertEqual(pm._pois_pmf(2, 0.0), 0.0)


class TestMatriz(unittest.TestCase):
    def test_matriz_suma_uno(self):
        matriz = pm.matriz_marcadores(1.5, 1.2, rho=0.0)
        total = sum(sum(fila) for fila in matriz)
        self.assertAlmostEqual(total, 1.0, places=6)

    def test_dixon_coles_tambien_normaliza(self):
        matriz = pm.matriz_marcadores(1.4, 1.1, rho=-0.05)
        total = sum(sum(fila) for fila in matriz)
        self.assertAlmostEqual(total, 1.0, places=6)


class TestMercados(unittest.TestCase):
    def test_1x2_suma_uno(self):
        matriz = pm.matriz_marcadores(1.6, 1.0, rho=0.0)
        p = pm.probabilidades_1x2(matriz)
        self.assertAlmostEqual(sum(p), 1.0, places=6)

    def test_favorito_local_mayor_prob(self):
        # Local con λ alto, visita con λ bajo -> P(local) la mayor.
        matriz = pm.matriz_marcadores(2.2, 0.7, rho=0.0)
        p_local, p_empate, p_visita = pm.probabilidades_1x2(matriz)
        self.assertGreater(p_local, p_visita)
        self.assertGreater(p_local, p_empate)

    def test_over_under_suma_uno(self):
        matriz = pm.matriz_marcadores(1.5, 1.5, rho=0.0)
        over, under = pm.probabilidad_over_under(matriz, 2.5)
        self.assertAlmostEqual(over + under, 1.0, places=6)

    def test_partido_de_muchos_goles_mas_over(self):
        matriz = pm.matriz_marcadores(2.5, 2.3, rho=0.0)
        over, under = pm.probabilidad_over_under(matriz, 2.5)
        self.assertGreater(over, under)

    def test_partido_cerrado_mas_under(self):
        matriz = pm.matriz_marcadores(0.7, 0.6, rho=0.0)
        over, under = pm.probabilidad_over_under(matriz, 2.5)
        self.assertGreater(under, over)

    def test_btts_suma_uno(self):
        matriz = pm.matriz_marcadores(1.4, 1.3, rho=0.0)
        si, no = pm.probabilidad_btts(matriz)
        self.assertAlmostEqual(si + no, 1.0, places=6)

    def test_marcador_mas_probable_es_tupla(self):
        matriz = pm.matriz_marcadores(1.2, 1.0, rho=0.0)
        mh, ma = pm.marcador_mas_probable(matriz)
        self.assertIsInstance(mh, int)
        self.assertIsInstance(ma, int)


def _liga_sintetica():
    # Fuerte (mete muchos, recibe pocos) vs Débil (mete pocos, recibe muchos).
    return [
        {"home_team": "Fuerte", "away_team": "Medio", "home_goals": 3, "away_goals": 0},
        {"home_team": "Fuerte", "away_team": "Debil", "home_goals": 4, "away_goals": 0},
        {"home_team": "Medio", "away_team": "Debil", "home_goals": 2, "away_goals": 1},
        {"home_team": "Medio", "away_team": "Fuerte", "home_goals": 0, "away_goals": 2},
        {"home_team": "Debil", "away_team": "Fuerte", "home_goals": 0, "away_goals": 3},
        {"home_team": "Debil", "away_team": "Medio", "home_goals": 1, "away_goals": 2},
    ]


class TestFuerzas(unittest.TestCase):
    def test_estima_fuerzas(self):
        f = pm.calcular_fuerzas(_liga_sintetica())
        self.assertIn("equipos", f)
        self.assertIn("fuerte", f["equipos"])
        self.assertGreater(f["avg_home"], 0)

    def test_equipo_fuerte_mayor_ataque(self):
        f = pm.calcular_fuerzas(_liga_sintetica())
        self.assertGreater(
            f["equipos"]["fuerte"]["ataque_local"],
            f["equipos"]["debil"]["ataque_local"],
        )

    def test_goles_esperados_fuerte_vs_debil(self):
        f = pm.calcular_fuerzas(_liga_sintetica())
        lam_l, lam_v = pm.goles_esperados("Fuerte", "Debil", f)
        self.assertGreater(lam_l, lam_v)

    def test_sin_partidos_lanza(self):
        with self.assertRaises(ValueError):
            pm.calcular_fuerzas([])


class TestPronostico(unittest.TestCase):
    def test_pronostico_completo(self):
        f = pm.calcular_fuerzas(_liga_sintetica())
        r = pm.pronostico("Fuerte", "Debil", f)
        for k in ("prob_local_pct", "prob_empate_pct", "prob_visitante_pct",
                  "prob_over_pct", "prob_under_pct", "prob_btts_si_pct",
                  "marcador_mas_probable", "pick_1x2", "pick_ou", "pick_btts"):
            self.assertIn(k, r)

    def test_fuerte_favorito(self):
        f = pm.calcular_fuerzas(_liga_sintetica())
        r = pm.pronostico("Fuerte", "Debil", f)
        self.assertEqual(r["pick_1x2"], "Gana Local")
        total = r["prob_local_pct"] + r["prob_empate_pct"] + r["prob_visitante_pct"]
        self.assertAlmostEqual(total, 100.0, places=1)


class TestCombinarConMercado(unittest.TestCase):
    def test_blend_50_50(self):
        modelo = [0.6, 0.25, 0.15]
        mercado = [0.4, 0.30, 0.30]
        mezcla = pm.combinar_con_mercado(modelo, mercado, peso_modelo=0.5)
        self.assertAlmostEqual(sum(mezcla), 1.0, places=9)
        self.assertAlmostEqual(mezcla[0], 0.5, places=6)  # (0.6+0.4)/2

    def test_peso_solo_modelo(self):
        modelo = [0.6, 0.25, 0.15]
        mercado = [0.1, 0.1, 0.8]
        mezcla = pm.combinar_con_mercado(modelo, mercado, peso_modelo=1.0)
        self.assertAlmostEqual(mezcla[0], 0.6, places=6)

    def test_largos_distintos_lanza(self):
        with self.assertRaises(ValueError):
            pm.combinar_con_mercado([0.5, 0.5], [0.3, 0.3, 0.4])

    def test_peso_invalido_lanza(self):
        with self.assertRaises(ValueError):
            pm.combinar_con_mercado([0.5, 0.5], [0.5, 0.5], peso_modelo=1.5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
