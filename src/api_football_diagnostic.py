#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_JSON = BASE_DIR / "data" / "api_football_diagnostic_ultimo.json"
OUTPUT_REPORT = BASE_DIR / "reports" / "api_football_diagnostic_ultimo.txt"

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
            "User-Agent": "survivor-ligamx-bot/api-football-diagnostic",
        },
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read().decode("utf-8")

    data = json.loads(raw)
    if not isinstance(data, dict):
        raise RuntimeError(f"Respuesta inesperada: {data}")

    return data


def maybe_budget(units: int) -> bool:
    if budget_can_call is None:
        return True

    permitido, mensaje = budget_can_call("api_football", units=units, min_interval_minutes=0)
    print(("✅ " if permitido else "⏸️ ") + mensaje)

    if not permitido:
        if budget_write_report is not None:
            budget_write_report()
        return False

    return True


def record(units: int, note: str) -> None:
    if budget_record_call is not None:
        budget_record_call("api_football", units=units, note=note)
    if budget_write_report is not None:
        budget_write_report()


def resumir_response(nombre: str, params: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    response = data.get("response", [])
    errors = data.get("errors", {})
    paging = data.get("paging", {})
    results = data.get("results")

    ligas = []
    if isinstance(response, list):
        for item in response[:20]:
            if not isinstance(item, dict):
                continue
            league = item.get("league", {})
            country = item.get("country", {})
            seasons = item.get("seasons", [])

            ligas.append(
                {
                    "league_id": league.get("id") if isinstance(league, dict) else None,
                    "name": league.get("name") if isinstance(league, dict) else None,
                    "type": league.get("type") if isinstance(league, dict) else None,
                    "country": country.get("name") if isinstance(country, dict) else None,
                    "seasons": [
                        s.get("year") for s in seasons if isinstance(s, dict)
                    ][:10] if isinstance(seasons, list) else [],
                }
            )

    return {
        "nombre": nombre,
        "params": params,
        "results": results,
        "errors": errors,
        "paging": paging,
        "ligas": ligas,
    }


def diagnosticar() -> Dict[str, Any]:
    leer_env_si_existe()

    tests = [
        ("leagues_country_mexico_no_season", {"country": "Mexico"}),
        ("leagues_country_mexico_2026", {"country": "Mexico", "season": 2026}),
        ("leagues_country_mexico_2025", {"country": "Mexico", "season": 2025}),
        ("leagues_country_mexico_2024", {"country": "Mexico", "season": 2024}),
        ("leagues_search_liga_mx", {"search": "Liga MX"}),
        ("leagues_name_liga_mx", {"name": "Liga MX"}),
    ]

    # Cada test es 1 request.
    if not maybe_budget(len(tests)):
        return {
            "generado_en": datetime.now().isoformat(timespec="seconds"),
            "error": "Bloqueado por presupuesto API-Football.",
            "tests": [],
        }

    resultados = []
    llamadas = 0

    for nombre, params in tests:
        try:
            data = api_get("/leagues", params)
            llamadas += 1
            resultados.append(resumir_response(nombre, params, data))
        except Exception as exc:
            llamadas += 1
            resultados.append(
                {
                    "nombre": nombre,
                    "params": params,
                    "error": str(exc),
                    "ligas": [],
                }
            )

    record(llamadas, f"api_football_diagnostic tests={llamadas}")

    ligas_encontradas = []
    for r in resultados:
        for liga in r.get("ligas", []):
            name = str(liga.get("name", "")).lower()
            if "liga mx" in name or "primera" in name:
                ligas_encontradas.append(liga)

    if ligas_encontradas:
        conclusion = "API-Football sí devolvió Liga MX en alguno de los filtros. Usaremos el league_id detectado."
    else:
        conclusion = "API-Football no devolvió Liga MX con los filtros probados. Puede ser restricción del plan, temporada aún no publicada o cobertura no activa para tu cuenta."

    return {
        "generado_en": datetime.now().isoformat(timespec="seconds"),
        "tests": resultados,
        "ligas_encontradas": ligas_encontradas,
        "conclusion": conclusion,
    }


def escribir_report(resultado: Dict[str, Any]) -> None:
    OUTPUT_REPORT.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append("API-FOOTBALL DIAGNOSTIC")
    lines.append("-" * 70)
    lines.append(f"Generado: {resultado.get('generado_en')}")
    lines.append("")

    if resultado.get("error"):
        lines.append(f"ERROR: {resultado['error']}")
        lines.append("")

    for test in resultado.get("tests", []):
        lines.append(f"TEST: {test.get('nombre')}")
        lines.append(f"Params: {test.get('params')}")
        lines.append(f"Results: {test.get('results')}")
        if test.get("errors"):
            lines.append(f"Errors: {test.get('errors')}")
        if test.get("error"):
            lines.append(f"Error: {test.get('error')}")

        ligas = test.get("ligas", [])
        if ligas:
            lines.append("Ligas:")
            for liga in ligas:
                lines.append(
                    f"- id={liga.get('league_id')} | {liga.get('name')} | "
                    f"type={liga.get('type')} | country={liga.get('country')} | "
                    f"seasons={liga.get('seasons')}"
                )
        else:
            lines.append("Ligas: ninguna")
        lines.append("")

    lines.append("Ligas Liga MX/Primera encontradas:")
    if resultado.get("ligas_encontradas"):
        for liga in resultado["ligas_encontradas"]:
            lines.append(f"- id={liga.get('league_id')} | {liga.get('name')} | seasons={liga.get('seasons')}")
    else:
        lines.append("- Ninguna")

    lines.append("")
    lines.append("Conclusión:")
    lines.append(str(resultado.get("conclusion", "")))

    OUTPUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    resultado = diagnosticar()

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    escribir_report(resultado)

    print("🧪 API-FOOTBALL DIAGNOSTIC")
    print("=" * 70)
    print(resultado.get("conclusion", "Sin conclusión."))
    print(f"✅ Reporte: {OUTPUT_REPORT}")
    print(f"✅ JSON: {OUTPUT_JSON}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
