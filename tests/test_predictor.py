#!/usr/bin/env python3
"""
Tests de caracterización para src/predictor.py (calcular_pronosticos_avanzados).

El módulo lee `data/jornadas.json` (ruta relativa al cwd) e imprime los
pronósticos (probabilidades implícitas, pick recomendado, marcador exacto con
Poisson). Estos tests NO modifican la lógica: montan un fixture controlado,
capturan stdout y verifican el comportamiento observable.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import predictor  # noqa: E402


def _partido(local, visita, cl, cv, ce, **extra):
    base = {
        "home_team": local,
        "away_team": visita,
        "bookmakers": [
            {"markets": [{"outcomes": [
                {"name": local, "price": cl},
                {"name": visita, "price": cv},
                {"name": "Draw", "price": ce},
            ]}]}
        ],
    }
    base.update(extra)
    return base


class _CwdSandbox(unittest.TestCase):
    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmp = tempfile.mkdtemp(prefix="pred_test_")
        os.makedirs(os.path.join(self._tmp, "data"), exist_ok=True)
        os.chdir(self._tmp)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write(self, data):
        with open("data/jornadas.json", "w", encoding="utf-8") as f:
            json.dump(data, f)

    def _run(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            predictor.calcular_pronosticos_avanzados()
        return buf.getvalue()


class TestPronosticos(_CwdSandbox):
    def test_imprime_partido_y_secciones(self):
        self._write([_partido("America", "Toluca", 1.5, 6.0, 4.0)])
        out = self._run()
        self.assertIn("America vs Toluca", out)
        self.assertIn("PROBABILIDADES", out)
        self.assertIn("PICK RECOMENDADO", out)
        self.assertIn("MARCADOR EXACTO", out)

    def test_favorito_claro_se_refleja_en_pick(self):
        # America favorito fuerte (cuota baja) -> pick "Gana America".
        self._write([_partido("America", "Toluca", 1.4, 7.0, 4.5)])
        out = self._run()
        self.assertIn("PICK RECOMENDADO: Gana America", out)

    def test_partido_parejo_puede_dar_empate(self):
        # Cuotas simétricas y empate más probable -> pick "Empate".
        self._write([_partido("A", "B", 3.0, 3.0, 2.4)])
        out = self._run()
        self.assertIn("PICK RECOMENDADO: Empate", out)

    def test_clima_fallback_etiquetado(self):
        # Sin clima_real -> debe marcar FALLBACK TÉCNICO.
        self._write([_partido("America", "Toluca", 1.5, 6.0, 4.0)])
        out = self._run()
        self.assertIn("FALLBACK TÉCNICO", out)

    def test_clima_real_etiquetado(self):
        self._write([_partido("America", "Toluca", 1.5, 6.0, 4.0,
                              clima_real=True, clima_temperatura_c=24.0)])
        out = self._run()
        self.assertIn("(REAL)", out)

    def test_avance_survivor_presente(self):
        self._write([_partido("America", "Toluca", 1.5, 6.0, 4.0)])
        out = self._run()
        self.assertIn("AVANCE SURVIVOR", out)


class TestEntradaFaltante(_CwdSandbox):
    def test_sin_jornadas_devuelve_none(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            resultado = predictor.calcular_pronosticos_avanzados()
        self.assertIsNone(resultado)
        self.assertIn("No se encuentra", buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
