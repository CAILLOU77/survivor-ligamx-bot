#!/usr/bin/env python3
"""
seguimiento_jornada.py — Lista de seguimiento para decidir el pick de Survivor
de forma SECUENCIAL a lo largo de la jornada.

Idea (estrategia real del usuario): el bot arma una lista PRIORIZADA de equipos
candidatos de la jornada (descarta el resto), ordenada por hora de partido. El
día del juego, ~1h antes de cada candidato, se revisa su alineación confirmada:
si convence, lo usas; si no, lo descartas y esperas al siguiente candidato hasta
cerrar uno.

Este módulo es la capa de presentación/orden: recibe los candidatos ya rankeados
(del motor estratégico) y un mapa de horarios, y arma la lista ordenada con el
plan. Los veredictos por alineación (cuando el XI ya salió) se inyectan aparte.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from team_normalizer import canonical_team_key
except ImportError:  # pragma: no cover
    from src.team_normalizer import canonical_team_key  # type: ignore

_DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]

# Umbrales de veredicto por fuerza del XI confirmado.
_XI_CONFIRMA = 85.0   # XI casi completo -> quédate
_XI_DESCARTA = 70.0   # XI muy mermado -> descarta, espera al siguiente


def _parse_dt(iso: Any) -> Optional[datetime]:
    if not iso:
        return None
    s = str(iso).replace("Z", "").strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def fmt_cuando(iso: Any) -> str:
    """'2026-07-18T19:00:00' -> 'sáb 19:00'. '' si no se puede."""
    dt = _parse_dt(iso)
    if dt is None:
        return ""
    return f"{_DIAS[dt.weekday()]} {dt.strftime('%H:%M')}"


def veredicto_xi(fuerza_xi_pct: Optional[float]) -> Dict[str, str]:
    """
    Veredicto por fuerza del XI confirmado del equipo candidato.
    Devuelve {estado, emoji, texto}. 'PENDIENTE' si aún no hay XI.
    """
    if fuerza_xi_pct is None:
        return {"estado": "PENDIENTE", "emoji": "⏳",
                "texto": "revisa su alineación ~1h antes"}
    try:
        f = float(fuerza_xi_pct)
    except (TypeError, ValueError):
        return {"estado": "PENDIENTE", "emoji": "⏳", "texto": "alineación no disponible"}
    if f >= _XI_CONFIRMA:
        return {"estado": "CONFIRMA", "emoji": "✅",
                "texto": f"XI casi completo ({f}%) — puedes quedarte con él"}
    if f < _XI_DESCARTA:
        return {"estado": "DESCARTA", "emoji": "⚠️",
                "texto": f"XI mermado ({f}%) — considera descartarlo y pasar al siguiente"}
    return {"estado": "DUDA", "emoji": "🟡",
            "texto": f"XI aceptable ({f}%) — decide con cuidado"}


def lista_seguimiento(
    picks: List[Dict[str, Any]],
    horarios: Optional[Dict[str, str]] = None,
    fuerza_xi: Optional[Dict[str, float]] = None,
    n: int = 5,
) -> List[Dict[str, Any]]:
    """
    Arma la lista de candidatos a SEGUIR (top `n` del ranking), ordenada por hora
    de partido (los sin hora al final). `horarios` y `fuerza_xi` son mapas por
    clave canónica de equipo. Cada item incluye 'cuando', 'cuando_iso' y 'veredicto'.
    """
    horarios = horarios or {}
    fuerza_xi = fuerza_xi or {}
    items: List[Dict[str, Any]] = []
    for pk in picks[: max(0, n)]:
        clave = canonical_team_key(pk.get("equipo", ""))
        iso = horarios.get(clave)
        f = fuerza_xi.get(clave)
        item = dict(pk)
        item["cuando_iso"] = iso
        item["cuando"] = fmt_cuando(iso)
        item["veredicto"] = veredicto_xi(f)
        items.append(item)
    items.sort(key=lambda c: (c.get("cuando_iso") is None, str(c.get("cuando_iso") or "")))
    return items
