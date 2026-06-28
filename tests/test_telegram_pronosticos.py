#!/usr/bin/env python3
"""Tests para src/telegram_pronosticos.py. Sin red: envío y motor mockeados."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import telegram_pronosticos as tp  # noqa: E402


def _resultado():
    return {
        "generado_utc": "2026-07-16T10:00:00Z",
        "fuente_datos": "ESPN",
        "total_pronosticos": 1,
        "pronosticos": [{
            "local": "América", "visitante": "Toluca", "pick_1x2": "Gana Local",
            "prob_local_pct": 55.0, "prob_empate_pct": 25.0, "prob_visitante_pct": 20.0,
            "pick_ou": "Over", "prob_over_pct": 60.0, "pick_btts": "Sí",
            "prob_btts_si_pct": 55.0, "marcador_mas_probable": "2-1",
            "no_perder_local_pct": 80.0, "no_perder_visitante_pct": 45.0,
        }],
        "decision": "INFORMATIVO / REVISIÓN HUMANA",
    }


class TestConstruirMensaje(unittest.TestCase):
    def test_incluye_partido_y_survivor(self):
        msg = tp.construir_mensaje(_resultado())
        self.assertIn("América vs Toluca", msg)
        self.assertIn("SURVIVOR sugerido", msg)
        self.assertIn("Gana Local", msg)

    def test_incluye_disclaimer(self):
        msg = tp.construir_mensaje(_resultado())
        self.assertIn("No es consejo de apuesta", msg)

    def test_sin_pronosticos(self):
        msg = tp.construir_mensaje({"pronosticos": [], "fuente_datos": "cache"})
        self.assertIn("Sin pronósticos", msg)
        self.assertIn("No es consejo de apuesta", msg)

    def test_no_recomienda_apostar_ni_ev_falso(self):
        msg = tp.construir_mensaje(_resultado())
        self.assertNotIn("Actúa rápido", msg)
        self.assertNotIn("Kelly", msg)


class TestEnviar(unittest.TestCase):
    def test_sin_credenciales_no_envia(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}, clear=False):
            self.assertFalse(tp.enviar_mensaje("hola"))

    def test_envia_con_credenciales(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}, clear=False):
            with mock.patch.object(tp, "requests") as mreq:
                mreq.post.return_value = mock.Mock(status_code=200)
                self.assertTrue(tp.enviar_mensaje("hola"))

    def test_enviar_pronosticos_flujo(self):
        with mock.patch.object(tp.motor, "generar_pronosticos", return_value=_resultado()):
            with mock.patch.object(tp, "enviar_mensaje", return_value=True) as menv:
                r = tp.enviar_pronosticos()
        self.assertTrue(r["enviado"])
        self.assertEqual(r["total_pronosticos"], 1)
        menv.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
