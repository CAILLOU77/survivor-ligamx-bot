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

    def test_historial_pronosticos_ciclo(self):
        db.init_db()
        # Registrar dos pronósticos.
        self.assertTrue(db.registrar_pronostico(
            "América", "Toluca", "Gana Local", 60.0, 22.0, 18.0, "2-1", fecha="2026-07-18"))
        self.assertTrue(db.registrar_pronostico(
            "Atlas", "Pumas", "Empate", 30.0, 40.0, 30.0, "1-1", fecha="2026-07-19"))
        # Duplicado (mismos equipos+fecha) -> no se inserta.
        self.assertFalse(db.registrar_pronostico(
            "america", "toluca", "Gana Local", 60.0, 22.0, 18.0, "2-1", fecha="2026-07-18"))
        self.assertEqual(len(db.historial_pronosticos()), 2)

        # Resolver con resultados reales: América ganó 2-1 (acierta 1X2 y marcador);
        # Atlas-Pumas terminó 0-2 (falla 1X2 y marcador).
        reales = [
            {"home_team": "América", "away_team": "Toluca", "home_goals": 2, "away_goals": 1, "fecha": "2026-07-18"},
            {"home_team": "Atlas", "away_team": "Pumas", "home_goals": 0, "away_goals": 2, "fecha": "2026-07-19"},
        ]
        self.assertEqual(db.settle_pronosticos(reales), 2)
        rent = db.rentabilidad_pronosticos()
        self.assertEqual(rent["resueltos"], 2)
        self.assertEqual(rent["aciertos_1x2"], 1)             # solo América
        self.assertEqual(rent["acierto_1x2_pct"], 50.0)
        self.assertEqual(rent["aciertos_marcador_exacto"], 1)  # solo América 2-1
        self.assertEqual(rent["pendientes"], 0)

    def test_settle_sin_resultado_queda_pendiente(self):
        db.init_db()
        db.registrar_pronostico("Leon", "Necaxa", "Gana Local", 55.0, 25.0, 20.0, "2-0", fecha="2026-08-01")
        # Resultado de otro partido -> no resuelve el de Leon.
        db.settle_pronosticos([{"home_team": "Cruz Azul", "away_team": "Atlas",
                                "home_goals": 1, "away_goals": 0, "fecha": "2026-08-01"}])
        self.assertEqual(db.rentabilidad_pronosticos()["pendientes"], 1)


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
