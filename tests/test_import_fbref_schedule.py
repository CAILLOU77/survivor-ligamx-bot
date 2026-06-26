#!/usr/bin/env python3
"""
Tests para scripts/import_fbref_schedule.py.

No usan el HTML real descargado: emplean un fixture HTML mínimo embebido.
Ejecutar:
    python3 -m unittest tests.test_import_fbref_schedule
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# Hacemos importable scripts/.
BASE_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = BASE_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import import_fbref_schedule as fb  # noqa: E402


# Fixture mínimo con los data-stat que usa FBref en "Scores & Fixtures".
HTML_OK = """
<html><body>
<table id="sched">
<thead><tr>
  <th data-stat="gameweek">Wk</th>
  <th data-stat="date">Date</th>
  <th data-stat="start_time">Time</th>
  <th data-stat="home_team">Home</th>
  <th data-stat="away_team">Away</th>
  <th data-stat="venue">Venue</th>
</tr></thead>
<tbody>
  <tr>
    <th data-stat="gameweek">1</th>
    <td data-stat="date">2026-07-04</td>
    <td data-stat="start_time">19:00</td>
    <td data-stat="home_team"><a href="/x">Club America</a></td>
    <td data-stat="away_team"><a href="/y">FC Juárez</a></td>
    <td data-stat="venue">Estadio Azteca</td>
  </tr>
  <tr>
    <th data-stat="gameweek">1</th>
    <td data-stat="date">2026-07-05</td>
    <td data-stat="start_time">17:00</td>
    <td data-stat="home_team">Querétaro</td>
    <td data-stat="away_team">UANL</td>
    <td data-stat="venue">Estadio La Corregidora</td>
  </tr>
  <tr>
    <th data-stat="gameweek">2</th>
    <td data-stat="date">2026-07-11</td>
    <td data-stat="start_time">19:00</td>
    <td data-stat="home_team">Toluca</td>
    <td data-stat="away_team">UNAM</td>
    <td data-stat="venue">Estadio Nemesio Díez</td>
  </tr>
</tbody>
</table>
</body></html>
"""

# Fixture sin columnas home_team/away_team/venue.
HTML_SIN_COLUMNAS = """
<table><thead><tr>
  <th data-stat="gameweek">Wk</th>
  <th data-stat="date">Date</th>
  <th data-stat="start_time">Time</th>
</tr></thead>
<tbody><tr>
  <th data-stat="gameweek">1</th>
  <td data-stat="date">2026-07-04</td>
  <td data-stat="start_time">19:00</td>
