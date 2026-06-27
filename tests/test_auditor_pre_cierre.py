#!/usr/bin/env python3
"""
Tests unitarios para src/auditor_pre_cierre.py.

Cubren funciones puras (fecha_hora_confirmada, mercado_real_disponible) y la
lógica de decisión evaluar_pre_cierre (con cargar_json mockeado para inyectar
datos controlados, sin tocar el filesystem real).
No modifican la lógica de producción.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import auditor_pre_cierre as apc  # noqa: E402


class TestFechaHora(unittest.TestCase):
    def test_confirmada(self):
        self.assertTrue(apc.fecha_hora_confirmada({"fecha": "2026-07-16", "hora": "19:00"}))

    def test_pendiente(self):
        self.assertFalse(apc.fecha_hora_confirmada({"fecha": "PENDIENTE", "hora": "19:00"}))

    def test_vacia(self):
        self.assertFalse(apc.fecha_hora_confirmada({}))


class TestMercadoReal(unittest.TestCase):
    def test_real(self):
        self.assertTrue(apc.mercado_real_disponible(
            {"bookmakers": [{"key": "bet365", "title": "Bet365"}]}
        ))

    def test_sin_bookmakers(self):
        self.assertFalse(apc.mercado_real_disponible({"bookmakers": []}))

    def test_fallback(self):
        self.assertFalse(apc.mercado_real_disponible(
            {"bookmakers": [{"key": "fallback", "title": "x"}]}
        ))


def _partido_completo():
    return {
        "home_team": "America", "away_team": "Toluca",
        "fecha": "2026-07-16", "hora": "19:00",
        "bookmakers": [{"key": "bet365", "title": "Bet365"}],
        "bajas_revisadas": True,
        "riesgo_sorpresa": {"nivel": "VERDE", "etiqueta": "🟢 RIESGO BAJO"},
    }


class TestEvaluarPreCierre(unittest.TestCase):
    def _patch_cargar(self, jornadas, pick):
        # cargar_json se llama primero con JORNADAS_PATH, luego con PICK_AJUSTADO_PATH.
        def _side_effect(path, default):
            p = str(path)
            if "pick_ajustado" in p:
                return pick
            return jornadas
        return mock.patch.object(apc, "cargar_json", side_effect=_side_effect)

    def test_sin_partidos_espera_no_enviar(self):
        with self._patch_cargar([], {}):
            res = apc.evaluar_pre_cierre()
        self.assertEqual(res["decision_final"], "ESPERAR / NO ENVIAR")
        self.assertTrue(res["problemas"])

    def test_partido_incompleto_espera_no_enviar(self):
        partido = {"home_team": "A", "away_team": "B"}  # sin fecha/mercado/bajas
        with self._patch_cargar([partido], {"decision": {"decision": "CERRAR"}}):
            res = apc.evaluar_pre_cierre()
        self.assertEqual(res["decision_final"], "ESPERAR / NO ENVIAR")

    def test_riesgo_rojo_bloquea(self):
        partido = _partido_completo()
        partido["riesgo_sorpresa"] = {"nivel": "ROJO", "etiqueta": "🔴 TUMBA QUINIELAS"}
        with self._patch_cargar([partido], {"decision": {"decision": "CERRAR"}}):
            res = apc.evaluar_pre_cierre()
        self.assertEqual(res["decision_final"], "ESPERAR / NO ENVIAR")

    def test_pick_no_cerrar_bloquea(self):
        partido = _partido_completo()
        with self._patch_cargar([partido], {"decision": {"decision": "ESPERAR"}}):
            res = apc.evaluar_pre_cierre()
        self.assertEqual(res["decision_final"], "ESPERAR / NO ENVIAR")

    def test_todo_completo_y_pick_cerrar_permite_cerrar(self):
        partido = _partido_completo()
        with self._patch_cargar([partido], {"decision": {"decision": "CERRAR"}}):
            res = apc.evaluar_pre_cierre()
        self.assertEqual(res["decision_final"], "CERRAR")
        self.assertFalse(res["problemas"])

    def test_estructura_resultado(self):
        with self._patch_cargar([], {}):
            res = apc.evaluar_pre_cierre()
        for k in ("decision_final", "mensaje", "problemas", "avisos", "decision_pick_ajustado"):
            self.assertIn(k, res)


if __name__ == "__main__":
    unittest.main(verbosity=2)
