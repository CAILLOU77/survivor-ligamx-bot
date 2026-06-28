#!/usr/bin/env python3
"""Tests para src/comparador_mercado.py (comparación modelo vs mercado). Sin red."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import comparador_mercado as cm  # noqa: E402


class TestQuitarVig(unittest.TestCase):
    def test_suma_uno_y_vig_positivo(self):
        r = cm.quitar_vig(2.0, 3.5, 4.0)
        self.assertAlmostEqual(r["prob_local"] + r["prob_empate"] + r["prob_visita"], 1.0, places=9)
        self.assertGreater(r["vig"], 0.0)

    def test_favorito_tiene_mayor_prob(self):
        r = cm.quitar_vig(1.5, 4.0, 6.0)  # local muy favorito
        self.assertGreater(r["prob_local"], r["prob_visita"])

    def test_momio_invalido_lanza(self):
        with self.assertRaises(ValueError):
            cm.quitar_vig(1.0, 3.0, 4.0)


class TestComparar(unittest.TestCase):
    def test_detecta_valor_cuando_modelo_supera_mercado(self):
        # Modelo da 70% local; mercado (2.0) implica ~50% -> valor en local.
        r = cm.comparar([0.70, 0.20, 0.10], 2.0, 3.5, 4.0)
        self.assertTrue(r["hay_valor"])
        self.assertEqual(r["valor_en"], "local")
        self.assertEqual(r["decision"], cm.DISCLAIMER)

    def test_sin_valor_cuando_modelo_igual_mercado(self):
        # Modelo ~ igual al mercado -> sin valor relevante.
        mkt = cm.quitar_vig(2.0, 3.5, 4.0)
        prob = [mkt["prob_local"], mkt["prob_empate"], mkt["prob_visita"]]
        r = cm.comparar(prob, 2.0, 3.5, 4.0)
        self.assertFalse(r["hay_valor"])
        self.assertIsNone(r["valor_en"])

    def test_acepta_porcentajes(self):
        r = cm.comparar([70.0, 20.0, 10.0], 2.0, 3.5, 4.0)
        self.assertAlmostEqual(sum(r["prob_modelo_pct"]), 100.0, places=1)

    def test_largo_invalido_lanza(self):
        with self.assertRaises(ValueError):
            cm.comparar([0.5, 0.5], 2.0, 3.5, 4.0)


class TestAnotar(unittest.TestCase):
    def _pron(self):
        return {"local": "América", "visitante": "Toluca",
                "prob_local_pct": 70.0, "prob_empate_pct": 20.0, "prob_visitante_pct": 10.0}

    def test_sin_momios_mercado_none(self):
        r = cm.anotar_pronostico(self._pron(), None)
        self.assertIsNone(r["mercado"])

    def test_con_momios_anota(self):
        r = cm.anotar_pronostico(self._pron(), {"local": 2.0, "empate": 3.5, "visita": 4.0})
        self.assertIsNotNone(r["mercado"])
        self.assertTrue(r["mercado"]["hay_valor"])

    def test_anotar_lista_empareja_por_clave(self):
        pron = self._pron()
        clave = cm._clave_partido("América", "Toluca")
        momios = {clave: {"local": 2.0, "empate": 3.5, "visita": 4.0}}
        out = cm.anotar_pronosticos([pron], momios)
        self.assertIsNotNone(out[0]["mercado"])


class TestParseOdds(unittest.TestCase):
    def test_promedia_casas(self):
        book = {
            "bet365": {"home": "2.00", "draw": "3.40", "away": "4.00"},
            "pinnacle": {"home": "2.10", "draw": "3.60", "away": "3.80"},
        }
        m = cm.parsear_odds_1x2(book)
        self.assertAlmostEqual(m["local"], 2.05, places=2)
        self.assertAlmostEqual(m["empate"], 3.50, places=2)

    def test_vacio_o_invalido_es_none(self):
        self.assertIsNone(cm.parsear_odds_1x2({}))
        self.assertIsNone(cm.parsear_odds_1x2({"x": {"home": "abc"}}))
        self.assertIsNone(cm.parsear_odds_1x2(None))


class TestGating(unittest.TestCase):
    def test_deshabilitado_sin_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(cm.mercado_habilitado())
            self.assertEqual(cm.obtener_momios_liga_mx(), {})

    def test_habilitado_con_key(self):
        with mock.patch.dict(os.environ, {cm.ENV_KEY: "abc123"}, clear=True):
            self.assertTrue(cm.mercado_habilitado())

    def test_comparar_pronosticos_passthrough_sin_key(self):
        pron = [{"local": "A", "visitante": "B", "prob_local_pct": 50,
                 "prob_empate_pct": 30, "prob_visitante_pct": 20}]
        with mock.patch.dict(os.environ, {}, clear=True):
            r = cm.comparar_pronosticos(pron)
        self.assertFalse(r["mercado_habilitado"])
        self.assertEqual(r["partidos_con_momios"], 0)
        self.assertIsNone(r["pronosticos"][0]["mercado"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
