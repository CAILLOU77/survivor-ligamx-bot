#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Tuple


BASE_DIR = Path(__file__).resolve().parents[1]
STATE_PATH = BASE_DIR / "data" / "api_budget_state.json"
REPORT_PATH = BASE_DIR / "reports" / "api_budget_ultimo.txt"


API_CONFIG = {
    "the_odds_api": {
        "label": "The Odds API",
        "limit": 500,
        "period": "month",
        "unit": "créditos aprox.",
        "hard_stop_pct": 98,
    },
    "api_football": {
        "label": "API-Football",
        "limit": 100,
        "period": "day",
        "unit": "requests",
        "hard_stop_pct": 95,
    },
    "open_meteo": {
        "label": "Open-Meteo",
        "limit": 10000,
        "period": "day",
        "unit": "requests",
        "hard_stop_pct": 95,
    },
    "google_news_rss": {
        "label": "Google News RSS",
        "limit": 200,
        "period": "day",
        "unit": "búsquedas internas",
        "hard_stop_pct": 95,
    },
    "groq": {
        "label": "Groq IA",
        "limit": 60,
        "period": "day",
        "unit": "llamadas IA estimadas",
        "hard_stop_pct": 90,
    },
}


def now() -> datetime:
    return datetime.now()


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def period_id(period: str, dt: datetime | None = None) -> str:
    dt = dt or now()

    if period == "month":
        return dt.strftime("%Y-%m")

    if period == "day":
        return dt.strftime("%Y-%m-%d")

    return "lifetime"


def cargar_state() -> Dict[str, Any]:
    if not STATE_PATH.exists():
        return {"apis": {}, "history": []}

    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("apis", {})
            data.setdefault("history", [])
            return data
    except Exception:
        pass

    return {"apis": {}, "history": []}


def guardar_state(state: Dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def get_config(api_name: str) -> Dict[str, Any]:
    return API_CONFIG.get(
        api_name,
        {
            "label": api_name,
            "limit": 999999,
            "period": "day",
            "unit": "requests",
            "hard_stop_pct": 95,
        },
    )


def asegurar_api(state: Dict[str, Any], api_name: str) -> Dict[str, Any]:
    cfg = get_config(api_name)
    current_period = period_id(cfg["period"])

    api = state["apis"].setdefault(
        api_name,
        {
            "period": cfg["period"],
            "period_id": current_period,
            "used": 0,
            "last_call_at": None,
            "last_note": "",
        },
    )

    if api.get("period_id") != current_period:
        api["period"] = cfg["period"]
        api["period_id"] = current_period
        api["used"] = 0
        api["last_call_at"] = None
        api["last_note"] = ""

    return api


def can_call(api_name: str, units: int = 1, min_interval_minutes: int = 0) -> Tuple[bool, str]:
    state = cargar_state()
    cfg = get_config(api_name)
    api = asegurar_api(state, api_name)

    limit = int(cfg["limit"])
    hard_stop_at = max(1, int(limit * float(cfg.get("hard_stop_pct", 100)) / 100))
    used = int(api.get("used", 0))

    if used + units > hard_stop_at:
        guardar_state(state)
        return (
            False,
            f"{cfg['label']}: bloqueado por presupuesto. Usado {used}/{limit}; hard stop {hard_stop_at}.",
        )

    last_call_at = api.get("last_call_at")

    if min_interval_minutes and last_call_at:
        try:
            last_dt = datetime.fromisoformat(last_call_at)
            next_allowed = last_dt + timedelta(minutes=min_interval_minutes)

            if now() < next_allowed:
                guardar_state(state)
                return (
                    False,
                    f"{cfg['label']}: cooldown activo hasta {iso(next_allowed)}. Usado {used}/{limit}.",
                )
        except Exception:
            pass

    guardar_state(state)
    return True, f"{cfg['label']}: permitido. Usado {used}/{limit}."


def record_call(api_name: str, units: int = 1, note: str = "") -> None:
    state = cargar_state()
    cfg = get_config(api_name)
    api = asegurar_api(state, api_name)

    api["used"] = int(api.get("used", 0)) + int(units)
    api["last_call_at"] = iso(now())
    api["last_note"] = note

    history = state.setdefault("history", [])
    history.append(
        {
            "time": iso(now()),
            "api": api_name,
            "label": cfg["label"],
            "units": units,
            "note": note,
            "period_id": api["period_id"],
            "used_after": api["used"],
        }
    )

    state["history"] = history[-100:]
    guardar_state(state)


def status_rows() -> list[Dict[str, Any]]:
    state = cargar_state()
    rows = []

    for api_name in API_CONFIG:
        cfg = get_config(api_name)
        api = asegurar_api(state, api_name)
        used = int(api.get("used", 0))
        limit = int(cfg["limit"])
        pct = round((used / limit) * 100, 1) if limit else 0.0
        hard_stop_at = max(1, int(limit * float(cfg.get("hard_stop_pct", 100)) / 100))

        if used >= hard_stop_at:
            estado = "BLOQUEADO"
        elif pct >= 80:
            estado = "ALTO"
        else:
            estado = "OK"

        rows.append(
            {
                "api": api_name,
                "label": cfg["label"],
                "used": used,
                "limit": limit,
                "pct": pct,
                "period": cfg["period"],
                "period_id": api["period_id"],
                "unit": cfg["unit"],
                "hard_stop_at": hard_stop_at,
                "estado": estado,
                "last_call_at": api.get("last_call_at"),
                "last_note": api.get("last_note", ""),
            }
        )

    guardar_state(state)
    return rows


def write_report() -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows = status_rows()

    lines = []
    lines.append("API BUDGET MANAGER")
    lines.append("-" * 60)
    lines.append(f"Generado: {iso(now())}")
    lines.append("")

    for row in rows:
        lines.append(
            f"{row['label']}: {row['used']}/{row['limit']} {row['unit']} "
            f"({row['pct']}%) | periodo={row['period_id']} | estado={row['estado']}"
        )

        if row.get("last_call_at"):
            lines.append(f"  Última llamada: {row['last_call_at']}")

        if row.get("last_note"):
            lines.append(f"  Nota: {row['last_note']}")

    lines.append("")
    lines.append("Regla del bot:")
    lines.append("- Si una API está bloqueada o en cooldown, usar cache local si existe.")
    lines.append("- Si falta dato crítico, decisión final = ESPERAR / NO ENVIAR.")
    lines.append("- Nunca inventar momios, lesiones, clima ni calendario.")

    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def print_status() -> None:
    write_report()
    print("📊 API BUDGET MANAGER")
    print("=" * 60)

    for row in status_rows():
        print(
            f"{row['label']}: {row['used']}/{row['limit']} "
            f"({row['pct']}%) | {row['estado']} | periodo {row['period_id']}"
        )

    print(f"✅ Reporte: {REPORT_PATH}")


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"

    if cmd in {"report", "status"}:
        print_status()
        return 0

    if cmd == "record":
        if len(sys.argv) < 3:
            raise SystemExit("Uso: python3 src/api_budget.py record <api_name> [units] [note]")

        api_name = sys.argv[2]
        units = int(sys.argv[3]) if len(sys.argv) >= 4 else 1
        note = " ".join(sys.argv[4:]) if len(sys.argv) >= 5 else ""
        record_call(api_name, units=units, note=note)
        print_status()
        return 0

    raise SystemExit(f"Comando no reconocido: {cmd}")


if __name__ == "__main__":
    raise SystemExit(main())
