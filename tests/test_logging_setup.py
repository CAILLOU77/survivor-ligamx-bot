#!/usr/bin/env python3
"""Tests para src/logging_setup.py (logging estructurado JSON). Sin red."""

from __future__ import annotations

import json
import logging
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import logging_setup as ls  # noqa: E402


class TestJSONFormatter(unittest.TestCase):
    def test_format_produce_json_con_campos_base(self):
        fmt = ls.JSONFormatter()
        record = logging.LogRecord("mi_logger", logging.INFO, "f.py", 1, "hola %s", ("mundo",), None)
        obj = json.loads(fmt.format(record))
        self.assertEqual(obj["level"], "INFO")
        self.assertEqual(obj["logger"], "mi_logger")
        self.assertEqual(obj["message"], "hola mundo")
        self.assertIn("timestamp", obj)

    def test_format_incluye_campos_extra(self):
        fmt = ls.JSONFormatter()
        record = logging.LogRecord("l", logging.WARNING, "f.py", 1, "msg", None, None)
        record.equipo = "América"  # campo extra personalizado
        obj = json.loads(fmt.format(record))
        self.assertEqual(obj["equipo"], "América")

    def test_format_con_excepcion(self):
        fmt = ls.JSONFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            record = logging.LogRecord("l", logging.ERROR, "f.py", 1, "falló", None, sys.exc_info())
        obj = json.loads(fmt.format(record))
        self.assertIn("exception", obj)
        self.assertIn("ValueError", obj["exception"])


class TestSetupLogging(unittest.TestCase):
    def test_setup_json_por_defecto(self):
        with mock.patch.dict(os.environ, {"LOG_FORMAT": "json", "LOG_LEVEL": "DEBUG"}):
            logger = ls.setup_logging()
        self.assertEqual(logger.level, logging.DEBUG)
        self.assertTrue(any(isinstance(h.formatter, ls.JSONFormatter) for h in logger.handlers))

    def test_setup_formato_texto(self):
        with mock.patch.dict(os.environ, {"LOG_FORMAT": "text"}):
            logger = ls.setup_logging()
        self.assertFalse(any(isinstance(h.formatter, ls.JSONFormatter) for h in logger.handlers))

    def test_setup_nivel_por_parametro(self):
        logger = ls.setup_logging(level="WARNING")
        self.assertEqual(logger.level, logging.WARNING)


class TestGetLogger(unittest.TestCase):
    def test_get_logger_nombre(self):
        self.assertEqual(ls.get_logger("mi_modulo").name, "mi_modulo")


if __name__ == "__main__":
    unittest.main(verbosity=2)
