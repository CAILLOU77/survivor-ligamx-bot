#!/usr/bin/env python3
"""Tests: construir snapshots de momios (comparador) y archivarlos (ligamx_api). Sin red."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import comparador_mercado as cm  # noqa: E402
import ligamx_api as lmx  # noqa: E402


class TestConstruirSnapshots(unittest.TestCase):
    def test_arma_snapshot_con_nombres_y_momios(self):
        pron = [{"local": "América", "visitante": "Toluca", "fecha": "2026-07-20"}]
        clave = cm._clave_partido("América", "Toluca")
        momios = {
            clave: {
                "ml": {"local": 1.8, "empate": 3.4, "visita": 4.2},
                "totals": {"linea": 2.5, "over": 1.9, "under": 1.9},
            }
        }
        snaps = cm.construir_snapshots_momios(pron, momios, source="odds-api.io")
        self.assertEqual(len(snaps), 1)
        s = snaps[0]
        self.assertEqual(s["home_team"], "América")
        self.assertEqual(s["away_team"], "Toluca")
        self.assertEqual(s["odds_local"], 1.8)
        self.assertEqual(s["ou_linea"], 2.5)
        self.assertEqual(s["source"], "odds-api.io")
        self.assertEqual(s["match_date"], "2026-07-20")

    def test_sin_momios_lista_vacia(self):
        pron = [{"local": "A", "visitante": "B"}]
        self.assertEqual(cm.construir_snapshots_momios(pron, {}), [])


class TestArchivarMomios(unittest.TestCase):
    def test_sin_key_no_op(self):
        with mock.patch.dict("os.environ", {"LIGAMX_API_SYNC_KEY": ""}, clear=False):
            self.assertEqual(lmx.archivar_momios([{"home_team": "A", "away_team": "B"}]), 0)

    def test_postea_con_key(self):
        fake = mock.Mock()
        fake.status_code = 200
        fake.json.return_value = {"guardados": 2}
        with (
            mock.patch.dict("os.environ", {"LIGAMX_API_SYNC_KEY": "k"}, clear=False),
            mock.patch.object(lmx.requests, "post", return_value=fake) as mpost,
        ):
            n = lmx.archivar_momios([{"home_team": "A", "away_team": "B"}, {"home_team": "C", "away_team": "D"}])
        self.assertEqual(n, 2)
        mpost.assert_called_once()
        # Debe mandar la X-API-Key en el header.
        _, kwargs = mpost.call_args
        self.assertEqual(kwargs["headers"]["X-API-Key"], "k")

    def test_error_de_red_no_rompe(self):
        with (
            mock.patch.dict("os.environ", {"LIGAMX_API_SYNC_KEY": "k"}, clear=False),
            mock.patch.object(lmx.requests, "post", side_effect=Exception("caida")),
        ):
            self.assertEqual(lmx.archivar_momios([{"home_team": "A", "away_team": "B"}]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
