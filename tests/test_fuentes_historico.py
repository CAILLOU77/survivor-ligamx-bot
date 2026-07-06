#!/usr/bin/env python3
"""Tests para fuentes_datos.obtener_historico_largo (selección de fuente). Sin red."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import fuentes_datos as fd  # noqa: E402


def _partidos(n: int) -> list:
    return [{"home_team": "A", "away_team": "B", "home_goals": 1,
             "away_goals": 0, "fecha": "2024-01-01"} for _ in range(n)]


class TestHistoricoLargo(unittest.TestCase):
    def test_prefiere_ligamx_si_tiene_mas(self):
        with mock.patch.object(fd.ligamx_api, "resultados_historicos", return_value=_partidos(500)), \
             mock.patch.object(fd.espn_data, "obtener_resultados", return_value=_partidos(200)), \
             mock.patch.object(fd, "guardar_cache"):
            r = fd.obtener_historico_largo()
        self.assertEqual(r["fuente"], "LigaMX-API")
        self.assertEqual(r["total"], 500)

    def test_cae_a_espn_si_ligamx_falla(self):
        with mock.patch.object(fd.ligamx_api, "resultados_historicos",
                               side_effect=RuntimeError("API caída")), \
             mock.patch.object(fd.espn_data, "obtener_resultados", return_value=_partidos(120)), \
             mock.patch.object(fd, "guardar_cache"):
            r = fd.obtener_historico_largo()
        self.assertEqual(r["fuente"], "ESPN")
        self.assertEqual(r["total"], 120)

    def test_cae_a_cache_si_todo_falla(self):
        with mock.patch.object(fd.ligamx_api, "resultados_historicos", return_value=[]), \
             mock.patch.object(fd.espn_data, "obtener_resultados", return_value=[]), \
             mock.patch.object(fd, "leer_cache", return_value=_partidos(30)):
            r = fd.obtener_historico_largo()
        self.assertEqual(r["fuente"], "cache")
        self.assertEqual(r["total"], 30)


if __name__ == "__main__":
    unittest.main(verbosity=2)
