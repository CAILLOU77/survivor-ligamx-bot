#!/usr/bin/env python3
"""
Tests unitarios para src/reglas_ligamx_2026.py.

Cubren las funciones puras del motor de reglas (sin I/O):
parse_fecha, detectar_jornada, nivel_por_score, evaluar_reglas,
aplicar_a_partido, extraer_partidos, nombre_partido.
No modifican la lógica de producción.
"""
from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import reglas_ligamx_2026 as reglas  # noqa: E402


class TestParseFecha(unittest.TestCase):
    def test_iso_simple(self):
        self.assertEqual(reglas.parse_fecha("2026-07-16"), date(2026, 7, 16))

    def test_iso_con_hora(self):
        self.assertEqual(reglas.parse_fecha("2026-07-16T19:00"), date(2026, 7, 16))

    def test_pendiente_es_none(self):
        self.assertIsNone(reglas.parse_fecha("PENDIENTE"))

    def test_vacio_es_none(self):
        self.assertIsNone(reglas.parse_fecha(""))
        self.assertIsNone(reglas.parse_fecha(None))


class TestDetectarJornada(unittest.TestCase):
    def test_jornada_texto(self):
        self.assertEqual(reglas.detectar_jornada({"jornada": "Jornada 1"}), 1)

    def test_round_texto(self):
        self.assertEqual(reglas.detectar_jornada({"round": "Round 3"}), 3)

    def test_solo_digito(self):
        self.assertEqual(reglas.detectar_jornada({"jornada": "1"}), 1)

    def test_sin_dato(self):
        self.assertIsNone(reglas.detectar_jornada({}))


class TestNivelPorScore(unittest.TestCase):
    def test_rojo(self):
        n = reglas.nivel_por_score(70)
        self.assertEqual(n["nivel"], "ROJO")
        self.assertIn("TUMBA QUINIELAS", n["etiqueta"])

    def test_amarillo(self):
        self.assertEqual(reglas.nivel_por_score(50)["nivel"], "AMARILLO")
        self.assertEqual(reglas.nivel_por_score(69.9)["nivel"], "AMARILLO")

    def test_verde(self):
        self.assertEqual(reglas.nivel_por_score(49)["nivel"], "VERDE")
        self.assertEqual(reglas.nivel_por_score(0)["nivel"], "VERDE")


class TestEvaluarReglas(unittest.TestCase):
    def test_inicio_de_torneo_suma(self):
        ev = reglas.evaluar_reglas({"jornada": "Jornada 1"})
        self.assertEqual(ev["ajuste_score"], 5.0)
        self.assertEqual(ev["jornada_detectada"], 1)

    def test_menores_riesgo_suma(self):
        ev = reglas.evaluar_reglas({"jornada": "Jornada 10", "menores_riesgo_rotacion": True})
        self.assertEqual(ev["ajuste_score"], 6.0)

    def test_posicion_zona_top8_suma(self):
        ev = reglas.evaluar_reglas({"posicion_local": 8})
        self.assertEqual(ev["ajuste_score"], 3.0)

    def test_siempre_incluye_aviso_formato_2026(self):
        ev = reglas.evaluar_reglas({})
        self.assertTrue(any("2026" in a for a in ev["avisos"]))

    def test_sin_gatillo_tiene_razon_neutral(self):
        ev = reglas.evaluar_reglas({})
        self.assertEqual(ev["ajuste_score"], 0.0)
        self.assertTrue(ev["razones"])  # nunca vacío


class TestAplicarAPartido(unittest.TestCase):
    def test_suma_ajuste_a_riesgo_existente(self):
        partido = {"jornada": "Jornada 1", "riesgo_sorpresa": {"score": 50}}
        res = reglas.aplicar_a_partido(partido)
        self.assertEqual(res["score_original"], 50.0)
        self.assertEqual(res["ajuste"], 5.0)
        self.assertEqual(res["score_nuevo"], 55.0)
        self.assertEqual(res["nivel"], "AMARILLO")
        # Muta el partido in-place.
        self.assertEqual(partido["riesgo_sorpresa"]["score"], 55.0)

    def test_escala_a_rojo(self):
        partido = {"jornada": "Jornada 1", "riesgo_sorpresa": {"score": 68}}
        res = reglas.aplicar_a_partido(partido)
        self.assertEqual(res["score_nuevo"], 73.0)
        self.assertEqual(res["nivel"], "ROJO")

    def test_sin_riesgo_previo_usa_default_50(self):
        partido = {"jornada": "Jornada 1"}
        res = reglas.aplicar_a_partido(partido)
        self.assertEqual(res["score_original"], 50.0)
        self.assertEqual(res["score_nuevo"], 55.0)

    def test_clamp_maximo_100(self):
        partido = {"jornada": "Jornada 1", "menores_riesgo_rotacion": True,
                   "riesgo_sorpresa": {"score": 99}}
        res = reglas.aplicar_a_partido(partido)
        self.assertLessEqual(res["score_nuevo"], 100.0)


class TestExtraccion(unittest.TestCase):
    def test_extraer_partidos_lista(self):
        data = [{"home_team": "A"}, "ruido", {"home_team": "B"}]
        self.assertEqual(len(reglas.extraer_partidos(data)), 2)

    def test_extraer_partidos_dict(self):
        data = {"partidos": [{"home_team": "A"}]}
        self.assertEqual(len(reglas.extraer_partidos(data)), 1)

    def test_nombre_partido(self):
        self.assertEqual(
            reglas.nombre_partido({"home_team": "America", "away_team": "Toluca"}),
            "America vs Toluca",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
