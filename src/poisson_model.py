#!/usr/bin/env python3
"""
poisson_model.py — Modelo de pronóstico Poisson / Dixon-Coles (Survivor Liga MX).

Calcula pronósticos basados en la FUERZA ofensiva/defensiva de cada equipo
estimada a partir de resultados históricos, no solo de los momios. Produce
probabilidades para 1X2, Over/Under y BTTS, y el marcador más probable.

Método (estándar en analítica de fútbol):
1. De los resultados históricos se estima, por equipo, su fuerza de ataque y
   defensa (local y visitante) relativa al promedio de la liga.
2. Para un partido, los goles esperados son:
       λ_local  = ataque_local(L)  * defensa_visita(V) * promedio_goles_local
       λ_visita = ataque_visita(V) * defensa_local(L)  * promedio_goles_visita
3. Con λ se arma la matriz de marcadores vía Poisson, con la corrección de
   Dixon-Coles para marcadores bajos (0-0, 1-0, 0-1, 1-1).
4. De la matriz se derivan 1X2, Over/Under, BTTS y el marcador más probable.

Matemática pura: sin red, sin I/O, sin scipy. NO cierra ni envía picks.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple


def _pois_pmf(k: int, lam: float) -> float:
    """Probabilidad Poisson P(X=k) para media lam."""
    if lam < 0:
        raise ValueError("lambda no puede ser negativo.")
    if lam == 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def _tau_dixon_coles(x: int, y: int, lam: float, mu: float, rho: float) -> float:
    """Factor de corrección de Dixon-Coles para los 4 marcadores bajos."""
    if x == 0 and y == 0:
        return 1.0 - lam * mu * rho
    if x == 0 and y == 1:
        return 1.0 + lam * rho
    if x == 1 and y == 0:
        return 1.0 + mu * rho
    if x == 1 and y == 1:
        return 1.0 - rho
    return 1.0


def matriz_marcadores(
    lam_local: float,
    lam_visita: float,
    max_goles: int = 10,
    rho: float = -0.05,
) -> List[List[float]]:
    """
    Matriz de probabilidad de marcadores [local][visita], normalizada a sumar 1.
    rho=0 => Poisson simple; rho!=0 => corrección Dixon-Coles de marcadores bajos.
    """
    matriz = [[0.0] * (max_goles + 1) for _ in range(max_goles + 1)]
    total = 0.0
    for i in range(max_goles + 1):
        for j in range(max_goles + 1):
            p = _pois_pmf(i, lam_local) * _pois_pmf(j, lam_visita)
            p *= _tau_dixon_coles(i, j, lam_local, lam_visita, rho)
            p = max(p, 0.0)
            matriz[i][j] = p
            total += p
    if total > 0:
        for i in range(max_goles + 1):
            for j in range(max_goles + 1):
                matriz[i][j] /= total
    return matriz


def probabilidades_1x2(matriz: List[List[float]]) -> Tuple[float, float, float]:
    """Devuelve (P_local, P_empate, P_visita) a partir de la matriz."""
    p_local = p_empate = p_visita = 0.0
    for i, fila in enumerate(matriz):
        for j, p in enumerate(fila):
            if i > j:
                p_local += p
            elif i == j:
                p_empate += p
            else:
                p_visita += p
    return p_local, p_empate, p_visita


def probabilidad_over_under(matriz: List[List[float]], linea: float = 2.5) -> Tuple[float, float]:
    """Devuelve (P_over, P_under) para la línea de goles totales dada."""
    p_over = 0.0
    for i, fila in enumerate(matriz):
        for j, p in enumerate(fila):
            if (i + j) > linea:
                p_over += p
    return p_over, 1.0 - p_over


def probabilidad_btts(matriz: List[List[float]]) -> Tuple[float, float]:
    """Devuelve (P_ambos_anotan_si, P_no) — BTTS (both teams to score)."""
    p_si = 0.0
    for i, fila in enumerate(matriz):
        for j, p in enumerate(fila):
            if i >= 1 and j >= 1:
                p_si += p
    return p_si, 1.0 - p_si


def marcador_mas_probable(matriz: List[List[float]]) -> Tuple[int, int]:
    """Devuelve el marcador (local, visita) con mayor probabilidad."""
    mejor = (0, 0)
    mejor_p = -1.0
    for i, fila in enumerate(matriz):
        for j, p in enumerate(fila):
            if p > mejor_p:
                mejor_p = p
                mejor = (i, j)
    return mejor



# ---------------------------------------------------------------------------
# Estimación de fuerzas de equipo desde resultados históricos
# ---------------------------------------------------------------------------
def _norm(nombre: str) -> str:
    return " ".join(str(nombre or "").strip().lower().split())


def calcular_fuerzas(partidos: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Estima fuerzas de ataque/defensa (local y visitante) por equipo a partir
    de resultados históricos. Cada partido debe tener:
        home_team, away_team, home_goals, away_goals

    Devuelve un dict con promedios de liga y, por equipo, factores relativos
    (1.0 = promedio de la liga; >1 mejor ataque / peor defensa según el caso).
    """
    acc: Dict[str, Dict[str, float]] = {}

    def _team(t: str) -> Dict[str, float]:
        return acc.setdefault(
            t,
            {"gf_h": 0.0, "gc_h": 0.0, "n_h": 0.0, "gf_a": 0.0, "gc_a": 0.0, "n_a": 0.0},
        )

    tot_home_goals = tot_away_goals = n_matches = 0.0

    for p in partidos:
        try:
            hg = float(p.get("home_goals"))
            ag = float(p.get("away_goals"))
        except (TypeError, ValueError):
            continue
        h = _norm(p.get("home_team"))
        a = _norm(p.get("away_team"))
        if not h or not a:
            continue
        th, ta = _team(h), _team(a)
        th["gf_h"] += hg; th["gc_h"] += ag; th["n_h"] += 1
        ta["gf_a"] += ag; ta["gc_a"] += hg; ta["n_a"] += 1
        tot_home_goals += hg; tot_away_goals += ag; n_matches += 1

    if n_matches == 0:
        raise ValueError("No hay partidos históricos válidos para estimar fuerzas.")

    avg_home = tot_home_goals / n_matches
    avg_away = tot_away_goals / n_matches
    avg_home = avg_home or 0.1
    avg_away = avg_away or 0.1

    fuerzas: Dict[str, Dict[str, float]] = {}
    for t, s in acc.items():
        n_h = s["n_h"] or 1.0
        n_a = s["n_a"] or 1.0
        fuerzas[t] = {
            "ataque_local": (s["gf_h"] / n_h) / avg_home if s["n_h"] else 1.0,
            "defensa_local": (s["gc_h"] / n_h) / avg_away if s["n_h"] else 1.0,
            "ataque_visita": (s["gf_a"] / n_a) / avg_away if s["n_a"] else 1.0,
            "defensa_visita": (s["gc_a"] / n_a) / avg_home if s["n_a"] else 1.0,
        }

    return {"avg_home": avg_home, "avg_away": avg_away, "equipos": fuerzas}


