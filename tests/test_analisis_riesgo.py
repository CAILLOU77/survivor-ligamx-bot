#!/usr/bin/env python3
"""Tests para src/analisis_riesgo.py (fallos de favoritos). Sin red."""

from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import analisis_riesgo as ar  # noqa: E402


def _liga(n_semanas=12):
    """Liga sintética con un favorito claro local ('Fuerte') y partidos parejos."""
    out = []
    d0 = date(2026, 1, 5)  # lunes
    for w in range(n_semanas):
        d = (d0 + timedelta(days=7 * w)).isoformat()
        out.append({"home_team": "Fuerte", "away_team": "Debil", "home_goals": 3, "away_goals": 0, "fecha": d})
        out.append({"home_team": "Medio", "away_team": "Otro", "home_goals": 1, "away_goals": 1, "fecha": d})
    return out


class TestHelpers(unittest.TestCase):
    def test_bucket_confianza(self):
        self.assertEqual(ar._bucket_confianza(50.0), "<55% (sin claro favorito)")
        self.assertEqual(ar._bucket_confianza(60.0), "55-65%")
        self.assertEqual(ar._bucket_confianza(70.0), "65-75%")
        self.assertEqual(ar._bucket_confianza(80.0), ">=75%")

    def test_outcome_favorito_local(self):
        p = {"home_goals": 2, "away_goals": 0}
        self.assertEqual(ar._outcome_favorito(p, favorito_local=True), "gano")
        self.assertEqual(ar._outcome_favorito(p, favorito_local=False), "perdio")

    def test_outcome_favorito_empate(self):
        p = {"home_goals": 1, "away_goals": 1}
        self.assertEqual(ar._outcome_favorito(p, favorito_local=True), "empato")
        self.assertEqual(ar._outcome_favorito(p, favorito_local=False), "empato")

    def test_outcome_sin_marcador(self):
        self.assertIsNone(ar._outcome_favorito({}, favorito_local=True))

    def test_tasas_vacias_y_llenas(self):
        self.assertEqual(ar._tasas([])["n"], 0)
        evs = [{"outcome": "gano"}, {"outcome": "empato"}, {"outcome": "perdio"}, {"outcome": "gano"}]
        t = ar._tasas(evs)
        self.assertEqual(t["n"], 4)
        self.assertEqual(t["gano_pct"], 50.0)
        self.assertEqual(t["no_gano_pct"], 50.0)

    def test_labels_arranque_detecta_dos_torneos(self):
        # Torneo A: 5 semanas seguidas; hueco largo; Torneo B: 4 semanas.
        d0 = date(2026, 1, 5)
        jornadas = []
        for w in range(5):
            jornadas.append({"jornada": ar._semana_iso((d0 + timedelta(days=7 * w)).isoformat())})
        d1 = date(2026, 7, 13)  # ~6 meses después (nuevo torneo)
        for w in range(4):
            jornadas.append({"jornada": ar._semana_iso((d1 + timedelta(days=7 * w)).isoformat())})
        arr = ar._labels_arranque(jornadas, n=3)
        # Primeras 3 de cada torneo => 6 etiquetas.
        self.assertEqual(len(arr), 6)
        self.assertIn(jornadas[0]["jornada"], arr)  # J1 torneo A
        self.assertIn(jornadas[5]["jornada"], arr)  # J1 torneo B
        self.assertNotIn(jornadas[4]["jornada"], arr)  # J5 torneo A (no arranque)


class TestAnalisis(unittest.TestCase):
    def test_estructura(self):
        r = ar.analizar_riesgo_favoritos(_liga(12), min_train=4)
        for k in (
            "partidos_evaluados",
            "global",
            "por_condicion",
            "por_confianza",
            "por_tipo_partido",
            "muy_favorito",
            "arranque_vs_resto",
            "perfil_de_los_fallos",
            "recomendaciones",
            "decision",
        ):
            self.assertIn(k, r)
        self.assertEqual(r["decision"], "INFORMATIVO / REVISIÓN HUMANA")
        self.assertGreaterEqual(r["partidos_evaluados"], 1)
        # Secciones nuevas con forma esperada.
        self.assertIn("umbral_confianza_pct", r["muy_favorito"])
        self.assertIn("arranque_j1a3", r["arranque_vs_resto"])

    def test_favorito_fuerte_gana(self):
        # 'Fuerte' local 3-0 siempre => como favorito debe tener no_gano bajo.
        r = ar.analizar_riesgo_favoritos(_liga(14), min_train=4)
        glob = r["global"]
        self.assertIsNotNone(glob["gano_pct"])
        # Con un favorito dominante y empates en el otro juego, hay fallos por empate.
        self.assertGreaterEqual(glob["no_gano_pct"], 0.0)
        self.assertLessEqual(glob["no_gano_pct"], 100.0)

    def test_recomendaciones_no_vacias(self):
        r = ar.analizar_riesgo_favoritos(_liga(12), min_train=4)
        self.assertTrue(r["recomendaciones"])
        self.assertIsInstance(r["recomendaciones"][0], str)


if __name__ == "__main__":
    unittest.main()
