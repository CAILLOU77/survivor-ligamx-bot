#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_JSON = BASE_DIR / "data" / "odds_api_diagnostic_ultimo.json"
OUTPUT_TXT = BASE_DIR / "reports" / "odds_api_diagnostic_ultimo.txt"

DEFAULT_SPORT = os.getenv("ODDS_SPORT", "soccer_mexico_ligamx")
REGIONS = os.getenv("ODDS_REGIONS", "us,eu")
MARKETS = os.getenv("ODDS_MARKETS", "h2h,totals")
ODDS_FORMAT = os.getenv("ODDS_FORMAT", "decimal")


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


def get_json(url: str) -> Tuple[Any, Dict[str, str]]:
    req = urllib.request.Request(url, headers={"User-Agent": "survivor-ligamx-bot/diagnostic"})

    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read().decode("utf-8")
        headers = {k.lower(): v for k, v in response.headers.items()}

    return json.loads(raw), headers


def api_url(path: str, params: Dict[str, str]) -> str:
    api_key = os.getenv("ODDS_API_KEY", "").strip()

    if not api_key:
        raise RuntimeError("Falta ODDS_API_KEY en .env")

    params = dict(params)
    params["apiKey"] = api_key

    return "https://api.the-odds-api.com/v4" + path + "?" + urllib.parse.urlencode(params)


def safe_url(path: str, params: Dict[str, str]) -> str:
    params = dict(params)
    params["apiKey"] = "***OCULTO***"
    return "https://api.the-odds-api.com/v4" + path + "?" + urllib.parse.urlencode(params)


def listar_sports() -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    url = api_url("/sports/", {})
    data, headers = get_json(url)

    if not isinstance(data, list):
        raise RuntimeError(f"Respuesta inesperada en /sports: {data}")

    return data, headers


