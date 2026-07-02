#!/usr/bin/env python3
"""Tests de fichajes: lectura/escritura de altas y bajas (sin scraping)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import fichajes as fich  # noqa: E402


class TestFichajes(unittest.TestCase):
    def setUp(self):
        # Redirigir el archivo a un temporal para no tocar el real.
        self._tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump({"temporada": "test", "equipos": {
            "América": {"altas": ["Delantero X"], "bajas": ["Volante Y"]},
            "Guadalajara": {"altas": [], "bajas": []},
        }}, self._tmp, ensure_ascii=False)
        self._tmp.close()
        self._orig = fich._PATH
        fich._PATH = Path(self._tmp.name)

    def tearDown(self):
        fich._PATH = self._orig
        os.unlink(self._tmp.name)

    def test_resumen_equipo(self):
        r = fich.resumen_equipo("América")
        self.assertEqual(r["altas"], ["Delantero X"])
        self.assertEqual(r["bajas"], ["Volante Y"])

    def test_alias(self):
        # "Club América" empareja con "América".
        self.assertEqual(fich.resumen_equipo("Club América")["altas"], ["Delantero X"])

    def test_linea_equipo(self):
        self.assertIn("Altas: Delantero X", fich.linea_equipo("América"))
        self.assertIn("Bajas: Volante Y", fich.linea_equipo("América"))

    def test_equipo_sin_datos(self):
        self.assertEqual(fich.linea_equipo("Toluca"), "")

    def test_disponible(self):
        self.assertTrue(fich.disponible())

    def test_guardar_equipo(self):
        fich.guardar_equipo("Toluca", ["Refuerzo Z"], ["Salida W"])
        self.assertIn("Refuerzo Z", fich.linea_equipo("Toluca"))


if __name__ == "__main__":
    unittest.main()
