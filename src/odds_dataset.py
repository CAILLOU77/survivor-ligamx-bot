#!/usr/bin/env python3
"""
odds_dataset.py — Generador de dataset limpio de momios (Survivor Liga MX).

Construye, desde los momios que el bot baja de The Odds API (data/jornadas.json),
un dataset de series de tiempo con columnas estándar:

    timestamp, id_mercado, momio_1, momio_2, momio_3,
    true_prob_1, true_prob_2, true_prob_3, vig_pct, trend_1, trend_2, trend_3

Convención 1X2:  _1 = local, _2 = empate, _3 = visitante.
- momio_*      : cuota decimal promedio entre casas reales.
- true_prob_*  : probabilidad sin vig (margen de casa eliminado), 0-1.
- vig_pct      : margen de la casa en % (overround).
- trend_*      : dirección del momio vs. snapshot anterior (1=subió, -1=bajó, 0=estable).

Cada corrida agrega una fila por partido (snapshot). El `trend` se calcula
comparando contra el último snapshot del mismo id_mercado en el dataset.

Fuente: SOLO datos ya presentes en data/jornadas.json (The Odds API). Sin red,
sin scraping. NO cierra ni envía picks. Decisión operativa: ESPERAR / NO ENVIAR.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

try:
    from odds_math import probabilidades_sin_vig, margen_casa_pct
    from pronostico_avanzado import (
        cuotas_promedio_1x2, extraer_partidos, nombre_local, nombre_visitante,
    )
except ImportError:  # pragma: no cover
    from src.odds_math import probabilidades_sin_vig, margen_casa_pct
    from src.pronostico_avanzado import (
        cuotas_promedio_1x2, extraer_partidos, nombre_local, nombre_visitante,
    )

BASE_DIR = Path(__file__).resolve().parents[1]
JORNADAS_PATH = BASE_DIR / "data" / "jornadas.json"
DATASET_PATH = BASE_DIR / "data" / "ligamx_odds_clean.csv"

DEC_ESPERAR = "ESPERAR / NO ENVIAR"

CAMPOS = [
    "timestamp", "id_mercado",
    "momio_1", "momio_2", "momio_3",
    "true_prob_1", "true_prob_2", "true_prob_3",
    "vig_pct",
    "trend_1", "trend_2", "trend_3",
]


def _slug(texto: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", str(texto or "").lower()).strip("_")
    return s or "x"


def id_mercado(partido: Dict[str, Any]) -> str:
    """ID estable del mercado: evento_id de The Odds API o fallback equipos."""
    momios = partido.get("momios", {})
    if isinstance(momios, dict) and momios.get("evento_id"):
        return str(momios["evento_id"])
    return f"{_slug(nombre_local(partido))}__{_slug(nombre_visitante(partido))}"


def fila_base(partido: Dict[str, Any], timestamp: str) -> Optional[Dict[str, Any]]:
    """
    Fila del snapshot actual (sin trend). None si no hay mercado real 1X2.
    cuotas_promedio_1x2 devuelve [local, empate, visitante].
    """
    cuotas = cuotas_promedio_1x2(partido)
    if cuotas is None:
        return None
    probs = probabilidades_sin_vig(cuotas)
    return {
        "timestamp": timestamp,
        "id_mercado": id_mercado(partido),
        "momio_1": round(cuotas[0], 3),
        "momio_2": round(cuotas[1], 3),
        "momio_3": round(cuotas[2], 3),
        "true_prob_1": round(probs[0], 4),
        "true_prob_2": round(probs[1], 4),
        "true_prob_3": round(probs[2], 4),
        "vig_pct": margen_casa_pct(cuotas),
        "trend_1": 0, "trend_2": 0, "trend_3": 0,
    }


def calcular_trend(
    momios_actual: Sequence[float],
    momios_previo: Optional[Sequence[float]],
    umbral: float = 0.01,
) -> List[int]:
    """
    Dirección del momio vs. el snapshot anterior:
    1 = subió (> umbral), -1 = bajó (< -umbral), 0 = estable.
    Si no hay previo, todo 0.
    """
    if not momios_previo:
        return [0, 0, 0]
    trends: List[int] = []
    for actual, previo in zip(momios_actual, momios_previo):
        try:
            actual = float(actual); previo = float(previo)
        except (TypeError, ValueError):
            trends.append(0); continue
        if previo <= 0:
            trends.append(0)
        elif actual > previo * (1 + umbral):
            trends.append(1)
        elif actual < previo * (1 - umbral):
            trends.append(-1)
        else:
            trends.append(0)
    return trends


def ultimos_momios_por_id(filas: Sequence[Dict[str, Any]]) -> Dict[str, List[float]]:
    """Último [momio_1,2,3] conocido por id_mercado (según orden del dataset)."""
    ultimos: Dict[str, List[float]] = {}
    for fila in filas:
        try:
            ultimos[str(fila["id_mercado"])] = [
                float(fila["momio_1"]), float(fila["momio_2"]), float(fila["momio_3"])
            ]
        except (KeyError, TypeError, ValueError):
            continue
    return ultimos


def construir_filas(
    partidos: Sequence[Dict[str, Any]],
    timestamp: str,
    previos_por_id: Optional[Dict[str, List[float]]] = None,
) -> List[Dict[str, Any]]:
    """Filas del snapshot actual, con trend calculado vs. previos_por_id."""
    previos_por_id = previos_por_id or {}
    filas: List[Dict[str, Any]] = []
    for p in partidos:
        base = fila_base(p, timestamp)
        if base is None:
            continue
        prev = previos_por_id.get(base["id_mercado"])
        t1, t2, t3 = calcular_trend(
            [base["momio_1"], base["momio_2"], base["momio_3"]], prev
        )
        base["trend_1"], base["trend_2"], base["trend_3"] = t1, t2, t3
        filas.append(base)
    return filas


def leer_dataset(path: Path) -> List[Dict[str, Any]]:
    if not Path(path).exists():
        return []
    with Path(path).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def escribir_dataset(filas: Sequence[Dict[str, Any]], path: Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CAMPOS)
        writer.writeheader()
        for fila in filas:
            writer.writerow({k: fila.get(k, "") for k in CAMPOS})


def main() -> int:
    parser = argparse.ArgumentParser(description="Genera/actualiza el dataset de momios.")
    parser.add_argument("--jornadas", default=str(JORNADAS_PATH))
    parser.add_argument("--dataset", default=str(DATASET_PATH))
    args = parser.parse_args()

    partidos = extraer_partidos(_cargar(Path(args.jornadas)))
    if not partidos:
        print("⚠️ No hay partidos en jornadas.json. Corre src/sync_odds_api.py primero.")
        return 1

    historico = leer_dataset(Path(args.dataset))
    previos = ultimos_momios_por_id(historico)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    nuevas = construir_filas(partidos, timestamp, previos)

    combinado = historico + nuevas
    escribir_dataset(combinado, Path(args.dataset))

    print(f"✅ Snapshot {timestamp}: {len(nuevas)} filas nuevas.")
    print(f"📊 Dataset total: {len(combinado)} filas → {args.dataset}")
    print(f"Decisión: {DEC_ESPERAR}")
    return 0


def _cargar(path: Path) -> Any:
    if not Path(path).exists():
        return []
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return []


if __name__ == "__main__":
    raise SystemExit(main())
