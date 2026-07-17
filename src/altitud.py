#!/usr/bin/env python3
"""
altitud.py — Factor de ALTITUD para el pronóstico (efecto real de Liga MX).

Cuando un equipo de costa/baja altura visita a uno de gran altitud (CDMX, Toluca,
Pachuca...), el visitante se fatiga y la ventaja de local se amplifica. El modelo
Poisson ya capta PARTE de esto (los equipos de altura ganan más en casa en los
datos), así que este factor solo agrega la parte CONDICIONADA al visitante, de
forma ACOTADA. Se activa solo si mejora la calibración (ver tuning/medición).

Altitudes de estadio en metros (datos públicos, aproximados). Equipo desconocido
=> sin ajuste (factor 0). INFORMATIVO / REVISIÓN HUMANA.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

try:
    import poisson_model as pm
    from team_normalizer import canonical_team_key
except ImportError:  # pragma: no cover
    from src import poisson_model as pm  # type: ignore
    from src.team_normalizer import canonical_team_key  # type: ignore

# Altitud del estadio (metros s.n.m.), por clave canónica de equipo.
ALTITUDES_M: Dict[str, int] = {
    "toluca": 2660,
    "pachuca": 2400,
    "pumas": 2280,
    "america": 2240,
    "cruz azul": 2240,  # juega en CDMX
    "puebla": 2150,
    "necaxa": 1880,
    "atletico de san luis": 1860,
    "queretaro": 1820,
    "leon": 1815,
    "guadalajara": 1560,
    "atlas": 1560,
    "fc juarez": 1140,
    "santos laguna": 1120,
    "monterrey": 540,
    "tigres": 500,
    "tijuana": 150,
    "atlante": 10,
    "mazatlan": 10,
}

# Diferencia de altitud (m) a partir de la cual empieza a pesar.
UMBRAL_DIFERENCIA_M: float = 1500.0
# Coeficiente por cada 1000 m de diferencia por encima del umbral.
K_ALTITUD: float = 0.06
# Tope del ajuste (máx +15% a los goles esperados del local).
CAP_ALTITUD: float = 0.15


def altitud_equipo(nombre: str) -> Optional[int]:
    """Altitud del estadio del equipo (m), o None si no está en la tabla."""
    return ALTITUDES_M.get(canonical_team_key(nombre))


def factor_altitud(home: str, away: str, k: float = K_ALTITUD) -> float:
    """
    Factor (0..CAP) de ventaja EXTRA para el local por diferencia de altitud.
    0 si no hay datos de alguno, o si la diferencia no supera el umbral.
    """
    ah, aa = altitud_equipo(home), altitud_equipo(away)
    if ah is None or aa is None:
        return 0.0
    diff = ah - aa
    if diff <= UMBRAL_DIFERENCIA_M:
        return 0.0
    return min((diff - UMBRAL_DIFERENCIA_M) / 1000.0 * max(0.0, k), CAP_ALTITUD)


def ajustar_1x2_por_altitud(
    pron: Dict[str, Any], k: float = K_ALTITUD, rho: float = pm.RHO_DIXON_COLES
) -> Tuple[float, float, float]:
    """
    Recalcula (prob_local, prob_empate, prob_visita) en % aplicando el factor de
    altitud a los goles esperados (sube el del local, baja un poco el del
    visitante) y rearmando la matriz. Si no aplica, devuelve las probs actuales.
    """
    gl = pron.get("lambda_local")
    gv = pron.get("lambda_visitante")
    f = factor_altitud(pron.get("local", ""), pron.get("visitante", ""), k)
    if f <= 0.0 or gl is None or gv is None:
        return (pron.get("prob_local_pct", 0.0), pron.get("prob_empate_pct", 0.0), pron.get("prob_visitante_pct", 0.0))
    gl2 = float(gl) * (1.0 + f)
    gv2 = float(gv) * (1.0 - f * 0.5)
    matriz = pm.matriz_marcadores(gl2, gv2, rho=rho)
    pl, pe, pv = pm.probabilidades_1x2(matriz)
    return (round(pl * 100, 2), round(pe * 100, 2), round(pv * 100, 2))


def aplicar_altitud(pron: Dict[str, Any], k: float = K_ALTITUD) -> Dict[str, Any]:
    """
    Copia del pronóstico con el 1X2 ajustado por altitud (y no-perder / pick
    recalculados). Si no aplica, devuelve copia sin cambios.
    """
    out = dict(pron)
    f = factor_altitud(pron.get("local", ""), pron.get("visitante", ""), k)
    if f <= 0.0:
        return out
    pl, pe, pv = ajustar_1x2_por_altitud(pron, k)
    if pl >= pe and pl >= pv:
        pick = "Gana Local"
    elif pv >= pl and pv >= pe:
        pick = "Gana Visitante"
    else:
        pick = "Empate"
    out.update(
        {
            "prob_local_pct": pl,
            "prob_empate_pct": pe,
            "prob_visitante_pct": pv,
            "prob_pick_pct": round(max(pl, pe, pv), 2),
            "pick_1x2": pick,
            "no_perder_local_pct": round(pl + pe, 2),
            "no_perder_visitante_pct": round(pv + pe, 2),
            "ajuste_altitud": {"factor": round(f, 3)},
        }
    )
    return out
