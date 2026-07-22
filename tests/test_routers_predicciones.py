#!/usr/bin/env python3
"""Tests para src/routers/predicciones.py (endpoints de predicciones reales).

Llaman a las funciones de endpoint directamente (sin servidor ni httpx),
con el motor mockeado. No tocan red.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import importlib

pred = importlib.import_module("routers.predicciones")

from starlette.requests import Request  # noqa: E402

# Request minimo para llamar a los endpoints directamente (sin servidor HTTP).
# El rate limiter esta desactivado en tests (conftest.py) y los cuerpos de los
# endpoints no usan `request`; solo esta en la firma por slowapi.
_REQ = Request(
    scope={
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "client": ("127.0.0.1", 50000),
        "scheme": "http",
    }
)


def _fake_data():
    return {
        "generado_utc": "2026-07-16T10:00:00Z",
        "fuente_datos": "ESPN",
        "total_pronosticos": 1,
        "pronosticos": [
            {
                "local": "América",
                "visitante": "Toluca",
                "pick_1x2": "Gana Local",
                "no_perder_local_pct": 80.0,
                "no_perder_visitante_pct": 40.0,
            },
        ],
        "decision": "INFORMATIVO / REVISIÓN HUMANA",
    }


class TestEndpoints(unittest.TestCase):
    def setUp(self):
        pred._CACHE["data"] = None
        pred._CACHE["ts"] = None

    def test_predicciones_devuelve_datos(self):
        with mock.patch.object(pred.motor, "generar_pronosticos", return_value=_fake_data()):
            r = pred.predicciones(request=_REQ)
        self.assertEqual(r["fuente_datos"], "ESPN")
        self.assertEqual(r["total_pronosticos"], 1)

    def test_cache_evita_segunda_llamada(self):
        with mock.patch.object(pred.motor, "generar_pronosticos", return_value=_fake_data()) as m:
            pred.predicciones(request=_REQ)
            pred.predicciones(request=_REQ)
            self.assertEqual(m.call_count, 1)  # 2a vez usa caché

    def test_survivor_elige_mejor(self):
        with mock.patch.object(pred.motor, "generar_pronosticos", return_value=_fake_data()):
            r = pred.survivor(request=_REQ)
        self.assertEqual(r["pick_survivor"]["equipo"], "América")
        self.assertEqual(r["decision"], "INFORMATIVO / REVISIÓN HUMANA")

    def test_survivor_excluye(self):
        with mock.patch.object(pred.motor, "generar_pronosticos", return_value=_fake_data()):
            r = pred.survivor(request=_REQ, excluir="América")
        self.assertEqual(r["equipos_excluidos"], ["América"])
        # Excluido América, el mejor restante es Toluca (visitante, 40%).
        self.assertEqual(r["pick_survivor"]["equipo"], "Toluca")

    def test_tabla_devuelve_datos_y_decision(self):
        pred._CACHE_TABLA["data"] = None
        pred._CACHE_TABLA["ts"] = None
        fake = {
            "torneo": "2026 Torneo Apertura",
            "tabla": [{"posicion": 1, "equipo": "América", "motivacion_nivel": "alta"}],
        }
        with mock.patch.object(pred.tabla_mod, "obtener_tabla", return_value=fake):
            r = pred.tabla(request=_REQ)
        self.assertEqual(r["torneo"], "2026 Torneo Apertura")
        self.assertEqual(r["tabla"][0]["equipo"], "América")
        self.assertEqual(r["decision"], "INFORMATIVO / REVISIÓN HUMANA")

    def test_valor_passthrough_sin_mercado(self):
        with mock.patch.object(pred.motor, "generar_pronosticos", return_value=_fake_data()):
            with mock.patch.object(pred.mercado_mod, "mercado_habilitado", return_value=False):
                r = pred.valor(request=_REQ)
        self.assertFalse(r["mercado_habilitado"])
        self.assertEqual(r["fuente_datos"], "ESPN")
        self.assertIsNone(r["pronosticos"][0]["mercado"])

    def test_health_fuentes(self):
        fake = {"fuentes": {"espn": {"ok": True}}, "ok_global": True}
        with mock.patch.object(pred.fuentes_mod, "estado_fuentes", return_value=fake):
            r = pred.health_fuentes(request=_REQ)
        self.assertTrue(r["ok_global"])
        self.assertTrue(r["fuentes"]["espn"]["ok"])

    def test_jornada_todo_en_uno(self):
        with mock.patch.object(pred.motor, "generar_pronosticos", return_value=_fake_data()):
            with mock.patch.object(pred.motor, "motivacion_por_equipo", return_value={}):
                with mock.patch.object(pred.mercado_mod, "mercado_habilitado", return_value=False):
                    r = pred.jornada(request=_REQ)
        self.assertEqual(r["fuente_datos"], "ESPN")
        self.assertEqual(r["pick_survivor"]["equipo"], "América")
        self.assertTrue(len(r["top_picks"]) >= 1)
        self.assertFalse(r["mercado_habilitado"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
