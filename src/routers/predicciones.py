#!/usr/bin/env python3
"""
routers/predicciones.py — Endpoints de predicciones REALES (ESPN + Poisson).

Expone en la web las predicciones legítimas basadas en datos reales de ESPN
(vía el motor), en lugar de los momios inventados. Read-only, con caché en
memoria (TTL) para no golpear ESPN en cada request.

- GET /predicciones  -> 1X2 / Over-Under / BTTS / marcador por partido próximo.
- GET /survivor      -> mejor equipo "no perder" de la jornada (excluye usados).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict

from fastapi import APIRouter

try:
    import motor_pronosticos as motor
except ImportError:  # pragma: no cover - contexto de paquete (web)
    from src import motor_pronosticos as motor  # type: ignore

try:
    import tabla_posiciones as tabla_mod
except ImportError:  # pragma: no cover
    from src import tabla_posiciones as tabla_mod  # type: ignore

router = APIRouter(tags=["Predicciones"])

_CACHE: Dict[str, Any] = {"data": None, "ts": None}
_CACHE_TABLA: Dict[str, Any] = {"data": None, "ts": None}
_TTL_MIN = 30


def _fresco() -> bool:
    return bool(_CACHE["data"]) and bool(_CACHE["ts"]) and (
        datetime.utcnow() - _CACHE["ts"] < timedelta(minutes=_TTL_MIN)
    )


def _obtener() -> Dict[str, Any]:
    if not _fresco():
        _CACHE["data"] = motor.generar_pronosticos()
        _CACHE["ts"] = datetime.utcnow()
    return _CACHE["data"]


def _obtener_tabla() -> Dict[str, Any]:
    fresco = bool(_CACHE_TABLA["data"]) and bool(_CACHE_TABLA["ts"]) and (
        datetime.utcnow() - _CACHE_TABLA["ts"] < timedelta(minutes=_TTL_MIN)
    )
    if not fresco:
        _CACHE_TABLA["data"] = tabla_mod.obtener_tabla()
        _CACHE_TABLA["ts"] = datetime.utcnow()
    return _CACHE_TABLA["data"]


@router.get("/predicciones", summary="Predicciones reales (ESPN + Poisson)")
def predicciones() -> Dict[str, Any]:
    """1X2 / Over-Under / BTTS / marcador por cada partido próximo."""
    return _obtener()


@router.get("/survivor", summary="Mejor pick de Survivor (no perder)")
def survivor(excluir: str = "") -> Dict[str, Any]:
    """
    Mejor equipo para Survivor (mayor prob. de no perder). `excluir`: equipos
    ya usados, separados por coma (ej. ?excluir=America,Toluca).
    """
    data = _obtener()
    usados = [e.strip() for e in excluir.split(",") if e.strip()]
    pick = motor.mejor_pick_survivor(data.get("pronosticos", []), usados)
    return {
        "generado_utc": data.get("generado_utc"),
        "fuente_datos": data.get("fuente_datos"),
        "equipos_excluidos": usados,
        "pick_survivor": pick,
        "decision": data.get("decision"),
    }


@router.get("/tabla", summary="Tabla Liga MX (ESPN) + motivación por equipo")
def tabla() -> Dict[str, Any]:
    """Tabla general con zona de clasificación y motivación por equipo."""
    try:
        data = _obtener_tabla()
    except Exception as exc:  # pragma: no cover - fallback defensivo de red
        return {"torneo": "", "tabla": [], "error": str(exc),
                "decision": "INFORMATIVO / REVISIÓN HUMANA"}
    return {**data, "decision": "INFORMATIVO / REVISIÓN HUMANA"}
