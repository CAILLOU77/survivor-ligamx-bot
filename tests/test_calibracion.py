#!/usr/bin/env python3
"""Tests para src/calibracion.py (calibración de probabilidades). Sin red."""
from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import calibracion as cal  # noqa: E402


class TestCalibrarProbs(unittest.TestCase):
    def test_alpha_cero_no_cambia(self):
        probs = [0.6, 0.25, 0.15]
        out = cal.calibrar_probs(probs, 0.0, [1 / 3, 1 / 3, 1 / 3])
        for a, b in zip(out, probs):
            self.assertAlmostEqual(a, b, places=6)

    def test_alpha_uno_da_base(self):
        base = [0.45, 0.28, 0.27]
        out = cal.calibrar_probs([0.9, 0.05, 0.05], 1.0, base)
        for a, b in zip(out, base):
            self.assertAlmostEqual(a, b, places=6)

    def test_shrink_reduce_confianza(self):
        base = [1 / 3, 1 / 3, 1 / 3]
        out = cal.calibrar_probs([0.8, 0.15, 0.05], 0.5, base)
        self.assertAlmostEqual(sum(out), 1.0, places=6)
        self.assertLess(out[0], 0.8)  # el favorito baja de confianza
        self.assertGreater(out[2], 0.05)

    def test_largos_distintos_error(self):
        with self.assertRaises(ValueError):
            cal.calibrar_probs([0.5, 0.5], 0.2, [1 / 3, 1 / 3, 1 / 3])


class TestTasaBase(unittest.TestCase):
    def test_cuenta_resultados(self):
        res = [
            {"home_goals": 2, "away_goals": 0},  # local
            {"home_goals": 1, "away_goals": 1},  # empate
            {"home_goals": 0, "away_goals": 3},  # visita
            {"home_goals": 3, "away_goals": 1},  # local
        ]
        pl, pe, pv = cal.tasa_base(res)
        self.assertAlmostEqual(pl + pe + pv, 1.0, places=6)
        self.assertAlmostEqual(pl, 0.5, places=6)  # 2 de 4 locales

    def test_sin_datos_uniforme(self):
        pl, pe, pv = cal.tasa_base([])
        self.assertAlmostEqual(pl, 1 / 3, places=6)


class TestAjustarAlpha(unittest.TestCase):
    def test_overconfianza_prefiere_alpha_positivo(self):
        # Modelo que dice 90% local pero en realidad gana ~50%: calibrar (shrink)
        # hacia la base debe bajar el Brier => alpha > 0.
        base = [0.5, 0.25, 0.25]
        muestras = []
        for i in range(20):
            resultado = 1 if i % 2 == 0 else 3  # local gana la mitad
            muestras.append({"probs": [0.9, 0.05, 0.05], "resultado": resultado})
        r = cal.ajustar_alpha(muestras, base)
        self.assertGreater(r["alpha"], 0.0)
        self.assertGreaterEqual(r["mejora_brier"], 0.0)

    def test_muestras_vacias(self):
        r = cal.ajustar_alpha([], [1 / 3, 1 / 3, 1 / 3])
        self.assertEqual(r["n"], 0)


def _liga_overconfianza(n_semanas: int = 20):
    """
    Liga donde el 'Fuerte' es MUY favorito de local pero pierde a veces:
    fuerza la overconfianza para que calibrar tenga algo que corregir.
    """
    out = []
    d0 = date(2025, 1, 6)
    for w in range(n_semanas):
        d = (d0 + timedelta(days=7 * w)).isoformat()
        # Fuerte gana casi siempre (goleadas) pero cada 4 semanas pierde.
        if w % 4 == 3:
            out.append({"home_team": "Fuerte", "away_team": "Debil",
                        "home_goals": 0, "away_goals": 1, "fecha": d})
        else:
            out.append({"home_team": "Fuerte", "away_team": "Debil",
                        "home_goals": 4, "away_goals": 0, "fecha": d})
        out.append({"home_team": "Medio", "away_team": "Otro",
                    "home_goals": 1, "away_goals": 1, "fecha": d})
        out.append({"home_team": "Local2", "away_team": "Visita2",
                    "home_goals": 2, "away_goals": 1, "fecha": d})
    return out


class TestEvaluarCalibracion(unittest.TestCase):
    def test_estructura(self):
        r = cal.evaluar_calibracion(_liga_overconfianza(24), min_train=6)
        # Con suficientes muestras devuelve el reporte completo.
        if r.get("n_muestras", 0) >= 20:
            for k in ("alpha_sugerido", "brier_sin_calibrar_eval",
                      "brier_calibrado_eval", "calibracion_ayuda", "tasa_base"):
                self.assertIn(k, r)
        else:
            self.assertIn("mensaje", r)

    def test_pocas_muestras(self):
        r = cal.evaluar_calibracion(_liga_overconfianza(2), min_train=6)
        self.assertIn("n_muestras", r)


class TestCalibrarPronostico(unittest.TestCase):
    def test_recalcula_pick_y_no_perder(self):
        pron = {
            "prob_local_pct": 80.0, "prob_empate_pct": 12.0, "prob_visitante_pct": 8.0,
            "pick_1x2": "Gana Local",
        }
        out = cal.calibrar_pronostico(pron, 0.5, [1 / 3, 1 / 3, 1 / 3])
        self.assertAlmostEqual(
            out["prob_local_pct"] + out["prob_empate_pct"] + out["prob_visitante_pct"],
            100.0, places=1)
        self.assertLess(out["prob_local_pct"], 80.0)  # menos confianza
        self.assertIn("calibrado", out)
        self.assertAlmostEqual(
            out["no_perder_local_pct"],
            out["prob_local_pct"] + out["prob_empate_pct"], places=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
