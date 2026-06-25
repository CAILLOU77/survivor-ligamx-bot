#!/usr/bin/env python3
"""
TheSportsDB Liga MX fallback.

Uso:
- Fuente gratis para calendario/resultados/equipos.
- NO reemplaza data/jornadas.json.
- NO decide picks Survivor.
- Sirve como respaldo/auditoría externa de Liga MX.

Config .env:
THESPORTSDB_API_KEY=123
THESPORTSDB_LIGAMX_ID=4350
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = BASE_DIR / "reports"

API_BASE = "https://www.thesportsdb.com/api/v1/json"


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


def get_config() -> tuple[str, str]:
    api_key = os.getenv("THESPORTSDB_API_KEY", "123").strip() or "123"
    league_id = os.getenv("THESPORTSDB_LIGAMX_ID", "4350").strip() or "4350"
    return api_key, league_id


def fetch_json(endpoint: str, params: Dict[str, str]) -> Dict[str, Any]:
    api_key, _ = get_config()

    query = urllib.parse.urlencode(params)
    url = f"{API_BASE}/{api_key}/{endpoint}?{query}"

    with urllib.request.urlopen(url, timeout=30) as response:
        raw = response.read().decode("utf-8")

    data = json.loads(raw)

    if not isinstance(data, dict):
        raise RuntimeError(f"Respuesta inesperada de TheSportsDB: {type(data).__name__}")

    return data


def limpiar_evento(evento: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id_event": evento.get("idEvent"),
        "league": evento.get("strLeague"),
        "season": evento.get("strSeason"),
        "round": evento.get("intRound"),
        "date": evento.get("dateEvent"),
        "time": evento.get("strTime"),
        "timestamp": evento.get("strTimestamp"),
        "home_team": evento.get("strHomeTeam"),
        "away_team": evento.get("strAwayTeam"),
        "home_score": evento.get("intHomeScore"),
        "away_score": evento.get("intAwayScore"),
        "venue": evento.get("strVenue"),
        "city": evento.get("strCity"),
        "status": evento.get("strStatus"),
    }


def limpiar_equipo(equipo: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id_team": equipo.get("idTeam"),
        "team": equipo.get("strTeam"),
        "short": equipo.get("strTeamShort"),
        "alternate": equipo.get("strAlternate"),
        "formed_year": equipo.get("intFormedYear"),
        "stadium": equipo.get("strStadium"),
        "stadium_location": equipo.get("strStadiumLocation"),
        "website": equipo.get("strWebsite"),
    }


def obtener_snapshot_ligamx() -> Dict[str, Any]:
    leer_env_si_existe()

    api_key, league_id = get_config()

    print("📚 TheSportsDB: consultando respaldo gratis Liga MX...")
    print(f"🏷️ Liga MX ID: {league_id}")
    print("🔐 API key: configurada / no se imprime completa")

    proximos_raw = fetch_json("eventsnextleague.php", {"id": league_id})
    recientes_raw = fetch_json("eventspastleague.php", {"id": league_id})
    temporada_raw = fetch_json("eventsseason.php", {"id": league_id, "s": "2026-2027"})
    equipos_raw = fetch_json("lookup_all_teams.php", {"id": league_id})

    proximos = [limpiar_evento(e) for e in (proximos_raw.get("events") or [])]
    recientes = [limpiar_evento(e) for e in (recientes_raw.get("events") or [])]
    temporada = [limpiar_evento(e) for e in (temporada_raw.get("events") or [])]
    equipos = [limpiar_equipo(t) for t in (equipos_raw.get("teams") or [])]

    snapshot = {
        "fuente": "TheSportsDB",
        "uso": "fallback_calendario_resultados_ligamx",
        "nota": "No reemplaza data/jornadas.json y no decide picks Survivor.",
        "generado_en": datetime.now(timezone.utc).isoformat(),
        "api_key_label": "free" if api_key == "123" else "custom",
        "league_id": league_id,
        "proximos_partidos_count": len(proximos),
        "partidos_recientes_count": len(recientes),
        "temporada_partidos_count": len(temporada),
        "equipos_count": len(equipos),
        "proximos_partidos": proximos,
        "partidos_recientes": recientes,
        "temporada_2026_2027": temporada,
        "equipos": equipos,
    }

    return snapshot


def guardar_snapshot(snapshot: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    REPORTS_DIR.mkdir(exist_ok=True)

    json_path = DATA_DIR / "thesportsdb_ligamx.json"
    report_path = REPORTS_DIR / "thesportsdb_ligamx_ultimo.txt"

    json_path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    lines: List[str] = []
    lines.append("📚 TheSportsDB Liga MX — Fallback calendario/resultados")
    lines.append("=" * 60)
    lines.append(f"Generado en: {snapshot.get('generado_en')}")
    lines.append(f"Liga ID: {snapshot.get('league_id')}")
    lines.append(f"API key label: {snapshot.get('api_key_label')}")
    lines.append("")
    lines.append("Estado:")
    lines.append(f"- Próximos partidos: {snapshot.get('proximos_partidos_count')}")
    lines.append(f"- Partidos recientes: {snapshot.get('partidos_recientes_count')}")
    lines.append(f"- Partidos temporada 2026-2027: {snapshot.get('temporada_partidos_count')}")
    lines.append(f"- Equipos: {snapshot.get('equipos_count')}")
    lines.append("")
    lines.append("⚠️ Uso operativo:")
    lines.append("- NO decide picks Survivor.")
    lines.append("- NO reemplaza data/jornadas.json.")
    lines.append("- Sirve para validar calendario/resultados/equipos.")
    lines.append("")

    lines.append("Próximos partidos detectados:")
    proximos = snapshot.get("proximos_partidos") or []
    if not proximos:
        lines.append("- Sin próximos partidos devueltos por TheSportsDB.")
    else:
        for partido in proximos[:20]:
            lines.append(
                f"- {partido.get('date')} {partido.get('time') or ''} | "
                f"{partido.get('home_team')} vs {partido.get('away_team')} | "
                f"{partido.get('venue') or 'Sede no disponible'}"
            )

    lines.append("")
    lines.append("Partidos temporada 2026-2027 detectados:")
    temporada = snapshot.get("temporada_2026_2027") or []
    if not temporada:
        lines.append("- Sin partidos de temporada devueltos por TheSportsDB.")
    else:
        for partido in temporada[:30]:
            score = ""
            if partido.get("home_score") is not None or partido.get("away_score") is not None:
                score = f" | {partido.get('home_score')} - {partido.get('away_score')}"

            lines.append(
                f"- {partido.get('date')} {partido.get('time') or ''} | "
                f"{partido.get('home_team')} vs {partido.get('away_team')}"
                f"{score} | {partido.get('venue') or 'Sede no disponible'}"
            )

    lines.append("")
    lines.append("Partidos recientes detectados:")
    recientes = snapshot.get("partidos_recientes") or []
    if not recientes:
        lines.append("- Sin partidos recientes devueltos por TheSportsDB.")
    else:
        for partido in recientes[:20]:
            score = ""
            if partido.get("home_score") is not None or partido.get("away_score") is not None:
                score = f" | {partido.get('home_score')} - {partido.get('away_score')}"

            lines.append(
                f"- {partido.get('date')} | "
                f"{partido.get('home_team')} vs {partido.get('away_team')}"
                f"{score}"
            )

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"✅ JSON guardado: {json_path}")
    print(f"✅ Reporte guardado: {report_path}")


def main() -> int:
    try:
        snapshot = obtener_snapshot_ligamx()
        guardar_snapshot(snapshot)

        print("")
        print("✅ TheSportsDB fallback listo.")
        print("➡️ No reemplazó jornadas ni picks.")
        return 0

    except Exception as exc:
        print(f"❌ Error consultando TheSportsDB: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