def goles_esperados(local: str, visitante: str, fuerzas: Dict[str, Any]) -> Tuple[float, float]:
    """Calcula (λ_local, λ_visita) para un partido usando las fuerzas estimadas."""
    eq = fuerzas["equipos"]
    L = eq.get(_norm(local), {"ataque_local": 1.0, "defensa_local": 1.0})
    V = eq.get(_norm(visitante), {"ataque_visita": 1.0, "defensa_visita": 1.0})
    lam_local = L.get("ataque_local", 1.0) * V.get("defensa_visita", 1.0) * fuerzas["avg_home"]
    lam_visita = V.get("ataque_visita", 1.0) * L.get("defensa_local", 1.0) * fuerzas["avg_away"]
    return max(lam_local, 0.05), max(lam_visita, 0.05)


def pronostico(
    local: str,
    visitante: str,
    fuerzas: Dict[str, Any],
    *,
    linea_goles: float = 2.5,
    rho: float = -0.05,
) -> Dict[str, Any]:
    """Pronóstico completo (1X2 + Over/Under + BTTS + marcador) para un partido."""
    lam_l, lam_v = goles_esperados(local, visitante, fuerzas)
    matriz = matriz_marcadores(lam_l, lam_v, rho=rho)

    p_local, p_empate, p_visita = probabilidades_1x2(matriz)
    p_over, p_under = probabilidad_over_under(matriz, linea_goles)
    p_btts_si, p_btts_no = probabilidad_btts(matriz)
    mh, ma = marcador_mas_probable(matriz)

    pick_1x2 = max(
        (("Gana Local", p_local), ("Empate", p_empate), ("Gana Visitante", p_visita)),
        key=lambda x: x[1],
    )[0]

    return {
        "local": local,
        "visitante": visitante,
        "lambda_local": round(lam_l, 3),
        "lambda_visitante": round(lam_v, 3),
        "prob_local_pct": round(p_local * 100, 2),
        "prob_empate_pct": round(p_empate * 100, 2),
        "prob_visitante_pct": round(p_visita * 100, 2),
        "prob_over_pct": round(p_over * 100, 2),
        "prob_under_pct": round(p_under * 100, 2),
        "linea_goles": linea_goles,
        "prob_btts_si_pct": round(p_btts_si * 100, 2),
        "prob_btts_no_pct": round(p_btts_no * 100, 2),
        "marcador_mas_probable": f"{mh}-{ma}",
        "pick_1x2": pick_1x2,
        "pick_ou": "Over" if p_over >= p_under else "Under",
        "pick_btts": "Sí" if p_btts_si >= p_btts_no else "No",
    }


def combinar_con_mercado(
    prob_modelo: Sequence[float],
    prob_mercado: Sequence[float],
    peso_modelo: float = 0.5,
) -> List[float]:
    """
    Mezcla (ensemble) las probabilidades del modelo con las del mercado sin vig.

    Ambas listas deben tener el mismo largo (ej. [local, empate, visita]) y
    sumar ~1. peso_modelo en [0,1]: 0 = solo mercado, 1 = solo modelo.
    Devuelve la mezcla renormalizada (suma 1).
    """
    if len(prob_modelo) != len(prob_mercado):
        raise ValueError("Las listas deben tener el mismo largo.")
    if not 0.0 <= peso_modelo <= 1.0:
        raise ValueError("peso_modelo debe estar entre 0 y 1.")
    peso_mercado = 1.0 - peso_modelo
    mezcla = [
        peso_modelo * m + peso_mercado * k
        for m, k in zip(prob_modelo, prob_mercado)
    ]
    total = sum(mezcla)
    if total <= 0:
        raise ValueError("La mezcla resultó en suma no positiva.")
    return [x / total for x in mezcla]