</tr></tbody></table>
"""


class TestExtraccionTabla(unittest.TestCase):
    def test_extrae_filas_partido(self):
        raw, datastats = fb.parse_schedule_html(HTML_OK)
        filas = fb.construir_filas(raw)
        # 3 filas de partido (la fila de encabezado se ignora).
        self.assertEqual(len(filas), 3)
        primera = filas[0]
        self.assertEqual(primera["date"], "2026-07-04")
        self.assertEqual(primera["time"], "19:00")
        self.assertEqual(primera["venue"], "Estadio Azteca")
        self.assertIn("home_team", datastats)
        self.assertIn("venue", datastats)


class TestNormalizacionNombres(unittest.TestCase):
    def test_display_requeridos(self):
        self.assertEqual(fb.normalizar_nombre_equipo("UANL"), "Tigres UANL")
        self.assertEqual(fb.normalizar_nombre_equipo("UNAM"), "Pumas UNAM")
        self.assertEqual(fb.normalizar_nombre_equipo("Santos Laguna"), "Santos")
        self.assertEqual(fb.normalizar_nombre_equipo("FC Juárez"), "FC Juarez")
        self.assertEqual(fb.normalizar_nombre_equipo("Atlético San Luis"), "Atlético de San Luis")
        self.assertEqual(fb.normalizar_nombre_equipo("Club America"), "América")
        self.assertEqual(fb.normalizar_nombre_equipo("America"), "América")

    def test_claves_equivalentes(self):
        self.assertEqual(fb.canonical_key("America"), fb.canonical_key("Club America"))
        self.assertEqual(fb.canonical_key("América"), fb.canonical_key("America"))
        self.assertEqual(fb.canonical_key("FC Juárez"), fb.canonical_key("FC Juarez"))
        self.assertEqual(fb.canonical_key("Santos Laguna"), fb.canonical_key("Santos"))
        self.assertEqual(fb.canonical_key("Atlético San Luis"), fb.canonical_key("Atlético de San Luis"))
        self.assertEqual(fb.canonical_key("UANL"), fb.canonical_key("Tigres"))
        self.assertEqual(fb.canonical_key("UNAM"), fb.canonical_key("Pumas"))


class TestFiltroJornada(unittest.TestCase):
    def test_filtra_jornada_1(self):
        raw, _ = fb.parse_schedule_html(HTML_OK)
        filas = fb.construir_filas(raw)
        j1 = fb.filtrar_jornada(filas, 1)
        self.assertEqual(len(j1), 2)
        self.assertTrue(all(f["wk"] == "1" for f in j1))


class TestComparacion(unittest.TestCase):
    def _filas_j1(self):
        raw, _ = fb.parse_schedule_html(HTML_OK)
        return fb.filtrar_jornada(fb.construir_filas(raw), 1)

    def test_matched_completo(self):
        partidos = [
            {"home_team": "América", "away_team": "FC Juarez", "fecha": "2026-07-04", "hora": "19:00",
             "estadio": "Estadio Azteca"},
            {"home_team": "Querétaro", "away_team": "Tigres", "fecha": "2026-07-05", "hora": "17:00",
             "estadio": "Estadio Corregidora"},
        ]
        res = fb.comparar(self._filas_j1(), partidos)
        self.assertEqual(len(res["matched"]), 2)
        self.assertEqual(len(res["missing"]), 0)
        self.assertEqual(len(res["con_diferencias"]), 0)

    def test_diferencia_de_hora_detectada(self):
        partidos = [
            {"home_team": "América", "away_team": "FC Juarez", "fecha": "2026-07-04", "hora": "20:00",
             "estadio": "Estadio Azteca"},
            {"home_team": "Querétaro", "away_team": "Tigres", "fecha": "2026-07-05", "hora": "17:00",
             "estadio": "Estadio La Corregidora"},
        ]
        res = fb.comparar(self._filas_j1(), partidos)
        self.assertEqual(len(res["con_diferencias"]), 1)
        diffs = res["con_diferencias"][0]["diffs"]
        campos = [d["campo"] for d in diffs]
        self.assertIn("HORA", campos)

    def test_diferencia_menor_estadio_ignorada(self):
        # "Estadio La Corregidora" (jornadas) vs "Estadio La Corregidora" (FBref) -> sin diff;
        # probamos artículo/acento: jornadas usa "Estadio Corregidora".
        partidos = [
            {"home_team": "Querétaro", "away_team": "Tigres", "fecha": "2026-07-05", "hora": "17:00",
             "estadio": "Estadio Corregidora"},
        ]
        res = fb.comparar(self._filas_j1(), partidos)
        # El único matched no debe tener diferencia de estadio.
        match_qro = [m for m in res["matched"] if m["partido"]["home_team"] == "Querétaro"]
        self.assertEqual(len(match_qro), 1)
        campos = [d["campo"] for d in match_qro[0]["diffs"]]
        self.assertNotIn("ESTADIO", campos)

    def test_estadio_realmente_distinto_si_reporta(self):
        partidos = [
            {"home_team": "América", "away_team": "FC Juarez", "fecha": "2026-07-04", "hora": "19:00",
             "estadio": "Estadio Akron"},
        ]
        res = fb.comparar(self._filas_j1(), partidos)
        match_ame = [m for m in res["matched"] if m["partido"]["home_team"] == "América"]
        self.assertEqual(len(match_ame), 1)
        campos = [d["campo"] for d in match_ame[0]["diffs"]]
        self.assertIn("ESTADIO", campos)


class TestEstadioTokens(unittest.TestCase):
    def test_articulos_y_acentos_no_cuentan(self):
        self.assertFalse(fb.estadio_parece_distinto("Estadio La Corregidora", "Estadio Corregidora"))
        self.assertFalse(
            fb.estadio_parece_distinto("Estadio Olímpico de Universitario", "Estadio Olímpico Universitario")
        )

    def test_nombre_diferente_si_cuenta(self):
        self.assertTrue(fb.estadio_parece_distinto("Estadio Azteca", "Estadio Akron"))


class TestErrores(unittest.TestCase):
    def test_html_faltante(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = str(Path(tmp) / "no_existe.html")
            with self.assertRaises(fb.FBrefImportError) as ctx:
                fb.cargar_html(ruta)
            mensaje = str(ctx.exception)
            self.assertIn("HTML Only", mensaje)
            self.assertIn(ruta, mensaje)

    def test_columnas_faltantes(self):
        _, datastats = fb.parse_schedule_html(HTML_SIN_COLUMNAS)
        with self.assertRaises(fb.FBrefImportError) as ctx:
            fb.validar_columnas(datastats)
        self.assertIn("Faltan columnas", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
