#!/usr/bin/env python3
"""Tests de matchup_h2h: señal de 'bestia negra' por H2H (datos reales)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import matchup_h2h as h2h  # noqa: E402


def _res(home, away, hg, ag):
    return {"home_team": home, "away_team": away, "home_goals": hg, "away_goals": ag}


# Pachuca le complica a América: en 5 duelos América gana 2, empata 2, pierde 1.
_HIST = [
    _res("Pachuca", "América", 0, 0),
    _res("América", "Pachuca", 2, 0),
    _res("Pachuca", "América", 0, 0),
    _res("América", "Pachuca", 2, 0),
    _res("Pachuca", "América", 1, 0),
    # ruido: otros partidos
    _res("Toluca", "Atlas", 3, 1),
    _res("Cruz Azul", "Querétaro", 2, 0),
]


class TestResumenH2H(unittest.TestCase):
    def test_cuenta_correcta(self):
        r = h2h.resumen_h2h(_HIST, "América", "Pachuca")
        self.assertEqual(r["jugados"], 5)
        self.assertEqual(r["a_gana"], 2)
        self.assertEqual(r["empates"], 2)
        self.assertEqual(r["b_gana"], 1)

    def test_simetria_perspectiva(self):
        r = h2h.resumen_h2h(_HIST, "Pachuca", "América")
        self.assertEqual(r["a_gana"], 1)  # Pachuca ganó 1
        self.assertEqual(r["b_gana"], 2)  # América ganó 2

    def test_alias_equipos(self):
        # "Club América" debe emparejar con "América".
        r = h2h.resumen_h2h(_HIST, "Club América", "Pachuca")
        self.assertEqual(r["jugados"], 5)


class TestAlertaH2H(unittest.TestCase):
    def test_favorito_no_domina_dispara(self):
        # América favorito pero solo gana 2/5 vs Pachuca -> alerta.
        nota = h2h.alerta_h2h(_HIST, "América", "Pachuca")
        self.assertIsNotNone(nota)
        self.assertIn("le sabe jugar", nota)

    def test_muestra_insuficiente_no_dispara(self):
        pocos = [_res("A", "B", 1, 0), _res("B", "A", 0, 1)]
        self.assertIsNone(h2h.alerta_h2h(pocos, "A", "B", min_juegos=3))

    def test_favorito_domina_no_dispara(self):
        dom = [_res("Tigres UANL", "Guadalajara", 3, 1),
               _res("Guadalajara", "Tigres UANL", 0, 2),
               _res("Tigres UANL", "Guadalajara", 4, 1)]
        self.assertIsNone(h2h.alerta_h2h(dom, "Tigres UANL", "Guadalajara"))


class TestAnotar(unittest.TestCase):
    def test_anota_solo_favorito_con_mal_h2h(self):
        pron = [{"local": "América", "visitante": "Pachuca", "pick_1x2": "Gana Local"}]
        out = h2h.anotar_h2h(pron, _HIST)
        self.assertIn("h2h_nota", out[0])

    def test_empate_no_anota(self):
        pron = [{"local": "América", "visitante": "Pachuca", "pick_1x2": "Empate"}]
        out = h2h.anotar_h2h(pron, _HIST)
        self.assertNotIn("h2h_nota", out[0])


if __name__ == "__main__":
    unittest.main()
