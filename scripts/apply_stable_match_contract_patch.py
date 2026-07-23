#!/usr/bin/env python3
"""Aplica una vez el contrato estable de partidos sobre src/ligamx_api.py."""
from pathlib import Path

SOURCE = Path("src/ligamx_api.py")
TEST = Path("tests/test_ligamx_contract.py")
text = SOURCE.read_text(encoding="utf-8")

if "def normalizar_partido_api(" in text:
    raise SystemExit("El contrato estable ya está aplicado")

text = text.replace(
    "import os\nfrom typing import Any, Dict, List, Optional, cast\nimport logging\n",
    "import os\nfrom datetime import datetime, timezone\nfrom typing import Any, Dict, List, Optional, cast\nimport logging\n",
    1,
)

marker = "# ---------------------------------------------------------------------------\n# Salud / estado\n"
contract = '''# ---------------------------------------------------------------------------
# Contrato estable de partidos (ligamx-api)
# ---------------------------------------------------------------------------
def normalizar_kickoff_utc(valor: Any) -> str:
    """Normaliza ISO-8601 con Z/offset a UTC explícito; naive legacy se asume UTC."""
    raw = str(valor or "").strip()
    if not raw:
        return ""
    iso = f"{raw[:-1]}+00:00" if raw[-1:].upper() == "Z" else raw
    try:
        kickoff = datetime.fromisoformat(iso)
    except ValueError:
        logger.warning("Kickoff ISO-8601 inválido recibido de ligamx-api: %s", raw)
        return raw
    # Compatibilidad con respuestas antiguas sin zona: históricamente eran UTC.
    if kickoff.tzinfo is None:
        kickoff = kickoff.replace(tzinfo=timezone.utc)
    return kickoff.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalizar_partido_api(partido: Dict[str, Any]) -> Dict[str, Any]:
    """Preserva espn_event_id y publica identidad/kickoff estables sin mutar la entrada."""
    salida = dict(partido)
    espn_raw = partido.get("espn_event_id")
    espn_event_id = str(espn_raw).strip() if espn_raw not in (None, "") else None
    kickoff_utc = normalizar_kickoff_utc(partido.get("match_date") or partido.get("date"))
    home = partido.get("home_team") or {}
    away = partido.get("away_team") or {}
    home_name = home.get("name", "") if isinstance(home, dict) else str(home)
    away_name = away.get("name", "") if isinstance(away, dict) else str(away)
    if espn_event_id:
        match_key = f"espn:{espn_event_id}"
    else:
        match_key = (
            f"legacy:{canonical_team_key(home_name)}:"
            f"{canonical_team_key(away_name)}:{kickoff_utc}"
        )
    salida.update(
        {
            "espn_event_id": espn_event_id,
            "match_key": match_key,
            "kickoff_utc": kickoff_utc,
        }
    )
    return salida


'''
if marker not in text:
    raise RuntimeError("No se encontró el marcador de inserción")
text = text.replace(marker, contract + marker, 1)

old_calendar = '''        for m in j.get("matches", []):
            home = (m.get("home_team") or {}).get("name", "")
            away = (m.get("away_team") or {}).get("name", "")
            if not home or not away:
                continue
            partidos.append(
                {
                    "home_team": display_team_name(home),
                    "away_team": display_team_name(away),
                    "date": m.get("date"),
                    "venue": m.get("venue"),
                }
            )'''
new_calendar = '''        for m in j.get("matches", []):
            normalizado = normalizar_partido_api(m)
            home = (m.get("home_team") or {}).get("name", "")
            away = (m.get("away_team") or {}).get("name", "")
            if not home or not away:
                continue
            partidos.append(
                {
                    "home_team": display_team_name(home),
                    "away_team": display_team_name(away),
                    "date": normalizado["kickoff_utc"] or m.get("date"),
                    "venue": m.get("venue"),
                    "espn_event_id": normalizado["espn_event_id"],
                    "match_key": normalizado["match_key"],
                    "kickoff_utc": normalizado["kickoff_utc"],
                }
            )'''
if old_calendar not in text:
    raise RuntimeError("No se encontró calendario_para_planificador")
text = text.replace(old_calendar, new_calendar, 1)

old_fixtures = '''            fixtures.append(
                {
                    "fecha": fecha,
                    "home_team": display_team_name(home),
                    "away_team": display_team_name(away),
                    "venue": m.get("venue"),
                }
            )'''
new_fixtures = '''            normalizado = normalizar_partido_api(m)
            fixtures.append(
                {
                    "fecha": normalizado["kickoff_utc"] or fecha,
                    "home_team": display_team_name(home),
                    "away_team": display_team_name(away),
                    "venue": m.get("venue"),
                    "espn_event_id": normalizado["espn_event_id"],
                    "match_key": normalizado["match_key"],
                    "kickoff_utc": normalizado["kickoff_utc"],
                }
            )'''
if old_fixtures not in text:
    raise RuntimeError("No se encontró fixtures_planos")
text = text.replace(old_fixtures, new_fixtures, 1)

old_results = '''            salida.append(
                {
                    "home_team": display_team_name(home),
                    "away_team": display_team_name(away),
                    "home_goals": hg,
                    "away_goals": ag,
                    "fecha": str(m.get("match_date") or "")[:10],
                }
            )'''
new_results = '''            normalizado = normalizar_partido_api(m)
            salida.append(
                {
                    "home_team": display_team_name(home),
                    "away_team": display_team_name(away),
                    "home_goals": hg,
                    "away_goals": ag,
                    "fecha": str(normalizado["kickoff_utc"] or m.get("match_date") or "")[:10],
                    "espn_event_id": normalizado["espn_event_id"],
                    "match_key": normalizado["match_key"],
                    "kickoff_utc": normalizado["kickoff_utc"],
                }
            )'''
if old_results not in text:
    raise RuntimeError("No se encontró resultados_historicos")
text = text.replace(old_results, new_results, 1)

start = text.index("def match_id_de_partido(")
end = text.index("\n\ndef jugadores_a_seguir_partido", start)
new_match_lookup = '''def match_id_de_partido(home: str, away: str, espn_event_id: Optional[str] = None) -> Optional[int]:
    """Resuelve id interno; con ESPN ID exige coincidencia exacta, sin fallback ambiguo."""
    esperado = str(espn_event_id).strip() if espn_event_id not in (None, "") else None

    def _buscar(lista: Any) -> Optional[int]:
        if not isinstance(lista, list):
            return None
        for m in lista:
            if not isinstance(m, dict):
                continue
            if esperado is not None:
                actual = m.get("espn_event_id")
                if actual is None or str(actual).strip() != esperado:
                    continue
            else:
                h = m.get("home_team") or {}
                a = m.get("away_team") or {}
                hn = h.get("name") if isinstance(h, dict) else h
                an = a.get("name") if isinstance(a, dict) else a
                if not hn or not an or not (
                    teams_match(str(hn), home) and teams_match(str(an), away)
                ):
                    continue
            mid = _campo(m, "id", "match_id", "matchId")
            try:
                return int(mid) if mid is not None else None
            except (TypeError, ValueError):
                return None
        return None

    fuentes = (
        lambda: partidos_proximos(limit=50),
        lambda: obtener_partidos(status="finished", limit=100),
        lambda: obtener_partidos(limit=100),
    )
    for cargar in fuentes:
        mid = _buscar(_safe(cargar, []))
        if mid is not None:
            return mid
    return None
'''
text = text[:start] + new_match_lookup + text[end:]
SOURCE.write_text(text, encoding="utf-8")

TEST.write_text('''#!/usr/bin/env python3
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
''', encoding="utf-8")
