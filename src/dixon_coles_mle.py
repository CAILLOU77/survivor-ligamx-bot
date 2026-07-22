#!/usr/bin/env python3
"""
dixon_coles_mle.py — Dixon-Coles por MÁXIMA VEROSIMILITUD (modelo alternativo).

Ajusta el modelo Dixon-Coles (1997) estimando por máxima verosimilitud, con
ponderación por recencia (time-decay) y regularización L2 (ridge), todos los
parámetros a la vez:
    λ_local = exp(gamma + ataque_local - defensa_visita)
    λ_visita = exp(ataque_visita - defensa_local)
más la corrección de marcadores bajos (rho) y la ventaja de local (gamma).

Estado (medido honestamente con walk-forward sobre ~500 partidos de Liga MX):
- Accuracy ~0.51, prácticamente EMPATADO con el modelo por cocientes
  (poisson_model), que va marginalmente arriba en aciertos.
- Brier (calibración) algo MEJOR que el modelo por cocientes.

Por eso este NO es el modelo por defecto: se ofrece como alternativa para
experimentación/calibración. La matriz de marcadores y las probabilidades se
reutilizan de poisson_model (DRY). numpy/scipy se importan de forma perezosa.

Informativo: no cierra ni envía picks.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any, Dict, Optional, Sequence, Tuple

from src import poisson_model as pm

# Defaults validados por walk-forward (ridge en el rango robusto 10–15).
HALF_LIFE_DIAS_DEFAULT = 365.0
RIDGE_DEFAULT = 12.0


def _ordinal(fecha: Any) -> Optional[int]:
    s = str(fecha or "")[:10]
    try:
        y, m, d = s.split("-")
        return date(int(y), int(m), int(d)).toordinal()
    except (ValueError, TypeError):
        return None


def ajustar_dixon_coles(
    partidos: Sequence[Dict[str, Any]],
    *,
    half_life_dias: float = HALF_LIFE_DIAS_DEFAULT,
    ridge: float = RIDGE_DEFAULT,
    max_iter: int = 200,
) -> Dict[str, Any]:
    """
    Estima los parámetros Dixon-Coles por máxima verosimilitud (ponderada por
    recencia + ridge). Devuelve:
        {equipos: {nombre: {ataque, defensa}}, gamma, rho, n_partidos}

    Requiere numpy y scipy (se importan aquí). Cada partido necesita
    home_team, away_team, home_goals, away_goals y, opcional, fecha.
    """
    import numpy as np
    from scipy.optimize import minimize

    filas = []
    for p in partidos:
        try:
            hg = int(p["home_goals"])
            ag = int(p["away_goals"])
        except (KeyError, TypeError, ValueError):
            continue
        h = pm._norm(p.get("home_team"))
        a = pm._norm(p.get("away_team"))
        if not h or not a:
            continue
        filas.append((h, a, hg, ag, _ordinal(p.get("fecha"))))

    if not filas:
        raise ValueError("No hay partidos válidos para ajustar Dixon-Coles.")

    equipos = sorted({f[0] for f in filas} | {f[1] for f in filas})
    idx = {t: i for i, t in enumerate(equipos)}
    nt = len(equipos)

    ords = [f[4] for f in filas if f[4] is not None]
    ref = max(ords) if ords else None

    H = np.array([idx[f[0]] for f in filas])
    A = np.array([idx[f[1]] for f in filas])
    X = np.array([f[2] for f in filas], dtype=float)
    Y = np.array([f[3] for f in filas], dtype=float)
    if ref is not None and half_life_dias and half_life_dias > 0:
        edades = np.array(
            [max(0, ref - (f[4] if f[4] is not None else ref)) for f in filas],
            dtype=float,
        )
        W = 0.5 ** (edades / float(half_life_dias))
    else:
        W = np.ones(len(filas))

    m00 = (X == 0) & (Y == 0)
    m01 = (X == 0) & (Y == 1)
    m10 = (X == 1) & (Y == 0)
    m11 = (X == 1) & (Y == 1)

    def nll(theta):
        atk = theta[:nt]
        dfn = theta[nt : 2 * nt]
        gamma = theta[2 * nt]
        rho = theta[2 * nt + 1]
        atk = atk - atk.mean()  # identificabilidad: sum(ataque)=0
        lam = np.clip(np.exp(gamma + atk[H] - dfn[A]), 1e-6, 30.0)
        mu = np.clip(np.exp(atk[A] - dfn[H]), 1e-6, 30.0)
        tau = np.ones_like(lam)
        tau[m00] = 1.0 - lam[m00] * mu[m00] * rho
        tau[m01] = 1.0 + lam[m01] * rho
        tau[m10] = 1.0 + mu[m10] * rho
        tau[m11] = 1.0 - rho
        tau = np.clip(tau, 1e-6, None)
        ll = np.log(tau) + (X * np.log(lam) - lam) + (Y * np.log(mu) - mu)
        pen = ridge * (np.sum(atk**2) + np.sum(dfn**2))
        return -np.sum(W * ll) + pen

    x0 = np.concatenate([np.zeros(nt), np.zeros(nt), [0.25], [-0.1]])
    bounds = [(-3, 3)] * nt + [(-3, 3)] * nt + [(-1.0, 1.5)] + [(-0.2, 0.2)]
    sol = minimize(nll, x0, method="L-BFGS-B", bounds=bounds, options={"maxiter": max_iter})

    theta = sol.x
    atk = theta[:nt]
    atk = atk - atk.mean()
    dfn = theta[nt : 2 * nt]
    return {
        "equipos": {t: {"ataque": float(atk[idx[t]]), "defensa": float(dfn[idx[t]])} for t in equipos},
        "gamma": float(theta[2 * nt]),
        "rho": float(theta[2 * nt + 1]),
        "n_partidos": len(filas),
    }


def goles_esperados(modelo: Dict[str, Any], local: str, visitante: str) -> Tuple[float, float]:
    """(λ_local, λ_visita) para un partido según el modelo MLE ajustado."""
    eq = modelo["equipos"]
    L = eq.get(pm._norm(local), {"ataque": 0.0, "defensa": 0.0})
    V = eq.get(pm._norm(visitante), {"ataque": 0.0, "defensa": 0.0})
    gamma = modelo.get("gamma", 0.0)
    lam = math.exp(gamma + L["ataque"] - V["defensa"])
    mu = math.exp(V["ataque"] - L["defensa"])
    return max(lam, 0.05), max(mu, 0.05)


def pronostico(
    modelo: Dict[str, Any],
    local: str,
    visitante: str,
    *,
    linea_goles: float = 2.5,
) -> Dict[str, Any]:
    """
    Pronóstico completo (1X2 + Over/Under + BTTS + marcador) con el modelo MLE.
    Reutiliza la matriz de marcadores y las probabilidades de poisson_model.
    """
    lam_l, lam_v = goles_esperados(modelo, local, visitante)
    rho = modelo.get("rho", pm.RHO_DIXON_COLES)
    matriz = pm.matriz_marcadores(lam_l, lam_v, rho=rho)

    p_local, p_empate, p_visita = pm.probabilidades_1x2(matriz)
    p_over, p_under = pm.probabilidad_over_under(matriz, linea_goles)
    p_btts_si, p_btts_no = pm.probabilidad_btts(matriz)
    mh, ma = pm.marcador_mas_probable(matriz)

    pick_1x2 = max(
        (("Gana Local", p_local), ("Empate", p_empate), ("Gana Visitante", p_visita)),
        key=lambda x: x[1],
    )[0]

    return {
        "local": local,
        "visitante": visitante,
        "modelo": "dixon_coles_mle",
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
