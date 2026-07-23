#!/usr/bin/env python3
"""Contrato estable entre survivor-ligamx-bot y ligamx-api. Sin red."""
from unittest import mock

from src import ligamx_api as api


def _match(event_id=401877045, date="2026-07-17T01:00:00Z"):
    return {
        "id": 77,
        "espn_event_id": event_id,
        "date": date,
        "match_date": date,
        "home_team": {"name": "Club América"},
        "away_team": {"name": "Chivas Guadalajara"},
        "home_score": 2,
        "away_score": 1,
    }


def test_kickoff_z_y_offset_se_normalizan_a_utc():
    assert api.normalizar_kickoff_utc("2026-07-17T01:00:00Z") == "2026-07-17T01:00:00Z"
    assert api.normalizar_kickoff_utc("2026-07-16T18:00:00-07:00") == "2026-07-17T01:00:00Z"


def test_kickoff_naive_legacy_se_trata_como_utc():
    assert api.normalizar_kickoff_utc("2026-07-17T01:00:00") == "2026-07-17T01:00:00Z"


def test_identidad_prefiere_espn_y_normaliza_tipo():
    a = api.normalizar_partido_api(_match(401877045))
    b = api.normalizar_partido_api({**_match("401877045"), "home_team": {"name": "América"}})
    assert a["espn_event_id"] == "401877045"
    assert a["match_key"] == b["match_key"] == "espn:401877045"


def test_identidad_legacy_es_determinista_sin_id():
    a = api.normalizar_partido_api(_match(None))
    b = api.normalizar_partido_api({**_match(None), "home_team": {"name": "América"}})
    assert a["match_key"] == b["match_key"]
    assert a["match_key"].startswith("legacy:")


def test_calendario_y_fixtures_propagan_contrato():
    payload = {"jornadas": [{"jornada": 1, "matches": [_match()]}]}
    with mock.patch.object(api, "obtener_calendario", return_value=payload):
        calendario = api.calendario_para_planificador()
        fixtures = api.fixtures_planos()
    for item in (calendario[0]["partidos"][0], fixtures[0]):
        assert item["espn_event_id"] == "401877045"
        assert item["match_key"] == "espn:401877045"
        assert item["kickoff_utc"].endswith("Z")


def test_resultados_propagan_contrato():
    with mock.patch.object(api, "obtener_partidos", side_effect=[[_match()], []]):
        resultado = api.resultados_historicos()[0]
    assert resultado["espn_event_id"] == "401877045"
    assert resultado["match_key"] == "espn:401877045"
    assert resultado["fecha"] == "2026-07-17"


def test_busqueda_por_espn_id_es_estricta():
    partidos = [_match("otro"), {**_match("objetivo"), "id": 88}]
    with mock.patch.object(api, "partidos_proximos", return_value=partidos):
        assert api.match_id_de_partido("nombre", "irrelevante", "objetivo") == 88
        assert api.match_id_de_partido("América", "Guadalajara", "ausente") is None


def test_busqueda_legacy_por_nombres_sigue_funcionando():
    with mock.patch.object(api, "partidos_proximos", return_value=[_match()]):
        assert api.match_id_de_partido("América", "Guadalajara") == 77
