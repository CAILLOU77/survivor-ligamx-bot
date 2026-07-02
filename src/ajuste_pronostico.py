#!/usr/bin/env python3
"""
ajuste_pronostico.py — Ajuste MODERADO y con TOPE del pronóstico por dos señales
reales de último momento: impacto del XI confirmado y dominio histórico (H2H).

Filosofía (regla del proyecto): datos reales, nada fabricado, y ajustes acotados
que NUNCA voltean un pronóstico entero por una baja. Si no hay XI publicado o no
hay muestra H2H suficiente, NO se ajusta (se devuelve el pronóstico base).

Base: goles esperados y probabilidades 1X2 del modelo Poisson.
- Lineup: por equipo, deficit = 100 − fuerza_xi_pct. Se reducen sus goles
  esperados por factor = min(deficit/100 · K, CAP), K=0.6, CAP=0.15 (máx 15%).
  Se recalculan las probabilidades 1X2 desde los goles ajustados.
- H2H: pequeño empujón por dominio histórico, SOLO si played ≥ 6; tope ±5 puntos
  sobre la probabilidad de victoria del favorito (luego se renormaliza).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

try:
    import poisson_model as pm
except ImportError:  # pragma: no cover
    from src import poisson_model as pm  # type: ignore

try:
    from team_normalizer import canonical_team_key
except ImportError:  # pragma: no cover
    from src.team_normalizer import canonical_team_key  # type: ignore

# Parámetros del ajuste (transparentes y acotados).
K_LINEUP = 0.6
CAP_LINEUP = 0.15          # recorte máximo de goles esperados por equipo (15%)
H2H_MIN_PARTIDOS = 6
H2H_TOPE_PTS = 5.0         # empujón máximo (puntos porcentuales) al favorito

# Umbrales de confianza 1X2 (coherentes con el motor).
_CONF_ALTA = 55.0
_CONF_MEDIA = 42.0


def factor_lineup(fuerza_xi_pct: Optional[float]) -> float:
    """Factor de recorte de goles esperados por déficit del XI (0..CAP_LINEUP)."""
    if fuerza_xi_pct is None:
        return 0.0
    try:
        deficit = max(0.0, 100.0 - float(fuerza_xi_pct))
    except (TypeError, ValueError):
        return 0.0
    return min(deficit / 100.0 * K_LINEUP, CAP_LINEUP)


def _nivel_conf(prob_pick_pct: float) -> str:
    if prob_pick_pct >= _CONF_ALTA:
        return "ALTA"
    if prob_pick_pct >= _CONF_MEDIA:
        return "MEDIA"
    return "BAJA"


def _buscar_equipo(impacto: Dict[str, Any], nombre: str) -> Dict[str, Any]:
    clave = canonical_team_key(nombre)
    for k, v in (impacto or {}).items():
        if canonical_team_key(k) == clave:
            return v or {}
    return {}


def _pick_1x2(pl: float, pe: float, pv: float) -> str:
    mayor = max(pl, pe, pv)
    if mayor == pl:
        return "Gana Local"
    if mayor == pv:
        return "Gana Visitante"
    return "Empate"


def ajustar_pronostico(
    pron: Dict[str, Any],
    impacto_equipos: Optional[Dict[str, Any]] = None,
    h2h: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Devuelve una COPIA del pronóstico con probabilidades ajustadas (si aplica) y
    un bloque `ajuste` explicando qué se movió. Si no hay señales válidas,
    devuelve el pronóstico base con `ajuste={"aplicado": False}`.
    """
    out = dict(pron)
    gl = pron.get("goles_esperados_local")
    gv = pron.get("goles_esperados_visitante")
    if gl is None or gv is None:
        out["ajuste"] = {"aplicado": False, "motivo": "sin goles esperados"}
        return out

    notas: List[str] = []
    fl = fv = 0.0

    # --- 1) Ajuste por XI confirmado (lineup-impact) ---
    if impacto_equipos:
        info_l = _buscar_equipo(impacto_equipos, pron.get("local", ""))
        info_v = _buscar_equipo(impacto_equipos, pron.get("visitante", ""))
        fl = factor_lineup(info_l.get("fuerza_xi_pct"))
        fv = factor_lineup(info_v.get("fuerza_xi_pct"))
        if fl > 0:
            notas.append(f"{pron.get('local')}: -{round(fl*100)}% ataque (XI incompleto)")
        if fv > 0:
            notas.append(f"{pron.get('visitante')}: -{round(fv*100)}% ataque (XI incompleto)")

    gl_adj = float(gl) * (1.0 - fl)
    gv_adj = float(gv) * (1.0 - fv)

    matriz = pm.matriz_marcadores(gl_adj, gv_adj)
    pl, pe, pv = pm.probabilidades_1x2(matriz)  # proporciones 0..1
    pl, pe, pv = pl * 100.0, pe * 100.0, pv * 100.0

    # --- 2) Empujón por dominio histórico (H2H) ---
    if h2h and isinstance(h2h, dict):
        played = int(h2h.get("played") or 0)
        if played >= H2H_MIN_PARTIDOS:
            t1 = h2h.get("team1") or {}
            t2 = h2h.get("team2") or {}
            # ¿Quién es local/visitante en este partido? Emparejar por nombre.
            clave_local = canonical_team_key(pron.get("local", ""))
            if canonical_team_key(t1.get("name", "")) == clave_local:
                w_local, w_visita = int(t1.get("wins") or 0), int(t2.get("wins") or 0)
            else:
                w_local, w_visita = int(t2.get("wins") or 0), int(t1.get("wins") or 0)
            dominio = (w_local - w_visita) / played  # -1..1 (local vs visita)
            empuje = max(-1.0, min(1.0, dominio)) * H2H_TOPE_PTS  # puntos %
            if abs(empuje) >= 0.5:
                pl = max(0.0, pl + empuje)
                pv = max(0.0, pv - empuje)
                total = pl + pe + pv
                if total > 0:
                    pl, pe, pv = pl / total * 100.0, pe / total * 100.0, pv / total * 100.0
                signo = "+" if empuje > 0 else ""
                notas.append(f"H2H ({played} duelos): {signo}{round(empuje,1)}pts al local")

    aplicado = bool(notas)
    if not aplicado:
        out["ajuste"] = {"aplicado": False}
        return out

    pl, pe, pv = round(pl, 2), round(pe, 2), round(pv, 2)
    prob_pick = max(pl, pe, pv)
    out.update({
        "prob_local_pct": pl,
        "prob_empate_pct": pe,
        "prob_visitante_pct": pv,
        "prob_pick_pct": round(prob_pick, 2),
        "pick_1x2": _pick_1x2(pl, pe, pv),
        "nivel_confianza": _nivel_conf(prob_pick),
        "no_perder_local_pct": round(pl + pe, 2),
        "no_perder_visitante_pct": round(pv + pe, 2),
        "goles_esperados_local": round(gl_adj, 3),
        "goles_esperados_visitante": round(gv_adj, 3),
    })
    out["ajuste"] = {
        "aplicado": True,
        "notas": notas,
        "base": {
            "prob_local_pct": pron.get("prob_local_pct"),
            "prob_empate_pct": pron.get("prob_empate_pct"),
            "prob_visitante_pct": pron.get("prob_visitante_pct"),
        },
    }
    return out
