#!/usr/bin/env python3
"""Tests para src/reglas_liga_mx.py (formato/reglas vigentes de Liga MX)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import reglas_liga_mx as rl  # noqa: E402


class TestConstantes(unittest.TestCase):
    def test_dieciocho_equipos(self):
        self.assertEqual(rl.EQUIPOS_LIGA_MX, 18)

    def test_descenso_suspendido(self):
        self.assertFalse(rl.descenso_activo())


class TestFormatoNormal(unittest.TestCase):
    def test_default_tiene_play_in(self):
        f = rl.formato_liguilla("")
        self.assertTrue(f["play_in"])
        self.assertEqual(f["clasificados_directo"], 6)
        self.assertEqual(f["total_liguilla"], 8)
        self.assertFalse(f["es_excepcion"])

    def test_apertura_2026_usa_formato_normal(self):
        # Apertura 2026 no está en excepciones -> formato normal (con Play-In).
        self.assertTrue(rl.hay_play_in("Apertura 2026"))

    def test_top6_clasifica_directo(self):
        for pos in (1, 6):
            self.assertTrue(rl.clasifica_directo(pos, "Apertura 2026"))
        self.assertFalse(rl.clasifica_directo(7, "Apertura 2026"))

    def test_zona_play_in_7_a_10(self):
        for pos in (7, 8, 9, 10):
            self.assertTrue(rl.va_play_in(pos, "Apertura 2026"))
        self.assertFalse(rl.va_play_in(6, "Apertura 2026"))
        self.assertFalse(rl.va_play_in(11, "Apertura 2026"))

    def test_fuera_de_liguilla(self):
        self.assertTrue(rl.fuera_de_liguilla(11, "Apertura 2026"))
        self.assertFalse(rl.fuera_de_liguilla(3, "Apertura 2026"))
        self.assertFalse(rl.fuera_de_liguilla(9, "Apertura 2026"))


class TestExcepcionClausura2026(unittest.TestCase):
    def test_sin_play_in(self):
        self.assertFalse(rl.hay_play_in("Clausura 2026"))

    def test_top8_directo(self):
        f = rl.formato_liguilla("Clausura 2026")
        self.assertEqual(f["clasificados_directo"], 8)
        self.assertTrue(f["es_excepcion"])
        # En esta excepción, la posición 8 clasifica directo (no hay Play-In).
        self.assertTrue(rl.clasifica_directo(8, "Clausura 2026"))
        self.assertFalse(rl.va_play_in(8, "Clausura 2026"))

    def test_nota_menciona_mundial(self):
        f = rl.formato_liguilla("Clausura 2026")
        self.assertIn("Mundial 2026", f["nota"])

    def test_normalizacion_de_clave(self):
        # Acentos/mayúsculas no deben romper la detección de la excepción.
        self.assertFalse(rl.hay_play_in("CLAUSURA 2026"))


class TestResumen(unittest.TestCase):
    def test_resumen_normal(self):
        out = rl.resumen_reglas("Apertura 2026")
        self.assertIn("18 equipos", out)
        self.assertIn("Play-In", out)
        self.assertIn("suspendido", out)

    def test_resumen_excepcion(self):
        out = rl.resumen_reglas("Clausura 2026")
        self.assertIn("8 directo", out)


class TestZonaYCupos(unittest.TestCase):
    def test_zona_clasificacion_normal(self):
        self.assertEqual(rl.zona_clasificacion(1, "Apertura 2026"), "directo")
        self.assertEqual(rl.zona_clasificacion(6, "Apertura 2026"), "directo")
        self.assertEqual(rl.zona_clasificacion(7, "Apertura 2026"), "play_in")
        self.assertEqual(rl.zona_clasificacion(10, "Apertura 2026"), "play_in")
        self.assertEqual(rl.zona_clasificacion(11, "Apertura 2026"), "fuera")

    def test_zona_clasificacion_excepcion(self):
        # Sin Play-In: 1–8 directo, el resto fuera.
        self.assertEqual(rl.zona_clasificacion(8, "Clausura 2026"), "directo")
        self.assertEqual(rl.zona_clasificacion(9, "Clausura 2026"), "fuera")

    def test_cupos_postemporada(self):
        self.assertEqual(rl.cupos_postemporada("Apertura 2026"), 10)  # incluye Play-In
        self.assertEqual(rl.cupos_postemporada("Clausura 2026"), 8)   # sin Play-In


if __name__ == "__main__":
    unittest.main(verbosity=2)
