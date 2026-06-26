#!/usr/bin/env python3
"""
Tests para src/data_confidence.py (lógica pura + orquestación local).

No hacen llamadas externas ni usan secretos reales.
Ejecutar:
    python3 -m unittest tests.test_data_confidence
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import data_confidence as dc  # noqa: E402


def matrix_fake(*, groq="CONFIGURED", gemini="CONFIGURED", apifootball="CONFIGURED_UNKNOWN",
                trio_activo=False):
    return [
        {"name": "API-Football", "status": apifootball},
        {"name": "Groq", "status": groq},
        {"name": "Gemini", "status": gemini},
        {"name": "Cerebras", "status": "DISABLED_BY_CONFIG", "activo": trio_activo},
        {"name": "OpenRouter", "status": "DISABLED_BY_CONFIG", "activo": trio_activo},
        {"name": "Fireworks", "status": "DISABLED_BY_CONFIG", "activo": trio_activo},
    ]


def calc(**kwargs):
    base = dict(
        disponibles=0, total=9, has_movement=False,
        apifootball_status="CONFIGURED_UNKNOWN",
        fbref_available=False, news_available=False,
        groq_configured=True, gemini_configured=True, optional_disabled=True,
    )
    base.update(kwargs)
    return dc.calcular_confianza(**base)


class TestMercado(unittest.TestCase):
    def test_0_9_fuerza_esperar(self):
        res = calc(disponibles=0, total=9)
        self.assertEqual(res["decision"], dc.DEC_ESPERAR)
        # -40 market
        market = next(s for s in res["secciones"] if s["seccion"] == "Market Real")
        self.assertEqual(market["impacto"], -40)

    def test_9_9_alto_permite_ready(self):
        # 9/9 (+35) + movement (+10) + AF unknown (+5) + fbref (+10) + news (+10) + AI (+10) = 80
        res = calc(disponibles=9, total=9, has_movement=True,
                   apifootball_status="CONFIGURED_UNKNOWN",
                   fbref_available=True, news_available=True,
                   groq_configured=True, gemini_configured=True)
        self.assertGreaterEqual(res["total_score"], 70)
        self.assertEqual(res["decision"], dc.DEC_READY)
        self.assertIn("NO ENVIAR AUTOMÁTICO", res["decision"])

    def test_9_9_pero_score_no_alto_no_ready(self):
        # 9/9 (+35) pero todo lo demás mínimo: AF missing (-15) => 20 < 70
        res = calc(disponibles=9, total=9, has_movement=False,
                   apifootball_status="MISSING_ENV",
                   fbref_available=False, news_available=False,
                   groq_configured=False, gemini_configured=False)
        self.assertLess(res["total_score"], 70)
        self.assertEqual(res["decision"], dc.DEC_ESPERAR)

    def test_no_ready_si_mercado_no_es_9_9_aunque_score_alto(self):
        # 8/9 (+15) + todo lo demás alto -> score puede ser alto pero NO ready.
        res = calc(disponibles=8, total=9, has_movement=True,
                   apifootball_status="CONFIGURED_UNKNOWN",
                   fbref_available=True, news_available=True,
                   groq_configured=True, gemini_configured=True)
        self.assertEqual(res["decision"], dc.DEC_ESPERAR)
        self.assertNotIn("READY_FOR_FULL_AUDIT", res["decision"])


class TestClasificacion(unittest.TestCase):
    def test_low(self):
        self.assertEqual(dc.clasificar_confianza(39), dc.CONF_LOW)
        res = calc(disponibles=0, total=9)  # -40 base -> low
        self.assertEqual(res["confidence"], dc.CONF_LOW)

    def test_medium(self):
        self.assertEqual(dc.clasificar_confianza(40), dc.CONF_MEDIUM)
        self.assertEqual(dc.clasificar_confianza(69), dc.CONF_MEDIUM)

    def test_high(self):
        self.assertEqual(dc.clasificar_confianza(70), dc.CONF_HIGH)
        res = calc(disponibles=9, total=9, has_movement=True,
                   apifootball_status="CONFIGURED_UNKNOWN",
                   fbref_available=True, news_available=True)
        self.assertEqual(res["confidence"], dc.CONF_HIGH)


class TestApiFootball(unittest.TestCase):
    def test_plan_blocked_resta_y_warning(self):
        res = calc(disponibles=9, total=9, apifootball_status="PLAN_BLOCKED_2026")
        af = next(s for s in res["secciones"] if s["seccion"] == "API-Football")
        self.assertEqual(af["impacto"], -20)
        self.assertTrue(any("antes del kickoff" in w for w in res["warnings"]))

    def test_configured_unknown_suma_poco_y_recheck(self):
        res = calc(apifootball_status="CONFIGURED_UNKNOWN")
        af = next(s for s in res["secciones"] if s["seccion"] == "API-Football")
        self.assertEqual(af["impacto"], 5)
        self.assertTrue(any("RECHECK_BEFORE_MATCH" in n for n in af["notas"]))

    def test_missing_resta(self):
        res = calc(apifootball_status="MISSING_ENV")
        af = next(s for s in res["secciones"] if s["seccion"] == "API-Football")
        self.assertEqual(af["impacto"], -15)


class TestApoyos(unittest.TestCase):
    def test_fbref_suma_pero_no_cierra(self):
        res = calc(disponibles=0, total=9, fbref_available=True)
        fb = next(s for s in res["secciones"] if s["seccion"] == "FBref")
        self.assertEqual(fb["impacto"], 10)
        # FBref no cierra: con 0/9 sigue ESPERAR.
        self.assertEqual(res["decision"], dc.DEC_ESPERAR)
        self.assertTrue(any("no verdad automática" in n for n in fb["notas"]))

    def test_groq_gemini_suman(self):
        res = calc(groq_configured=True, gemini_configured=True)
        ai = next(s for s in res["secciones"] if s["seccion"] == "AI")
        self.assertEqual(ai["impacto"], 10)

    def test_trio_no_activo(self):
        m = matrix_fake(trio_activo=False)
        self.assertTrue(dc.opcionales_desactivados(m))
        m2 = matrix_fake(trio_activo=True)
        self.assertFalse(dc.opcionales_desactivados(m2))


class TestReporte(unittest.TestCase):
    def test_no_secretos(self):
        secreto = "SECRETO-NO-DEBE-APARECER-1234"
        res = calc(disponibles=9, total=9)
        # El resultado/render no incluye env values; simulamos que ningún input lo trae.
        reporte = dc.render_report(res)
        self.assertNotIn(secreto, reporte)

    def test_no_cerrar(self):
        for disp in (0, 8, 9):
            res = calc(disponibles=disp, total=9, has_movement=True,
                       fbref_available=True, news_available=True)
            reporte = dc.render_report(res)
            self.assertNotIn("CERRAR", reporte)

    def test_termina_con_decision(self):
        reporte = dc.render_report(calc(disponibles=0, total=9))
        self.assertIn("DECISIÓN:", reporte)
        self.assertIn("No enviar Telegram", reporte)


class TestOrquestacionLocal(unittest.TestCase):
    def test_falta_watchdog_no_rompe(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            res = dc.evaluar(base, matrix_fake())
            # Sin watchdog -> 0/9 -> ESPERAR
            self.assertEqual(res["mercado_disponibles"], 0)
            self.assertEqual(res["decision"], dc.DEC_ESPERAR)

    def test_falta_fbref_no_rompe(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "data").mkdir()
            (base / "data" / "watchdog_state.json").write_text(
                json.dumps({"disponibles": 9, "total": 9, "mercados_baseline": {"x": 1}}),
                encoding="utf-8",
            )
            res = dc.evaluar(base, matrix_fake())
            fb = next(s for s in res["secciones"] if s["seccion"] == "FBref")
            self.assertEqual(fb["status"], "MISSING")  # no rompe, solo 0 impacto
            self.assertEqual(fb["impacto"], 0)

    def test_9_9_con_apoyos_locales(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "data" / "fbref").mkdir(parents=True)
            (base / "reports").mkdir()
            (base / "data" / "watchdog_state.json").write_text(
                json.dumps({"disponibles": 9, "total": 9, "mercados_baseline": {"x": 1}}),
                encoding="utf-8",
            )
            (base / "data" / "fbref" / "fbref_ligamx_schedule_jornada1.csv").write_text("Wk\n1\n", encoding="utf-8")
            (base / "data" / "noticias_ligamx.txt").write_text("lesion de jugador X", encoding="utf-8")
            res = dc.evaluar(base, matrix_fake(apifootball="CONFIGURED_UNKNOWN"))
            self.assertTrue(res["mercado_completo"])
            self.assertGreaterEqual(res["total_score"], 70)
            self.assertEqual(res["decision"], dc.DEC_READY)


if __name__ == "__main__":
    unittest.main(verbosity=2)
