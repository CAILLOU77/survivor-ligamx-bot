#!/usr/bin/env python3
"""Tests para src/ligamx_api.py (cliente Liga MX API). Sin red: requests mockeado."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import ligamx_api as api  # noqa: E402


def _resp(status=200, payload=None):
    r = mock.Mock()
    r.status_code = status
    r.json.return_value = payload if payload is not None else {}
    return r


_CALENDAR = {
    "season": "vigente",
    "total_matches": 4,
    "jornadas": [
        {
            "jornada": 2,
            "matches": [
                {"id": 1, "date": "2026-07-24T01:00:00", "status": "scheduled",
                 "home_team": {"id": 1, "name": "Club América"},
                 "away_team": {"id": 2, "name": "Chivas Guadalajara"},
                 "venue": "Estadio Azteca"},
            ],
        },
        {
            "jornada": 1,
            "matches": [
                {"id": 2, "date": "2026-07-17T01:00:00", "status": "scheduled",
                 "home_team": {"id": 3, "name": "Necaxa"},
                 "away_team": {"id": 4, "name": "Atlante"},
                 "venue": "Estadio Victoria"},
                # partido incompleto (sin visitante) -> se descarta:
                {"id": 3, "date": "2026-07-17T03:00:00", "status": "scheduled",
                 "home_team": {"id": 5, "name": "Tijuana"},
                 "away_team": {}, "venue": "Estadio Caliente"},
            ],
        },
    ],
}


class TestGet(unittest.TestCase):
    def test_get_ok(self):
        with mock.patch.object(api.requests, "get", return_value=_resp(200, {"a": 1})) as g:
            self.assertEqual(api._get("/season"), {"a": 1})
            g.assert_called_once()

    def test_get_http_error(self):
        with mock.patch.object(api.requests, "get", return_value=_resp(503)):
            with self.assertRaises(RuntimeError):
                api._get("/season")

    def test_get_network_error(self):
        with mock.patch.object(api.requests, "get",
                               side_effect=api.requests.RequestException("boom")):
            with self.assertRaises(RuntimeError):
                api._get("/season")


class TestBaseUrl(unittest.TestCase):
    def test_default(self):
        import os
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LIGAMX_API_URL", None)
            self.assertEqual(api.base_url(), api.DEFAULT_BASE_URL)

    def test_env_override_strips_trailing_slash(self):
        import os
        with mock.patch.dict(os.environ, {"LIGAMX_API_URL": "https://x.test/"}):
            self.assertEqual(api.base_url(), "https://x.test")


class TestUsarComoFuente(unittest.TestCase):
    def test_off_por_defecto(self):
        import os
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LIGAMX_API_AS_SOURCE", None)
            self.assertFalse(api.usar_como_fuente())

    def test_on_con_1(self):
        import os
        with mock.patch.dict(os.environ, {"LIGAMX_API_AS_SOURCE": "1"}):
            self.assertTrue(api.usar_como_fuente())


class TestDisponible(unittest.TestCase):
    def test_true(self):
        with mock.patch.object(api.requests, "get", return_value=_resp(200, {})):
            self.assertTrue(api.disponible())

    def test_false_on_error(self):
        with mock.patch.object(api.requests, "get", side_effect=Exception("down")):
            self.assertFalse(api.disponible())


class TestCalendarioPlanificador(unittest.TestCase):
    def test_mapeo_y_orden(self):
        with mock.patch.object(api.requests, "get", return_value=_resp(200, _CALENDAR)):
            cal = api.calendario_para_planificador()
        self.assertEqual([j["jornada"] for j in cal], [1, 2])
        self.assertEqual(len(cal[0]["partidos"]), 1)  # descarta el incompleto
        self.assertEqual(cal[0]["partidos"][0]["home_team"], "Necaxa")
        self.assertEqual(cal[0]["partidos"][0]["away_team"], "Atlante")
        self.assertIn("home_team", cal[0]["partidos"][0])
        self.assertIn("away_team", cal[0]["partidos"][0])

    def test_nombres_normalizados(self):
        with mock.patch.object(api.requests, "get", return_value=_resp(200, _CALENDAR)):
            cal = api.calendario_para_planificador()
        self.assertEqual(cal[1]["partidos"][0]["home_team"], "América")

    def test_calendario_vacio(self):
        with mock.patch.object(api.requests, "get", return_value=_resp(200, {"jornadas": []})):
            self.assertEqual(api.calendario_para_planificador(), [])


class TestFixturesPlanos(unittest.TestCase):
    def test_lista_plana_con_fecha(self):
        with mock.patch.object(api.requests, "get", return_value=_resp(200, _CALENDAR)):
            fx = api.fixtures_planos()
        # 2 partidos completos (descarta el de Tijuana sin visitante).
        self.assertEqual(len(fx), 2)
        for f in fx:
            self.assertIn("fecha", f)
            self.assertIn("home_team", f)
            self.assertIn("away_team", f)
        # Nombres normalizados.
        nombres = {f["home_team"] for f in fx}
        self.assertIn("América", nombres)


class TestResultadosHistoricos(unittest.TestCase):
    def test_mapea_finalizados(self):
        finished = [
            {"home_team": {"name": "Club América"}, "away_team": {"name": "Necaxa"},
             "home_score": 2, "away_score": 1, "match_date": "2026-08-01T01:00:00"},
            # sin marcador -> se descarta:
            {"home_team": {"name": "Toluca"}, "away_team": {"name": "Atlas"},
             "home_score": None, "away_score": None, "match_date": "2026-08-02T01:00:00"},
        ]
        # Primera página devuelve la lista; segunda vacía para cortar el loop.
        with mock.patch.object(api, "obtener_partidos", side_effect=[finished, []]):
            res = api.resultados_historicos()
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["home_team"], "América")
        self.assertEqual(res[0]["home_goals"], 2)
        self.assertEqual(res[0]["away_goals"], 1)
        self.assertEqual(res[0]["fecha"], "2026-08-01")

    def test_pretemporada_vacio(self):
        with mock.patch.object(api, "obtener_partidos", return_value=[]):
            self.assertEqual(api.resultados_historicos(), [])


class TestPredecir(unittest.TestCase):
    def test_pasa_parametros(self):
        with mock.patch.object(api.requests, "get", return_value=_resp(200, {"ok": 1})) as g:
            api.predecir(229, 226)
            _, kwargs = g.call_args
            self.assertEqual(kwargs["params"]["home"], 229)
            self.assertEqual(kwargs["params"]["away"], 226)


_TEAMS = [
    {"id": 205, "name": "Club América"},
    {"id": 234, "name": "Pachuca"},
    {"id": 232, "name": "Tigres UANL"},
]

_STANDINGS = [
    {"position": 2, "team": {"name": "Pachuca"}, "played": 3, "won": 2, "drawn": 1,
     "lost": 0, "goals_for": 5, "goals_against": 2, "goal_difference": 3, "points": 7},
    {"position": 1, "team": {"name": "Club América"}, "played": 3, "won": 3, "drawn": 0,
     "lost": 0, "goals_for": 8, "goals_against": 1, "goal_difference": 7, "points": 9},
]


class TestEquiposResolver(unittest.TestCase):
    def test_mapa_e_id(self):
        with mock.patch.object(api, "obtener_equipos", return_value=_TEAMS):
            m = api.mapa_equipos()
            # canonical_team_key("Club América") == canonical_team_key("America")
            self.assertEqual(api.id_de_equipo("America", m), 205)
            self.assertEqual(api.id_de_equipo("Tigres", m), 232)
            self.assertIsNone(api.id_de_equipo("Equipo Inexistente", m))


class TestTablaNormalizada(unittest.TestCase):
    def test_mapea_y_ordena(self):
        def _side(path, params=None):
            if path == "/standings":
                return _STANDINGS
            if path == "/season":
                return {"tournament_now": "Apertura 2026"}
            return {}
        with mock.patch.object(api, "_get", side_effect=_side):
            t = api.tabla_normalizada()
        self.assertEqual(t["torneo"], "Apertura 2026")
        # Ordenada por posición: América (1) antes que Pachuca (2).
        self.assertEqual([f["posicion"] for f in t["tabla"]], [1, 2])
        self.assertEqual(t["tabla"][0]["equipo"], "América")
        self.assertEqual(t["tabla"][0]["puntos"], 9)
        self.assertEqual(t["tabla"][1]["ganados"], 2)


class TestAnalisisPartido(unittest.TestCase):
    _MAPA = {api.canonical_team_key("América"): 227,
             api.canonical_team_key("Toluca"): 223}

    def test_dossier_agrega_senales(self):
        with mock.patch.object(api, "mapa_equipos", return_value=self._MAPA), \
             mock.patch.object(api, "predecir", return_value={"p1": 0.5}), \
             mock.patch.object(api, "forma_equipo", return_value={"form": "WWD"}), \
             mock.patch.object(api, "disciplina_equipo", return_value={"at_risk": []}), \
             mock.patch.object(api, "racha_equipo", return_value={"streaks": {}}), \
             mock.patch.object(api, "h2h_resumen", return_value={"played": 10}):
            d = api.analisis_partido("America", "Toluca")
        self.assertEqual(d["home"], "América")
        self.assertEqual(d["home_id"], 227)
        self.assertEqual(d["away_id"], 223)
        self.assertEqual(d["prediccion_api"], {"p1": 0.5})
        self.assertEqual(d["h2h_resumen"], {"played": 10})
        self.assertIn("decision", d)

    def test_tolerante_si_una_senal_falla(self):
        # predecir lanza (pretemporada); el resto sigue y no rompe.
        with mock.patch.object(api, "mapa_equipos", return_value=self._MAPA), \
             mock.patch.object(api, "predecir", side_effect=RuntimeError("sin partidos")), \
             mock.patch.object(api, "forma_equipo", return_value={"form": ""}), \
             mock.patch.object(api, "disciplina_equipo", return_value={"at_risk": []}), \
             mock.patch.object(api, "racha_equipo", return_value={}), \
             mock.patch.object(api, "h2h_resumen", return_value={}):
            d = api.analisis_partido("America", "Toluca")
        self.assertIsNone(d["prediccion_api"])  # falló -> None, sin romper
        self.assertEqual(d["forma_local"], {"form": ""})

    def test_equipo_no_resuelto(self):
        with mock.patch.object(api, "mapa_equipos", return_value=self._MAPA):
            d = api.analisis_partido("America", "Equipo Inexistente")
        self.assertIsNone(d["away_id"])
        self.assertIn("nota", d)


class TestResumenPartido(unittest.TestCase):
    _MAPA = {api.canonical_team_key("América"): 227,
             api.canonical_team_key("Toluca"): 223}

    def test_resumen_compacto(self):
        pred = {"probabilities": {"home_win": 0.55, "draw": 0.25, "away_win": 0.20},
                "expected_goals": {"home": 1.8, "away": 1.0}}
        disc = {"at_risk": [{"player": "Jugador X"}, {"player": "Jugador Y"}]}
        with mock.patch.object(api, "mapa_equipos", return_value=self._MAPA), \
             mock.patch.object(api, "predecir", return_value=pred), \
             mock.patch.object(api, "forma_equipo", return_value={"form": "WWDLW"}), \
             mock.patch.object(api, "disciplina_equipo", return_value=disc), \
             mock.patch.object(api, "h2h_resumen", return_value={"played": 12}):
            r = api.resumen_partido("America", "Toluca")
        self.assertEqual(r["prediccion_api"]["prob_local_pct"], 55.0)
        self.assertEqual(r["prediccion_api"]["goles_esp"], "1.8-1.0")
        self.assertEqual(r["forma_local"], "WWDLW")
        self.assertEqual(r["en_riesgo_local"], ["Jugador X", "Jugador Y"])
        self.assertEqual(r["h2h"], {"played": 12})

    def test_resumen_pretemporada_tolerante(self):
        # predecir falla (sin partidos); forma/disciplina vacías -> sin romper.
        with mock.patch.object(api, "mapa_equipos", return_value=self._MAPA), \
             mock.patch.object(api, "predecir", side_effect=RuntimeError("sin partidos")), \
             mock.patch.object(api, "forma_equipo", return_value={"form": ""}), \
             mock.patch.object(api, "disciplina_equipo", return_value={"at_risk": []}), \
             mock.patch.object(api, "h2h_resumen", return_value={}):
            r = api.resumen_partido("America", "Toluca")
        self.assertIsNone(r["prediccion_api"])
        self.assertEqual(r["en_riesgo_local"], [])
        self.assertIsNone(r["h2h"])


if __name__ == "__main__":
    unittest.main()
