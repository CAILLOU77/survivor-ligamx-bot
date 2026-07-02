#!/usr/bin/env python3
"""Tests de seguimiento_jornada: lista priorizada por hora + veredicto por XI."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import seguimiento_jornada as seg  # noqa: E402


def _picks():
    return [
        {"equipo": "Cruz Azul", "rival": "Querétaro", "condicion": "Local",
         "no_perder_pct": 88.0, "prob_victoria_pct": 64.0, "nivel": "ALTA"},
        {"equipo": "América", "rival": "Pachuca", "condicion": "Local",
         "no_perder_pct": 78.0, "prob_victoria_pct": 52.0, "nivel": "MEDIA"},
    ]


class TestFmtCuando(unittest.TestCase):
    def test_formatea_dia_hora(self):
        # 2026-07-18 es sábado
        self.assertEqual(seg.fmt_cuando("2026-07-18T19:00:00"), "sáb 19:00")

    def test_invalido_vacio(self):
        self.assertEqual(seg.fmt_cuando(""), "")
        self.assertEqual(seg.fmt_cuando(None), "")


class TestVeredicto(unittest.TestCase):
    def test_pendiente_sin_xi(self):
        self.assertEqual(seg.veredicto_xi(None)["estado"], "PENDIENTE")

    def test_confirma_xi_completo(self):
        self.assertEqual(seg.veredicto_xi(90.0)["estado"], "CONFIRMA")

    def test_descarta_xi_mermado(self):
        self.assertEqual(seg.veredicto_xi(60.0)["estado"], "DESCARTA")

    def test_duda_intermedio(self):
        self.assertEqual(seg.veredicto_xi(78.0)["estado"], "DUDA")


class TestListaSeguimiento(unittest.TestCase):
    def test_ordena_por_hora(self):
        horarios = {
            seg.canonical_team_key("Cruz Azul"): "2026-07-19T19:00:00",  # domingo
            seg.canonical_team_key("América"): "2026-07-17T21:00:00",    # viernes
        }
        items = seg.lista_seguimiento(_picks(), horarios=horarios)
        # América (viernes) debe ir primero aunque sea el 2º del ranking
        self.assertEqual(items[0]["equipo"], "América")
        self.assertEqual(items[1]["equipo"], "Cruz Azul")

    def test_veredicto_por_fuerza_xi(self):
        fuerza = {seg.canonical_team_key("Cruz Azul"): 92.0}
        items = seg.lista_seguimiento(_picks(), fuerza_xi=fuerza, n=2)
        caz = next(i for i in items if i["equipo"] == "Cruz Azul")
        self.assertEqual(caz["veredicto"]["estado"], "CONFIRMA")
        ame = next(i for i in items if i["equipo"] == "América")
        self.assertEqual(ame["veredicto"]["estado"], "PENDIENTE")  # sin XI

    def test_respeta_n(self):
        self.assertEqual(len(seg.lista_seguimiento(_picks(), n=1)), 1)


if __name__ == "__main__":
    unittest.main()
