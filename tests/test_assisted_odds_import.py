#!/usr/bin/env python3
"""
Tests para src/assisted_odds_import.py y el CLI scripts/assisted_caliente_odds.py.

Lógica pura: NO abre navegador, NO usa red, NO requiere Playwright.

Ejecutar:
    python3 -m unittest tests.test_assisted_odds_import
o:
    python3 tests/test_assisted_odds_import.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Hacemos importable src/ (mismo patrón de imports planos del proyecto).
BASE_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import assisted_odds_import as aoi  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures: texto visible single-line (estilo Caliente Liga MX, v1.39.0)
# ---------------------------------------------------------------------------
TEXTO_CALIENTE_9 = """\
Apuestas Fútbol México  Liga MX  Hoy  Mañana  Más ligas
Local   Empate   Visitante
21:05 16 Jul América -160 Empate +320 Atlas +420
19:00 16 Jul Necaxa -125 Empate +260 Atlante +275
17:00 17 Jul Cruz Azul -140 Empate +280 Pumas UNAM +360
19:00 17 Jul Chivas +110 Empate +240 Tigres UANL +210
21:00 17 Jul Monterrey -170 Empate +330 Mazatlán +440
12:00 18 Jul Toluca -150 Empate +290 Querétaro +390
17:00 18 Jul León -115 Empate +250 Juárez +300
19:00 18 Jul Pachuca -130 Empate +270 Santos +330
21:00 18 Jul Tijuana +105 Empate +245 Puebla +215
Ver más mercados  Reglas de la casa
"""

TEXTO_BLOQUE_GIGANTE = (
    "Liga MX Apuestas "
    "19:00 16 Jul Necaxa -125 Empate +260 Atlante +275 "
    "21:05 16 Jul América -160 Empate +320 Atlas +420 "
    "fin de la lista"
)

# ---------------------------------------------------------------------------
# Fixtures: texto multiline (formato Chrome normal, v1.39.1)
# ---------------------------------------------------------------------------
TEXTO_MULTILINE_1 = """\
Necaxa
-125
Empate
+260
Atlante
+275
"""

TEXTO_MULTILINE_9 = """\
Apuestas Fútbol México
Liga MX
Próximos eventos
Necaxa
-125
Empate
+260
Atlante
+275
Tijuana Xolos de Caliente
+180
Empate
+230
Tigres UANL
+140
Atlético San Luis
+260
Empate
+220
Cruz Azul
-110
León
+150
Empate
+230
Atlas
+175
FC Juárez
+130
Empate
+240
Puebla
+200
Pumas UNAM
+160
Empate
+225
Pachuca
+155
Chivas Guadalajara
+120
Empate
+235
Toluca
+210
Monterrey
-145
Empate
+280
Santos Laguna
+350
Querétaro FC
+300
Empate
+250
América
-130
"""

# Texto con mercado de campeón mezclado entre partidos 1X2.
TEXTO_MULTILINE_CON_FUTURO = """\
Necaxa
-125
Empate
+260
Atlante
+275
Ganador Liga MX
América
+150
Cruz Azul
+200
Chivas Guadalajara
+120
Empate
+235
Toluca
+210
"""

# Texto con momios sueltos que NO forman un partido completo.
TEXTO_MOMIOS_SUELTOS = """\
Apuestas Fútbol
Liga MX
-125
+260
+275
Más mercados
"""


class TestMomioAmericano(unittest.TestCase):
    def test_validos(self):
        for m in ("+120", "-125", "+260", "-160", "+100", "-100", "+275"):
            self.assertTrue(aoi.es_momio_americano_valido(m), m)

    def test_invalidos(self):
        for m in ("125", "+99", "-50", "+5", "abc", "", None, "+", "1.5"):
            self.assertFalse(aoi.es_momio_americano_valido(m), repr(m))


# ===========================================================================
# Tests SINGLE-LINE (formato original v1.39.0)
# ===========================================================================
class TestParser9Partidos(unittest.TestCase):
    def test_detecta_nueve(self):
        res = aoi.analizar_texto(TEXTO_CALIENTE_9, esperados=9)
        self.assertEqual(res["status"], aoi.STATUS_OK)
        self.assertEqual(res["total_validos"], 9)
        self.assertTrue(res["coincide_esperados"])
        self.assertEqual(res["duplicados_removidos"], 0)
        self.assertEqual(len(res["invalidos"]), 0)

    def test_campos_extraidos(self):
        res = aoi.analizar_texto(TEXTO_CALIENTE_9, esperados=9)
        necaxa = next(
            e for e in res["eventos"] if e["equipo_local"] == "Necaxa"
        )
        self.assertEqual(necaxa["hora"], "19:00")
        self.assertEqual(necaxa["fecha"], "16 Jul")
        self.assertEqual(necaxa["equipo_visitante"], "Atlante")
        self.assertEqual(necaxa["momio_local"], "-125")
        self.assertEqual(necaxa["momio_empate"], "+260")
        self.assertEqual(necaxa["momio_visitante"], "+275")

    def test_equipos_multipalabra(self):
        res = aoi.analizar_texto(TEXTO_CALIENTE_9, esperados=9)
        cruz = next(e for e in res["eventos"] if e["equipo_local"] == "Cruz Azul")
        self.assertEqual(cruz["equipo_visitante"], "Pumas UNAM")

    def test_singleline_formato_detectado(self):
        res = aoi.analizar_texto(TEXTO_CALIENTE_9, esperados=9)
        self.assertEqual(res["formato_detectado"], "single-line")


class TestNoMezclaBloqueGigante(unittest.TestCase):
    def test_no_mezcla_pares(self):
        res = aoi.analizar_texto(TEXTO_BLOQUE_GIGANTE, esperados=2)
        self.assertEqual(res["total_validos"], 2)
        pares = {
            (e["equipo_local"], e["equipo_visitante"]) for e in res["eventos"]
        }
        self.assertIn(("Necaxa", "Atlante"), pares)
        self.assertIn(("América", "Atlas"), pares)
        self.assertNotIn(("Necaxa", "Atlas"), pares)
        self.assertNotIn(("América", "Atlante"), pares)

    def test_no_se_traga_otro_partido_en_visitante(self):
        res = aoi.analizar_texto(TEXTO_BLOQUE_GIGANTE, esperados=2)
        for e in res["eventos"]:
            self.assertNotRegex(e["equipo_local"], r"\d{1,2}:\d{2}")
            self.assertNotRegex(e["equipo_visitante"], r"\d{1,2}:\d{2}")
            self.assertNotIn("+", e["equipo_visitante"])
            self.assertNotIn("-", e["equipo_visitante"])


# ===========================================================================
# Tests MULTILINE (nuevo en v1.39.1)
# ===========================================================================
class TestParserMultiline1Partido(unittest.TestCase):
    """Parser multiline con formato: Necaxa / -125 / Empate / +260 / Atlante / +275."""

    def test_detecta_un_partido(self):
        res = aoi.analizar_texto(TEXTO_MULTILINE_1, esperados=1)
        self.assertEqual(res["status"], aoi.STATUS_OK)
        self.assertEqual(res["total_validos"], 1)
        self.assertTrue(res["coincide_esperados"])

    def test_campos_multiline(self):
        res = aoi.analizar_texto(TEXTO_MULTILINE_1, esperados=1)
        ev = res["eventos"][0]
        self.assertEqual(ev["equipo_local"], "Necaxa")
        self.assertEqual(ev["momio_local"], "-125")
        self.assertEqual(ev["momio_empate"], "+260")
        self.assertEqual(ev["equipo_visitante"], "Atlante")
        self.assertEqual(ev["momio_visitante"], "+275")

    def test_multiline_formato_detectado(self):
        res = aoi.analizar_texto(TEXTO_MULTILINE_1, esperados=1)
        self.assertEqual(res["formato_detectado"], "multiline")


class TestParserMultiline9Partidos(unittest.TestCase):
    """Parser multiline con los 9 partidos reales de Liga MX."""

    def test_detecta_nueve(self):
        res = aoi.analizar_texto(TEXTO_MULTILINE_9, esperados=9)
        self.assertEqual(res["status"], aoi.STATUS_OK)
        self.assertEqual(res["total_validos"], 9)
        self.assertTrue(res["coincide_esperados"])
        self.assertEqual(res["duplicados_removidos"], 0)

    def test_partidos_correctos(self):
        res = aoi.analizar_texto(TEXTO_MULTILINE_9, esperados=9)
        pares = [
            (e["equipo_local"], e["equipo_visitante"]) for e in res["eventos"]
        ]
        esperados = [
            ("Necaxa", "Atlante"),
            ("Tijuana Xolos de Caliente", "Tigres UANL"),
            ("Atlético San Luis", "Cruz Azul"),
            ("León", "Atlas"),
            ("FC Juárez", "Puebla"),
            ("Pumas UNAM", "Pachuca"),
            ("Chivas Guadalajara", "Toluca"),
            ("Monterrey", "Santos Laguna"),
            ("Querétaro FC", "América"),
        ]
        for par in esperados:
            self.assertIn(par, pares, f"{par} no encontrado en resultados")

    def test_momios_correctos_necaxa(self):
        res = aoi.analizar_texto(TEXTO_MULTILINE_9, esperados=9)
        necaxa = next(e for e in res["eventos"] if e["equipo_local"] == "Necaxa")
        self.assertEqual(necaxa["momio_local"], "-125")
        self.assertEqual(necaxa["momio_empate"], "+260")
        self.assertEqual(necaxa["momio_visitante"], "+275")

    def test_momios_correctos_monterrey(self):
        res = aoi.analizar_texto(TEXTO_MULTILINE_9, esperados=9)
        mty = next(e for e in res["eventos"] if e["equipo_local"] == "Monterrey")
        self.assertEqual(mty["momio_local"], "-145")
        self.assertEqual(mty["momio_empate"], "+280")
        self.assertEqual(mty["momio_visitante"], "+350")
        self.assertEqual(mty["equipo_visitante"], "Santos Laguna")

    def test_no_mezcla_partidos_multiline(self):
        """Verificar que cada par local/visitante es correcto (no se mezclan)."""
        res = aoi.analizar_texto(TEXTO_MULTILINE_9, esperados=9)
        for ev in res["eventos"]:
            # Ningún nombre de equipo debe contener un momio.
            self.assertFalse(aoi.es_momio_americano_valido(ev["equipo_local"]))
            self.assertFalse(aoi.es_momio_americano_valido(ev["equipo_visitante"]))
            # Ningún nombre debe ser "Empate"/"Draw"/"X".
            self.assertNotIn(ev["equipo_local"].lower(), ("empate", "draw", "x"))
            self.assertNotIn(ev["equipo_visitante"].lower(), ("empate", "draw", "x"))


class TestNoMezclaFuturos(unittest.TestCase):
    """No mezcla mercados de campeón/futuros con partidos 1X2."""

    def test_filtra_campeon_multiline(self):
        res = aoi.analizar_texto(TEXTO_MULTILINE_CON_FUTURO, esperados=2)
        # Solo debe detectar Necaxa vs Atlante y Chivas vs Toluca.
        self.assertEqual(res["total_validos"], 2)
        pares = {
            (e["equipo_local"], e["equipo_visitante"]) for e in res["eventos"]
        }
        self.assertIn(("Necaxa", "Atlante"), pares)
        self.assertIn(("Chivas Guadalajara", "Toluca"), pares)
        # No debe incluir equipos del mercado de campeón como partido 1X2.
        locales = {e["equipo_local"] for e in res["eventos"]}
        self.assertNotIn("América", locales)
        self.assertNotIn("Cruz Azul", locales)


# ===========================================================================
# Tests: PARSER_NEEDS_REVIEW (momios detectados pero sin partidos completos)
# ===========================================================================
class TestParserNeedsReview(unittest.TestCase):
    """Si detecta momios pero no puede formar partidos, reporta PARSER_NEEDS_REVIEW."""

    def test_momios_sueltos_sin_partidos(self):
        res = aoi.analizar_texto(TEXTO_MOMIOS_SUELTOS, esperados=1)
        self.assertEqual(res["status"], aoi.STATUS_PARSER_NEEDS_REVIEW)
        self.assertEqual(res["total_validos"], 0)
        self.assertEqual(res["decision"], aoi.DEC_ESPERAR)

    def test_reporte_parser_needs_review(self):
        res = aoi.analizar_texto(TEXTO_MOMIOS_SUELTOS, esperados=1)
        reporte = aoi.render_report(res)
        self.assertIn("PARSER_NEEDS_REVIEW", reporte)
        self.assertIn("ESPERAR / NO ENVIAR", reporte)
        self.assertNotIn("NO_MATCHES_FOUND", reporte)


# ===========================================================================
# Tests de momio inválido y deduplicación
# ===========================================================================
class TestMomioInvalido(unittest.TestCase):
    def test_evento_con_momio_invalido_se_descarta(self):
        texto = "19:00 16 Jul Necaxa +50 Empate +260 Atlante +275"
        res = aoi.analizar_texto(texto, esperados=1)
        self.assertEqual(res["total_validos"], 0)
        self.assertEqual(len(res["invalidos"]), 1)

    def test_evento_valido_convive_con_invalido(self):
        texto = (
            "19:00 16 Jul Necaxa +50 Empate +260 Atlante +275\n"
            "21:05 16 Jul América -160 Empate +320 Atlas +420\n"
        )
        res = aoi.analizar_texto(texto, esperados=1)
        self.assertEqual(res["total_validos"], 1)
        self.assertEqual(len(res["invalidos"]), 1)
        self.assertEqual(res["eventos"][0]["equipo_local"], "América")


class TestDuplicados(unittest.TestCase):
    def test_partido_duplicado_se_deduplica(self):
        texto = (
            "19:00 16 Jul Necaxa -125 Empate +260 Atlante +275\n"
            "19:00 16 Jul Necaxa -125 Empate +260 Atlante +275\n"
        )
        res = aoi.analizar_texto(texto, esperados=1)
        self.assertEqual(res["total_validos"], 1)
        self.assertEqual(res["duplicados_removidos"], 1)

    def test_dedup_ignora_acentos_y_mayusculas(self):
        texto = (
            "21:05 16 Jul América -160 Empate +320 Atlas +420\n"
            "21:05 16 Jul America -160 Empate +320 ATLAS +420\n"
        )
        res = aoi.analizar_texto(texto, esperados=1)
        self.assertEqual(res["total_validos"], 1)
        self.assertEqual(res["duplicados_removidos"], 1)

    def test_dedup_multiline(self):
        """Duplicados multiline también se remueven."""
        texto = (
            "Necaxa\n-125\nEmpate\n+260\nAtlante\n+275\n"
            "Necaxa\n-125\nEmpate\n+260\nAtlante\n+275\n"
        )
        res = aoi.analizar_texto(texto, esperados=1)
        self.assertEqual(res["total_validos"], 1)
        self.assertEqual(res["duplicados_removidos"], 1)


# ===========================================================================
# Tests de NO_MATCHES_FOUND
# ===========================================================================
class TestNoMatchesFound(unittest.TestCase):
    def test_texto_sin_eventos_ni_momios(self):
        res = aoi.analizar_texto("Bienvenido a la página. No hay momios visibles.")
        self.assertEqual(res["status"], aoi.STATUS_NO_MATCHES)
        self.assertEqual(res["total_validos"], 0)

    def test_texto_vacio(self):
        res = aoi.analizar_texto("")
        self.assertEqual(res["status"], aoi.STATUS_NO_MATCHES)


# ===========================================================================
# Tests de reporte
# ===========================================================================
class TestReporte(unittest.TestCase):
    def test_reporte_mantiene_esperar_no_enviar(self):
        res = aoi.analizar_texto(TEXTO_CALIENTE_9, esperados=9)
        reporte = aoi.render_report(res, url=aoi.FUENTE)
        self.assertIn("ESPERAR / NO ENVIAR", reporte)
        self.assertIn("No marcar pick listo", reporte)
        self.assertNotIn("CERRAR", reporte)

    def test_reporte_multiline_esperar(self):
        res = aoi.analizar_texto(TEXTO_MULTILINE_9, esperados=9)
        reporte = aoi.render_report(res)
        self.assertIn("ESPERAR / NO ENVIAR", reporte)
        self.assertIn("No marcar pick listo", reporte)
        self.assertNotIn("CERRAR", reporte)

    def test_reporte_sin_secretos(self):
        res = aoi.analizar_texto(TEXTO_CALIENTE_9, esperados=9)
        url_con_secreto = (
            "https://sports.caliente.mx/es_MX/Apuestas-Futbol-Mexico"
            "?apikey=SUPERSECRETO123&token=BEARER_XYZ"
        )
        reporte = aoi.render_report(res, url=url_con_secreto)
        self.assertIn("sports.caliente.mx", reporte)
        self.assertNotIn("SUPERSECRETO123", reporte)
        self.assertNotIn("BEARER_XYZ", reporte)
        self.assertNotIn("apikey", reporte)
        for marcador in ("API_KEY", "password", "Bearer ", "Authorization"):
            self.assertNotIn(marcador, reporte)

    def test_reporte_no_matches(self):
        res = aoi.analizar_texto("sin nada util y sin momios")
        reporte = aoi.render_report(res)
        self.assertIn("NO_MATCHES_FOUND", reporte)
        self.assertIn("ESPERAR / NO ENVIAR", reporte)


# ===========================================================================
# Tests de JSON export
# ===========================================================================
class TestExportJSON(unittest.TestCase):
    def test_payload_no_marca_pick_listo(self):
        res = aoi.analizar_texto(TEXTO_CALIENTE_9, esperados=9)
        payload = aoi.construir_payload_json(res)
        self.assertEqual(payload["decision"], "ESPERAR / NO ENVIAR")
        self.assertFalse(payload["pick_listo"])
        self.assertEqual(payload["total"], 9)
        self.assertEqual(payload["liga"], "Liga MX")
        for ev in payload["eventos"]:
            self.assertEqual(
                set(ev.keys()),
                {
                    "fecha", "hora", "equipo_local", "equipo_visitante",
                    "momio_local", "momio_empate", "momio_visitante",
                },
            )

    def test_json_serializable(self):
        import json
        res = aoi.analizar_texto(TEXTO_CALIENTE_9, esperados=9)
        data = json.loads(aoi.exportar_json(res))
        self.assertEqual(len(data["eventos"]), 9)

    def test_json_multiline(self):
        import json
        res = aoi.analizar_texto(TEXTO_MULTILINE_9, esperados=9)
        data = json.loads(aoi.exportar_json(res))
        self.assertEqual(len(data["eventos"]), 9)
        self.assertEqual(data["decision"], "ESPERAR / NO ENVIAR")
        self.assertFalse(data["pick_listo"])


# ===========================================================================
# Garantías de seguridad/cumplimiento sobre el código fuente
# ===========================================================================
class TestRestriccionesCodigoFuente(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src_modulo = (SRC_DIR / "assisted_odds_import.py").read_text(encoding="utf-8")
        cls.src_script = (
            BASE_DIR / "scripts" / "assisted_caliente_odds.py"
        ).read_text(encoding="utf-8")
        cls.fuentes = (cls.src_modulo, cls.src_script)

    def test_no_usa_stealth(self):
        for fuente in self.fuentes:
            self.assertNotIn("playwright_stealth", fuente)
            self.assertNotIn("stealth(", fuente)
            self.assertNotIn("stealth_async", fuente)
            self.assertNotIn("stealth_sync", fuente)

    def test_no_usa_proxy(self):
        for fuente in self.fuentes:
            self.assertNotIn("proxy=", fuente)

    def test_no_automatiza_login(self):
        for fuente in self.fuentes:
            self.assertNotIn(".fill(", fuente)
            self.assertNotIn("password", fuente)
            self.assertNotIn("credentials", fuente)
            self.assertNotIn(".set_credentials", fuente)

    def test_no_manda_telegram(self):
        for fuente in self.fuentes:
            self.assertNotIn("telegram_notifier", fuente)
            self.assertNotIn("import telegram", fuente)
            self.assertNotIn("sendMessage", fuente)
            self.assertNotIn("bot.send", fuente)

    def test_no_cambia_picks(self):
        for fuente in self.fuentes:
            self.assertNotIn("ajustar_pick_survivor", fuente)
            self.assertNotIn("registrar_voto", fuente)
            self.assertNotIn("CERRAR", fuente)

    def test_browser_visible(self):
        self.assertIn("headless=False", self.src_script)
        self.assertNotIn("headless=True", self.src_script)

    def test_decision_fija_en_modulo(self):
        self.assertEqual(aoi.DEC_ESPERAR, "ESPERAR / NO ENVIAR")


if __name__ == "__main__":
    unittest.main(verbosity=2)
