#!/usr/bin/env python3
"""Tests de humo para src/database.py (backend SQLite). Sin red, sin Postgres."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import database as db  # noqa: E402


class TestDatabaseSQLite(unittest.TestCase):
    def setUp(self):
        # Forzar backend SQLite en un archivo temporal aislado.
        self._tmp = tempfile.TemporaryDirectory()
        self._patchers = [
            mock.patch.object(db, "USE_POSTGRES", False),
            mock.patch.object(db, "PH", "?"),
            mock.patch.object(db, "SQLITE_PATH", str(Path(self._tmp.name) / "test.db")),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        self._tmp.cleanup()

    def test_ciclo_completo(self):
        db.init_db()
        # Métricas vacías al inicio.
        m0 = db.get_metrics()
        self.assertEqual(m0["total_picks"], 0)
        self.assertEqual(m0["win_rate"], 0)

        # Guardar dos picks.
        db.save_pick("match-1", "1x2", 0.55, 2.0, 0.10, 0.05)
        db.save_pick("match-2", "ou", 0.60, 1.8, 0.08, 0.04)

        hist = db.get_history(limit=10)
        self.assertEqual(len(hist), 2)
        self.assertEqual(hist[0]["match_id"], "match-2")  # más reciente primero
        self.assertEqual(hist[0]["status"], "pending")

        # Liquidar el primero como ganado.
        pick_id = hist[-1]["id"]
        filas = db.settle_pick(pick_id, result=1.0, profit_loss=1.0)
        self.assertEqual(filas, 1)

        m1 = db.get_metrics()
        self.assertEqual(m1["total_picks"], 1)  # solo 1 settled
        self.assertEqual(m1["wins"], 1)
        self.assertEqual(m1["win_rate"], 100.0)
        self.assertAlmostEqual(m1["total_profit"], 1.0)

    def test_get_history_paginacion(self):
        db.init_db()
        for i in range(5):
            db.save_pick(f"m{i}", "1x2", 0.5, 2.0, 0.0, 0.0)
        page = db.get_history(limit=2, offset=0)
        self.assertEqual(len(page), 2)
        page2 = db.get_history(limit=2, offset=2)
        self.assertEqual(len(page2), 2)
        # Sin solapamiento entre páginas.
        ids = {r["id"] for r in page} | {r["id"] for r in page2}
        self.assertEqual(len(ids), 4)

    def test_equipos_usados_ciclo(self):
        db.init_db()
        self.assertEqual(db.get_equipos_usados(), [])
        self.assertTrue(db.add_equipo_usado("América"))
        self.assertTrue(db.add_equipo_usado("Toluca"))
        # Duplicado por normalización (acentos/mayúsculas) -> no se agrega.
        self.assertFalse(db.add_equipo_usado("america"))
        usados = db.get_equipos_usados()
        self.assertEqual(len(usados), 2)
        self.assertIn("América", usados)
        # Quitar uno.
        self.assertEqual(db.remove_equipo_usado("TOLUCA"), 1)
        self.assertEqual(db.get_equipos_usados(), ["América"])
        # Reset.
        db.add_equipo_usado("Cruz Azul")
        self.assertGreaterEqual(db.clear_equipos_usados(), 1)
        self.assertEqual(db.get_equipos_usados(), [])

    def test_norm_equipo(self):
        self.assertEqual(db._norm_equipo("  Club  AMÉRICA "), "club america")


class TestEsPostgres(unittest.TestCase):
    def test_detecta_postgres(self):
        self.assertTrue(db._es_postgres("postgresql://u:p@h/db"))
        self.assertTrue(db._es_postgres("postgres://u:p@h/db"))

    def test_no_postgres(self):
        self.assertFalse(db._es_postgres(""))
        self.assertFalse(db._es_postgres("data/premium_history.db"))
        self.assertFalse(db._es_postgres("sqlite:///x.db"))


if __name__ == "__main__":
    unittest.main()
