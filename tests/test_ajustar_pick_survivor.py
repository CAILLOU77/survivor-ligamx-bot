#!/usr/bin/env python3
"""
Tests unitarios para src/ajustar_pick_survivor.py (ajuste anti-tumba).

Cubren funciones puras: parsear_avances_desde_log, mercado_real_disponible,
fecha_hora_confirmada, datos_reales_completos, construir_candidatos y el
núcleo de seguridad construir_decision.
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

import ajustar_pick_survivor as ap  # noqa: E402


class TestParsearAvances(unittest.TestCase):
    def test_parsea_linea_avance(self):
        log = "AVANCE SURVIVOR (No perder): America: 84.6% | Toluca: 38.5%"
        avances = ap.parsear_avances_desde_log(log)
        self.assertAlmostEqual(avances["america"], 84.6)
        self.assertAlmostEqual(avances["toluca"], 38.5)

    def test_log_sin_avances(self):
        self.assertEqual(ap.parsear_avances_desde_log("texto sin patron"), {})


class TestMercadoReal(unittest.TestCase):
    def test_bookmaker_real(self):
        self.assertTrue(ap.mercado_real_disponible(
            {"bookmakers": [{"key": "bet365", "title": "Bet365"}]}
        ))

    def test_sin_bookmakers(self):
        self.assertFalse(ap.mercado_real_disponible({"bookmakers": []}))

    def test_fallback_no_cuenta(self):
        self.assertFalse(ap.mercado_real_disponible(
            {"bookmakers": [{"key": "fallback_tecnico", "title": "Fallback"}]}
        ))

    def test_estado_cerrado(self):
        self.assertFalse(ap.mercado_real_disponible(
            {"momios": {"estado": "cerrado"}, "bookmakers": [{"key": "x"}]}
        ))


class TestFechaHora(unittest.TestCase):
    def test_confirmada(self):
        self.assertTrue(ap.fecha_hora_confirmada({"fecha": "2026-07-16", "hora": "19:00"}))

    def test_pendiente(self):
        self.assertFalse(ap.fecha_hora_confirmada({"fecha": "PENDIENTE", "hora": "19:00"}))

    def test_vacia(self):
        self.assertFalse(ap.fecha_hora_confirmada({}))


class TestDatosCompletos(unittest.TestCase):
    def test_completo(self):
        partido = {
            "fecha": "2026-07-16", "hora": "19:00",
            "bookmakers": [{"key": "bet365", "title": "Bet365"}],
        }
        self.assertTrue(ap.datos_reales_completos(partido))

    def test_incompleto_por_mercado(self):
        partido = {"fecha": "2026-07-16", "hora": "19:00", "bookmakers": []}
        self.assertFalse(ap.datos_reales_completos(partido))


class TestConstruirDecision(unittest.TestCase):
    """Núcleo de seguridad: cuándo CERRAR vs ESPERAR / NO ENVIAR."""

    def _cand(self, **kw):
        base = {
            "equipo": "America", "rival": "Toluca", "condicion": "Local",
            "avance_no_perder": 80.0, "riesgo_score": 30.0,
            "riesgo_etiqueta": "🟢 RIESGO BAJO", "riesgo_recomendacion": "",
            "score_ajustado": 70.0, "decision_candidato": "CANDIDATO_FUERTE",
            "mercado_real": True, "fecha_hora_confirmada": True,
            "datos_reales_completos": True,
        }
        base.update(kw)
        return base

    def test_sin_candidatos_no_enviar(self):
        d = ap.construir_decision([])
        self.assertEqual(d["decision"], "NO_ENVIAR")
        self.assertIsNone(d["pick"])

    def test_datos_incompletos_espera_no_enviar(self):
        d = ap.construir_decision([self._cand(
            datos_reales_completos=False, mercado_real=False
        )])
        self.assertEqual(d["decision"], "ESPERAR / NO ENVIAR")
        self.assertIn("faltan datos reales", d["mensaje"].lower())

    def test_riesgo_alto_no_cierra(self):
        d = ap.construir_decision([self._cand(riesgo_score=70.0)])
        self.assertEqual(d["decision"], "ESPERAR / NO ENVIAR")

    def test_candidato_fuerte_cierra(self):
        d = ap.construir_decision([self._cand(riesgo_score=30.0, avance_no_perder=80.0)])
        self.assertEqual(d["decision"], "CERRAR")

    def test_candidato_debil_espera(self):
        d = ap.construir_decision([self._cand(riesgo_score=30.0, avance_no_perder=65.0)])
        self.assertEqual(d["decision"], "ESPERAR")


class TestConstruirCandidatos(unittest.TestCase):
    def test_construye_y_excluye_sin_avance(self):
        data = [
            {"home_team": "America", "away_team": "Toluca",
             "riesgo_sorpresa": {"score": 30, "etiqueta": "🟢"}},
            {"home_team": "Atlas", "away_team": "Leon",
             "riesgo_sorpresa": {"score": 40, "etiqueta": "🟡"}},
        ]
        # El log solo trae avance para America/Toluca.
        log = "AVANCE SURVIVOR (No perder): America: 84.0% | Toluca: 40.0%"
        # Config vacío -> sin bloqueados.
        with mock.patch.object(ap, "cargar_json", return_value={}):
            cands = ap.construir_candidatos(data, log)
        equipos = {c["equipo"] for c in cands}
        self.assertIn("America", equipos)
        self.assertIn("Toluca", equipos)
        # Atlas/Leon sin avance en el log -> no son candidatos.
        self.assertNotIn("Atlas", equipos)
        self.assertNotIn("Leon", equipos)

    def test_ordenado_por_score_ajustado(self):
        data = [{"home_team": "America", "away_team": "Toluca",
                 "riesgo_sorpresa": {"score": 20, "etiqueta": "🟢"}}]
        log = "AVANCE SURVIVOR (No perder): America: 85.0% | Toluca: 35.0%"
        with mock.patch.object(ap, "cargar_json", return_value={}):
            cands = ap.construir_candidatos(data, log)
        scores = [c["score_ajustado"] for c in cands]
        self.assertEqual(scores, sorted(scores, reverse=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
