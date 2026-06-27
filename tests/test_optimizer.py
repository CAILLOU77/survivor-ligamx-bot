#!/usr/bin/env python3
"""
Tests de caracterización para src/optimizer.py (seleccionar_pick_survivor).

El módulo lee `data/jornadas.json` (ruta relativa al cwd) e imprime el pick
técnico. Estos tests NO modifican la lógica: montan un jornadas.json controlado
en un directorio temporal, capturan stdout y verifican el comportamiento
observable.

Math verificada a mano para el fixture:
    America (1.5) vs Toluca (6.0), Draw 4.0 -> surv America = 84.6%
    Cruz Azul (1.8) vs Pumas (3.5), Draw 3.2 -> surv Cruz Azul = 75.2%
Orden esperado: America > Cruz Azul > Pumas > Toluca
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

import optimizer  # noqa: E402


def _jornada_fixture():
    return [
        {
            "home_team": "America",
            "away_team": "Toluca",
            "bookmakers": [
                {"markets": [{"outcomes": [
                    {"name": "America", "price": 1.5},
                    {"name": "Toluca", "price": 6.0},
                    {"name": "Draw", "price": 4.0},
                ]}]}
            ],
        },
        {
            "home_team": "Cruz Azul",
            "away_team": "Pumas",
            "bookmakers": [
                {"markets": [{"outcomes": [
                    {"name": "Cruz Azul", "price": 1.8},
                    {"name": "Pumas", "price": 3.5},
                    {"name": "Draw", "price": 3.2},
                ]}]}
            ],
        },
    ]


class _CwdSandbox(unittest.TestCase):
    """Base: ejecuta cada test en un cwd temporal con data/jornadas.json."""

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmp = tempfile.mkdtemp(prefix="optim_test_")
        os.makedirs(os.path.join(self._tmp, "data"), exist_ok=True)
        os.chdir(self._tmp)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        # Limpieza best-effort.
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_jornadas(self, data):
        with open("data/jornadas.json", "w", encoding="utf-8") as f:
            json.dump(data, f)

    def _write_historial(self, usados):
        with open("data/historial_picks.json", "w", encoding="utf-8") as f:
            json.dump(usados, f)

    def _run(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            optimizer.seleccionar_pick_survivor()
        return buf.getvalue()


class TestPickSeleccion(_CwdSandbox):
    def test_pick_es_el_equipo_con_mayor_prob_avance(self):
        self._write_jornadas(_jornada_fixture())
        out = self._run()
        # America tiene la mayor probabilidad de avance (84.6%).
        self.assertIn("CANDIDATO TÉCNICO: America", out)

    def test_historial_limpio_no_bloquea(self):
        self._write_jornadas(_jornada_fixture())
        out = self._run()
        self.assertIn("Historial limpio", out)

    def test_respeta_equipos_usados(self):
        self._write_jornadas(_jornada_fixture())
        self._write_historial(["America"])
        out = self._run()
        # America bloqueado -> el candidato pasa a Cruz Azul (75.2%).
        self.assertIn("Equipos bloqueados", out)
        self.assertIn("America", out)  # aparece en la línea de bloqueados
        self.assertIn("CANDIDATO TÉCNICO: Cruz Azul", out)

    def test_orden_de_respaldo(self):
        self._write_jornadas(_jornada_fixture())
        out = self._run()
        # El segundo en seguridad debe ser Cruz Azul.
        self.assertIn("2. Cruz Azul", out)


class TestSeguridad(_CwdSandbox):
    def test_salida_conserva_no_enviar(self):
        self._write_jornadas(_jornada_fixture())
        out = self._run()
        self.assertIn("NO ENVIAR", out)
        self.assertIn("REFERENCIA TÉCNICA", out)

    def test_no_cierra_pick(self):
        self._write_jornadas(_jornada_fixture())
        out = self._run()
        # El módulo nunca debe declarar el cierre real por su cuenta.
        self.assertIn("El cierre real lo decide", out)


class TestEntradaFaltante(_CwdSandbox):
    def test_sin_jornadas_devuelve_none(self):
        # No se escribe data/jornadas.json.
        buf = io.StringIO()
        with redirect_stdout(buf):
            resultado = optimizer.seleccionar_pick_survivor()
        self.assertIsNone(resultado)
        self.assertIn("No se encuentra", buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
