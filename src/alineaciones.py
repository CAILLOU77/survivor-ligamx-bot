#!/usr/bin/env python3
"""
API-Football Liga MX — Alineaciones y lesiones.

Uso:
- Descarga fixtures, lesiones y alineaciones disponibles.
- Lee FOOTBALL_API_KEY_1, FOOTBALL_API_KEY_2, etc. desde .env.
- También acepta APIFOOTBALL_KEY como compatibilidad.
- Usa salto automático SOLO por fallas técnicas:
  Timeout, ConnectionError, 500, 502, 503, 504 o mantenimiento técnico.
- NO rota por 401/403/429/cuota/rate limit/auth.
- NO decide picks Survivor.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = BASE_DIR / "reports"

API_BASE = "https://v3.football.api-sports.io"

DEFAULT_LEAGUE_ID = "45"
DEFAULT_SEASON = "2026"

FAILOVER_STATUS_CODES = {500, 502, 503, 504}
NO_ROTATE_STATUS_CODES = {401, 403, 429}

TECHNICAL_ERROR_WORDS = [
    "maintenance",
    "temporarily unavailable",
    "unavailable",
    "server error",
    "bad gateway",
    "gateway timeout",
    "timeout",
    "connection",
    "network",
]

NO_ROTATE_ERROR_WORDS = [
    "quota",
    "rate",
    "limit",
    "too many",
    "request limit",
    "subscription",
    "plan",
    "token",
    "key",
    "auth",
    "unauthorized",
    "forbidden",
]


class TechnicalAPIError(RuntimeError):
    pass


class NoRotateAPIError(RuntimeError):
    pass


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


def key_valida(value: Optional[str]) -> bool:
    if not value:
        return False

    value = value.strip()
    return bool(value) and "tu_api_key" not in value.lower() and "aqui" not in value.lower()


def football_api_keys(max_keys: int = 20) -> List[Tuple[str, str]]:
    """
    Orden de lectura:
    FOOTBALL_API_KEY_1
    FOOTBALL_API_KEY_2
    ...
    FOOTBALL_API_KEY_20

    Compatibilidad:
    APIFOOTBALL_KEY
    """
    keys: List[Tuple[str, str]] = []
    seen = set()

    for idx in range(1, max_keys + 1):
        env_name = f"FOOTBALL_API_KEY_{idx}"
        value = os.getenv(env_name, "").strip()

        if not key_valida(value):
            continue

        if value in seen:
            continue

        keys.append((env_name, value))
        seen.add(value)

    fallback = os.getenv("APIFOOTBALL_KEY", "").strip()
    if key_valida(fallback) and fallback not in seen:
        keys.append(("APIFOOTBALL_KEY", fallback))

    return keys


def texto_errores_api(data: Dict[str, Any]) -> str:
    errors = data.get("errors")

    if not errors:
        return ""

    if isinstance(errors, dict):
        return " ".join(str(v) for v in errors.values())

    if isinstance(errors, list):
        return " ".join(str(v) for v in errors)

    return str(errors)


def clasificar_respuesta(status_code: int, data: Optional[Dict[str, Any]] = None) -> None:
    """
    Decide si:
    - Se acepta respuesta.
    - Se permite failover técnico.
    - Se bloquea rotación por auth/cuota/rate limit.
    """
    if status_code in FAILOVER_STATUS_CODES:
        raise TechnicalAPIError(f"HTTP técnico {status_code}")

    if status_code in NO_ROTATE_STATUS_CODES:
        raise NoRotateAPIError(
            f"HTTP {status_code}. No se rota llave por auth/cuota/rate limit."
        )

    if status_code < 200 or status_code >= 300:
        raise NoRotateAPIError(f"HTTP no exitoso {status_code}. No se rota por seguridad.")

    if not data:
        return

    error_text = texto_errores_api(data).lower().strip()
    if not error_text:
        return

    if any(word in error_text for word in NO_ROTATE_ERROR_WORDS):
        raise NoRotateAPIError(
            f"API-Football devolvió error de cuota/auth/plan/rate limit: {error_text}"
        )

    if any(word in error_text for word in TECHNICAL_ERROR_WORDS):
        raise TechnicalAPIError(f"API-Football devolvió falla técnica: {error_text}")

    raise NoRotateAPIError(f"API-Football devolvió error no técnico: {error_text}")


def api_get_con_key(
    path: str,
    params: Dict[str, Any],
    label: str,
    api_key: str,
    timeout: int = 30,
) -> Dict[str, Any]:
    url = f"{API_BASE}{path}"

    response = requests.get(
        url,
        headers={"x-apisports-key": api_key},
        params=params,
        timeout=timeout,
    )

    try:
        data = response.json()
    except ValueError:
        data = None

    clasificar_respuesta(response.status_code, data)

    if not isinstance(data, dict):
        raise TechnicalAPIError("Respuesta JSON inválida o vacía de API-Football.")

    return data


def api_get_failover(path: str, params: Dict[str, Any], keys: List[Tuple[str, str]]) -> Dict[str, Any]:
    last_error: Optional[BaseException] = None

    for idx, (label, api_key) in enumerate(keys):
        try:
            print(f"⚽ API-Football: intentando llave {label}...")
            data = api_get_con_key(path=path, params=params, label=label, api_key=api_key)
            print(f"✅ API-Football: respuesta exitosa con {label}.")
            return data

        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = exc
            print(f"⚠️ Falla técnica de red con {label}: {type(exc).__name__}")

            if idx < len(keys) - 1:
                print("Servidor principal no responde, conectando a nodo de respaldo")
                continue

            raise TechnicalAPIError("API-Football no respondió y no hay más llaves backup.") from exc

        except TechnicalAPIError as exc:
            last_error = exc
            print(f"⚠️ Falla técnica API-Football con {label}: {exc}")

            if idx < len(keys) - 1:
                print("Servidor principal no responde, conectando a nodo de respaldo")
                continue

            raise TechnicalAPIError("API-Football falló técnicamente y no hay más llaves backup.") from exc

        except NoRotateAPIError as exc:
            print(f"⛔ {exc}")
            print("➡️ No se intenta backup porque no es falla técnica.")
            raise

    raise TechnicalAPIError("No se pudo consultar API-Football con ninguna llave.") from last_error


def limpiar_fixture(item: Dict[str, Any]) -> Dict[str, Any]:
    fixture = item.get("fixture") or {}
    league = item.get("league") or {}
    teams = item.get("teams") or {}
    goals = item.get("goals") or {}

    home = teams.get("home") or {}
    away = teams.get("away") or {}

    return {
        "fixture_id": fixture.get("id"),
        "date": fixture.get("date"),
        "timezone": fixture.get("timezone"),
        "status": (fixture.get("status") or {}).get("short"),
        "league_id": league.get("id"),
        "league_name": league.get("name"),
        "season": league.get("season"),
        "round": league.get("round"),
        "home_team_id": home.get("id"),
        "home_team": home.get("name"),
        "away_team_id": away.get("id"),
        "away_team": away.get("name"),
        "home_goals": goals.get("home"),
        "away_goals": goals.get("away"),
    }


def limpiar_injury(item: Dict[str, Any]) -> Dict[str, Any]:
    fixture = item.get("fixture") or {}
    team = item.get("team") or {}
    player = item.get("player") or {}
    league = item.get("league") or {}

    return {
        "fixture_id": fixture.get("id"),
        "fixture_date": fixture.get("date"),
        "league_id": league.get("id"),
        "season": league.get("season"),
        "team_id": team.get("id"),
        "team": team.get("name"),
        "player_id": player.get("id"),
        "player": player.get("name"),
        "type": item.get("type"),
        "reason": item.get("reason"),
    }


def limpiar_lineup(item: Dict[str, Any]) -> Dict[str, Any]:
    team = item.get("team") or {}
    coach = item.get("coach") or {}

    start_xi = []
    for row in item.get("startXI") or []:
        player = row.get("player") or {}
        start_xi.append(
            {
                "id": player.get("id"),
                "name": player.get("name"),
                "number": player.get("number"),
                "pos": player.get("pos"),
                "grid": player.get("grid"),
            }
        )

    substitutes = []
    for row in item.get("substitutes") or []:
        player = row.get("player") or {}
        substitutes.append(
            {
                "id": player.get("id"),
                "name": player.get("name"),
                "number": player.get("number"),
                "pos": player.get("pos"),
            }
        )

    return {
        "team_id": team.get("id"),
        "team": team.get("name"),
        "formation": item.get("formation"),
        "coach": coach.get("name"),
        "start_xi": start_xi,
        "substitutes": substitutes,
    }


def obtener_datos_ligamx() -> Dict[str, Any]:
    leer_env_si_existe()

    keys = football_api_keys()
    if not keys:
        raise RuntimeError(
            "Faltan FOOTBALL_API_KEY_1/FOOTBALL_API_KEY_2 o APIFOOTBALL_KEY en .env"
        )

    league_id = os.getenv("FOOTBALL_LIGAMX_LEAGUE_ID", DEFAULT_LEAGUE_ID).strip()
    season = os.getenv("FOOTBALL_LIGAMX_SEASON", DEFAULT_SEASON).strip()
    max_lineups = int(os.getenv("FOOTBALL_LINEUPS_MAX_FIXTURES", "9"))

    print("🧾 API-Football Liga MX — alineaciones y lesiones")
    print(f"🏷️ League ID: {league_id}")
    print(f"📅 Season: {season}")
    print(f"🔐 Llaves detectadas: {[label for label, _ in keys]}")
    print("⚠️ No se imprimen API keys.")

    fixtures_data = api_get_failover(
        "/fixtures",
        {"league": league_id, "season": season},
        keys,
    )

    fixtures_raw = fixtures_data.get("response") or []
    fixtures = [limpiar_fixture(item) for item in fixtures_raw if isinstance(item, dict)]

    injuries_data = api_get_failover(
        "/injuries",
        {"league": league_id, "season": season},
        keys,
    )

    injuries_raw = injuries_data.get("response") or []
    injuries = [limpiar_injury(item) for item in injuries_raw if isinstance(item, dict)]

    lineups_by_fixture: Dict[str, Any] = {}
    fixture_ids = [
        f.get("fixture_id")
        for f in fixtures
        if f.get("fixture_id") is not None
    ]

    for fixture_id in fixture_ids[:max_lineups]:
        try:
            lineup_data = api_get_failover(
                "/fixtures/lineups",
                {"fixture": fixture_id},
                keys,
            )
            lineup_raw = lineup_data.get("response") or []
            lineups_by_fixture[str(fixture_id)] = [
                limpiar_lineup(item) for item in lineup_raw if isinstance(item, dict)
            ]
            print(f"✅ Lineups fixture {fixture_id}: {len(lineups_by_fixture[str(fixture_id)])}")

        except NoRotateAPIError as exc:
            lineups_by_fixture[str(fixture_id)] = {
                "error": str(exc),
                "nota": "No se rota llave por cuota/auth/rate limit o error no técnico.",
            }
            print(f"⛔ Fixture {fixture_id}: {exc}")

        except TechnicalAPIError as exc:
            lineups_by_fixture[str(fixture_id)] = {
                "error": str(exc),
                "nota": "Falló técnicamente incluso con backups.",
            }
            print(f"⚠️ Fixture {fixture_id}: {exc}")

    snapshot = {
        "fuente": "API-Football",
        "base_url": API_BASE,
        "uso": "alineaciones_lesiones_ligamx",
        "nota": "No decide picks Survivor. Solo aporta lesiones/alineaciones si API-Football las publica.",
        "generado_en": datetime.now(timezone.utc).isoformat(),
        "league_id": league_id,
        "season": season,
        "keys_detectadas": [label for label, _ in keys],
        "fixtures_count": len(fixtures),
        "injuries_count": len(injuries),
        "lineups_fixture_count": len(lineups_by_fixture),
        "fixtures": fixtures,
        "injuries": injuries,
        "lineups_by_fixture": lineups_by_fixture,
    }

    return snapshot


def guardar_snapshot(snapshot: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    REPORTS_DIR.mkdir(exist_ok=True)

    json_path = DATA_DIR / "alineaciones_ligamx.json"
    report_path = REPORTS_DIR / "alineaciones_ligamx_ultimo.txt"

    json_path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    lines: List[str] = []
    lines.append("🧾 API-Football Liga MX — Alineaciones / Lesiones")
    lines.append("=" * 64)
    lines.append(f"Generado en: {snapshot.get('generado_en')}")
    lines.append(f"League ID: {snapshot.get('league_id')}")
    lines.append(f"Season: {snapshot.get('season')}")
    lines.append(f"Llaves detectadas: {', '.join(snapshot.get('keys_detectadas') or [])}")
    lines.append("")
    lines.append("Estado:")
    lines.append(f"- Fixtures: {snapshot.get('fixtures_count')}")
    lines.append(f"- Lesiones/suspensiones: {snapshot.get('injuries_count')}")
    lines.append(f"- Fixtures revisados para lineups: {snapshot.get('lineups_fixture_count')}")
    lines.append("")
    lines.append("⚠️ Uso operativo:")
    lines.append("- NO decide picks Survivor.")
    lines.append("- NO reemplaza data/jornadas.json.")
    lines.append("- Sirve para detectar alineaciones/lesiones si API-Football ya las publica.")
    lines.append("- No rota por 401/403/429/cuota/rate limit.")
    lines.append("")

    lines.append("Fixtures detectados:")
    for fixture in (snapshot.get("fixtures") or [])[:30]:
        lines.append(
            f"- {fixture.get('fixture_id')} | {fixture.get('date')} | "
            f"{fixture.get('home_team')} vs {fixture.get('away_team')} | "
            f"status={fixture.get('status')}"
        )

    lines.append("")
    lines.append("Lesiones/suspensiones detectadas:")
    injuries = snapshot.get("injuries") or []
    if not injuries:
        lines.append("- Sin lesiones/suspensiones devueltas por API-Football.")
    else:
        for injury in injuries[:50]:
            lines.append(
                f"- {injury.get('team')} | {injury.get('player')} | "
                f"{injury.get('type') or ''} | {injury.get('reason') or ''}"
            )

    lines.append("")
    lines.append("Lineups detectados:")
    lineups = snapshot.get("lineups_by_fixture") or {}
    if not lineups:
        lines.append("- Sin lineups consultados.")
    else:
        for fixture_id, rows in list(lineups.items())[:30]:
            if isinstance(rows, list):
                lines.append(f"- Fixture {fixture_id}: {len(rows)} equipo(s) con lineup.")
            else:
                lines.append(f"- Fixture {fixture_id}: {rows.get('nota')}")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"✅ JSON guardado: {json_path}")
    print(f"✅ Reporte guardado: {report_path}")


def guardar_reporte_no_disponible(exc: Exception) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    REPORTS_DIR.mkdir(exist_ok=True)

    snapshot = {
        "fuente": "API-Football",
        "uso": "alineaciones_lesiones_ligamx",
        "estado": "NO_DISPONIBLE_PLAN_O_CUOTA",
        "nota": "No se rota llave porque no es falla técnica. No decide picks Survivor.",
        "generado_en": datetime.now(timezone.utc).isoformat(),
        "league_id": os.getenv("FOOTBALL_LIGAMX_LEAGUE_ID", DEFAULT_LEAGUE_ID).strip(),
        "season": os.getenv("FOOTBALL_LIGAMX_SEASON", DEFAULT_SEASON).strip(),
        "error_tipo": type(exc).__name__,
        "error_mensaje": str(exc),
        "fixtures_count": 0,
        "injuries_count": 0,
        "lineups_fixture_count": 0,
        "fixtures": [],
        "injuries": [],
        "lineups_by_fixture": {},
    }

    json_path = DATA_DIR / "alineaciones_ligamx.json"
    report_path = REPORTS_DIR / "alineaciones_ligamx_ultimo.txt"

    json_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "🧾 API-Football Liga MX — Alineaciones / Lesiones",
        "=" * 64,
        f"Generado en: {snapshot['generado_en']}",
        f"League ID: {snapshot['league_id']}",
        f"Season: {snapshot['season']}",
        "",
        "Estado: NO DISPONIBLE EN PLAN/CUOTA ACTUAL",
        "",
        f"Error: {snapshot['error_mensaje']}",
        "",
        "⚠️ Lectura operativa:",
        "- No es falla técnica de red.",
        "- No se rota llave porque no es Timeout/ConnectionError/5xx.",
        "- El plan actual no permite consultar esa temporada o endpoint.",
        "- No decide picks Survivor.",
        "- El bot debe mantener ESPERAR / NO ENVIAR si faltan datos críticos.",
        "",
    ]

    report_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"✅ JSON de estado guardado: {json_path}")
    print(f"✅ Reporte de estado guardado: {report_path}")


def main() -> int:
    try:
        snapshot = obtener_datos_ligamx()
        guardar_snapshot(snapshot)

        print("")
        print("✅ Alineaciones/lesiones API-Football listo.")
        print("➡️ No reemplazó jornadas ni picks.")
        return 0

    except NoRotateAPIError as exc:
        print(f"⛔ API-Football no disponible por plan/cuota/auth: {exc}")
        guardar_reporte_no_disponible(exc)
        print("➡️ Se generó reporte y se continúa sin romper el bot.")
        return 0

    except Exception as exc:
        print(f"❌ Error en alineaciones API-Football: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
