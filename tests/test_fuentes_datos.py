#!/usr/bin/env python3
"""Tests para src/fuentes_datos.py (redundancia multi-fuente). Sin red."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import fuentes_datos as fd  # noqa: E402


class TestParsearTheSportsDB(unittest.TestCase):
    def test_evento_con_marcador(self):
        data = {"events": [{
            "strHomeTeam": "Pumas", "strAwayTeam": "Cruz Azul",
            "intHomeScore": "1", "intAwayScore": "2", "dateEvent": "2026-05-25",
        }]}
        r = fd.parsear_thesportsdb(data)[0]
        self.assertEqual(r["home_team"], "Pumas")
        self.assertEqual(r["home_goals"], 1)
        self.assertEqual(r["away_goals"], 2)

    def test_sin_marcador_se_ignora(self):
        data = {"events": [{
            "strHomeTeam": "Necaxa", "strAwayTeam": "Atlante",
            "intHomeScore": None, "intAwayScore": None, "dateEvent": "2026-07-17",
        }]}
        self.assertEqual(fd.parsear_thesportsdb(data), [])

    def test_vacio(self):
        self.assertEqual(fd.parsear_thesportsdb({"events": None}), [])


def _r(h, a, hg, ag, fecha="2026-02-01"):
    return {"home_team": h, "away_team": a, "home_goals": hg, "away_goals": ag, "fecha": fecha}


class TestRedundancia(unittest.TestCase):
    def test_espn_primaria_si_suficiente(self):
        espn = [_r(f"H{i}", f"A{i}", 1, 0, f"2026-02-{i+1:02d}") for i in range(12)]
        with mock.patch.object(fd.espn_data, "obtener_resultados", return_value=espn):
            res = fd.obtener_resultados(minimo=10)
        self.assertEqual(res["fuente"], "ESPN")
        self.assertEqual(res["total"], 12)

    def test_fallback_thesportsdb_si_espn_falla(self):
        tsdb = [_r("Pumas", "Cruz Azul", 1, 2)]
        with mock.patch.object(fd.espn_data, "obtener_resultados", side_effect=RuntimeError("ESPN caído")):
            with mock.patch.object(fd, "obtener_resultados_thesportsdb", return_value=tsdb):
                with mock.patch.object(fd, "guardar_cache"):
                    res = fd.obtener_resultados(minimo=10)
        self.assertIn("TheSportsDB", res["fuente"])
        self.assertEqual(res["total"], 1)

    def test_fallback_cache_si_todo_falla(self):
        with mock.patch.object(fd.espn_data, "obtener_resultados", return_value=[]):
            with mock.patch.object(fd, "obtener_resultados_thesportsdb", side_effect=RuntimeError("down")):
                with mock.patch.object(fd, "leer_cache", return_value=[_r("X", "Y", 0, 0)]):
                    res = fd.obtener_resultados(minimo=10)
        self.assertEqual(res["fuente"], "cache")
        self.assertEqual(res["total"], 1)

    def test_combina_espn_parcial_con_tsdb(self):
        espn = [_r("A", "B", 1, 0, "2026-02-01")]  # solo 1, < minimo
        tsdb = [_r("C", "D", 2, 2, "2026-02-02"), _r("A", "B", 1, 0, "2026-02-01")]  # 1 dup
        with mock.patch.object(fd.espn_data, "obtener_resultados", return_value=espn):
            with mock.patch.object(fd, "obtener_resultados_thesportsdb", return_value=tsdb):
                with mock.patch.object(fd, "guardar_cache"):
                    res = fd.obtener_resultados(minimo=10)
        self.assertEqual(res["total"], 2)  # dedup quitó el repetido
        self.assertIn("TheSportsDB", res["fuente"])


class TestCache(unittest.TestCase):
    def test_guardar_y_leer(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cache.json"
            fd.guardar_cache([_r("A", "B", 1, 0)], p)
            leido = fd.leer_cache(p)
        self.assertEqual(len(leido), 1)

    def test_leer_inexistente_vacio(self):
        self.assertEqual(fd.leer_cache(Path("/no/existe.json")), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
