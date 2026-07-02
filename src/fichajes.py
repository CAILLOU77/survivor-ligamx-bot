#!/usr/bin/env python3
"""
fichajes.py — Altas y bajas por equipo (importación ASISTIDA, sin scraping).

Los fichajes son clave para el Survivor (quién entra/sale cambia la fuerza real
de un equipo, sobre todo en pretemporada). Transfermarkt es la mejor fuente,
pero tiene anti-bot y su ToS prohíbe scraping, así que NO se scrapea: el usuario
copia las altas/bajas y se guardan en data/fichajes.json (dato validado por
humano). Este módulo solo LEE ese archivo y lo expone al pick/dossier.

Regla del proyecto: no inventar. Si no hay datos para un equipo, devuelve vacío.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

try:
    from team_normalizer import canonical_team_key, display_team_name
except ImportError:  # pragma: no cover
    from src.team_normalizer import canonical_team_key, display_team_name  # type: ignore

_PATH = Path(__file__).resolve().parents[1] / "data" / "fichajes.json"


def _cargar() -> Dict[str, Any]:
    try:
        if _PATH.exists():
            with open(_PATH, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
    except Exception:  # pragma: no cover - archivo malformado
        pass
    return {}


def disponible() -> bool:
    """True si hay al menos un equipo con altas/bajas cargadas."""
    equipos = _cargar().get("equipos") or {}
    return any((v or {}).get("altas") or (v or {}).get("bajas") for v in equipos.values())


def _buscar_equipo(equipos: Dict[str, Any], nombre: str) -> Dict[str, Any]:
    """Encuentra el equipo por nombre normalizado (tolerante a alias)."""
    clave = canonical_team_key(nombre)
    for k, v in equipos.items():
        if canonical_team_key(k) == clave:
            return v or {}
    return {}


def resumen_equipo(nombre: str, max_items: int = 4) -> Dict[str, List[str]]:
    """
    Devuelve {altas:[...], bajas:[...]} del equipo (por nombre, tolerante).
    Listas vacías si no hay datos. Limita a `max_items` por lista.
    """
    equipos = _cargar().get("equipos") or {}
    eq = _buscar_equipo(equipos, nombre)
    altas = [str(x) for x in (eq.get("altas") or [])][: max(0, max_items)]
    bajas = [str(x) for x in (eq.get("bajas") or [])][: max(0, max_items)]
    return {"altas": altas, "bajas": bajas}


def linea_equipo(nombre: str) -> str:
    """Texto compacto 'Altas: A, B · Bajas: C' o '' si no hay datos."""
    r = resumen_equipo(nombre)
    partes: List[str] = []
    if r["altas"]:
        partes.append("Altas: " + ", ".join(r["altas"]))
    if r["bajas"]:
        partes.append("Bajas: " + ", ".join(r["bajas"]))
    return " · ".join(partes)


def guardar_equipo(nombre: str, altas: List[str], bajas: List[str]) -> Dict[str, Any]:
    """
    Escribe/actualiza las altas y bajas de un equipo en data/fichajes.json.
    Uso ASISTIDO (el usuario pasa los datos de Transfermarkt). Devuelve el
    registro guardado.
    """
    data = _cargar()
    if not isinstance(data.get("equipos"), dict):
        data["equipos"] = {}
    display = display_team_name(nombre)
    data["equipos"][display] = {
        "altas": [str(x).strip() for x in altas if str(x).strip()],
        "bajas": [str(x).strip() for x in bajas if str(x).strip()],
    }
    with open(_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    return data["equipos"][display]
