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
        self.assertIn("SURVIVOR", msg)
        self.assertIn("🥇", msg)  # ranking top-3
        # el pick del partido se muestra con el nombre real del club (no "Gana Local")
        self.assertIn("🎯 Pick: <b>América</b>", msg)
        self.assertNotIn("Gana Local", msg)

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

    def test_incluye_contexto_api_si_se_pasa(self):
        ctx = {
            "home": "América", "away": "Toluca",
            "prediccion_api": {"prob_local_pct": 55.0, "prob_empate_pct": 25.0,
                               "prob_visita_pct": 20.0, "goles_esp": "1.8-1.0"},
            "forma_local": "WWDLW", "forma_visita": "LDLWD",
            "en_riesgo_local": ["Jugador X"], "en_riesgo_visita": [],
            "h2h": None,
        }
        msg = tp.construir_mensaje(_resultado(), contexto_pick=ctx)
        self.assertIn("Contexto (Liga MX API)", msg)
        self.assertIn("2ª opinión API", msg)
        self.assertIn("En riesgo", msg)
        self.assertIn("Jugador X", msg)

    def test_contexto_pretemporada_no_ensucia(self):
        # dossier resuelto pero vacío (sin datos aún) -> no agrega bloque.
        ctx = {"home": "América", "away": "Toluca", "prediccion_api": None,
               "forma_local": None, "forma_visita": None,
               "en_riesgo_local": [], "en_riesgo_visita": [], "h2h": None}
        msg = tp.construir_mensaje(_resultado(), contexto_pick=ctx)
        self.assertNotIn("Contexto (Liga MX API)", msg)


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
            with mock.patch.object(tp.motor, "motivacion_por_equipo", return_value={}):
                with mock.patch.object(tp, "_contexto_top_pick", return_value=None):
                    with mock.patch.object(tp, "_partidos_jugados_torneo", return_value=100):
                        with mock.patch.object(tp, "enviar_mensaje", return_value=True) as menv:
                            r = tp.enviar_pronosticos()
        self.assertTrue(r["enviado"])
        self.assertEqual(r["total_pronosticos"], 1)
        menv.assert_called_once()

    def test_enviar_pronosticos_sin_contexto_no_llama_api(self):
        # incluir_contexto=False no debe intentar resolver el dossier.
        with mock.patch.object(tp.motor, "generar_pronosticos", return_value=_resultado()):
            with mock.patch.object(tp.motor, "motivacion_por_equipo", return_value={}):
                with mock.patch.object(tp, "_partidos_jugados_torneo", return_value=100):
                    with mock.patch.object(tp, "_contexto_top_pick") as mctx:
                        with mock.patch.object(tp, "enviar_mensaje", return_value=True):
                            tp.enviar_pronosticos(incluir_contexto=False)
        mctx.assert_not_called()


class TestMercadoYMotivacion(unittest.TestCase):
    def test_linea_mercado_aparece(self):
        res = _resultado()
        res["pronosticos"][0]["mercado"] = {
            "1x2": {"favorito_mercado": "local", "hay_valor": True, "valor_en": "local",
                    "momios": {"local": 1.85, "empate": 3.40, "visita": 4.50}},
            "over_under": {"mercado_ve": "explosivo", "hay_valor": False, "valor_en": None,
                           "linea": 2.5, "momios": {"over": 1.90, "under": 1.95}},
            "handicap": {"favorito": "local", "linea": -0.5},
        }
        msg = tp.construir_mensaje(res)
        self.assertIn("📈 Mercado ve:", msg)
        self.assertIn("fav local", msg)
        self.assertIn("explosivo", msg)

    def test_momios_reales_aparecen(self):
        res = _resultado()
        res["pronosticos"][0]["mercado"] = {
            "1x2": {"favorito_mercado": "local",
                    "momios": {"local": 1.85, "empate": 3.40, "visita": 4.50}},
            "over_under": {"mercado_ve": "explosivo", "linea": 2.5,
                           "momios": {"over": 1.90, "under": 1.95}},
        }
        msg = tp.construir_mensaje(res)
        self.assertIn("💰 Momios:", msg)
        self.assertIn("América 1.85", msg)
        self.assertIn("Toluca 4.5", msg)
        self.assertIn("Over 1.9", msg)

    def test_sin_mercado_no_pone_linea(self):
        msg = tp.construir_mensaje(_resultado())
        self.assertNotIn("💰 Momios:", msg)
        self.assertNotIn("📈 Mercado ve:", msg)

    def test_motivacion_rival_en_pick(self):
        motivacion = {"toluca": {"motivacion_nivel": "baja"}}
        msg = tp.construir_mensaje(_resultado(), motivacion=motivacion)
        self.assertIn("rival mot.: baja", msg)


class TestNivelRiesgoYPlan(unittest.TestCase):
    def test_top3_incluye_nivel_y_ganar(self):
        msg = tp.construir_mensaje(_resultado())
        self.assertIn("🏆 Gana:", msg)                 # prob. de ganar (punto)
        self.assertIn("Sobrevive (gana o empata):", msg)  # no-perder, claro
        # nivel entre corchetes (ALTA/MEDIA/RIESGOSA)
        self.assertTrue(any(n in msg for n in ("[ALTA]", "[MEDIA]", "[RIESGOSA]")))

    def test_mensaje_plan_con_datos(self):
        plan = {
            "prob_supervivencia_total_pct": 66.8, "victorias_esperadas": 2.05,
            "jornadas_riesgosas": [2],
            "plan": [
                {"jornada": 1, "equipo": "Tigres UANL", "rival": "Mazatlán FC",
                 "condicion": "Local", "prob_ganar_pct": 78.8, "no_perder_pct": 94.0, "nivel": "ALTA"},
                {"jornada": 2, "equipo": "Cruz Azul", "rival": "Querétaro",
                 "condicion": "Visitante", "prob_ganar_pct": 50.0, "no_perder_pct": 62.0, "nivel": "RIESGOSA"},
            ],
        }
        msg = tp.construir_mensaje_plan(plan)
        self.assertIn("PLAN SURVIVOR", msg)
        self.assertIn("Tigres UANL", msg)
        self.assertIn("J1", msg)
        self.assertIn("⚠️ Jornadas riesgosas", msg)
        self.assertIn("No es consejo de apuesta", msg)

    def test_mensaje_plan_sin_calendario(self):
        msg = tp.construir_mensaje_plan({"calendario_incompleto": True, "plan": []})
        self.assertIn("calendario", msg.lower())
        self.assertIn("No es consejo de apuesta", msg)

    def test_enviar_plan_sin_calendario(self):
        import planificador_survivor as ps
        with mock.patch.object(ps, "cargar_calendario", return_value=[]):
            with mock.patch.object(tp, "enviar_mensaje", return_value=True) as menv:
                r = tp.enviar_plan()
        self.assertTrue(r["calendario_incompleto"])
        self.assertEqual(r["jornadas"], 0)
        menv.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
