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

# ---------------------------------------------------------------------------
# Parámetros calibrados del modelo (validados por walk-forward sobre Liga MX,
# ~500 partidos reales de ESPN). Ver src/validacion_modelo.py para medirlos.
#   - RECENCIA_HALF_LIFE_DIAS: vida media del peso por recencia. Cada ~1 año el
#     peso de un partido se reduce a la mitad (los recientes pesan más).
#   - SHRINK_PRIOR: regularización (shrinkage) hacia el promedio de la liga,
#     en "partidos efectivos" de prior. Estabiliza a equipos con pocos juegos.
#   - RHO_DIXON_COLES: corrección Dixon-Coles para marcadores bajos.
# Estos valores mejoran calibración (Brier) y mantienen el accuracy por encima
# del baseline 'siempre local'. Se pueden sobreescribir por argumento.
# ---------------------------------------------------------------------------
RECENCIA_HALF_LIFE_DIAS: float = 365.0
SHRINK_PRIOR: float = 4.0
RHO_DIXON_COLES: float = -0.10


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
    rho: float = RHO_DIXON_COLES,
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


def _fecha_ordinal(fecha: Any) -> Optional[int]:
    """Convierte 'YYYY-MM-DD' (o ISO) a número de día (ordinal). None si no parsea."""
    s = str(fecha or "")[:10]
    if not s:
        return None
    try:
        from datetime import date
        y, m, d = s.split("-")
        return date(int(y), int(m), int(d)).toordinal()
    except (ValueError, TypeError):
        return None


def _peso_recencia(orden: Optional[int], ref: Optional[int], half_life_dias: Optional[float]) -> float:
    """
    Peso por recencia: 0.5 ** (antigüedad_en_días / half_life_dias).
    El partido más reciente pesa 1.0 y el peso decae con la antigüedad.
    Sin half_life (o sin fechas) => peso uniforme 1.0.
    """
    if not half_life_dias or half_life_dias <= 0 or orden is None or ref is None:
        return 1.0
    antiguedad = max(0, ref - orden)
    return 0.5 ** (antiguedad / float(half_life_dias))


def calcular_fuerzas(
    partidos: Sequence[Dict[str, Any]],
    *,
    half_life_dias: Optional[float] = RECENCIA_HALF_LIFE_DIAS,
    shrink: float = SHRINK_PRIOR,
) -> Dict[str, Any]:
    """
    Estima fuerzas de ataque/defensa (local y visitante) por equipo a partir
    de resultados históricos. Cada partido debe tener:
        home_team, away_team, home_goals, away_goals
    y, opcionalmente, `fecha` ('YYYY-MM-DD') para ponderar por recencia.

    Parámetros (opcionales, mejoran la calidad de la estimación):
    - half_life_dias: vida media (en días) del peso por recencia. Los partidos
      recientes pesan más; cada `half_life_dias` el peso se reduce a la mitad.
      None => todos los partidos pesan igual (comportamiento clásico).
    - shrink: regularización (shrinkage) hacia el promedio de la liga, medida en
      "partidos efectivos" de prior. Estabiliza a equipos con pocos juegos
      arrastrando su fuerza hacia 1.0. 0 => sin regularización (clásico).

    Devuelve un dict con promedios de liga y, por equipo, factores relativos
    (1.0 = promedio de la liga; >1 mejor ataque / peor defensa según el caso).
    """
    acc: Dict[str, Dict[str, float]] = {}

    def _team(t: str) -> Dict[str, float]:
        return acc.setdefault(
            t,
            {"gf_h": 0.0, "gc_h": 0.0, "w_h": 0.0, "gf_a": 0.0, "gc_a": 0.0, "w_a": 0.0},
        )

    # Referencia de recencia = partido más reciente del set.
    ref_ord: Optional[int] = None
    if half_life_dias:
        ords = [o for o in (_fecha_ordinal(p.get("fecha")) for p in partidos) if o is not None]
        ref_ord = max(ords) if ords else None

    tot_home_goals = tot_away_goals = peso_total = 0.0

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
        w = _peso_recencia(_fecha_ordinal(p.get("fecha")), ref_ord, half_life_dias)
        th, ta = _team(h), _team(a)
        th["gf_h"] += w * hg; th["gc_h"] += w * ag; th["w_h"] += w
        ta["gf_a"] += w * ag; ta["gc_a"] += w * hg; ta["w_a"] += w
        tot_home_goals += w * hg; tot_away_goals += w * ag; peso_total += w

    if peso_total == 0:
        raise ValueError("No hay partidos históricos válidos para estimar fuerzas.")

    avg_home = tot_home_goals / peso_total
    avg_away = tot_away_goals / peso_total
    avg_home = avg_home or 0.1
    avg_away = avg_away or 0.1

    k = max(0.0, float(shrink))

    def _fuerza(suma_goles: float, peso: float, base: float) -> float:
        # Tasa regularizada hacia la media de liga (`base`), luego normalizada.
        # (suma_goles + k*base) / (peso + k)  ->  /base  => shrink hacia 1.0.
        if peso <= 0 and k <= 0:
            return 1.0
        tasa = (suma_goles + k * base) / (peso + k)
        return tasa / base

    fuerzas: Dict[str, Dict[str, float]] = {}
    for t, s in acc.items():
        fuerzas[t] = {
            "ataque_local": _fuerza(s["gf_h"], s["w_h"], avg_home),
            "defensa_local": _fuerza(s["gc_h"], s["w_h"], avg_away),
            "ataque_visita": _fuerza(s["gf_a"], s["w_a"], avg_away),
            "defensa_visita": _fuerza(s["gc_a"], s["w_a"], avg_home),
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
    rho: float = RHO_DIXON_COLES,
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



# ---------------------------------------------------------------------------
# Compatibilidad con la página web (src/api.py)
# ---------------------------------------------------------------------------
def calibrate_and_predict(momio_1: float, momio_2: float, momio_3: float) -> Dict[str, Any]:
    """
    Modelo Poisson calibrado a partir de momios 1X2 (usado por la API web).

    Devuelve probabilidad real sin vig, EV y Kelly fraccional para el local.
    numpy/scipy se importan de forma perezosa para no romper el resto del
    módulo (matemática pura) si no están instalados.
    """
    import numpy as np
    from scipy.stats import poisson as _poisson

    probs = np.array([1.0 / momio_1, 1.0 / momio_2, 1.0 / momio_3])
    vig = probs.sum() - 1.0
    true_probs = probs / (1.0 + vig)

    lambda_home = -np.log(true_probs[1] + true_probs[2]) * 1.42
    lambda_away = -np.log(true_probs[1] + true_probs[0]) * 1.18

    max_g = 7
    p1 = p2 = p3 = 0.0
    for h in range(max_g):
        for a in range(max_g):
            p_score = _poisson.pmf(h, lambda_home) * _poisson.pmf(a, lambda_away)
            if h > a:
                p1 += p_score
            elif h == a:
                p2 += p_score
            else:
                p3 += p_score

    total = p1 + p2 + p3
    p1, p2, p3 = p1 / total, p2 / total, p3 / total

    ev = p1 * momio_1 - 1.0
    b = momio_1 - 1.0
    kelly = (b * p1 - (1.0 - p1)) / b if b > 0 else 0.0
    kelly = max(0.0, min(kelly * 0.25, 0.08))

    return {
        "vig": round(float(vig), 4),
        "true_prob": round(float(p1), 4),
        "expected_value": round(float(ev), 4),
        "kelly_stake": round(float(kelly) * 100, 2),
        "lambda_home": round(float(lambda_home), 2),
        "lambda_away": round(float(lambda_away), 2),
    }
