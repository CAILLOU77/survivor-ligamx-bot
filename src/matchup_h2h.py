#!/usr/bin/env python3
"""
matchup_h2h.py — Señal de "bestia negra" por enfrentamiento directo (H2H).

La Liga MX tiene patrones de emparejamiento reales: hay equipos a los que
"se les sabe jugar" sin importar la tabla (p. ej. Pachuca suele complicar a
América; Tigres suele ganarle a Chivas). Este módulo mide ESO con datos reales
del historial de resultados y avisa cuando el favorito del modelo NO domina
históricamente a ese rival concreto.

No inventa nada: todo sale de los resultados ya jugados (misma fuente que el
modelo). Es una SEÑAL de cautela, no un veredicto.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

try:
    from team_normalizer import canonical_team_key, display_team_name
except ImportError:  # pragma: no cover
    from src.team_normalizer import canonical_team_key, display_team_name  # type: ignore

# Mínimo de enfrentamientos para que el H2H sea informativo (evita muestras de 1-2).
MIN_JUEGOS = 3


def resumen_h2h(resultados: Sequence[Dict[str, Any]], equipo_a: str,
                equipo_b: str) -> Dict[str, Any]:
    """
    Cuenta los enfrentamientos directos (en cualquier sede) entre A y B desde el
    historial. Devuelve el registro desde la perspectiva de A:
      {jugados, a_gana, empates, b_gana, a_sin_perder}
    """
    na, nb = canonical_team_key(equipo_a), canonical_team_key(equipo_b)
    a_gana = empates = b_gana = 0
    for m in resultados or []:
        h = canonical_team_key(m.get("home_team", ""))
        v = canonical_team_key(m.get("away_team", ""))
        if {h, v} != {na, nb}:
            continue
        try:
            hg = int(m.get("home_goals"))
            vg = int(m.get("away_goals"))
        except (TypeError, ValueError):
            continue
        # Resultado desde la perspectiva de A.
        a_g, b_g = (hg, vg) if h == na else (vg, hg)
        if a_g > b_g:
            a_gana += 1
        elif a_g < b_g:
            b_gana += 1
        else:
            empates += 1
    jugados = a_gana + empates + b_gana
    return {
        "jugados": jugados,
        "a_gana": a_gana,
        "empates": empates,
        "b_gana": b_gana,
        "a_sin_perder": a_gana + empates,
    }


def alerta_h2h(resultados: Sequence[Dict[str, Any]], favorito: str, rival: str,
               min_juegos: int = MIN_JUEGOS) -> Optional[str]:
    """
    Devuelve una nota de cautela si el `favorito` NO domina históricamente al
    `rival` (le cuesta / es su bestia negra). None si no hay muestra suficiente
    o si el favorito sí domina.

    Criterio: con >= min_juegos enfrentamientos, si el favorito ganó la MITAD o
    menos de los duelos (el rival lo aguanta), se marca la señal.
    """
    r = resumen_h2h(resultados, favorito, rival)
    n = r["jugados"]
    if n < min_juegos:
        return None
    if r["a_gana"] * 2 <= n:  # favorito gana <= 50% de los duelos
        fav = display_team_name(favorito)
        riv = display_team_name(rival)
        return (f"{riv} le sabe jugar a {fav}: en {n} duelos {fav} ganó "
                f"{r['a_gana']}, {riv} {r['b_gana']}, empates {r['empates']}.")
    return None


def anotar_h2h(pronosticos: Sequence[Dict[str, Any]],
               resultados: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Añade `h2h_nota` a cada pronóstico cuando el favorito del modelo (local o
    visitante, según pick_1x2) tiene mal registro histórico vs el rival. Copia
    defensiva; nunca lanza.
    """
    salida: List[Dict[str, Any]] = []
    for p in pronosticos or []:
        q = dict(p)
        try:
            pick = q.get("pick_1x2", "")
            local = q.get("local", "")
            visita = q.get("visitante", "")
            if pick == "Gana Local":
                favorito, rival = local, visita
            elif pick == "Gana Visitante":
                favorito, rival = visita, local
            else:
                favorito = rival = None
            if favorito and rival:
                nota = alerta_h2h(resultados, favorito, rival)
                if nota:
                    q["h2h_nota"] = nota
        except Exception:  # pragma: no cover - nunca tumbar el pipeline
            pass
        salida.append(q)
    return salida
