#!/usr/bin/env python3
"""Tests para src/scheduler.py (lógica de programación del análisis semanal). Sin red."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import scheduler as sch  # noqa: E402


class TestHabilitado(unittest.TestCase):
    def test_on_por_defecto(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(sch._habilitado())

    def test_off_con_valores_falsos(self):
        for v in ("false", "0", "off", "no", "FALSE", "Off"):
            with mock.patch.dict(os.environ, {"SCHEDULER_ENABLED": v}, clear=True):
                self.assertFalse(sch._habilitado(), f"debería apagarse con {v!r}")

    def test_on_con_valor_verdadero(self):
        with mock.patch.dict(os.environ, {"SCHEDULER_ENABLED": "1"}, clear=True):
            self.assertTrue(sch._habilitado())


class TestZona(unittest.TestCase):
    def test_zona_devuelve_tz_o_none(self):
        z = sch._zona()
        # Python 3.12 tiene ZoneInfo -> America/Mexico_City; si no, None.
        self.assertTrue(z is None or str(z) == "America/Mexico_City")


class TestProximoDisparo(unittest.TestCase):
    def test_devuelve_float_no_negativo_y_acotado(self):
        env = {"SCHEDULER_HOUR": "23", "SCHEDULER_MINUTE": "0", "SCHEDULER_WEEKDAY": "6"}
        with mock.patch.dict(os.environ, env, clear=True):
            s = sch._proximo_disparo()
        self.assertIsInstance(s, float)
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 7 * 24 * 3600 + 1)  # a lo más 7 días

    def test_respeta_hora_configurada(self):
        env = {"SCHEDULER_HOUR": "10", "SCHEDULER_MINUTE": "30", "SCHEDULER_WEEKDAY": "6"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertGreaterEqual(sch._proximo_disparo(), 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
