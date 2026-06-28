#!/usr/bin/env python3
"""Tests para src/tabla_posiciones.py (tabla ESPN + motivación). Sin red."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import tabla_posiciones as tp  # noqa: E402


def _entry(equipo, rank, points, gp, w=0, t=0, l=0, gf=0, ga=0, diff=0):
    return {
        "team": {"displayName": equipo},
        "stats": [
            {"name": "rank", "value": rank},
            {"name": "points", "value": points},
            {"name": "gamesPlayed", "value": gp},
            {"name": "wins", "value": w},
            {"name": "ties", "value": t},
            {"name": "losses", "value": l},
            {"name": "pointsFor", "value": gf},
            {"name": "pointsAgainst", "value": ga},
            {"name": "pointDifferential", "value": diff},
        ],
    }


def _payload(entries, torneo="2026 Torneo Apertura"):
    return {"children": [{"name": torneo, "standings": {"entries": entries}}]}


def _tabla_avanzada():
    # Jornada 15 (faltan 2): líder 40 pts, decreciente de 2 en 2.
    entries = [_entry(f"Equipo{i+1}", i + 1, max(40 - 2 * i, 3), 15) for i in range(18)]
    return _payload(entries)


class TestParseo(unittest.TestCase):
    def test_parsea_torneo_y_tabla(self):
        d = tp.parsear_standings(_payload([_entry("América", 1, 30, 15)]))
        self.assertEqual(d["torneo"], "2026 Torneo Apertura")
        self.assertEqual(len(d["tabla"]), 1)
        self.assertEqual(d["tabla"][0]["equipo"], "América")
        self.assertEqual(d["tabla"][0]["puntos"], 30)
        self.assertEqual(d["tabla"][0]["jugados"], 15)

    def test_payload_vacio_no_rompe(self):
        self.assertEqual(tp.parsear_standings({}), {"torneo": "", "tabla": []})

    def test_ordena_por_posicion(self):
        d = tp.parsear_standings(_payload([_entry("B", 2, 10, 5), _entry("A", 1, 12, 5)]))
        self.assertEqual([f["posicion"] for f in d["tabla"]], [1, 2])


class TestMotivacion(unittest.TestCase):
    def test_temporada_no_iniciada_es_na(self):
        d = tp.parsear_standings(_payload([_entry("A", 1, 0, 0)]))
        anot = tp.tabla_con_motivacion(d)["tabla"][0]
        self.assertEqual(anot["motivacion_nivel"], "n/a")
        self.assertEqual(anot["jornadas_restantes"], tp.JORNADAS_FASE_REGULAR)

    def test_lider_asegurado_es_media(self):
        anot = tp.tabla_con_motivacion(tp.parsear_standings(_tabla_avanzada()))["tabla"]
        self.assertEqual(anot[0]["motivacion_nivel"], "media")
        self.assertTrue(anot[0]["liguilla_asegurada"])

    def test_zona_corte_pelea_alta(self):
        anot = tp.tabla_con_motivacion(tp.parsear_standings(_tabla_avanzada()))["tabla"]
        # Equipo8/9/10 están vivos pero no asegurados -> alta.
        self.assertEqual(anot[7]["motivacion_nivel"], "alta")
        self.assertTrue(anot[7]["vivo_para_liguilla"])
        self.assertFalse(anot[7]["liguilla_asegurada"])

    def test_fondo_eliminado_es_baja(self):
        anot = tp.tabla_con_motivacion(tp.parsear_standings(_tabla_avanzada()))["tabla"]
        ultimo = anot[-1]
        self.assertEqual(ultimo["motivacion_nivel"], "baja")
        self.assertFalse(ultimo["vivo_para_liguilla"])

    def test_zonas_directo_playin_fuera(self):
        anot = tp.tabla_con_motivacion(tp.parsear_standings(_tabla_avanzada()))["tabla"]
        self.assertEqual(anot[0]["zona"], "directo")   # pos 1
        self.assertEqual(anot[6]["zona"], "play_in")   # pos 7
        self.assertEqual(anot[10]["zona"], "fuera")    # pos 11

    def test_motivacion_de_por_nombre(self):
        d = tp.parsear_standings(_tabla_avanzada())
        info = tp.motivacion_de(d, "equipo1")  # normalización ignora may/acentos
        self.assertIsNotNone(info)
        self.assertEqual(info["zona"], "directo")
        self.assertIsNone(tp.motivacion_de(d, "Inexistente FC"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
