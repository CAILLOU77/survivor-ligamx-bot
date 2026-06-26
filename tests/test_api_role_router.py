#!/usr/bin/env python3
"""
Tests para src/api_role_router.py (lógica pura, sin red ni secretos reales).

Ejecutar:
    python3 -m unittest tests.test_api_role_router
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import api_role_router as router  # noqa: E402


def _record_por_nombre(matrix, nombre):
    for r in matrix:
        if r["name"] == nombre:
            return r
    raise AssertionError(f"No se encontró el proveedor {nombre} en la matriz")


class TestEnvDeteccion(unittest.TestCase):
    def test_env_set_sin_imprimir_valor(self):
        env = {"ODDS_API_KEY": "super-secreto-123"}
        resultado = router.env_set(env, ["ODDS_API_KEY"])
        # Solo debe devolver booleano, nunca el valor.
        self.assertIsInstance(resultado, bool)
        self.assertTrue(resultado)

    def test_env_missing(self):
        self.assertFalse(router.env_set({}, ["ODDS_API_KEY"]))
        self.assertFalse(router.env_set({"ODDS_API_KEY": ""}, ["ODDS_API_KEY"]))
        self.assertFalse(router.env_set({"ODDS_API_KEY": "tu_api_key"}, ["ODDS_API_KEY"]))

    def test_reporte_no_filtra_secretos(self):
        secreto = "KEYVALUE-NO-DEBE-APARECER-9999"
        env = {
            "ODDS_API_KEY_PRIMARY": secreto,
            "GROQ_API_KEY": secreto,
            "GEMINI_API_KEY": secreto,
            "CEREBRAS_API_KEY": secreto,
            "ODDS_MARKETS": "h2h,totals,spreads",
        }
        reporte = router.render_report(router.build_matrix(env))
        self.assertNotIn(secreto, reporte)
        # Pero sí debe indicar que está configurado.
        self.assertIn("Env: SET", reporte)


class TestDisabledProviders(unittest.TestCase):
    def test_enabled_false_es_disabled_by_config(self):
        env = {
            "CEREBRAS_API_KEY": "x", "CEREBRAS_ENABLED": "false",
            "OPENROUTER_API_KEY": "x", "OPENROUTER_ENABLED": "false",
            "FIREWORKS_API_KEY": "x", "FIREWORKS_ENABLED": "false",
        }
        matrix = router.build_matrix(env)
        for nombre in ("Cerebras", "OpenRouter", "Fireworks"):
            rec = _record_por_nombre(matrix, nombre)
            self.assertEqual(rec["status"], router.ST_DISABLED_BY_CONFIG)
            self.assertEqual(rec["enabled"], False)

    def test_trio_no_se_activa_aunque_enabled_true(self):
        env = {
            "CEREBRAS_API_KEY": "x", "CEREBRAS_ENABLED": "true",
            "OPENROUTER_API_KEY": "x", "OPENROUTER_ENABLED": "true",
            "FIREWORKS_API_KEY": "x", "FIREWORKS_ENABLED": "true",
        }
        matrix = router.build_matrix(env)
        for nombre in ("Cerebras", "OpenRouter", "Fireworks"):
            rec = _record_por_nombre(matrix, nombre)
            # Nunca activos en v1.36.0, aunque ENABLED=true.
            self.assertFalse(rec["activo"])
            self.assertFalse(router.proveedor_activo(rec))
            self.assertNotEqual(rec["status"], router.ST_CONFIGURED)

    def test_openrouter_nota_content_none(self):
        rec = _record_por_nombre(router.build_matrix({}), "OpenRouter")
        self.assertTrue(any("content=None" in n for n in rec["notas"]))


class TestOddsMarkets(unittest.TestCase):
    def test_recomendado(self):
        info = router.clasificar_odds_markets("h2h,totals,spreads")
        self.assertEqual(info["status"], "OK")
        self.assertTrue(info["recomendado"])
        self.assertTrue(any("recomendada" in n for n in info["notas"]))

    def test_btts_o_dnb_es_unsupported(self):
        info = router.clasificar_odds_markets("h2h,totals,spreads,btts")
        self.assertEqual(info["status"], router.ERR_UNSUPPORTED_MARKET)
        info2 = router.clasificar_odds_markets("h2h,draw_no_bet")
        self.assertEqual(info2["status"], router.ERR_UNSUPPORTED_MARKET)

    def test_http_422_no_es_fallo_de_llave(self):
        self.assertEqual(router.clasificar_error_odds(422), router.ERR_UNSUPPORTED_MARKET)
        self.assertNotEqual(router.clasificar_error_odds(422), router.ERR_AUTH)


class TestApiFootball(unittest.TestCase):
    def test_plan_season_block_es_plan_blocked_2026(self):
        res = router.clasificar_error_apifootball(403, "Your subscription does not allow access to season 2026")
        self.assertEqual(res["clasificacion"], router.ST_PLAN_BLOCKED_2026)

    def test_plan_season_block_no_rota_llave(self):
        for status, msg in [
            (403, "This season is not available in your plan"),
            (200, "You are not subscribed to this season (2026)"),
            (429, "Too many requests / daily limit"),
            (401, "Invalid API key"),
        ]:
            res = router.clasificar_error_apifootball(status, msg)
            self.assertFalse(res["rotar"], f"No debe rotar para: {msg}")
            self.assertFalse(router.debe_rotar_llave(res))

    def test_fallo_tecnico_si_rota(self):
        res = router.clasificar_error_apifootball(503, "Service Unavailable")
        self.assertEqual(res["clasificacion"], router.ERR_TECHNICAL)
        self.assertTrue(res["rotar"])

    def test_recheck_before_match_presente(self):
        env = {"FOOTBALL_API_KEY_1": "x"}
        rec = _record_por_nombre(router.build_matrix(env), "API-Football")
        self.assertTrue(rec["recheck"])
        self.assertTrue(any(router.RECHECK_TAG in n for n in rec["notas"]))

    def test_estado_plan_blocked_por_flag(self):
        env = {"FOOTBALL_API_KEY_1": "x", "APIFOOTBALL_PLAN_BLOCKED_2026": "true"}
        self.assertEqual(router.clasificar_estado_apifootball(env), router.ST_PLAN_BLOCKED_2026)

    def test_estado_configured_unknown_con_llave(self):
        env = {"FOOTBALL_API_KEY_1": "x"}
        self.assertEqual(router.clasificar_estado_apifootball(env), router.ST_CONFIGURED_UNKNOWN)


class TestReporte(unittest.TestCase):
    def test_reporte_termina_en_esperar_no_enviar(self):
        reporte = router.render_report(router.build_matrix({}))
        self.assertIn("Mantener ESPERAR / NO ENVIAR", reporte)
        self.assertTrue(reporte.rstrip().endswith("Mantener ESPERAR / NO ENVIAR."))

    def test_reporte_tiene_encabezado_y_roles(self):
        reporte = router.render_report(router.build_matrix({}))
        self.assertIn("# API HEALTH MATRIX — SURVIVOR LIGA MX", reporte)
        self.assertIn(router.ROLE_MARKET_TRUTH, reporte)
        self.assertIn(router.ROLE_TEAM_NEWS, reporte)
        self.assertIn(router.ROLE_PRIMARY_AI, reporte)

    def test_no_pone_cerrar(self):
        reporte = router.render_report(router.build_matrix({}))
        self.assertNotIn("CERRAR", reporte)


if __name__ == "__main__":
    unittest.main(verbosity=2)
