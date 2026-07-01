#!/usr/bin/env python3
"""Tests para src/telegram_webhook.py (comandos por Telegram). Sin red/BD real."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import telegram_webhook as tw  # noqa: E402


class TestParsearComando(unittest.TestCase):
    def test_comando_con_arg(self):
        self.assertEqual(tw.parsear_comando("/usado América"), ("usado", "América"))

    def test_comando_sin_arg(self):
        self.assertEqual(tw.parsear_comando("/usados"), ("usados", ""))

    def test_sufijo_bot_y_mayusculas(self):
        self.assertEqual(tw.parsear_comando("/PICK@MiBot"), ("pick", ""))

    def test_texto_normal_no_es_comando(self):
        self.assertEqual(tw.parsear_comando("hola bot"), (None, ""))

    def test_picks_y_pick_disparan_pronostico(self):
        # Tanto /pick como /picks deben estar en el set que genera el pronóstico.
        self.assertIn(tw.parsear_comando("/pick")[0], tw.CMDS_PICK)
        self.assertIn(tw.parsear_comando("/picks")[0], tw.CMDS_PICK)


class TestExtraerMensaje(unittest.TestCase):
    def test_message(self):
        upd = {"message": {"chat": {"id": 6019845354}, "text": "/usados"}}
        self.assertEqual(tw.extraer_mensaje(upd), (6019845354, "/usados"))

    def test_edited_message(self):
        upd = {"edited_message": {"chat": {"id": 7}, "text": "/pick"}}
        self.assertEqual(tw.extraer_mensaje(upd), (7, "/pick"))

    def test_sin_texto(self):
        self.assertEqual(tw.extraer_mensaje({"message": {"chat": {"id": 1}}}), (1, ""))


class TestResponder(unittest.TestCase):
    def setUp(self):
        self.db = mock.Mock()
        self._patch = mock.patch.object(tw, "_db", return_value=self.db)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def test_ayuda(self):
        self.assertIn("Comandos", tw.responder("ayuda", ""))
        self.assertIn("Comandos", tw.responder(None, ""))

    def test_usado_agrega(self):
        self.db.add_equipo_usado.return_value = True
        self.db.get_equipos_usados.return_value = ["América"]
        r = tw.responder("usado", "América")
        self.db.add_equipo_usado.assert_called_once_with("América")
        self.assertIn("Registrado", r)
        self.assertIn("América", r)

    def test_usado_ya_estaba(self):
        self.db.add_equipo_usado.return_value = False
        self.db.get_equipos_usados.return_value = ["América"]
        self.assertIn("Ya estaba", tw.responder("usado", "América"))

    def test_usado_sin_arg(self):
        self.assertIn("Uso:", tw.responder("usado", ""))
        self.db.add_equipo_usado.assert_not_called()

    def test_usados_lista(self):
        self.db.get_equipos_usados.return_value = ["América", "Toluca"]
        r = tw.responder("usados", "")
        self.assertIn("América", r)
        self.assertIn("Toluca", r)

    def test_quitar(self):
        self.db.remove_equipo_usado.return_value = 1
        self.db.get_equipos_usados.return_value = []
        self.assertIn("Quitado", tw.responder("quitar", "Toluca"))

    def test_reset(self):
        self.db.clear_equipos_usados.return_value = 3
        self.assertIn("reiniciada", tw.responder("reset", ""))

    def test_desconocido(self):
        self.assertIn("no reconocido", tw.responder("xyz", ""))


if __name__ == "__main__":
    unittest.main()
