#!/usr/bin/env python3
"""
import_calendario.py — Construye data/calendario.json para el planificador.

Fuentes (en orden de preferencia):
  1. **Liga MX API** (`src/ligamx_api.py`, `/calendar`) — YA viene agrupada por
     jornada oficial, así que es la fuente preferida y más fiable.
  2. **ESPN** (fallback) — fixtures programados agrupados heurísticamente por
     fin de semana; se usa si la Liga MX API no está disponible o con `--fuente espn`.

Produce el esquema que consume src/planificador_survivor.py:

    [{"jornada": 1, "partidos": [{"home_team","away_team"}, ...]}, ...]

NO hace scraping (usa APIs públicas JSON), NO toca picks, NO envía Telegram.
Solo escribe data/calendario.json para uso del planificador.

Uso:
    python3 scripts/import_calendario.py                 # Liga MX API -> ESPN fallback
    python3 scripts/import_calendario.py --fuente espn   # fuerza ESPN
    python3 scripts/import_calendario.py --fuente ligamx # fuerza Liga MX API
    python3 scripts/import_calendario.py --dias 170      # ventana ESPN hacia adelante
    python3 scripts/import_calendario.py --dry-run       # muestra, no escribe
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


def _calendario_desde_ligamx() -> List[Dict[str, Any]]:
    """
    Calendario desde la Liga MX API. Toma la lista PLANA de partidos (con sus
    fechas reales) y RE-DERIVA las jornadas con `construir_calendario` (regla
    round-robin), en vez de confiar en el campo `jornada` del upstream —que a
    veces agrupa mal (J1=11, J12=18, 16 jornadas). Así se obtienen 17×9 limpias.
    Lanza si la API falla.
    """
    import ligamx_api  # noqa: E402
    fixtures = ligamx_api.fixtures_planos()
    return construir_calendario(fixtures)


def _calendario_desde_espn(dias: int) -> List[Dict[str, Any]]:
    """Calendario desde ESPN (fixtures programados + agrupado heurístico)."""
    import espn_data  # noqa: E402
    fixtures = espn_data.obtener_fixtures_futuros(dias)
    return construir_calendario(fixtures)


def main() -> int:
    parser = argparse.ArgumentParser(description="Construye data/calendario.json.")
    parser.add_argument("--fuente", choices=["auto", "ligamx", "espn"], default="auto",
                        help="Fuente del calendario (auto = Liga MX API con fallback a ESPN).")
    parser.add_argument("--dias", type=int, default=160, help="Ventana ESPN hacia adelante (días).")
    parser.add_argument("--dry-run", action="store_true", help="Muestra sin escribir.")
    parser.add_argument("--output", default=str(CALENDARIO_PATH))
    args = parser.parse_args()

    calendario: List[Dict[str, Any]] = []

    # 1) Liga MX API (preferida): ya viene agrupada por jornada oficial.
    if args.fuente in ("auto", "ligamx"):
        print("📥 Bajando calendario de la Liga MX API (/calendar)...")
        try:
            calendario = _calendario_desde_ligamx()
            if calendario:
                print(f"✅ Liga MX API: {len(calendario)} jornadas.")
        except Exception as exc:  # pragma: no cover - error de red
            print(f"⚠️  Liga MX API no disponible: {exc}")
            if args.fuente == "ligamx":
                return 1

    # 2) ESPN (fallback) si no hubo calendario y no se forzó ligamx.
    if not calendario and args.fuente != "ligamx":
        print(f"📥 Bajando fixtures programados de ESPN (próximos {args.dias} días)...")
        try:
            calendario = _calendario_desde_espn(args.dias)
        except Exception as exc:  # pragma: no cover - error de red
            print(f"⚠️  No se pudo consultar ESPN: {exc}")
            return 1

    total_partidos = sum(len(j["partidos"]) for j in calendario)
    print(f"✅ {len(calendario)} jornadas, {total_partidos} partidos.")
    if not calendario:
        print("   (Ninguna fuente publicó el calendario todavía. Reintenta cerca "
              "del arranque, ~17-jul.)")
        return 0
    for j in calendario:
        print(f"  J{j['jornada']:>2}: {len(j['partidos'])} partidos")

    # Aviso de calidad: Liga MX regular = 17 jornadas de 9 partidos cada una.
    anomalas = [j["jornada"] for j in calendario if len(j["partidos"]) != 9]
    if len(calendario) != 17 or anomalas:
        print("⚠️  El calendario no luce como 17 jornadas × 9 partidos "
              f"({len(calendario)} jornadas; jornadas != 9 partidos: {anomalas}).")
        print("    Puede ser un agrupado imperfecto de la fuente. Revisa antes de "
              "confiar en el plan; alternativa: --fuente espn.")

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
