#!/usr/bin/env python3
"""Tests para src/odds_dataset.py (generador de dataset de momios)."""
from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import odds_dataset as od  # noqa: E402


def _bookmaker(key, c1, cx, c2, local="America", visita="Toluca"):
    return {
        "key": key, "title": key,
        "markets": [{"key": "h2h", "outcomes": [
            {"name": local, "price": c1},
            {"name": "Draw", "price": cx},
            {"name": visita, "price": c2},
        ]}],
    }


def _partido(local="America", visita="Toluca", c1=1.8, cx=3.5, c2=4.5, evento_id="evt1"):
    return {
        "home_team": local, "away_team": visita,
        "momios": {"evento_id": evento_id},
        "bookmakers": [_bookmaker("bet365", c1, cx, c2, local, visita)],
    }


class TestIdMercado(unittest.TestCase):
    def test_usa_evento_id(self):
        self.assertEqual(od.id_mercado(_partido(evento_id="abc123")), "abc123")

    def test_fallback_equipos(self):
        p = {"home_team": "America", "away_team": "Toluca", "bookmakers": []}
        self.assertEqual(od.id_mercado(p), "america__toluca")


class TestFilaBase(unittest.TestCase):
    def test_columnas_completas(self):
        fila = od.fila_base(_partido(), "2026-07-16T00:00:00Z")
        for c in od.CAMPOS:
            self.assertIn(c, fila)

    def test_true_prob_suman_uno(self):
        fila = od.fila_base(_partido(), "t")
        total = fila["true_prob_1"] + fila["true_prob_2"] + fila["true_prob_3"]
        self.assertAlmostEqual(total, 1.0, places=3)

    def test_vig_positivo(self):
        fila = od.fila_base(_partido(), "t")
        self.assertGreater(fila["vig_pct"], 0)

    def test_sin_mercado_real_none(self):
        p = {"home_team": "A", "away_team": "B",
             "bookmakers": [_bookmaker("fallback_local", 1.8, 3.4, 4.5)]}
        self.assertIsNone(od.fila_base(p, "t"))


class TestTrend(unittest.TestCase):
    def test_sin_previo_es_cero(self):
        self.assertEqual(od.calcular_trend([1.8, 3.5, 4.5], None), [0, 0, 0])

    def test_subio_bajo_estable(self):
        # actual vs previo: m1 sube, m2 baja, m3 estable.
        actual = [2.0, 3.0, 4.5]
        previo = [1.8, 3.5, 4.5]
        self.assertEqual(od.calcular_trend(actual, previo), [1, -1, 0])

    def test_umbral_evita_ruido(self):
        # Cambio mínimo (<1%) -> estable.
        self.assertEqual(od.calcular_trend([1.805, 3.5, 4.5], [1.8, 3.5, 4.5]), [0, 0, 0])


class TestConstruirFilas(unittest.TestCase):
    def test_trend_vs_previo(self):
        partidos = [_partido(c1=2.0, cx=3.0, c2=4.5, evento_id="evt1")]
        previos = {"evt1": [1.8, 3.5, 4.5]}
        filas = od.construir_filas(partidos, "t2", previos)
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["trend_1"], 1)   # momio local subió
        self.assertEqual(filas[0]["trend_2"], -1)  # empate bajó

    def test_primer_snapshot_trend_cero(self):
        filas = od.construir_filas([_partido()], "t1", {})
        self.assertEqual([filas[0]["trend_1"], filas[0]["trend_2"], filas[0]["trend_3"]], [0, 0, 0])


class TestPersistencia(unittest.TestCase):
    def test_escribir_y_leer(self):
        filas = od.construir_filas([_partido()], "t1", {})
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "ds.csv"
            od.escribir_dataset(filas, path)
            leido = od.leer_dataset(path)
            with path.open(encoding="utf-8") as f:
                header = next(csv.reader(f))
        self.assertEqual(header, od.CAMPOS)
        self.assertEqual(len(leido), 1)
        self.assertEqual(leido[0]["id_mercado"], "evt1")

    def test_ultimos_momios_por_id(self):
        filas = [
            {"id_mercado": "evt1", "momio_1": "1.8", "momio_2": "3.5", "momio_3": "4.5"},
            {"id_mercado": "evt1", "momio_1": "2.0", "momio_2": "3.2", "momio_3": "4.0"},
        ]
        ult = od.ultimos_momios_por_id(filas)
        self.assertEqual(ult["evt1"], [2.0, 3.2, 4.0])  # se queda con el último

    def test_acumula_snapshots(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "ds.csv"
            f1 = od.construir_filas([_partido(c1=1.8)], "t1", {})
            od.escribir_dataset(f1, path)
            hist = od.leer_dataset(path)
            previos = od.ultimos_momios_por_id(hist)
            f2 = od.construir_filas([_partido(c1=2.0)], "t2", previos)
            od.escribir_dataset(hist + f2, path)
            final = od.leer_dataset(path)
        self.assertEqual(len(final), 2)
        self.assertEqual(int(final[1]["trend_1"]), 1)  # subió en el 2o snapshot


if __name__ == "__main__":
    unittest.main(verbosity=2)
