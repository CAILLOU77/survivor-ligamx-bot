#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List


BASE_DIR = Path(__file__).resolve().parents[1]
CACHE_DIR = BASE_DIR / "data" / "cache"
OUTPUT_JSON = BASE_DIR / "data" / "espn_ligamx_fixtures_preview.json"
OUTPUT_REPORT = BASE_DIR / "reports" / "espn_ligamx_fixtures_preview.txt"
JORNADAS_PATH = BASE_DIR / "data" / "jornadas.json"

ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/mex.1/scoreboard"


def cache_path(date_from: str, date_to: str) -> Path:
    safe = f"{date_from.replace('-', '')}_{date_to.replace('-', '')}"
    return CACHE_DIR / f"espn_ligamx_scoreboard_{safe}.json"


def cache_fresco(path: Path, max_age_minutes: int) -> bool:
    if not path.exists():
        return False

    age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
    return age <= timedelta(minutes=max_age_minutes)


def fetch_espn(date_from: str, date_to: str, force: bool, cache_minutes: int) -> Dict[str, Any]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cpath = cache_path(date_from, date_to)

    if not force and cache_fresco(cpath, cache_minutes):
        return json.loads(cpath.read_text(encoding="utf-8"))

    dates = f"{date_from.replace('-', '')}-{date_to.replace('-', '')}"
    params = {
        "dates": dates,
        "limit": "200",
    }

    url = ESPN_SCOREBOARD_URL + "?" + urllib.parse.urlencode(params)

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "survivor-ligamx-bot/espn-fixtures-preview",
            "Accept": "application/json",
        },
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read().decode("utf-8")

    data = json.loads(raw)

    if not isinstance(data, dict):
        raise RuntimeError(f"Respuesta inesperada ESPN: {data}")

    cpath.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def parse_datetime(value: str) -> tuple[str, str]:
    if not value:
        return "PENDIENTE_CONFIRMAR", "PENDIENTE_CONFIRMAR"

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
        return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")
    except Exception:
        return value[:10], "PENDIENTE_CONFIRMAR"


def extraer_competidores(event: Dict[str, Any]) -> tuple[str, str]:
    competitions = event.get("competitions", [])
    if not competitions or not isinstance(competitions, list):
        return "", ""

    competition = competitions[0]
    competitors = competition.get("competitors", [])

    local = ""
    visitante = ""

    for comp in competitors:
        if not isinstance(comp, dict):
            continue

        team = comp.get("team", {})
        name = (
            team.get("displayName")
            or team.get("shortDisplayName")
            or team.get("name")
            or team.get("abbreviation")
            or ""
        )

        home_away = str(comp.get("homeAway", "")).lower()

        if home_away == "home":
            local = str(name)
        elif home_away == "away":
            visitante = str(name)

    return local, visitante


def extraer_venue(event: Dict[str, Any]) -> tuple[str, str]:
    competitions = event.get("competitions", [])
    if not competitions or not isinstance(competitions, list):
        return "PENDIENTE_CONFIRMAR", "PENDIENTE_CONFIRMAR"

    competition = competitions[0]
    venue = competition.get("venue", {})

    if not isinstance(venue, dict):
        return "PENDIENTE_CONFIRMAR", "PENDIENTE_CONFIRMAR"

    estadio = venue.get("fullName") or venue.get("name") or "PENDIENTE_CONFIRMAR"

    address = venue.get("address", {})
    ciudad = "PENDIENTE_CONFIRMAR"

    if isinstance(address, dict):
        ciudad = address.get("city") or "PENDIENTE_CONFIRMAR"

    return str(estadio), str(ciudad)


