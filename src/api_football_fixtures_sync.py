#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_JSON = BASE_DIR / "data" / "api_football_fixtures_preview.json"
OUTPUT_REPORT = BASE_DIR / "reports" / "api_football_fixtures_preview.txt"

API_BASE = "https://v3.football.api-sports.io"


try:
    from api_budget import can_call as budget_can_call
    from api_budget import record_call as budget_record_call
    from api_budget import write_report as budget_write_report
except Exception:
    budget_can_call = None
    budget_record_call = None
    budget_write_report = None


def leer_env_si_existe() -> None:
    env_path = BASE_DIR / ".env"

    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def api_get(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    key = os.getenv("APIFOOTBALL_KEY", "").strip()

    if not key:
        raise RuntimeError("Falta APIFOOTBALL_KEY en .env")

    url = API_BASE + path + "?" + urllib.parse.urlencode(params)

    req = urllib.request.Request(
        url,
        headers={
            "x-apisports-key": key,
            "User-Agent": "survivor-ligamx-bot/1.8.0",
        },
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read().decode("utf-8")

    data = json.loads(raw)

    if not isinstance(data, dict):
        raise RuntimeError(f"Respuesta inesperada API-Football: {data}")

    return data


def budget_check(units: int = 1) -> bool:
    if budget_can_call is None:
        return True

    min_interval = int(os.getenv("APIFOOTBALL_SYNC_MIN_INTERVAL_MINUTES", "720"))

    permitido, mensaje = budget_can_call(
        "api_football",
        units=units,
        min_interval_minutes=min_interval,
    )

    if not permitido:
        print(f"⏸️ {mensaje}")
        print("➡️ No se consulta API-Football para ahorrar saldo.")

        if budget_write_report is not None:
            budget_write_report()

        return False

    print(f"✅ Budget OK API-Football: {mensaje}")
    return True


def budget_record(units: int, note: str) -> None:
    if budget_record_call is not None:
        budget_record_call("api_football", units=units, note=note)

    if budget_write_report is not None:
        budget_write_report()


def buscar_liga_mx(season: int) -> Dict[str, Any]:
    data = api_get("/leagues", {"country": "Mexico", "season": season})
    response = data.get("response", [])

    if not isinstance(response, list):
        raise RuntimeError(f"Respuesta inválida /leagues: {data}")

    candidatos = []
    disponibles = []

    for item in response:
        if not isinstance(item, dict):
            continue

        league = item.get("league", {})
        country = item.get("country", {})

        if not isinstance(league, dict):
            continue

        name = str(league.get("name", ""))
        league_id = league.get("id")
        league_type = league.get("type")

        disponibles.append(
            {
                "league_id": league_id,
                "name": name,
                "type": league_type,
            }
        )

        blob = name.lower()

        if (
            "liga mx" in blob
            or "primera division" in blob
            or "primera división" in blob
            or name.strip().lower() == "mexico liga mx"
        ):
            candidatos.append(
                {
                    "league_id": league_id,
                    "name": name,
                    "type": league_type,
                    "country": country.get("name"),
                    "logo": league.get("logo"),
                    "raw": item,
                }
            )

    if not candidatos:
        raise RuntimeError(
            "No encontré Liga MX en API-Football para esa temporada. "
            f"Ligas mexicanas encontradas: {disponibles[:15]}"
        )

    candidatos.sort(
        key=lambda x: (
            0 if "liga mx" in str(x["name"]).lower() else 1,
            0 if str(x.get("type", "")).lower() == "league" else 1,
        )
    )

    return candidatos[0]


def obtener_fixtures(league_id: int, season: int, next_games: int, timezone: str) -> Dict[str, Any]:
    params = {
        "league": league_id,
        "season": season,
        "next": next_games,
        "timezone": timezone,
    }

    return api_get("/fixtures", params)


def convertir_fixture_a_partido(item: Dict[str, Any]) -> Dict[str, Any]:
    fixture = item.get("fixture", {})
    teams = item.get("teams", {})
    league = item.get("league", {})

    home = teams.get("home", {}) if isinstance(teams, dict) else {}
    away = teams.get("away", {}) if isinstance(teams, dict) else {}
    venue = fixture.get("venue", {}) if isinstance(fixture, dict) else {}
    status = fixture.get("status", {}) if isinstance(fixture, dict) else {}

    date_raw = str(fixture.get("date", ""))
    fecha = "PENDIENTE_CONFIRMAR"
    hora = "PENDIENTE_CONFIRMAR"

    if date_raw:
        try:
            dt = datetime.fromisoformat(date_raw.replace("Z", "+00:00"))
            fecha = dt.strftime("%Y-%m-%d")
            hora = dt.strftime("%H:%M")
        except Exception:
            fecha = date_raw[:10] if len(date_raw) >= 10 else date_raw

    local = str(home.get("name") or "")
    visitante = str(away.get("name") or "")

    return {
        "home_team": local,
        "away_team": visitante,
        "local": local,
        "visitante": visitante,
        "fecha": fecha,
        "hora": hora,
        "estadio": venue.get("name") or "PENDIENTE_CONFIRMAR",
        "ciudad": venue.get("city") or "PENDIENTE_CONFIRMAR",
        "jornada": league.get("round") or "PENDIENTE_CONFIRMAR",
        "api_football": {
            "fixture_id": fixture.get("id"),
            "league_id": league.get("id"),
            "league_name": league.get("name"),
            "season": league.get("season"),
            "round": league.get("round"),
            "status_short": status.get("short"),
            "status_long": status.get("long"),
            "timestamp": fixture.get("timestamp"),
            "timezone": fixture.get("timezone"),
        },
        "momios": {
            "estado": "pendiente_odds_api",
            "fuente": "API-Football fixtures only",
            "nota": "Calendario real detectado; momios deben venir de The Odds API o mercado real.",
        },
        "bookmakers": [
            {
                "key": "fallback_local",
                "title": "Fallback técnico - esperando momios reales",
                "markets": [
                    {
                        "key": "h2h",
                        "last_update": None,
                        "outcomes": [
                            {"name": local, "price": 1.80},
                            {"name": "Draw", "price": 3.40},
                            {"name": visitante, "price": 4.50},
                        ],
                    }
                ],
            }
        ],
        "lesiones": [],
        "suspendidos": [],
        "bajas_revisadas": False,
    }


def escribir_report(result: Dict[str, Any]) -> None:
    OUTPUT_REPORT.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append("API-FOOTBALL FIXTURES PREVIEW")
    lines.append("-" * 70)
    lines.append(f"Generado: {result['generado_en']}")
    lines.append(f"Season: {result['season']}")
    lines.append(f"League ID: {result.get('league', {}).get('league_id')}")
    lines.append(f"League: {result.get('league', {}).get('name')}")
    lines.append(f"Fixtures recibidos: {result['fixtures_count']}")
    lines.append("")

    if result.get("error"):
        lines.append(f"ERROR: {result['error']}")
        lines.append("")

    partidos = result.get("partidos_preview", [])

    for idx, p in enumerate(partidos, start=1):
        lines.append(
            f"{idx}. {p['home_team']} vs {p['away_team']} | "
            f"{p['fecha']} {p['hora']} | {p['jornada']} | "
            f"{p['estadio']} / {p['ciudad']}"
        )

    lines.append("")
    lines.append("Nota:")
    lines.append("- Esto es preview. No reemplaza data/jornadas.json todavía.")
    lines.append("- Momios siguen dependiendo de The Odds API / mercado real.")
    lines.append("- Si el preview se ve correcto, después activamos --apply.")

    OUTPUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=int(os.getenv("APIFOOTBALL_SEASON", "2026")))
    parser.add_argument("--next", type=int, default=int(os.getenv("APIFOOTBALL_NEXT", "20")))
    parser.add_argument("--timezone", default=os.getenv("APIFOOTBALL_TIMEZONE", "America/Mexico_City"))
    args = parser.parse_args()

    leer_env_si_existe()

    result: Dict[str, Any] = {
        "generado_en": datetime.now().isoformat(timespec="seconds"),
        "season": args.season,
        "next": args.next,
        "timezone": args.timezone,
        "league": {},
        "fixtures_count": 0,
        "partidos_preview": [],
        "error": None,
    }

    if not budget_check(units=2):
        result["error"] = "Bloqueado por API Budget Manager/cooldown."
        escribir_report(result)
        OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 0

    try:
        liga = buscar_liga_mx(args.season)
        result["league"] = liga

        fixtures_data = obtener_fixtures(
            league_id=int(liga["league_id"]),
            season=args.season,
            next_games=args.next,
            timezone=args.timezone,
        )

        response = fixtures_data.get("response", [])

        if not isinstance(response, list):
            raise RuntimeError(f"Respuesta inválida /fixtures: {fixtures_data}")

        partidos = [convertir_fixture_a_partido(item) for item in response if isinstance(item, dict)]

        result["fixtures_count"] = len(response)
        result["partidos_preview"] = partidos

        budget_record(units=2, note=f"api_football preview fixtures={len(partidos)}")

    except Exception as exc:
        result["error"] = str(exc)

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    escribir_report(result)

    print("📅 API-FOOTBALL FIXTURES PREVIEW")
    print("=" * 70)

    if result.get("error"):
        print(f"ERROR: {result['error']}")
    else:
        print(f"League: {result['league'].get('name')} | ID {result['league'].get('league_id')}")
        print(f"Fixtures recibidos: {result['fixtures_count']}")

        for p in result["partidos_preview"][:10]:
            print(f"- {p['home_team']} vs {p['away_team']} | {p['fecha']} {p['hora']} | {p['jornada']}")

    print(f"✅ Reporte: {OUTPUT_REPORT}")
    print(f"✅ JSON: {OUTPUT_JSON}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
