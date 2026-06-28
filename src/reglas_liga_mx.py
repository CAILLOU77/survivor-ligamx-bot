#!/usr/bin/env python3
"""
reglas_liga_mx.py — Fuente única de verdad del FORMATO/REGLAS vigentes de Liga MX.

Datos verificados (2025–2026), con la excepción del Mundial 2026 documentada.
Este módulo NO predice ni toma picks: solo expone los hechos del reglamento para
que el resto del bot (estrategia, riesgo, pronóstico) los consulte de forma
consistente, en vez de tener números/supuestos regados por el código.

Hechos (fuentes: Wikipedia "Liga MX" / squawka, junio 2026; reformulado):
- 18 equipos. Dos torneos por temporada: Apertura (jul–dic) y Clausura (ene–may).
- Liguilla NORMAL: top 6 clasifica directo + Play-In (lugares 7–10) por los 2
  boletos restantes = 8 equipos a cuartos (ida/vuelta).
- EXCEPCIÓN Clausura 2026: se eliminó el Play-In y los 8 primeros pasaron
  directo a cuartos, por la compresión de calendario del Mundial 2026.
- Descenso: SUSPENDIDO desde 2020.
"""
from __future__ import annotations

import unicodedata
from typing import Any, Dict, List

EQUIPOS_LIGA_MX = 18
TORNEOS = ("Apertura", "Clausura")
DESCENSO_SUSPENDIDO = True

# Formato vigente por defecto (normal): top 6 directo + Play-In 7–10.
LIGUILLA_DIRECTO_DEFAULT = 6
LIGUILLA_PLAY_IN_RANGO = (7, 10)
LIGUILLA_TOTAL = 8

# Excepciones conocidas y documentadas, por torneo (clave normalizada).
EXCEPCIONES_FORMATO: Dict[str, Dict[str, Any]] = {
    "clausura 2026": {
        "play_in": False,
        "clasificados_directo": 8,
        "nota": (
            "Clausura 2026: sin Play-In; top 8 directo a cuartos por compresión "
            "de calendario del Mundial 2026."
        ),
    },
}


def _norm(texto: str) -> str:
    base = unicodedata.normalize("NFKD", str(texto or "")).lower()
    base = "".join(c for c in base if not unicodedata.combining(c))
    return " ".join(base.split())


def formato_liguilla(torneo: str = "") -> Dict[str, Any]:
    """
    Devuelve el formato de liguilla vigente para el torneo dado.

    Si el torneo está en EXCEPCIONES_FORMATO, usa esa configuración; si no,
    devuelve el formato normal (top 6 + Play-In). Siempre 8 equipos en liguilla.
    """
    exc = EXCEPCIONES_FORMATO.get(_norm(torneo))
    if exc:
        return {
            "torneo": torneo,
            "play_in": exc["play_in"],
            "clasificados_directo": exc["clasificados_directo"],
            "play_in_rango": None if not exc["play_in"] else LIGUILLA_PLAY_IN_RANGO,
            "total_liguilla": LIGUILLA_TOTAL,
            "nota": exc.get("nota", ""),
            "es_excepcion": True,
        }
    return {
        "torneo": torneo or "normal",
        "play_in": True,
        "clasificados_directo": LIGUILLA_DIRECTO_DEFAULT,
        "play_in_rango": LIGUILLA_PLAY_IN_RANGO,
        "total_liguilla": LIGUILLA_TOTAL,
        "nota": "Formato normal: top 6 directo + Play-In (7–10) por 2 boletos.",
        "es_excepcion": False,
    }


def hay_play_in(torneo: str = "") -> bool:
    """True si el torneo usa Play-In (formato normal); False en la excepción."""
    return bool(formato_liguilla(torneo)["play_in"])


def clasifica_directo(posicion: int, torneo: str = "") -> bool:
    """True si esa posición clasifica DIRECTO a cuartos."""
    f = formato_liguilla(torneo)
    return 1 <= int(posicion) <= f["clasificados_directo"]


def va_play_in(posicion: int, torneo: str = "") -> bool:
    """True si esa posición juega el Play-In (solo en formato normal)."""
    f = formato_liguilla(torneo)
    if not f["play_in"]:
        return False
    lo, hi = f["play_in_rango"]
    return lo <= int(posicion) <= hi


def fuera_de_liguilla(posicion: int, torneo: str = "") -> bool:
    """True si esa posición NO tiene opción de liguilla (ni directo ni Play-In)."""
    p = int(posicion)
    if clasifica_directo(p, torneo):
        return False
    if va_play_in(p, torneo):
        return False
    return True


def zona_clasificacion(posicion: int, torneo: str = "") -> str:
    """
    Clasifica una posición de la tabla en su zona: 'directo', 'play_in' o 'fuera'.
    Útil para derivar la motivación de cada equipo desde la tabla.
    """
    if clasifica_directo(posicion, torneo):
        return "directo"
    if va_play_in(posicion, torneo):
        return "play_in"
    return "fuera"


def cupos_postemporada(torneo: str = "") -> int:
    """
    Número de equipos que llegan a la postemporada (incluyendo Play-In).
    Formato normal: 10 (top 6 directo + Play-In 7–10). Excepción sin Play-In: 8.
    """
    f = formato_liguilla(torneo)
    if f["play_in"]:
        return int(f["play_in_rango"][1])
    return int(f["clasificados_directo"])


def descenso_activo() -> bool:
    """Descenso suspendido desde 2020 -> False."""
    return not DESCENSO_SUSPENDIDO


def resumen_reglas(torneo: str = "") -> str:
    """Resumen legible de las reglas vigentes (para reportes)."""
    f = formato_liguilla(torneo)
    lineas = [
        f"Liga MX — {EQUIPOS_LIGA_MX} equipos, torneos: {', '.join(TORNEOS)}.",
        f"Liguilla: {f['clasificados_directo']} directo"
        + ("" if not f["play_in"] else f" + Play-In {f['play_in_rango'][0]}–{f['play_in_rango'][1]}")
        + f" = {f['total_liguilla']} equipos.",
        f"Descenso: {'activo' if descenso_activo() else 'suspendido (desde 2020)'}.",
    ]
    if f["nota"]:
        lineas.append(f"Nota: {f['nota']}")
    return "\n".join(lineas)