def buscar_candidatos_ligamx(sports: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    candidatos = []

    palabras = ["mexico", "liga mx", "ligamx", "mx", "mexican"]

    for sport in sports:
        key = str(sport.get("key", "")).lower()
        title = str(sport.get("title", "")).lower()
        desc = str(sport.get("description", "")).lower()
        group = str(sport.get("group", "")).lower()

        blob = " ".join([key, title, desc, group])

        if "soccer" in group or "soccer" in key or "football" in group:
            if any(p in blob for p in palabras):
                candidatos.append(sport)

    return candidatos


def probar_odds(sport_key: str, markets: str) -> Dict[str, Any]:
    params = {
        "regions": REGIONS,
        "markets": markets,
        "oddsFormat": ODDS_FORMAT,
    }

    url = api_url(f"/sports/{sport_key}/odds/", params)
    data, headers = get_json(url)

    if not isinstance(data, list):
        return {
            "sport_key": sport_key,
            "markets": markets,
            "ok": False,
            "error": f"Respuesta inesperada: {data}",
            "eventos": 0,
            "samples": [],
            "headers": headers,
            "safe_url": safe_url(f"/sports/{sport_key}/odds/", params),
        }

    samples = []
    for event in data[:5]:
        if not isinstance(event, dict):
            continue

        bookmakers = event.get("bookmakers", [])
        market_keys = []

        if isinstance(bookmakers, list):
            for bookmaker in bookmakers[:3]:
                if not isinstance(bookmaker, dict):
                    continue
                for market in bookmaker.get("markets", []) or []:
                    if isinstance(market, dict):
                        market_keys.append(market.get("key"))

        samples.append(
            {
                "id": event.get("id"),
                "home_team": event.get("home_team"),
                "away_team": event.get("away_team"),
                "commence_time": event.get("commence_time"),
                "bookmakers_count": len(bookmakers) if isinstance(bookmakers, list) else 0,
                "market_keys_sample": sorted(set([x for x in market_keys if x])),
            }
        )

    return {
        "sport_key": sport_key,
        "markets": markets,
        "ok": True,
        "eventos": len(data),
        "samples": samples,
        "headers": headers,
        "safe_url": safe_url(f"/sports/{sport_key}/odds/", params),
    }


def diagnosticar() -> Dict[str, Any]:
    leer_env_si_existe()

    resultado: Dict[str, Any] = {
        "generado_en": datetime.now().isoformat(timespec="seconds"),
        "default_sport": DEFAULT_SPORT,
        "regions": REGIONS,
        "markets": MARKETS,
        "odds_format": ODDS_FORMAT,
        "sports_endpoint_ok": False,
        "liga_mx_candidates": [],
        "tests": [],
        "conclusion": "",
    }

    sports, sports_headers = listar_sports()
    resultado["sports_endpoint_ok"] = True
    resultado["sports_count"] = len(sports)
    resultado["sports_headers"] = sports_headers

    candidatos = buscar_candidatos_ligamx(sports)
    resultado["liga_mx_candidates"] = candidatos

    sport_keys = [DEFAULT_SPORT]
    for c in candidatos:
        key = c.get("key")
        if isinstance(key, str) and key not in sport_keys:
            sport_keys.append(key)

    # Si no encuentra candidatos, aun así prueba el default.
    market_tests = [MARKETS, "h2h", "totals", "h2h,totals"]

    vistos = set()

    for sport_key in sport_keys:
        for markets in market_tests:
            combo = (sport_key, markets)
            if combo in vistos:
                continue
            vistos.add(combo)

            try:
                resultado["tests"].append(probar_odds(sport_key, markets))
            except Exception as exc:
                resultado["tests"].append(
                    {
                        "sport_key": sport_key,
                        "markets": markets,
                        "ok": False,
                        "error": str(exc),
                        "eventos": 0,
                    }
                )

    eventos_totales = sum(int(t.get("eventos", 0)) for t in resultado["tests"] if t.get("ok"))

    if not candidatos:
        resultado["conclusion"] = (
            "No encontré un sport key claro de Liga MX en /sports. "
            "Puede que el key default esté mal, que la liga no esté activa, o que tu plan no la liste ahora."
        )
    elif eventos_totales == 0:
        resultado["conclusion"] = (
            "La API respondió, pero no devolvió eventos con los mercados probados. "
            "Probable causa: Liga MX sin mercados abiertos todavía o calendario no publicado en The Odds API."
        )
    else:
        resultado["conclusion"] = (
            "La API sí devolvió eventos. Revisa samples para confirmar nombres de equipos y mercados disponibles."
        )

    return resultado


def escribir_txt(resultado: Dict[str, Any]) -> None:
    OUTPUT_TXT.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append("ODDS API DIAGNOSTIC — SURVIVOR LIGA MX")
    lines.append("-" * 70)
    lines.append(f"Generado: {resultado['generado_en']}")
    lines.append(f"Sport default: {resultado['default_sport']}")
    lines.append(f"Regions: {resultado['regions']}")
    lines.append(f"Markets: {resultado['markets']}")
    lines.append(f"Odds format: {resultado['odds_format']}")
    lines.append("")
    lines.append(f"/sports OK: {resultado['sports_endpoint_ok']}")
    lines.append(f"Sports encontrados: {resultado.get('sports_count', 'N/A')}")
    lines.append("")

    lines.append("Candidatos Liga MX encontrados:")
    candidatos = resultado.get("liga_mx_candidates", [])
    if candidatos:
        for c in candidatos:
            lines.append(
                f"- key={c.get('key')} | title={c.get('title')} | group={c.get('group')} | active={c.get('active')}"
            )
    else:
        lines.append("- Ninguno")

    lines.append("")
    lines.append("Pruebas de odds:")
    for t in resultado.get("tests", []):
        lines.append(
            f"- sport={t.get('sport_key')} | markets={t.get('markets')} | ok={t.get('ok')} | eventos={t.get('eventos')}"
        )

        if t.get("error"):
            lines.append(f"  error: {t.get('error')}")

        headers = t.get("headers", {})
        if isinstance(headers, dict):
            remaining = headers.get("x-requests-remaining")
            used = headers.get("x-requests-used")
            last = headers.get("x-requests-last")
            if remaining or used or last:
                lines.append(f"  usage: remaining={remaining}, used={used}, last={last}")

        samples = t.get("samples", [])
        if samples:
            lines.append("  samples:")
            for s in samples:
                lines.append(
                    f"    - {s.get('home_team')} vs {s.get('away_team')} | "
                    f"{s.get('commence_time')} | books={s.get('bookmakers_count')} | "
                    f"markets={s.get('market_keys_sample')}"
                )

    lines.append("")
    lines.append("Conclusión:")
    lines.append(str(resultado.get("conclusion", "")))
    lines.append("")

    OUTPUT_TXT.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    try:
        resultado = diagnosticar()
    except Exception as exc:
        resultado = {
            "generado_en": datetime.now().isoformat(timespec="seconds"),
            "error": str(exc),
            "conclusion": "Falló el diagnóstico. Revisa ODDS_API_KEY, internet o límite de API.",
        }

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    escribir_txt(resultado)

    print("🧪 ODDS API DIAGNOSTIC")
    print("=" * 70)
    if resultado.get("error"):
        print(f"ERROR: {resultado['error']}")
    print(resultado.get("conclusion", "Sin conclusión."))
    print(f"✅ Reporte: {OUTPUT_TXT}")
    print(f"✅ JSON: {OUTPUT_JSON}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
