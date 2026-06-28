#!/usr/bin/env python3
"""
import_calendario.py — Construye data/calendario.json para el planificador.

Toma los fixtures PROGRAMADOS de ESPN (cuando ya publicaron el calendario del
torneo) y los agrupa en jornadas (por fin de semana ISO), produciendo el
esquema que consume src/planificador_survivor.py:

    [{"jornada": 1, "partidos": [{"home_team","away_team"}, ...]}, ...]

NO hace scraping (usa la API pública JSON de ESPN), NO toca picks, NO envía
Telegram. Solo escribe data/calendario.json para uso del planificador.

Uso:
    python3 scripts/import_calendario.py            # baja de ESPN y escribe
    python3 scripts/import_calendario.py --dias 170 # ventana hacia adelante
    python3 scripts/import_calendario.py --dry-run  # muestra, no escribe
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

BASE_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

CALENDARIO_PATH = BASE_DIR / "data" / "calendario.json"


def _semana_iso(fecha: Any) -> str:
    """'YYYY-Www' (año-semana ISO) para agrupar partidos del mismo fin de semana."""
    from datetime import date
    s = str(fecha or "")[:10]
    try:
        y, m, d = s.split("-")
        iso = date(int(y), int(m), int(d)).isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    except (ValueError, TypeError):
        return ""


def construir_calendario(fixtures: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Agrupa fixtures (con `fecha`, `home_team`, `away_team`) por semana ISO y
    numera las jornadas 1..N en orden cronológico. Función pura (sin red).
    """
    grupos: Dict[str, List[Dict[str, Any]]] = {}
    for fx in fixtures:
        semana = _semana_iso(fx.get("fecha"))
        if not semana or not fx.get("home_team") or not fx.get("away_team"):
            continue
        grupos.setdefault(semana, []).append(
            {"home_team": fx["home_team"], "away_team": fx["away_team"]}
        )
    calendario: List[Dict[str, Any]] = []
    for i, semana in enumerate(sorted(grupos), start=1):
        calendario.append({"jornada": i, "semana_iso": semana, "partidos": grupos[semana]})
    return calendario


def main() -> int:
    parser = argparse.ArgumentParser(description="Construye data/calendario.json desde ESPN.")
    parser.add_argument("--dias", type=int, default=160, help="Ventana hacia adelante (días).")
    parser.add_argument("--dry-run", action="store_true", help="Muestra sin escribir.")
    parser.add_argument("--output", default=str(CALENDARIO_PATH))
    args = parser.parse_args()

    import espn_data  # noqa: E402

    print(f"📥 Bajando fixtures programados de ESPN (próximos {args.dias} días)...")
    try:
        fixtures = espn_data.obtener_fixtures_futuros(args.dias)
    except Exception as exc:  # pragma: no cover - error de red
        print(f"⚠️  No se pudo consultar ESPN: {exc}")
        return 1

    calendario = construir_calendario(fixtures)
    total_partidos = sum(len(j["partidos"]) for j in calendario)
    print(f"✅ {len(calendario)} jornadas, {total_partidos} partidos.")
    if not calendario:
        print("   (ESPN aún no publica el calendario del torneo, o no hay fixtures "
              "en la ventana. Reintenta cerca del arranque, ~17-jul.)")
        return 0
    for j in calendario:
        print(f"  J{j['jornada']:>2} ({j.get('semana_iso')}): {len(j['partidos'])} partidos")

    if args.dry_run:
        print("(dry-run: no se escribió nada)")
        return 0

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(calendario, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"📝 Calendario escrito en {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
