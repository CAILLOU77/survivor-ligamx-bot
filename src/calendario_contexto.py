#!/usr/bin/env python3
"""
calendario_contexto.py — Contexto de calendario para los picks.

Cruza la fecha de cada partido de Liga MX (Apertura 2026) con EVENTOS EXTERNOS
reales (torneos paralelos y fechas FIFA) que afectan la disponibilidad/desgaste
de los jugadores. NO inventa: las fechas salen de fuentes oficiales confirmadas
(calendario oficial Liga MX en PDF + Concacaf/Leagues Cup + Wikipedia).

Uso: dado un partido (equipos + fecha), devuelve avisos de contexto para que el
pick tome en cuenta rotaciones, viajes y ausencias por selección. Es una SEÑAL
informativa más, no una afirmación de "jugó con suplentes" (eso no lo sabemos).

Fuentes de las fechas (2026):
- Leagues Cup: 4 ago – 6 sep (los 18 equipos de Liga MX). [Concacaf/Leagues Cup]
- Campeón de Campeones: 25 jul, Toluca vs Cruz Azul (Carson, CA). [Wikipedia/PDF]
- Campeones Cup: 16 sep, Inter Miami vs campeón Liga MX (Toluca o Cruz Azul). [Wikipedia]
- Fecha FIFA: ventana única de 16 días 21 sep–6 oct (nueva a partir de 2026, la
  J10 cae dentro) y 9–17 nov. [FIFA Council / PDF oficial]
- Copa Intercontinental: diciembre (ya en Liguilla; fuera de fase regular). [PDF]
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

try:
    from team_normalizer import canonical_team_key
except ImportError:  # pragma: no cover
    from src.team_normalizer import canonical_team_key  # type: ignore

# Margen (días) para considerar un evento "cercano" a un partido.
MARGEN_DIAS = 5

# Eventos externos con fechas confirmadas (equipos=[] significa "todos").
EVENTOS_EXTERNOS: List[Dict[str, Any]] = [
    {
        "nombre": "Campeón de Campeones",
        "inicio": "2026-07-25",
        "fin": "2026-07-25",
        "equipos": ["Toluca", "Cruz Azul"],
        "tipo": "partido_extra",
        "emoji": "🏆",
        "nota": ("Toluca y Cruz Azul disputan el Campeón de Campeones (25 jul, "
                 "Carson). Posible desgaste/viaje/rotación en la jornada cercana."),
    },
    {
        "nombre": "Leagues Cup",
        "inicio": "2026-08-04",
        "fin": "2026-09-06",
        "equipos": [],  # los 18 equipos de Liga MX participan
        "tipo": "torneo_paralelo",
        "emoji": "🌎",
        "nota": ("Leagues Cup (4 ago–6 sep): TODOS los equipos de Liga MX juegan "
                 "en paralelo. Alta carga de partidos → rotaciones y desgaste probables."),
    },
    {
        "nombre": "Campeones Cup",
        "inicio": "2026-09-16",
        "fin": "2026-09-16",
        "equipos": ["Toluca", "Cruz Azul"],  # el campeón de Liga MX que gane el C de C
        "tipo": "partido_extra",
        "emoji": "🏆",
        "nota": ("Campeones Cup (16 sep, Miami): el campeón de Liga MX (Toluca o "
                 "Cruz Azul) viaja a jugar vs Inter Miami. Desgaste/viaje en jornada cercana."),
    },
    {
        "nombre": "Fecha FIFA (sep–oct)",
        "inicio": "2026-09-21",
        "fin": "2026-10-06",
        "equipos": [],
        "tipo": "fecha_fifa",
        "emoji": "🌐",
        "nota": ("Ventana FIFA de 16 días (21 sep–6 oct, nueva a partir de 2026). La "
                 "J10 cae DENTRO de esta ventana: varios equipos con seleccionados "
                 "ausentes o recién llegados con desgaste/viaje. Ojo con rotaciones."),
    },
    {
        "nombre": "Fecha FIFA (noviembre)",
        "inicio": "2026-11-09",
        "fin": "2026-11-17",
        "equipos": [],
        "tipo": "fecha_fifa",
        "emoji": "🌐",
        "nota": ("Fecha FIFA (9–17 nov): jugadores de selección ausentes con sus "
                 "países; ojo con desgaste/viaje de cara a la jornada siguiente."),
    },
    {
        "nombre": "Copa Intercontinental",
        "inicio": "2026-12-09",
        "fin": "2026-12-27",
        "equipos": [],
        "tipo": "torneo_paralelo",
        "emoji": "🌍",
        "nota": ("Copa Intercontinental (dic): ocurre en fase de Liguilla, fuera de "
                 "las 17 jornadas regulares. Informativo."),
    },
]


def _cargar_override() -> List[Dict[str, Any]]:
    """Permite sobrescribir los eventos con data/eventos_externos.json si existe."""
    ruta = os.getenv("EVENTOS_EXTERNOS_JSON", "data/eventos_externos.json")
    try:
        if os.path.exists(ruta):
            with open(ruta, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list) and data:
                return data
    except Exception:  # pragma: no cover - archivo malformado: usar embebidos
        pass
    return EVENTOS_EXTERNOS


def _parse_fecha(valor: Any) -> Optional[date]:
    """Convierte 'YYYY-MM-DD' (o con tiempo) a date. None si no se puede."""
    if not valor:
        return None
    s = str(valor).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[: len(fmt) + 4], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "")).date()
    except ValueError:
        return None


def _rangos_intersectan(a_ini: date, a_fin: date, b_ini: date, b_fin: date) -> bool:
    return a_ini <= b_fin and b_ini <= a_fin


def _evento_aplica_a_equipos(evento: Dict[str, Any], equipos: Optional[Sequence[str]]) -> bool:
    """True si el evento aplica a alguno de `equipos` (o a todos si equipos=[])."""
    ev_equipos = evento.get("equipos") or []
    if not ev_equipos:
        return True
    if not equipos:
        return True  # sin filtro de equipos: se considera aplicable
    claves_ev = {canonical_team_key(e) for e in ev_equipos}
    claves_in = {canonical_team_key(e) for e in equipos}
    return bool(claves_ev & claves_in)


def eventos_para_fecha(
    fecha: Any,
    equipos: Optional[Sequence[str]] = None,
    margen_dias: int = MARGEN_DIAS,
) -> List[Dict[str, Any]]:
    """
    Devuelve los eventos externos relevantes para un partido en `fecha` (con un
    margen de `margen_dias` a cada lado), filtrando por `equipos` si se pasan.
    Cada elemento incluye 'nombre', 'nota', 'emoji', 'tipo' y 'equipos'.
    """
    f = _parse_fecha(fecha)
    if f is None:
        return []
    ventana_ini = f - timedelta(days=margen_dias)
    ventana_fin = f + timedelta(days=margen_dias)
    relevantes: List[Dict[str, Any]] = []
    for ev in _cargar_override():
        ev_ini = _parse_fecha(ev.get("inicio"))
        ev_fin = _parse_fecha(ev.get("fin")) or ev_ini
        if ev_ini is None:
            continue
        if not _rangos_intersectan(ventana_ini, ventana_fin, ev_ini, ev_fin):
            continue
        if not _evento_aplica_a_equipos(ev, equipos):
            continue
        relevantes.append(ev)
    return relevantes


def notas_para_partido(
    home: str,
    away: str,
    fecha: Any,
    margen_dias: int = MARGEN_DIAS,
) -> List[str]:
    """Líneas de aviso (con emoji) para un partido concreto. Vacío si no hay."""
    eventos = eventos_para_fecha(fecha, [home, away], margen_dias)
    return [f"{ev.get('emoji', '🗓️')} {ev.get('nombre')}: {ev.get('nota')}" for ev in eventos]


def resumen_jornada(
    partidos: Sequence[Dict[str, Any]],
    fecha_jornada: Any = None,
) -> List[str]:
    """
    Avisos de calendario a nivel jornada (sin duplicar). `partidos` es una lista
    de dicts con 'local'/'visitante' (o 'home_team'/'away_team') y opcional 'fecha'.
    """
    vistos: Dict[str, str] = {}
    for p in partidos or []:
        home = p.get("local") or p.get("home_team") or ""
        away = p.get("visitante") or p.get("away_team") or ""
        f = p.get("fecha") or fecha_jornada
        for ev in eventos_para_fecha(f, [home, away]):
            vistos[ev["nombre"]] = f"{ev.get('emoji', '🗓️')} {ev.get('nombre')}: {ev.get('nota')}"
    return list(vistos.values())
