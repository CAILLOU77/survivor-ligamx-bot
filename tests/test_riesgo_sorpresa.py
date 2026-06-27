#!/usr/bin/env python3
"""
Tests unitarios para src/riesgo_sorpresa.py (capa anti-tumba quinielas).

Cubren funciones puras: normalizar, equipos_son_rivalidad, mercado_disponible,
contar_bajas, obtener_probabilidades_si_existen y el núcleo calcular_riesgo.
No modifican la lógica de producción.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import riesgo_sorpresa as rs  # noqa: E402


class TestNormalizar(unittest.TestCase):
    def test_quita_acentos_y_baja(self):
        self.assertEqual(rs.normalizar("América"), "america")
        self.assertEqual(rs.normalizar("  Léon  "), "leon")


class TestRivalidad(unittest.TestCase):
    def test_clasico_nacional(self):
        self.assertTrue(rs.equipos_son_rivalidad("Club América", "Chivas Guadalajara"))

    def test_clasico_regio(self):
        self.assertTrue(rs.equipos_son_rivalidad("Tigres", "Monterrey"))

    def test_no_rivalidad(self):
        self.assertFalse(rs.equipos_son_rivalidad("Necaxa", "Atlante"))


class TestMercadoDisponible(unittest.TestCase):
    def test_abierto(self):
        self.assertTrue(rs.mercado_disponible({"momios": {"estado": "abierto"}}))

    def test_sin_momios(self):
        self.assertFalse(rs.mercado_disponible({}))

    def test_no_publicado(self):
        self.assertFalse(rs.mercado_disponible({"momios": {"estado": "mercado_no_publicado"}}))

    def test_cerrado(self):
        self.assertFalse(rs.mercado_disponible({"momios": {"estado": "cerrado"}}))


class TestContarBajas(unittest.TestCase):
    def test_cuenta(self):
        self.assertEqual(
            rs.contar_bajas({"lesiones": [{}, {}], "suspendidos": [{}]}), (2, 1)
        )

    def test_vacio(self):
        self.assertEqual(rs.contar_bajas({}), (0, 0))


class TestProbabilidades(unittest.TestCase):
    def test_extrae_floats(self):
        p = rs.obtener_probabilidades_si_existen(
            {"probabilidades": {"local": 0.4, "empate": 0.3, "visitante": 0.3}}
        )
        self.assertAlmostEqual(p["local"], 0.4)
        self.assertAlmostEqual(p["empate"], 0.3)

    def test_sin_datos(self):
        self.assertEqual(rs.obtener_probabilidades_si_existen({}), {})


class TestCalcularRiesgo(unittest.TestCase):
    def test_datos_completos_riesgo_bajo(self):
        # Mercado abierto, fecha/hora confirmada, bajas revisadas -> sin penalizaciones extra.
        partido = {
            "home_team": "Equipo X", "away_team": "Equipo Y",
            "momios": {"estado": "abierto"},
            "fecha": "2026-07-16", "hora": "19:00",
            "bajas_revisadas": True,
        }
        r = rs.calcular_riesgo(partido)
        self.assertEqual(r["nivel"], "VERDE")
        self.assertIn("RIESGO BAJO", r["etiqueta"])

    def test_datos_incompletos_sube_riesgo(self):
        # Sin momios, sin fecha/hora, sin bajas revisadas.
        partido = {"home_team": "Equipo X", "away_team": "Equipo Y"}
        r = rs.calcular_riesgo(partido)
        self.assertEqual(r["nivel"], "AMARILLO")

    def test_clasico_es_rojo(self):
        partido = {"home_team": "Club América", "away_team": "Chivas Guadalajara"}
        r = rs.calcular_riesgo(partido)
        self.assertEqual(r["nivel"], "ROJO")
        self.assertIn("TUMBA QUINIELAS", r["etiqueta"])

    def test_probabilidades_peligrosas_suben_riesgo(self):
        partido = {
            "home_team": "Equipo X", "away_team": "Equipo Y",
            "momios": {"estado": "abierto"},
            "fecha": "2026-07-16", "hora": "19:00",
            "bajas_revisadas": True,
            "probabilidades": {"local": 40, "empate": 30, "visitante": 30},
        }
        r = rs.calcular_riesgo(partido)
        # Empate alto + visitante peligroso + favorito débil -> ROJO.
        self.assertEqual(r["nivel"], "ROJO")

    def test_score_acotado_0_100(self):
        partido = {"home_team": "Club América", "away_team": "Chivas Guadalajara",
                   "lesiones": [{}] * 10, "suspendidos": [{}] * 10}
        r = rs.calcular_riesgo(partido)
        self.assertLessEqual(r["score"], 100)
        self.assertGreaterEqual(r["score"], 0)

    def test_estructura_resultado(self):
        r = rs.calcular_riesgo({"home_team": "X", "away_team": "Y"})
        for k in ("score", "nivel", "etiqueta", "recomendacion", "razones"):
            self.assertIn(k, r)


if __name__ == "__main__":
    unittest.main(verbosity=2)
