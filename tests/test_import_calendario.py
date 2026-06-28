#!/usr/bin/env python3
"""Tests para scripts/import_calendario.py y espn_data._rangos_dias_adelante. Sin red."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
for p in (str(BASE / "src"), str(BASE / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import espn_data  # noqa: E402
import import_calendario as ic  # noqa: E402


class TestConstruirCalendario(unittest.TestCase):
    def test_agrupa_por_semana_y_numera(self):
        fixtures = [
            {"home_team": "América", "away_team": "Toluca", "fecha": "2026-07-18"},
            {"home_team": "Cruz Azul", "away_team": "Pumas UNAM", "fecha": "2026-07-19"},
            {"home_team": "Tigres UANL", "away_team": "Atlas", "fecha": "2026-07-25"},
        ]
        cal = ic.construir_calendario(fixtures)
        self.assertEqual(len(cal), 2)  # dos fines de semana => dos jornadas
        self.assertEqual([j["jornada"] for j in cal], [1, 2])
        self.assertEqual(len(cal[0]["partidos"]), 2)  # J1 tiene 2 partidos
        self.assertEqual(len(cal[1]["partidos"]), 1)

    def test_ignora_incompletos(self):
        fixtures = [
            {"home_team": "América", "away_team": "", "fecha": "2026-07-18"},
            {"home_team": "", "away_team": "Toluca", "fecha": "2026-07-18"},
            {"home_team": "A", "away_team": "B", "fecha": "basura"},
        ]
        self.assertEqual(ic.construir_calendario(fixtures), [])

    def test_semana_iso(self):
        self.assertTrue(ic._semana_iso("2026-07-18").startswith("2026-W"))
        self.assertEqual(ic._semana_iso("basura"), "")


class TestRangosAdelante(unittest.TestCase):
    def test_rangos_van_hacia_adelante(self):
        hoy = datetime(2026, 7, 1, tzinfo=timezone.utc)
        rangos = espn_data._rangos_dias_adelante(60, hoy=hoy)
        self.assertTrue(rangos)
        # El primer rango arranca hoy.
        self.assertTrue(rangos[0].startswith("20260701-"))
        # Formato 'YYYYMMDD-YYYYMMDD'.
        for r in rangos:
            ini, fin = r.split("-")
            self.assertEqual(len(ini), 8)
            self.assertEqual(len(fin), 8)
            self.assertLess(ini, fin)


if __name__ == "__main__":
    unittest.main()
