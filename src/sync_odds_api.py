#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from team_normalizer import team_aliases, clean_team_name, teams_match
except ImportError:  # pragma: no cover
    from src.team_normalizer import team_aliases, clean_team_name, teams_match

try:
    from api_budget import can_call as budget_can_call
    from api_budget import record_call as budget_record_call
    from api_budget import write_report as budget_write_report
except Exception:
    budget_can_call = None
    budget_record_call = None
    budget_write_report = None


BASE_DIR = Path(__file__).resolve().parents[1]
JORNADAS_PATH = BASE_DIR / "data" / "jornadas.json"

SPORT = "soccer_mexico_ligamx"
REGIONS = os.getenv("ODDS_REGIONS", "us,eu")
MARKETS = os.getenv("ODDS_MARKETS", "h2h,totals")
ODDS_FORMAT = os.getenv("ODDS_FORMAT", "decimal")


ALIASES = {
    "america": ["america", "club america", "club de futbol america", "américa", "club américa"],
    "juarez": ["juarez", "fc juarez", "juárez", "fc juárez"],
    "chivas": ["chivas", "guadalajara", "cd guadalajara", "chivas guadalajara"],
    "cruz azul": ["cruz azul"],
    "pumas": ["pumas", "pumas unam", "unam"],
    "tigres": ["tigres", "tigres uanl", "uanl"],
    "monterrey": ["monterrey", "rayados", "cf monterrey"],
    "toluca": ["toluca"],
    "tijuana": ["tijuana", "xolos", "club tijuana"],
    "atlas": ["atlas"],
    "leon": ["leon", "león"],
    "pachuca": ["pachuca"],
    "santos": ["santos", "santos laguna"],
    "queretaro": ["queretaro", "querétaro"],
    "puebla": ["puebla"],
    "necaxa": ["necaxa"],
    "mazatlan": ["mazatlan", "mazatlán"],
    "san luis": ["san luis", "atletico san luis", "atlético san luis"],
}


def normalizar(texto: str) -> str:
    texto = clean_team_name(texto)
    for prefijo in ("club ", "cf ", "fc "):
        if texto.startswith(prefijo):
            texto = texto[len(prefijo):].strip()
    return " ".join(texto.split())


def expandir_alias(nombre: str) -> set[str]:
    return team_aliases(nombre)


def equipos_coinciden(a: str, b: str) -> bool:
    return teams_match(a, b)


