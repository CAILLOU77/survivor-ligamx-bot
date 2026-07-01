#!/usr/bin/env python3
"""Tests para src/motor_pronosticos.py (cerebro de pronósticos). Sin red."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import motor_pronosticos as mp  # noqa: E402


def _historico():
    return [
        {"home_team": "América", "away_team": "Toluca", "home_goals": 3, "away_goals": 0},
        {"home_team": "América", "away_team": "Atlas", "home_goals": 2, "away_goals": 1},
        {"home_team": "Toluca", "away_team": "Atlas", "home_goals": 1, "away_goals": 1},
        {"home_team": "Toluca", "away_team": "América", "home_goals": 0, "away_goals": 2},
        {"home_team": "Atlas", "away_team": "América", "home_goals": 0, "away_goals": 3},
        {"home_team": "Atlas", "away_team": "Toluca", "home_goals": 1, "away_goals": 1},
    ]


class TestGenerar(unittest.TestCase):
    def test_genera_pronosticos(self):
        fixtures = [{"home_team": "América", "away_team": "Toluca", "fecha": "2026-07-18"}]
        res = mp.generar_pronosticos(fixtures=fixtures, resultados=_historico())
        self.assertEqual(res["total_pronosticos"], 1)
        p = res["pronosticos"][0]
        self.assertIn("pick_1x2", p)
        self.assertIn("no_perder_local_pct", p)
        self.assertEqual(res["decision"], "INFORMATIVO / REVISIÓN HUMANA")

    def test_equipo_desconocido_se_omite(self):
        fixtures = [{"home_team": "Equipo Inventado", "away_team": "Otro Raro", "fecha": "x"}]
        res = mp.generar_pronosticos(fixtures=fixtures, resultados=_historico())
        self.assertEqual(res["total_pronosticos"], 0)

    def test_sin_resultados_no_revienta(self):
        res = mp.generar_pronosticos(fixtures=[{"home_team": "A", "away_team": "B"}], resultados=[])
        self.assertEqual(res["total_pronosticos"], 0)

    def test_no_perder_es_suma_coherente(self):
        fixtures = [{"home_team": "América", "away_team": "Toluca", "fecha": "x"}]
        p = mp.generar_pronosticos(fixtures=fixtures, resultados=_historico())["pronosticos"][0]
        self.assertAlmostEqual(
            p["no_perder_local_pct"], round(p["prob_local_pct"] + p["prob_empate_pct"], 2), places=1
        )

    def test_incluye_explicaciones(self):
        fixtures = [{"home_team": "América", "away_team": "Toluca", "fecha": "x"}]
        p = mp.generar_pronosticos(fixtures=fixtures, resultados=_historico())["pronosticos"][0]
        self.assertIn("explicacion_1x2", p)
        self.assertIn("explicacion_ou", p)
        self.assertTrue(p["explicacion_1x2"])
        # La explicación menciona al equipo o el escenario (parejo/empate).
        self.assertTrue(any(w in p["explicacion_1x2"] for w in ("América", "Toluca", "parejo", "EMPATE")))
        self.assertIn("goles_esperados_local", p)

    def test_incluye_nivel_confianza(self):
        fixtures = [{"home_team": "América", "away_team": "Toluca", "fecha": "x"}]
        p = mp.generar_pronosticos(fixtures=fixtures, resultados=_historico())["pronosticos"][0]
        self.assertIn(p["nivel_confianza"], ("ALTA", "MEDIA", "BAJA"))
        self.assertIn("prob_pick_pct", p)

    def test_umbrales_nivel_confianza(self):
        self.assertEqual(mp._nivel_confianza_1x2(60.0), "ALTA")
        self.assertEqual(mp._nivel_confianza_1x2(45.0), "MEDIA")
        self.assertEqual(mp._nivel_confianza_1x2(30.0), "BAJA")


class TestSurvivor(unittest.TestCase):
    def _pronos(self):
        return [
            {"local": "América", "visitante": "Toluca", "no_perder_local_pct": 85.0,
             "no_perder_visitante_pct": 40.0},
            {"local": "Atlas", "visitante": "Pumas", "no_perder_local_pct": 55.0,
             "no_perder_visitante_pct": 60.0},
        ]

    def test_elige_mayor_no_perder(self):
        pick = mp.mejor_pick_survivor(self._pronos())
        self.assertEqual(pick["equipo"], "América")
        self.assertEqual(pick["no_perder_pct"], 85.0)

    def test_excluye_usados(self):
        pick = mp.mejor_pick_survivor(self._pronos(), equipos_usados=["América"])
        # Excluido América -> el siguiente mejor es Pumas (60) como visitante.
        self.assertEqual(pick["equipo"], "Pumas")

    def test_sin_candidatos(self):
        self.assertIsNone(mp.mejor_pick_survivor([]))

    def test_motivacion_es_desempate(self):
        # Dos candidatos con MISMO no_perder; gana el que enfrenta al rival
        # con menor motivación (rival 'baja' = más seguro).
        pronos = [
            {"local": "América", "visitante": "Eliminado", "no_perder_local_pct": 70.0,
             "no_perder_visitante_pct": 30.0},
            {"local": "Pumas", "visitante": "Puntero", "no_perder_local_pct": 70.0,
             "no_perder_visitante_pct": 30.0},
        ]
        motivacion = {
            "eliminado": {"motivacion_nivel": "baja"},
            "puntero": {"motivacion_nivel": "alta"},
        }
        pick = mp.mejor_pick_survivor(pronos, motivacion=motivacion)
        self.assertEqual(pick["equipo"], "América")  # rival 'baja' desempata
        self.assertEqual(pick["rival_motivacion"], "baja")

    def test_motivacion_no_altera_orden_principal(self):
        # El no_perder manda: aunque el rival del mejor esté motivado, gana por prob.
        pronos = [
            {"local": "América", "visitante": "X", "no_perder_local_pct": 85.0,
             "no_perder_visitante_pct": 30.0},
            {"local": "Pumas", "visitante": "Y", "no_perder_local_pct": 60.0,
             "no_perder_visitante_pct": 30.0},
        ]
        motivacion = {"x": {"motivacion_nivel": "alta"}, "y": {"motivacion_nivel": "baja"}}
        pick = mp.mejor_pick_survivor(pronos, motivacion=motivacion)
        self.assertEqual(pick["equipo"], "América")  # 85 > 60 pese a la motivación

    def test_mejores_picks_top_n_ordenados(self):
        pronos = [
            {"local": "América", "visitante": "Toluca", "no_perder_local_pct": 80.0,
             "no_perder_visitante_pct": 45.0},
            {"local": "Pumas", "visitante": "Atlas", "no_perder_local_pct": 70.0,
             "no_perder_visitante_pct": 35.0},
        ]
        top = mp.mejores_picks_survivor(pronos, n=3)
        self.assertEqual([c["equipo"] for c in top], ["América", "Pumas", "Toluca"])
        self.assertEqual(top[0]["no_perder_pct"], 80.0)
        # mejor_pick_survivor es el #1 de la lista
        self.assertEqual(mp.mejor_pick_survivor(pronos)["equipo"], top[0]["equipo"])

    def test_campos_de_riesgo_presentes(self):
        # Con pronósticos completos, cada candidato trae victoria/empate/nivel.
        pronos = [{
            "local": "América", "visitante": "Toluca",
            "prob_local_pct": 70.0, "prob_empate_pct": 20.0, "prob_visitante_pct": 10.0,
            "no_perder_local_pct": 90.0, "no_perder_visitante_pct": 30.0,
        }]
        pick = mp.mejor_pick_survivor(pronos)
        self.assertEqual(pick["equipo"], "América")
        self.assertEqual(pick["prob_victoria_pct"], 70.0)
        self.assertEqual(pick["prob_empate_pct"], 20.0)
        self.assertEqual(pick["nivel"], "ALTA")  # no_perder 90 y victoria 70

    def test_victoria_desempata_mismo_no_perder(self):
        # Mismo no_perder; gana el de MAYOR prob. de victoria (más puntos).
        pronos = [
            {"local": "A", "visitante": "B", "prob_local_pct": 50.0, "prob_empate_pct": 35.0,
             "prob_visitante_pct": 15.0, "no_perder_local_pct": 85.0, "no_perder_visitante_pct": 50.0},
            {"local": "C", "visitante": "D", "prob_local_pct": 70.0, "prob_empate_pct": 15.0,
             "prob_visitante_pct": 15.0, "no_perder_local_pct": 85.0, "no_perder_visitante_pct": 30.0},
        ]
        pick = mp.mejor_pick_survivor(pronos)
        self.assertEqual(pick["equipo"], "C")  # 70% victoria > 50%, mismo no-perder 85

    def test_nivel_riesgosa(self):
        self.assertEqual(mp._nivel_pick(55.0, 40.0), "RIESGOSA")
        self.assertEqual(mp._nivel_pick(68.0, 40.0), "MEDIA")
        self.assertEqual(mp._nivel_pick(80.0, 60.0), "ALTA")
        self.assertEqual(mp._nivel_pick(80.0, None), "ALTA")  # sin info de victoria


class TestEstrategia(unittest.TestCase):
    def _pronos(self):
        # Local fuerte (no-perder 82) vs Visitante fuerte (no-perder 84).
        return [
            {"local": "Casa", "visitante": "Rival1", "prob_local_pct": 62.0,
             "prob_empate_pct": 20.0, "prob_visitante_pct": 18.0,
             "no_perder_local_pct": 82.0, "no_perder_visitante_pct": 40.0},
            {"local": "Rival2", "visitante": "Visita", "prob_local_pct": 16.0,
             "prob_empate_pct": 18.0, "prob_visitante_pct": 66.0,
             "no_perder_local_pct": 34.0, "no_perder_visitante_pct": 84.0},
        ]

    def test_cautela_por_pocos_datos(self):
        r = mp.mejores_picks_estrategico(self._pronos(), partidos_jugados_torneo=0)
        self.assertTrue(r["cautela"])
        self.assertIsNotNone(r["advertencia"])

    def test_sin_dato_es_cauteloso(self):
        r = mp.mejores_picks_estrategico(self._pronos(), partidos_jugados_torneo=None)
        self.assertTrue(r["cautela"])

    def test_temporada_avanzada_sin_cautela(self):
        r = mp.mejores_picks_estrategico(self._pronos(), partidos_jugados_torneo=100)
        self.assertFalse(r["cautela"])
        self.assertIsNone(r["advertencia"])

    def test_local_preferido_sobre_visitante_en_arranque(self):
        # En cautela, el LOCAL (82) debe ganarle al VISITANTE (84) por la penalización.
        r = mp.mejores_picks_estrategico(self._pronos(), partidos_jugados_torneo=0, n=1)
        self.assertEqual(r["picks"][0]["equipo"], "Casa")
        self.assertEqual(r["picks"][0]["condicion"], "Local")

    def test_favorito_visitante_no_es_alta(self):
        # Un favorito visitante fuerte no puede etiquetarse 'ALTA' (riesgo sorpresa).
        r = mp.mejores_picks_estrategico(self._pronos(), partidos_jugados_torneo=100)
        visita = next(p for p in r["picks"] if p["equipo"] == "Visita")
        self.assertNotEqual(visita["nivel"], "ALTA")

    def test_incluye_razon(self):
        r = mp.mejores_picks_estrategico(self._pronos(), partidos_jugados_torneo=0, n=2)
        self.assertTrue(all(p.get("razon") for p in r["picks"]))

    def test_razon_incluye_numeros(self):
        r = mp.mejores_picks_estrategico(self._pronos(), partidos_jugados_torneo=100, n=1)
        razon = r["picks"][0]["razon"]
        self.assertIn("no perder", razon)
        self.assertIn("%", razon)


if __name__ == "__main__":
    unittest.main(verbosity=2)
