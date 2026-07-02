#!/usr/bin/env python3
"""Tests de calendario_contexto: cruce de partidos con eventos externos reales."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import calendario_contexto as cc  # noqa: E402


class TestEventosParaFecha(unittest.TestCase):
    def test_leagues_cup_aplica_a_todos(self):
        # Un partido en pleno Leagues Cup (agosto) afecta a cualquier equipo.
        evs = cc.eventos_para_fecha("2026-08-16", ["Necaxa", "Atlas"])
        nombres = [e["nombre"] for e in evs]
        self.assertIn("Leagues Cup", nombres)

    def test_campeon_de_campeones_solo_involucrados(self):
        # 25 jul: Toluca y Cruz Azul sí; otros no.
        evs_tol = cc.eventos_para_fecha("2026-07-24", ["Toluca", "Pumas UNAM"])
        self.assertIn("Campeón de Campeones", [e["nombre"] for e in evs_tol])
        evs_otros = cc.eventos_para_fecha("2026-07-24", ["Necaxa", "Atlas"])
        self.assertNotIn("Campeón de Campeones", [e["nombre"] for e in evs_otros])

    def test_fecha_fifa_noviembre(self):
        evs = cc.eventos_para_fecha("2026-11-16", ["Tigres UANL", "América"])
        self.assertTrue(any(e["tipo"] == "fecha_fifa" for e in evs))

    def test_fuera_de_ventana_no_devuelve(self):
        # Un partido en mayo no debe cruzar con ningún evento de 2026 Apertura.
        self.assertEqual(cc.eventos_para_fecha("2026-05-01", ["América", "Toluca"]), [])

    def test_fecha_invalida_no_rompe(self):
        self.assertEqual(cc.eventos_para_fecha("", ["América"]), [])
        self.assertEqual(cc.eventos_para_fecha(None, ["América"]), [])

    def test_alias_equipos(self):
        # "Chivas" debe reconocerse aunque el evento no la liste (Leagues Cup = todos).
        evs = cc.eventos_para_fecha("2026-08-05", ["Chivas", "Rayados"])
        self.assertIn("Leagues Cup", [e["nombre"] for e in evs])


class TestNotasYResumen(unittest.TestCase):
    def test_notas_para_partido_formato(self):
        notas = cc.notas_para_partido("Toluca", "Pumas UNAM", "2026-07-25")
        self.assertTrue(notas)
        self.assertTrue(any("Campeón de Campeones" in n for n in notas))

    def test_notas_vacias_sin_evento(self):
        self.assertEqual(cc.notas_para_partido("Necaxa", "Atlas", "2026-05-01"), [])

    def test_resumen_jornada_dedup(self):
        partidos = [
            {"local": "Necaxa", "visitante": "Atlas", "fecha": "2026-08-16"},
            {"local": "León", "visitante": "Puebla", "fecha": "2026-08-16"},
        ]
        res = cc.resumen_jornada(partidos)
        # Leagues Cup aplica a ambos pero no debe duplicarse.
        leagues = [r for r in res if "Leagues Cup" in r]
        self.assertEqual(len(leagues), 1)


if __name__ == "__main__":
    unittest.main()