def convertir_evento(event: Dict[str, Any]) -> Dict[str, Any]:
    local, visitante = extraer_competidores(event)
    fecha, hora = parse_datetime(str(event.get("date", "")))
    estadio, ciudad = extraer_venue(event)

    name = event.get("name") or f"{local} vs {visitante}"
    short_name = event.get("shortName") or ""

    return {
        "home_team": local,
        "away_team": visitante,
        "local": local,
        "visitante": visitante,
        "fecha": fecha,
        "hora": hora,
        "estadio": estadio,
        "ciudad": ciudad,
        "jornada": "PENDIENTE_CONFIRMAR",
        "fixture_source": {
            "source": "ESPN public scoreboard",
            "event_id": event.get("id"),
            "name": name,
            "short_name": short_name,
            "date_raw": event.get("date"),
            "status": event.get("status", {}),
        },
        "momios": {
            "estado": "pendiente_odds_api",
            "fuente": "ESPN fixtures only",
            "nota": "Calendario detectado gratis; momios reales deben venir de The Odds API u otra fuente real.",
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


def parse_events(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    events = data.get("events", [])
    if not isinstance(events, list):
        return []

    partidos = []

    for event in events:
        if not isinstance(event, dict):
            continue

        local, visitante = extraer_competidores(event)
        if not local or not visitante:
            continue

        partidos.append(convertir_evento(event))

    partidos.sort(key=lambda p: (p.get("fecha", ""), p.get("hora", ""), p.get("home_team", "")))
    return partidos


def aplicar_a_jornadas(partidos: List[Dict[str, Any]], date_from: str, date_to: str) -> Path:
    """
    Reemplaza data/jornadas.json con fixtures ESPN del rango elegido.
    Los momios quedan como fallback técnico y Real Data Gate debe bloquear CERRAR
    hasta que The Odds API traiga mercado real.
    """
    JORNADAS_PATH.parent.mkdir(parents=True, exist_ok=True)

    backup = JORNADAS_PATH.with_suffix(
        f".backup-espn-fixtures-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    )

    if JORNADAS_PATH.exists():
        backup.write_text(JORNADAS_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        backup.write_text("[]\n", encoding="utf-8")

    salida = []
    for partido in partidos:
        p = dict(partido)
        p["fixture_source"]["aplicado_a_jornadas"] = True
        p["fixture_source"]["rango_aplicado"] = {
            "date_from": date_from,
            "date_to": date_to,
        }
        salida.append(p)

    JORNADAS_PATH.write_text(
        json.dumps(salida, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return backup


def escribir_report(result: Dict[str, Any]) -> None:
    OUTPUT_REPORT.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append("ESPN LIGA MX FIXTURES PREVIEW")
    lines.append("-" * 70)
    lines.append(f"Generado: {result['generado_en']}")
    lines.append(f"Rango: {result['date_from']} a {result['date_to']}")
    lines.append(f"Fixtures detectados: {result['fixtures_count']}")
    lines.append(f"Aplicado a jornadas: {'Sí' if result.get('applied') else 'No'}")
    if result.get("backup_path"):
        lines.append(f"Backup: {result['backup_path']}")
    lines.append("")

    if result.get("error"):
        lines.append(f"ERROR: {result['error']}")
        lines.append("")

    for idx, p in enumerate(result.get("partidos_preview", []), start=1):
        lines.append(
            f"{idx}. {p['home_team']} vs {p['away_team']} | "
            f"{p['fecha']} {p['hora']} | {p['estadio']} / {p['ciudad']}"
        )

    lines.append("")
    lines.append("Nota:")
    lines.append("- Esto es preview. No reemplaza data/jornadas.json todavía.")
    lines.append("- ESPN sirve para calendario gratis; no sirve para momios reales.")
    lines.append("- El Real Data Gate debe seguir bloqueando CERRAR si faltan momios reales.")

    OUTPUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date-from", default="2026-07-16")
    parser.add_argument("--date-to", default="2026-07-31")
    parser.add_argument("--cache-minutes", type=int, default=720)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--apply", action="store_true", help="Reemplaza data/jornadas.json con el preview ESPN del rango elegido.")
    args = parser.parse_args()

    result: Dict[str, Any] = {
        "generado_en": datetime.now().isoformat(timespec="seconds"),
        "date_from": args.date_from,
        "date_to": args.date_to,
        "fixtures_count": 0,
        "partidos_preview": [],
        "error": None,
    }

    try:
        data = fetch_espn(
            date_from=args.date_from,
            date_to=args.date_to,
            force=args.force,
            cache_minutes=args.cache_minutes,
        )
        partidos = parse_events(data)

        result["fixtures_count"] = len(partidos)
        result["partidos_preview"] = partidos
        result["espn_leagues"] = data.get("leagues", [])
        result["espn_season"] = data.get("season", {})

        if args.apply:
            backup = aplicar_a_jornadas(partidos, args.date_from, args.date_to)
            result["applied"] = True
            result["jornadas_path"] = str(JORNADAS_PATH)
            result["backup_path"] = str(backup)
        else:
            result["applied"] = False

    except Exception as exc:
        result["error"] = str(exc)

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    escribir_report(result)

    print("📅 ESPN LIGA MX FIXTURES PREVIEW")
    print("=" * 70)

    if result.get("error"):
        print(f"ERROR: {result['error']}")
    else:
        print(f"Fixtures detectados: {result['fixtures_count']}")
        for p in result["partidos_preview"][:15]:
            print(f"- {p['home_team']} vs {p['away_team']} | {p['fecha']} {p['hora']}")

        if result.get("applied"):
            print(f"✅ Aplicado a: {JORNADAS_PATH}")
            print(f"✅ Backup: {result.get('backup_path')}")

    print(f"✅ Reporte: {OUTPUT_REPORT}")
    print(f"✅ JSON: {OUTPUT_JSON}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
