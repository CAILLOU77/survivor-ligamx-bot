#!/usr/bin/env python3
"""
Tests para src/prematch_recheck.py + CLI scripts/prematch_recheck_scheduler.py.

No hacen llamadas externas ni usan secretos reales.
Ejecutar:
    python3 -m unittest tests.test_prematch_recheck
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import prematch_recheck as pr  # noqa: E402

NOW = datetime(2026, 7, 16, 12, 0, 0)


def matrix_fake(apifootball="CONFIGURED_UNKNOWN", trio_activo=False):
    return [
        {"name": "The Odds API", "status": "CONFIGURED"},
        {"name": "API-Football", "status": apifootball},
        {"name": "Groq", "status": "CONFIGURED"},
        {"name": "Gemini", "status": "CONFIGURED"},
        {"name": "Cerebras", "status": "DISABLED_BY_CONFIG", "activo": trio_activo},
        {"name": "OpenRouter", "status": "DISABLED_BY_CONFIG", "activo": trio_activo},
        {"name": "Fireworks", "status": "DISABLED_BY_CONFIG", "activo": trio_activo},
    ]


def kickoff_en(minutos: float) -> datetime:
    return NOW + timedelta(minutes=minutos)


class TestClasificarVentana(unittest.TestCase):
    def test_upcoming_mas_de_48h(self):
        self.assertEqual(pr.clasificar_ventana(NOW, kickoff_en(3 * 24 * 60)), pr.WIN_UPCOMING)

    def test_due_t48(self):
        self.assertEqual(pr.clasificar_ventana(NOW, kickoff_en(47 * 60)), pr.WIN_T48)

    def test_due_t24(self):
        self.assertEqual(pr.clasificar_ventana(NOW, kickoff_en(20 * 60)), pr.WIN_T24)

    def test_due_t6(self):
        self.assertEqual(pr.clasificar_ventana(NOW, kickoff_en(5 * 60)), pr.WIN_T6)

    def test_due_t2(self):
        self.assertEqual(pr.clasificar_ventana(NOW, kickoff_en(90)), pr.WIN_T2)

    def test_due_t60(self):
        self.assertEqual(pr.clasificar_ventana(NOW, kickoff_en(30)), pr.WIN_T60)

    def test_live_or_locked(self):
        self.assertEqual(pr.clasificar_ventana(NOW, kickoff_en(-10)), pr.WIN_LIVE_OR_LOCKED)

    def test_unknown_time(self):
        self.assertEqual(pr.clasificar_ventana(NOW, None), pr.WIN_UNKNOWN_TIME)

    def test_bordes(self):
        # Exactamente 60 min -> T60; 60.x -> T2.
        self.assertEqual(pr.clasificar_ventana(NOW, kickoff_en(60)), pr.WIN_T60)
        self.assertEqual(pr.clasificar_ventana(NOW, kickoff_en(61)), pr.WIN_T2)
        # Exactamente 2880 (48h) -> T48; 2881 -> UPCOMING.
        self.assertEqual(pr.clasificar_ventana(NOW, kickoff_en(2880)), pr.WIN_T48)
        self.assertEqual(pr.clasificar_ventana(NOW, kickoff_en(2881)), pr.WIN_UPCOMING)


class TestParseKickoff(unittest.TestCase):
    def test_fecha_hora_valida(self):
        ko = pr.parse_kickoff("2026-07-16", "19:00")
        self.assertEqual(ko, datetime(2026, 7, 16, 19, 0))

    def test_pendiente_es_none(self):
        self.assertIsNone(pr.parse_kickoff("PENDIENTE_CONFIRMAR", "PENDIENTE_CONFIRMAR"))
        self.assertIsNone(pr.parse_kickoff("2026-07-16", "PENDIENTE_CONFIRMAR"))
        self.assertIsNone(pr.parse_kickoff("", ""))

    def test_fecha_iso_completa_sin_hora(self):
        # fecha ISO completa con 'T' y hora vacía/pendiente -> usa la hora del ISO.
        self.assertEqual(pr.parse_kickoff("2026-07-16T19:00:00", ""), datetime(2026, 7, 16, 19, 0))
        self.assertEqual(
            pr.parse_kickoff("2026-07-16T19:00:00", "PENDIENTE_CONFIRMAR"),
            datetime(2026, 7, 16, 19, 0),
        )

    def test_solo_fecha_sin_hora_es_none(self):
        # Fecha sin hora ISO y sin hora separada -> no se puede programar -> None.
        self.assertIsNone(pr.parse_kickoff("2026-07-16", ""))


class TestEvaluarPartido(unittest.TestCase):
    def test_plan_blocked_agrega_warning(self):
        partido = {"home_team": "Necaxa", "away_team": "Atlante",
                   "fecha": "2026-07-16", "hora": "18:00"}  # +6h -> T6
        ev = pr.evaluar_partido(NOW, partido, pr.AF_PLAN_BLOCKED_2026)
        self.assertEqual(ev["window"], pr.WIN_T6)
        self.assertTrue(any("alternativa" in w for w in ev["warnings"]))
        self.assertEqual(ev["decision"], pr.DEC_ESPERAR)

    def test_configured_unknown_mantiene_recheck(self):
        notas = pr.notas_apifootball(pr.AF_CONFIGURED_UNKNOWN)
        self.assertIn("RECHECK_BEFORE_MATCH", notas)
        self.assertTrue(any("No rotar llave" in n for n in notas))

    def test_unknown_time_sin_hora(self):
        partido = {"home_team": "A", "away_team": "B",
                   "fecha": "PENDIENTE_CONFIRMAR", "hora": "PENDIENTE_CONFIRMAR"}
        ev = pr.evaluar_partido(NOW, partido, pr.AF_MISSING)
        self.assertEqual(ev["window"], pr.WIN_UNKNOWN_TIME)


class TestCargarPartidos(unittest.TestCase):
    def test_falta_archivo_no_rompe(self):
        partidos, existe = pr.cargar_partidos(BASE_DIR / "no_existe_jornadas.json", 1)
        self.assertEqual(partidos, [])
        self.assertFalse(existe)


class TestResultadoYRender(unittest.TestCase):
    def _resultado(self, apifootball="PLAN_BLOCKED_2026"):
        partidos = [
            {"home_team": "Necaxa", "away_team": "Atlante", "fecha": "2026-07-16", "hora": "18:00"},
        ]
        return pr.construir_resultado(
            now=NOW, jornada=1, partidos=partidos, jornadas_existe=True,
            matrix=matrix_fake(apifootball=apifootball),
        )

    def test_decision_general_espera(self):
        res = self._resultado()
        self.assertEqual(res["decision_general"], pr.DEC_ESPERAR)

    def test_reporte_no_contiene_cerrar(self):
        reporte = pr.render_report(self._resultado())
        self.assertNotIn("CERRAR", reporte)

    def test_reporte_no_contiene_secretos(self):
        secreto = "SECRETO-NO-DEBE-APARECER-7777"
        reporte = pr.render_report(self._resultado())
        self.assertNotIn(secreto, reporte)
        self.assertIn("ESPERAR / NO ENVIAR", reporte)

    def test_reporte_tiene_encabezado_y_window(self):
        reporte = pr.render_report(self._resultado())
        self.assertIn("# PRE-MATCH RECHECK SCHEDULER — SURVIVOR LIGA MX", reporte)
        self.assertIn("Window: DUE_T6", reporte)

    def test_trio_no_activo(self):
        self.assertTrue(pr.opcionales_desactivados(matrix_fake(trio_activo=False)))
        self.assertFalse(pr.opcionales_desactivados(matrix_fake(trio_activo=True)))


class TestCLI(unittest.TestCase):
    def test_cli_genera_reporte(self):
        out_path = BASE_DIR / "reports" / "prematch_recheck_ultimo.txt"
        proc = subprocess.run(
            [sys.executable, "scripts/prematch_recheck_scheduler.py",
             "--jornada", "1", "--now", "2026-07-16T12:00:00"],
            cwd=str(BASE_DIR), capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(out_path.exists())
        contenido = out_path.read_text(encoding="utf-8")
        self.assertIn("PRE-MATCH RECHECK SCHEDULER", contenido)
        self.assertNotIn("CERRAR", contenido)
        self.assertIn("ESPERAR / NO ENVIAR", contenido)


if __name__ == "__main__":
    unittest.main(verbosity=2)
