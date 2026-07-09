#!/usr/bin/env python3
"""Tests para src/espn_data.py (ingesta ESPN). Sin red: requests mockeado."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import espn_data as ed  # noqa: E402


def _evento(home, away, hg, ag, estado="STATUS_FULL_TIME", fecha="2026-02-07T01:00Z"):
    return {
        "date": fecha,
        "status": {"type": {"name": estado}},
        "competitions": [{"competitors": [
            {"homeAway": "home", "team": {"displayName": home}, "score": hg},
            {"homeAway": "away", "team": {"displayName": away}, "score": ag},
        ]}],
    }


class TestParsearEventos(unittest.TestCase):
    def test_partido_jugado(self):
        data = {"events": [_evento("Necaxa", "Atlético de San Luis", "4", "1")]}
        p = ed.parsear_eventos(data)[0]
        self.assertEqual(p["home_team"], "Necaxa")
        self.assertEqual(p["away_team"], "Atlético de San Luis")
        self.assertTrue(p["jugado"])
        self.assertEqual(p["home_goals"], 4)
        self.assertEqual(p["away_goals"], 1)

    def test_partido_programado_sin_goles(self):
        data = {"events": [_evento("Necaxa", "Atlante", "0", "0", estado="STATUS_SCHEDULED")]}
        p = ed.parsear_eventos(data)[0]
        self.assertFalse(p["jugado"])
        self.assertNotIn("home_goals", p)

    def test_evento_incompleto_se_ignora(self):
        data = {"events": [{"competitions": [{"competitors": []}]}, "ruido"]}
        self.assertEqual(ed.parsear_eventos(data), [])

    def test_vacio(self):
        self.assertEqual(ed.parsear_eventos({}), [])


class TestObtenerResultados(unittest.TestCase):
    @mock.patch("espn_data._fetch_scoreboard")
    def test_filtra_jugados_y_formato_poisson(self, mock_fetch):
        mock_fetch.return_value = {"events": [
            _evento("Necaxa", "Atlante", "2", "1"),
            _evento("Pumas UNAM", "América", "0", "0", estado="STATUS_SCHEDULED"),
        ]}
        res = ed.obtener_resultados(meses=1)
        self.assertEqual(len(res), 1)
        self.assertEqual(set(res[0].keys()), {"home_team", "away_team", "home_goals", "away_goals", "fecha"})
        self.assertEqual(res[0]["home_goals"], 2)

    @mock.patch("espn_data._fetch_scoreboard")
    def test_deduplica(self, mock_fetch):
        # El mismo partido aparece en dos rangos -> una sola vez.
        mock_fetch.return_value = {"events": [_evento("Necaxa", "Atlante", "2", "1")]}
        res = ed.obtener_resultados(meses=3)
        self.assertEqual(len(res), 1)


class TestFetch(unittest.TestCase):
    def test_sin_requests_lanza(self):
        original = ed.requests
        try:
            ed.requests = None
            with self.assertRaises(RuntimeError):
                ed._fetch_scoreboard()
        finally:
            ed.requests = original

    @mock.patch("espn_data.requests")
    def test_http_error_lanza(self, mock_requests):
        resp = mock.Mock()
        resp.status_code = 500
        mock_requests.get.return_value = resp
        with self.assertRaises(RuntimeError):
            ed._fetch_scoreboard("20260201-20260228")


class TestRangos(unittest.TestCase):
    def test_genera_rangos(self):
        from datetime import datetime, timezone
        hoy = datetime(2026, 3, 15, tzinfo=timezone.utc)
        rangos = ed._rangos_meses_atras(3, hoy)
        self.assertEqual(len(rangos), 3)
        self.assertTrue(rangos[0].startswith("20260301"))


class TestIntegracionPoisson(unittest.TestCase):
    @mock.patch("espn_data._fetch_scoreboard")
    def test_resultados_alimentan_poisson(self, mock_fetch):
        import poisson_model as pm
        mock_fetch.return_value = {"events": [
            _evento("América", "Toluca", "3", "0"),
            _evento("América", "Atlas", "2", "1"),
            _evento("Toluca", "Atlas", "1", "1"),
            _evento("Toluca", "América", "0", "2"),
            _evento("Atlas", "América", "0", "3"),
            _evento("Atlas", "Toluca", "1", "1"),
        ]}
        res = ed.obtener_resultados(meses=1)
        fuerzas = pm.calcular_fuerzas(res)
        self.assertIn("américa", fuerzas["equipos"])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestProximaJornada(unittest.TestCase):
    def test_toma_solo_la_primera_jornada(self):
        # J1 (17-19 jul, 9 juegos) + arranque de J2 (22 jul). Debe cortar en J1.
        futuros = [
            {"home_team": "Necaxa", "away_team": "Atlante", "fecha": "2026-07-17"},
            {"home_team": "Tijuana", "away_team": "Tigres", "fecha": "2026-07-17"},
            {"home_team": "San Luis", "away_team": "Cruz Azul", "fecha": "2026-07-18"},
            {"home_team": "León", "away_team": "Atlas", "fecha": "2026-07-18"},
            {"home_team": "Juárez", "away_team": "Puebla", "fecha": "2026-07-18"},
            {"home_team": "Pumas", "away_team": "Pachuca", "fecha": "2026-07-18"},
            {"home_team": "Monterrey", "away_team": "Santos", "fecha": "2026-07-19"},
            {"home_team": "Guadalajara", "away_team": "Toluca", "fecha": "2026-07-19"},
            {"home_team": "Querétaro", "away_team": "América", "fecha": "2026-07-19"},
            # J2 (hueco de 3 días -> nueva jornada)
            {"home_team": "Cruz Azul", "away_team": "Puebla", "fecha": "2026-07-22"},
            {"home_team": "Toluca", "away_team": "Pumas", "fecha": "2026-07-22"},
        ]
        with mock.patch.object(ed, "obtener_fixtures_futuros", return_value=futuros):
            jj = ed.obtener_fixtures_proxima_jornada()
        self.assertEqual(len(jj), 9)
        nombres = {(p["home_team"], p["away_team"]) for p in jj}
        self.assertIn(("Querétaro", "América"), nombres)
        self.assertNotIn(("Cruz Azul", "Puebla"), nombres)  # ya es J2

    def test_corta_por_equipo_repetido(self):
        # Sin hueco de fechas, pero un equipo se repite -> cierra la jornada.
        futuros = [
            {"home_team": "América", "away_team": "Toluca", "fecha": "2026-07-18"},
            {"home_team": "Chivas", "away_team": "Atlas", "fecha": "2026-07-18"},
            {"home_team": "América", "away_team": "Pumas", "fecha": "2026-07-19"},
        ]
        with mock.patch.object(ed, "obtener_fixtures_futuros", return_value=futuros):
            jj = ed.obtener_fixtures_proxima_jornada()
        self.assertEqual(len(jj), 2)

    def test_sin_datos_devuelve_vacio(self):
        with mock.patch.object(ed, "obtener_fixtures_futuros", return_value=[]):
            self.assertEqual(ed.obtener_fixtures_proxima_jornada(), [])
