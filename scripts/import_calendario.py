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
    """'YYYY-Www' (año-semana ISO). Se conserva como referencia/etiqueta."""
    from datetime import date
    s = str(fecha or "")[:10]
    try:
        y, m, d = s.split("-")
        iso = date(int(y), int(m), int(d)).isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    except (ValueError, TypeError):
        return ""


def _a_fecha(fecha: Any):
    """'YYYY-MM-DD' -> date, o None si no parsea."""
    from datetime import date
    s = str(fecha or "")[:10]
    try:
        y, m, d = s.split("-")
        return date(int(y), int(m), int(d))
    except (ValueError, TypeError):
        return None


def construir_calendario(
    fixtures: Sequence[Dict[str, Any]],
    gap_dias: int = 3,
    max_por_jornada: int = 9,
) -> List[Dict[str, Any]]:
    """
    Agrupa fixtures en jornadas y las numera 1..N en orden cronológico.
    Función pura (sin red).

    Una nueva jornada empieza cuando, recorriendo los partidos por fecha:
      - un equipo se REPITE (nadie juega dos veces en la misma jornada), o
      - hay un hueco de fechas mayor a `gap_dias` (cambio de fin de semana), o
      - la jornada ya está llena (`max_por_jornada`, 9 en Liga MX de 18 equipos).

    Esto evita los errores del agrupado por semana ISO (partidos entre semana o
    que cruzan el límite Sáb-Dom-Lun caían en jornadas equivocadas).
    """
    validos = []
    for fx in fixtures:
        f = _a_fecha(fx.get("fecha"))
        if f and fx.get("home_team") and fx.get("away_team"):
            validos.append((f, fx))
    validos.sort(key=lambda t: t[0])

    grupos: List[Dict[str, Any]] = []
    actual: List[Dict[str, str]] = []
    equipos: set = set()
    fecha_prev = None
    for f, fx in validos:
        h, a = fx["home_team"], fx["away_team"]
        repite = h.lower() in equipos or a.lower() in equipos
        hueco = fecha_prev is not None and (f - fecha_prev).days > gap_dias
        lleno = len(actual) >= max_por_jornada
        if actual and (repite or hueco or lleno):
            grupos.append({"partidos": actual, "_equipos": equipos})
            actual, equipos = [], set()
        actual.append({"home_team": h, "away_team": a})
        equipos |= {h.lower(), a.lower()}
        fecha_prev = f
    if actual:
        grupos.append({"partidos": actual, "_equipos": equipos})

    return [{"jornada": i, "partidos": g["partidos"]} for i, g in enumerate(grupos, start=1)]


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
        print(f"  J{j['jornada']:>2}: {len(j['partidos'])} partidos")

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