def cargar_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def guardar_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def extraer_partidos(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [p for p in data if isinstance(p, dict)]

    if isinstance(data, dict) and isinstance(data.get("partidos"), list):
        return [p for p in data["partidos"] if isinstance(p, dict)]

    return []


def nombre_local(partido: Dict[str, Any]) -> str:
    return str(partido.get("home_team") or partido.get("local") or partido.get("equipo_local") or "")


def nombre_visitante(partido: Dict[str, Any]) -> str:
    return str(partido.get("away_team") or partido.get("visitante") or partido.get("equipo_visitante") or "")


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



FAILOVER_STATUS_CODES = {500, 502, 503, 504}
NO_ROTATE_STATUS_CODES = {401, 403, 429}


def key_valida(value: str) -> bool:
    if not value:
        return False

    value = value.strip()
    return bool(value) and "AQUÍ_" not in value and "tu_api_key" not in value.lower()


def odds_api_key_candidates() -> List[tuple[str, str]]:
    primary = os.getenv("ODDS_API_KEY_PRIMARY", "").strip() or os.getenv("ODDS_API_KEY", "").strip()
    backup = os.getenv("ODDS_API_KEY_BACKUP", "").strip()

    keys: List[tuple[str, str]] = []
    seen = set()

    for label, value in [("primary", primary), ("backup", backup)]:
        if not key_valida(value):
            continue

        if value in seen:
            continue

        keys.append((label, value))
        seen.add(value)

    return keys


def build_odds_url(api_key: str) -> str:
    params = {
        "apiKey": api_key,
        "regions": REGIONS,
        "markets": MARKETS,
        "oddsFormat": ODDS_FORMAT,
    }

    return (
        f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds/"
        + "?"
        + urllib.parse.urlencode(params)
    )


def fetch_odds_with_key(label: str, api_key: str) -> List[Dict[str, Any]]:
    url = build_odds_url(api_key)

    with urllib.request.urlopen(url, timeout=30) as response:
        raw = response.read().decode("utf-8")

    data = json.loads(raw)

    if not isinstance(data, list):
        raise RuntimeError(f"Respuesta inesperada de The Odds API usando llave {label}: {data}")

    return data


def fetch_odds() -> List[Dict[str, Any]]:
    import socket
    import urllib.error

    keys = odds_api_key_candidates()

    if not keys:
        raise RuntimeError("Falta ODDS_API_KEY_PRIMARY u ODDS_API_KEY válida en .env")

    last_error: Exception | None = None

    for idx, (label, api_key) in enumerate(keys):
        try:
            print(f"🎰 The Odds API: intentando llave {label}...")
            data = fetch_odds_with_key(label, api_key)
            print(f"✅ The Odds API: conexión exitosa con llave {label}.")
            return data

        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            last_error = exc

            if status in FAILOVER_STATUS_CODES:
                print(f"⚠️ The Odds API error técnico {status} con llave {label}.")
                if idx < len(keys) - 1:
                    print("➡️ Probando llave backup por falla técnica del servidor.")
                    continue

                raise RuntimeError(f"The Odds API sigue con error técnico {status}; no hay más backup.") from exc

            if status in NO_ROTATE_STATUS_CODES:
                raise RuntimeError(
                    f"The Odds API respondió {status}. No se rota llave por auth/cuota/rate limit."
                ) from exc

            raise RuntimeError(f"The Odds API respondió error HTTP {status}. No se rota llave.") from exc

        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            last_error = exc
            print(f"⚠️ Falla técnica de red con The Odds API usando llave {label}: {type(exc).__name__}")

            if idx < len(keys) - 1:
                print("➡️ Probando llave backup por timeout/conexión.")
                continue

            raise RuntimeError("The Odds API no respondió y no hay más backup.") from exc

    raise RuntimeError("No se pudo consultar The Odds API con ninguna llave.") from last_error

def evento_coincide(partido: Dict[str, Any], evento: Dict[str, Any]) -> bool:
    local = nombre_local(partido)
    visitante = nombre_visitante(partido)

    home = str(evento.get("home_team", ""))
    away = str(evento.get("away_team", ""))

    return equipos_coinciden(local, home) and equipos_coinciden(visitante, away)


def normalizar_bookmakers(evento: Dict[str, Any]) -> List[Dict[str, Any]]:
    bookmakers = evento.get("bookmakers", [])

    if not isinstance(bookmakers, list):
        return []

    salida = []

    for bookmaker in bookmakers:
        if not isinstance(bookmaker, dict):
            continue

        markets = bookmaker.get("markets", [])
        if not isinstance(markets, list):
            continue

        mercados_limpios = []

        for market in markets:
            if not isinstance(market, dict):
                continue

            if market.get("key") not in {"h2h", "totals", "btts"}:
                continue

            outcomes = market.get("outcomes", [])
            if not isinstance(outcomes, list) or len(outcomes) < 2:
                continue

            mercados_limpios.append(
                {
                    "key": "h2h",
                    "last_update": market.get("last_update"),
                    "outcomes": outcomes,
                }
            )

        if mercados_limpios:
            salida.append(
                {
                    "key": bookmaker.get("key", "unknown"),
                    "title": bookmaker.get("title", "Unknown bookmaker"),
                    "last_update": bookmaker.get("last_update"),
                    "markets": mercados_limpios,
                }
            )

    return salida


def parsear_commence_time(value: str) -> Tuple[str, str]:
    if not value:
        return "PENDIENTE_CONFIRMAR", "PENDIENTE_CONFIRMAR"

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        dt_local = dt.astimezone()
        return dt_local.strftime("%Y-%m-%d"), dt_local.strftime("%H:%M")
    except Exception:
        return value, "PENDIENTE_CONFIRMAR"


def aplicar_evento(partido: Dict[str, Any], evento: Dict[str, Any]) -> bool:
    bookmakers = normalizar_bookmakers(evento)

    if not bookmakers:
        return False

    fecha, hora = parsear_commence_time(str(evento.get("commence_time", "")))

    partido["home_team"] = nombre_local(partido)
    partido["away_team"] = nombre_visitante(partido)
    partido["local"] = partido["home_team"]
    partido["visitante"] = partido["away_team"]

    if fecha != "PENDIENTE_CONFIRMAR":
        partido["fecha"] = fecha

    if hora != "PENDIENTE_CONFIRMAR":
        partido["hora"] = hora

    partido["bookmakers"] = bookmakers
    partido["momios"] = {
        "estado": "mercado_real_api",
        "fuente": "The Odds API",
        "sport": SPORT,
        "regions": REGIONS,
        "markets": MARKETS,
        "odds_format": ODDS_FORMAT,
        "evento_id": evento.get("id"),
        "home_team_api": evento.get("home_team"),
        "away_team_api": evento.get("away_team"),
        "commence_time_api": evento.get("commence_time"),
        "actualizado_en": datetime.now().isoformat(timespec="seconds"),
    }

    partido["_odds_sync"] = {
        "actualizado_por": "src/sync_odds_api.py",
        "actualizado_en": datetime.now().isoformat(timespec="seconds"),
        "status": "matched",
    }

    return True


def aplicar_fallback_no_api(partido: Dict[str, Any]) -> None:
    """
    Si The Odds API no trae mercado real, limpiamos cualquier momio manual viejo
    para evitar CERRAR falso. Esto deja el partido en estado automático seguro.
    """
    local = nombre_local(partido)
    visitante = nombre_visitante(partido)

    partido["home_team"] = local
    partido["away_team"] = visitante
    partido["local"] = local
    partido["visitante"] = visitante

    partido["momios"] = {
        "estado": "mercado_no_publicado_api",
        "fuente": "The Odds API",
        "sport": SPORT,
        "regions": REGIONS,
        "markets": MARKETS,
        "odds_format": ODDS_FORMAT,
        "actualizado_en": datetime.now().isoformat(timespec="seconds"),
        "nota": "The Odds API no devolvió mercado real para este partido. No usar para CERRAR.",
    }

    partido["bookmakers"] = [
        {
            "key": "fallback_local",
            "title": "Fallback técnico - mercado API no publicado",
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
    ]

    partido["_odds_sync"] = {
        "actualizado_por": "src/sync_odds_api.py",
        "actualizado_en": datetime.now().isoformat(timespec="seconds"),
        "status": "no_api_market",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--force",
        action="store_true",
        help="Salta el cooldown normal, pero respeta el límite mensual del API Budget.",
    )
    args = parser.parse_args()

    leer_env_si_existe()

    if not JORNADAS_PATH.exists():
        raise SystemExit(f"ERROR: No existe {JORNADAS_PATH}")

    data = cargar_json(JORNADAS_PATH, [])
    partidos = extraer_partidos(data)

    if not partidos:
        raise SystemExit("ERROR: No encontré partidos en data/jornadas.json")

    print("🎰 AUTO ODDS SYNC — THE ODDS API")
    print("=" * 60)

    min_interval = int(os.getenv("ODDS_SYNC_MIN_INTERVAL_MINUTES", "360"))

    if args.force:
        print("⚡ FORCE MODE: se salta cooldown normal, pero se respeta límite mensual.")
        min_interval = 0

    if budget_can_call is not None:
        permitido, mensaje_budget = budget_can_call(
            "the_odds_api",
            units=1,
            min_interval_minutes=min_interval,
        )

        if not permitido:
            print(f"⏸️ {mensaje_budget}")
            print("➡️ No se consulta The Odds API en esta corrida para ahorrar saldo.")
            print("➡️ Se mantiene data actual. Real Data Gate decide si puede CERRAR o no.")

            if budget_write_report is not None:
                budget_write_report()

            return 0

        print(f"✅ Budget OK: {mensaje_budget}")

    try:
        eventos = fetch_odds()

        if budget_record_call is not None:
            budget_record_call(
                "the_odds_api",
                units=1,
                note=f"sync_odds_api eventos={len(eventos)} force={args.force}",
            )

        if budget_write_report is not None:
            budget_write_report()

    except Exception as exc:
        print(f"⚠️ No se pudieron traer momios reales: {exc}")
        print("➡️ Se mantiene fallback/local. Real Data Gate debe bloquear CERRAR.")

        if budget_write_report is not None:
            budget_write_report()

        return 0

    print(f"✅ Eventos recibidos desde The Odds API: {len(eventos)}")

    backup = JORNADAS_PATH.with_suffix(
        f".backup-odds-sync-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    )
    backup.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    aplicados = 0
    no_match = []

    for partido in partidos:
        local = nombre_local(partido)
        visitante = nombre_visitante(partido)

        match: Optional[Dict[str, Any]] = None

        for evento in eventos:
            if evento_coincide(partido, evento):
                match = evento
                break

        if match and aplicar_evento(partido, match):
            aplicados += 1
            print(f"✅ Momios reales aplicados: {local} vs {visitante}")
        else:
            aplicar_fallback_no_api(partido)
            no_match.append(f"{local} vs {visitante}")
            print(f"⚠️ Sin mercado real API para: {local} vs {visitante}")

    if isinstance(data, list):
        salida = partidos
    elif isinstance(data, dict):
        data["partidos"] = partidos
        salida = data
    else:
        salida = partidos

    guardar_json(JORNADAS_PATH, salida)

    print("")
    print(f"✅ Partidos con momios reales API: {aplicados}/{len(partidos)}")
    print(f"✅ Backup creado: {backup}")

    if no_match:
        print("⚠️ Partidos sin match API:")
        for item in no_match:
            print(f"   - {item}")
        print("➡️ Esos partidos quedarán bloqueados por Real Data Gate si solo tienen fallback.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
