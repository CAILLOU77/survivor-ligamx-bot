#!/usr/bin/env python3
"""
planificador_survivor.py — Estrategia de temporada para el Survivor (PlayDoit).

El problema NO es "qué equipo es mejor esta jornada", sino "en QUÉ jornada usar
cada equipo" mirando TODO el calendario, sin repetir, para:
  1) sobrevivir las 17 jornadas (no perder NUNCA: una derrota = eliminado), y
  2) maximizar victorias (puntos / desempate), usando el empate solo como colchón.

Es un problema de ASIGNACIÓN (jornada ↔ equipo). Se resuelve de forma óptima con
el algoritmo húngaro (scipy.optimize.linear_sum_assignment) maximizando:

    valor(equipo, jornada) = log(P_no_perder) + peso_victoria * P_ganar

- log(P_no_perder) castiga fuerte las jornadas donde el equipo podría PERDER
  (prioridad #1: no eliminarte).
- peso_victoria * P_ganar premia las victorias (prioridad #2).

Probabilidades reales del modelo Poisson/Dixon-Coles (ESPN). Si se pasan momios
reales (odds-api.io) se pueden mezclar. NUNCA inventa datos.
INFORMATIVO / REVISIÓN HUMANA.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, cast

try:
    import poisson_model as pm
except ImportError:  # pragma: no cover
    from src import poisson_model as pm  # type: ignore

BASE_DIR = Path(__file__).resolve().parents[1]
CALENDARIO_PATH = BASE_DIR / "data" / "calendario.json"

DEC_INFORMATIVA = "INFORMATIVO / REVISIÓN HUMANA"
_PROB_FLOOR = 1e-6  # evita log(0)

# Pesos/umbrales por defecto (tunables).
PESO_VICTORIA: float = 0.5
UMBRAL_NO_PERDER_ALTA: float = 0.75
UMBRAL_GANAR_ALTA: float = 0.55
UMBRAL_NO_PERDER_MEDIA: float = 0.65

# Ajuste de riesgo por SORPRESA (coherente con motor_pronosticos): el favorito
# VISITANTE del modelo falla más (medido ~58% vs ~44% del local en analisis_riesgo).
# Se descuenta su probabilidad de no-perder SOLO para el valor de asignación
# (decidir en qué jornada gastarlo), NUNCA para los % que se le muestran al
# usuario (esos siguen siendo los reales del modelo: honestidad).
DESCUENTO_VISITANTE: float = 0.05  # -5% a picks visitantes
DESCUENTO_VISITANTE_ARRANQUE: float = 0.10  # extra en jornadas de arranque
JORNADAS_ARRANQUE_PLAN: int = 3  # primeras N jornadas = más sorpresas


# ---------------------------------------------------------------------------
# Momios americanos (para cuando el usuario pega momios reales tipo -125 / +110)
# ---------------------------------------------------------------------------
def prob_implicita_americana(momio: float) -> float:
    """Probabilidad implícita (con vig) de un momio americano. -125 -> 0.5556."""
    m = float(momio)
    if m < 0:
        return (-m) / ((-m) + 100.0)
    if m > 0:
        return 100.0 / (m + 100.0)
    raise ValueError("Momio americano no puede ser 0.")


def devig_americano(m_local: float, m_empate: float, m_visita: float) -> Tuple[float, float, float]:
    """Quita el vig de un 1X2 americano y normaliza a (p_local, p_empate, p_visita)."""
    pl = prob_implicita_americana(m_local)
    pe = prob_implicita_americana(m_empate)
    pv = prob_implicita_americana(m_visita)
    s = pl + pe + pv
    if s <= 0:
        raise ValueError("Momios inválidos.")
    return pl / s, pe / s, pv / s


# ---------------------------------------------------------------------------
# Probabilidades por partido (modelo, opcionalmente mezclado con momios reales)
# ---------------------------------------------------------------------------
def _norm(t: str) -> str:
    return cast(str, pm._norm(t))


def _probs_partido(
    home: str,
    away: str,
    fuerzas: Dict[str, Any],
    odds_por_partido: Optional[Dict[Tuple[str, str], Tuple[float, float, float]]] = None,
    peso_modelo: float = 0.5,
) -> Optional[Tuple[float, float, float]]:
    """(p_local, p_empate, p_visita) del modelo; mezclado con momios si se proveen."""
    if _norm(home) not in fuerzas.get("equipos", {}) or _norm(away) not in fuerzas.get("equipos", {}):
        return None
    pr = pm.pronostico(home, away, fuerzas)
    modelo = (pr["prob_local_pct"] / 100.0, pr["prob_empate_pct"] / 100.0, pr["prob_visitante_pct"] / 100.0)
    if odds_por_partido:
        mercado = odds_por_partido.get((_norm(home), _norm(away)))
        if mercado:
            mezcla = pm.combinar_con_mercado(modelo, mercado, peso_modelo=peso_modelo)
            return mezcla[0], mezcla[1], mezcla[2]
    return modelo


def _probs_equipo(p_local: float, p_empate: float, p_visita: float, es_local: bool) -> Dict[str, float]:
    """Desde 1X2 del partido, las probabilidades RELEVANTES para el equipo elegido."""
    p_win = p_local if es_local else p_visita
    return {"p_ganar": p_win, "p_empate": p_empate, "p_no_perder": p_win + p_empate}


def _nivel(p_no_perder: float, p_ganar: float) -> str:
    if p_no_perder >= UMBRAL_NO_PERDER_ALTA and p_ganar >= UMBRAL_GANAR_ALTA:
        return "ALTA"
    if p_no_perder >= UMBRAL_NO_PERDER_MEDIA:
        return "MEDIA"
    return "RIESGOSA"


def _nivel_estrategico(p_no_perder: float, p_ganar: float, es_local: bool, es_arranque: bool) -> str:
    """
    Nivel ajustado por sorpresa (coherente con motor_pronosticos._nivel_estrategico):
    un favorito VISITANTE nunca es 'ALTA', y en el arranque 'ALTA' exige más margen.
    """
    nivel = _nivel(p_no_perder, p_ganar)
    if not es_local and nivel == "ALTA":
        nivel = "MEDIA"
    if es_arranque and nivel == "ALTA" and p_no_perder < 0.80:
        nivel = "MEDIA"
    return nivel


# ---------------------------------------------------------------------------
# Planificador (asignación óptima jornada ↔ equipo)
# ---------------------------------------------------------------------------
def _opciones_por_jornada(
    calendario: Sequence[Dict[str, Any]],
    fuerzas: Dict[str, Any],
    odds_por_partido: Optional[Dict[Tuple[str, str], Tuple[float, float, float]]],
    peso_modelo: float,
) -> Tuple[List[int], List[str], Dict[Tuple[int, str], Dict[str, Any]]]:
    """
    Devuelve (jornadas, equipos, celdas) donde celdas[(jornada, equipo_norm)] tiene
    las probabilidades y metadatos de usar ese equipo esa jornada.
    """
    jornadas: List[int] = []
    equipos: set = set()
    celdas: Dict[Tuple[int, str], Dict[str, Any]] = {}
    for j in sorted(calendario, key=lambda x: int(x.get("jornada", 0))):
        jnum = int(j.get("jornada", 0))
        jornadas.append(jnum)
        for partido in j.get("partidos", []):
            home, away = partido.get("home_team", ""), partido.get("away_team", "")
            probs = _probs_partido(home, away, fuerzas, odds_por_partido, peso_modelo)
            if probs is None:
                continue
            pl, pe, pv = probs
            for equipo, rival, es_local in ((home, away, True), (away, home, False)):
                pe_eq = _probs_equipo(pl, pe, pv, es_local)
                equipos.add(_norm(equipo))
                celdas[(jnum, _norm(equipo))] = {
                    "equipo": equipo,
                    "rival": rival,
                    "condicion": "Local" if es_local else "Visitante",
                    **pe_eq,
                }
    return jornadas, sorted(equipos), celdas


def planificar(
    calendario: Sequence[Dict[str, Any]],
    fuerzas: Dict[str, Any],
    equipos_usados: Optional[Sequence[str]] = None,
    peso_victoria: float = PESO_VICTORIA,
    odds_por_partido: Optional[Dict[Tuple[str, str], Tuple[float, float, float]]] = None,
    peso_modelo: float = 0.5,
    descuento_visitante: float = DESCUENTO_VISITANTE,
    descuento_visitante_arranque: float = DESCUENTO_VISITANTE_ARRANQUE,
    jornadas_arranque: int = JORNADAS_ARRANQUE_PLAN,
) -> Dict[str, Any]:
    """
    Plan óptimo de temporada: qué equipo usar en cada jornada, sin repetir,
    maximizando supervivencia (no perder) y victorias.

    `calendario`: [{jornada:int, partidos:[{home_team, away_team}, ...]}, ...]
    `equipos_usados`: equipos ya gastados (se excluyen del pool).
    `peso_victoria`: cuánto premiar ganar vs solo no-perder (0 = solo sobrevivir).
    `odds_por_partido`: opcional {(home_norm, away_norm): (p_local,p_empate,p_visita)}.
    `descuento_visitante`: castigo (0..1) a la prob. de no-perder de picks
        VISITANTES al DECIDIR en qué jornada usarlos (fallan más). No cambia los
        % reales que se muestran; solo el valor de asignación. 0 = desactivado.
    `descuento_visitante_arranque`: descuento EXTRA para picks visitantes en las
        primeras `jornadas_arranque` jornadas (más sorpresas al inicio).
    """
    from scipy.optimize import linear_sum_assignment  # lazy import (dep ya fijada)
    import numpy as np

    usados = {_norm(e) for e in (equipos_usados or [])}
    jornadas, equipos_all, celdas = _opciones_por_jornada(calendario, fuerzas, odds_por_partido, peso_modelo)
    equipos = [e for e in equipos_all if e not in usados]

    if not jornadas or not equipos:
        return {
            "plan": [],
            "jornadas_total": len(jornadas),
            "equipos_disponibles": len(equipos),
            "calendario_incompleto": True,
            "mensaje": "Faltan jornadas o equipos (¿calendario vacío o sin histórico?).",
            "decision": DEC_INFORMATIVA,
        }

    # Jornadas de "arranque" = las primeras (más pequeñas) del calendario.
    arranque = set(sorted(jornadas)[: max(0, jornadas_arranque)])

    n_j, n_e = len(jornadas), len(equipos)
    NEG = -1e9
    valor = np.full((n_j, n_e), NEG, dtype=float)
    for i, jnum in enumerate(jornadas):
        for k, eq in enumerate(equipos):
            c = celdas.get((jnum, eq))
            if c is None:
                continue  # ese equipo no juega esa jornada (o sin histórico)
            p_np = c["p_no_perder"]
            p_win = c["p_ganar"]
            # Castigo por sorpresa a picks visitantes (solo para decidir, no para
            # mostrar): reduce su no-perder efectivo, extra en el arranque.
            if c["condicion"] == "Visitante":
                desc = descuento_visitante + (descuento_visitante_arranque if jnum in arranque else 0.0)
                desc = max(0.0, min(desc, 0.9))
                p_np = p_np * (1.0 - desc)
                p_win = p_win * (1.0 - desc)
            npd = max(p_np, _PROB_FLOOR)
            valor[i, k] = math.log(npd) + peso_victoria * p_win

    # Maximizar valor == minimizar -valor.
    filas, cols = linear_sum_assignment(-valor)

    plan: List[Dict[str, Any]] = []
    jornadas_sin_equipo: List[int] = []
    asignados: set = set()
    asign = dict(zip(filas.tolist(), cols.tolist()))
    for i, jnum in enumerate(jornadas):
        ki: Optional[int] = asign.get(i)
        if ki is None or valor[i, ki] <= NEG / 2:
            jornadas_sin_equipo.append(jnum)
            continue
        eq = equipos[ki]
        c = celdas[(jnum, eq)]
        asignados.add(eq)
        es_local = c["condicion"] == "Local"
        es_arranque = jnum in arranque
        item = {
            "jornada": jnum,
            "equipo": c["equipo"],
            "rival": c["rival"],
            "condicion": c["condicion"],
            "prob_ganar_pct": round(100.0 * c["p_ganar"], 1),
            "prob_empate_pct": round(100.0 * c["p_empate"], 1),
            "no_perder_pct": round(100.0 * c["p_no_perder"], 1),
            "nivel": _nivel_estrategico(c["p_no_perder"], c["p_ganar"], es_local, es_arranque),
        }
        if not es_local:
            item["ajuste_riesgo"] = "pick visitante: castigado al planear (de visita hay más sorpresas)"
        plan.append(item)

    plan.sort(key=lambda p: p["jornada"])
    prob_superv = 1.0
    for p in plan:
        prob_superv *= p["no_perder_pct"] / 100.0
    vict_esp = sum(p["prob_ganar_pct"] / 100.0 for p in plan)
    emp_esp = sum(p["prob_empate_pct"] / 100.0 for p in plan)
    riesgosas = [p["jornada"] for p in plan if p["nivel"] == "RIESGOSA"]
    # Mapa nombre_normalizado -> nombre de display (para mostrar bonito al usuario).
    display: Dict[str, str] = {}
    for (_jnum, eq_norm), c in celdas.items():
        display.setdefault(eq_norm, c["equipo"])
    no_usados = [display.get(e, e) for e in equipos if e not in asignados]

    return {
        "plan": plan,
        "jornadas_total": n_j,
        "equipos_disponibles": n_e,
        "prob_supervivencia_total_pct": round(100.0 * prob_superv, 2),
        "victorias_esperadas": round(vict_esp, 2),
        "empates_esperados": round(emp_esp, 2),
        "jornadas_riesgosas": riesgosas,
        "jornadas_sin_equipo": jornadas_sin_equipo,
        "equipos_no_usados": no_usados,
        "peso_victoria": peso_victoria,
        "calendario_incompleto": bool(jornadas_sin_equipo),
        "decision": DEC_INFORMATIVA,
    }


# ---------------------------------------------------------------------------
# Carga de calendario + CLI
# ---------------------------------------------------------------------------
def construir_odds_por_partido(
    calendario: Sequence[Dict[str, Any]],
    momios_crudos: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[Tuple[str, str], Tuple[float, float, float]]:
    """
    Construye {(home_norm, away_norm): (p_local, p_empate, p_visita)} sin vig,
    a partir de los momios reales de odds-api.io (comparador_mercado), casando
    cada partido del calendario con match flexible de nombres.

    `momios_crudos` se puede inyectar (tests). Sin key/momios => {} (no-op).
    """
    try:
        import comparador_mercado as cm
    except ImportError:  # pragma: no cover
        from src import comparador_mercado as cm  # type: ignore

    if momios_crudos is not None:
        momios = momios_crudos
    else:
        momios, _fuente = cm.momios_para_uso()
    if not momios:
        return {}
    out: Dict[Tuple[str, str], Tuple[float, float, float]] = {}
    for j in calendario:
        for partido in j.get("partidos", []):
            home, away = partido.get("home_team", ""), partido.get("away_team", "")
            mercado = cm.buscar_mercado_partido(home, away, momios)
            ml = (mercado or {}).get("ml")
            if not ml:
                continue
            try:
                dv = cm.quitar_vig(ml["local"], ml["empate"], ml["visita"])
            except (ValueError, KeyError, TypeError):
                continue
            out[(_norm(home), _norm(away))] = (dv["prob_local"], dv["prob_empate"], dv["prob_visita"])
    return out


# Calendario incrustado directamente (sin imports, sin archivos externos)
_CALENDARIO_INLINE = json.loads('[{"jornada":1,"fecha_inicio":"2026-07-16","fecha_fin":"2026-07-18","partidos":[{"home_team":"Necaxa","away_team":"Atlante"},{"home_team":"Tijuana","away_team":"Tigres UANL"},{"home_team":"Atlético de San Luis","away_team":"Cruz Azul"},{"home_team":"León","away_team":"Atlas"},{"home_team":"FC Juarez","away_team":"Puebla"},{"home_team":"Pumas UNAM","away_team":"Pachuca"},{"home_team":"Guadalajara","away_team":"Toluca"},{"home_team":"Monterrey","away_team":"Santos"},{"home_team":"Querétaro","away_team":"América"}]},{"jornada":2,"fecha_inicio":"2026-07-21","fecha_fin":"2026-07-26","partidos":[{"home_team":"Cruz Azul","away_team":"Puebla"},{"home_team":"Toluca","away_team":"Pumas UNAM"},{"home_team":"Tigres UANL","away_team":"Atlético de San Luis"},{"home_team":"Atlante","away_team":"América"},{"home_team":"Tijuana","away_team":"León"},{"home_team":"Guadalajara","away_team":"FC Juarez"},{"home_team":"Santos","away_team":"Atlas"},{"home_team":"Necaxa","away_team":"Monterrey"},{"home_team":"Pachuca","away_team":"Querétaro"}]},{"jornada":3,"fecha_inicio":"2026-07-31","fecha_fin":"2026-08-02","partidos":[{"home_team":"Puebla","away_team":"Guadalajara"},{"home_team":"Atlético de San Luis","away_team":"Tijuana"},{"home_team":"FC Juarez","away_team":"Pumas UNAM"},{"home_team":"Querétaro","away_team":"Tigres UANL"},{"home_team":"León","away_team":"Pachuca"},{"home_team":"Atlas","away_team":"Monterrey"},{"home_team":"Cruz Azul","away_team":"Atlante"},{"home_team":"América","away_team":"Santos"},{"home_team":"Toluca","away_team":"Necaxa"}]},{"jornada":4,"fecha_inicio":"2026-08-15","fecha_fin":"2026-08-17","partidos":[{"home_team":"Atlante","away_team":"Toluca"},{"home_team":"Monterrey","away_team":"FC Juarez"},{"home_team":"Atlas","away_team":"Tigres UANL"},{"home_team":"Pumas UNAM","away_team":"Querétaro"},{"home_team":"América","away_team":"Atlético de San Luis"},{"home_team":"Santos","away_team":"Guadalajara"},{"home_team":"Tijuana","away_team":"Cruz Azul"},{"home_team":"Necaxa","away_team":"León"},{"home_team":"Pachuca","away_team":"Puebla"}]},{"jornada":5,"fecha_inicio":"2026-08-21","fecha_fin":"2026-08-23","partidos":[{"home_team":"Puebla","away_team":"Santos"},{"home_team":"FC Juarez","away_team":"América"},{"home_team":"Querétaro","away_team":"Toluca"},{"home_team":"Guadalajara","away_team":"Tijuana"},{"home_team":"León","away_team":"Monterrey"},{"home_team":"Tigres UANL","away_team":"Atlante"},{"home_team":"Cruz Azul","away_team":"Atlas"},{"home_team":"Atlético de San Luis","away_team":"Pachuca"},{"home_team":"Pumas UNAM","away_team":"Necaxa"}]},{"jornada":6,"fecha_inicio":"2026-08-28","fecha_fin":"2026-08-30","partidos":[{"home_team":"Necaxa","away_team":"Cruz Azul"},{"home_team":"Atlante","away_team":"León"},{"home_team":"Tijuana","away_team":"Pumas UNAM"},{"home_team":"Atlas","away_team":"Querétaro"},{"home_team":"Pachuca","away_team":"Guadalajara"},{"home_team":"América","away_team":"Puebla"},{"home_team":"Santos","away_team":"Tigres UANL"},{"home_team":"Toluca","away_team":"FC Juarez"},{"home_team":"Monterrey","away_team":"Atlético de San Luis"}]},{"jornada":7,"fecha_inicio":"2026-09-04","fecha_fin":"2026-09-06","partidos":[{"home_team":"Puebla","away_team":"Toluca"},{"home_team":"FC Juarez","away_team":"Pachuca"},{"home_team":"Atlético de San Luis","away_team":"Guadalajara"},{"home_team":"Querétaro","away_team":"Monterrey"},{"home_team":"Tigres UANL","away_team":"Necaxa"},{"home_team":"América","away_team":"Tijuana"},{"home_team":"Atlas","away_team":"Atlante"},{"home_team":"Pumas UNAM","away_team":"León"},{"home_team":"Cruz Azul","away_team":"Santos"}]},{"jornada":8,"fecha_inicio":"2026-09-11","fecha_fin":"2026-09-13","partidos":[{"home_team":"Necaxa","away_team":"Puebla"},{"home_team":"Atlante","away_team":"Pachuca"},{"home_team":"Tijuana","away_team":"Querétaro"},{"home_team":"León","away_team":"Atlético de San Luis"},{"home_team":"Toluca","away_team":"Atlas"},{"home_team":"Cruz Azul","away_team":"América"},{"home_team":"Santos","away_team":"FC Juarez"},{"home_team":"Guadalajara","away_team":"Pumas UNAM"},{"home_team":"Monterrey","away_team":"Tigres UANL"}]},{"jornada":9,"fecha_inicio":"2026-09-18","fecha_fin":"2026-09-20","partidos":[{"home_team":"Puebla","away_team":"Atlante"},{"home_team":"FC Juarez","away_team":"Tigres UANL"},{"home_team":"Atlas","away_team":"Pumas UNAM"},{"home_team":"Atlético de San Luis","away_team":"Necaxa"},{"home_team":"Monterrey","away_team":"Cruz Azul"},{"home_team":"América","away_team":"Guadalajara"},{"home_team":"Pachuca","away_team":"Tijuana"},{"home_team":"Toluca","away_team":"Santos"},{"home_team":"Querétaro","away_team":"León"}]},{"jornada":10,"fecha_inicio":"2026-09-25","fecha_fin":"2026-09-27","partidos":[{"home_team":"Atlante","away_team":"Monterrey"},{"home_team":"Tijuana","away_team":"Atlas"},{"home_team":"Guadalajara","away_team":"Querétaro"},{"home_team":"Santos","away_team":"Pachuca"},{"home_team":"Tigres UANL","away_team":"Puebla"},{"home_team":"Cruz Azul","away_team":"Toluca"},{"home_team":"Pumas UNAM","away_team":"Atlético de San Luis"},{"home_team":"León","away_team":"FC Juarez"},{"home_team":"Necaxa","away_team":"América"}]},{"jornada":11,"fecha_inicio":"2026-10-09","fecha_fin":"2026-10-11","partidos":[{"home_team":"Querétaro","away_team":"Atlante"},{"home_team":"Puebla","away_team":"León"},{"home_team":"Tigres UANL","away_team":"Toluca"},{"home_team":"FC Juarez","away_team":"Tijuana"},{"home_team":"Atlas","away_team":"Guadalajara"},{"home_team":"América","away_team":"Monterrey"},{"home_team":"Pachuca","away_team":"Necaxa"},{"home_team":"Atlético de San Luis","away_team":"Santos"},{"home_team":"Pumas UNAM","away_team":"Cruz Azul"}]},{"jornada":12,"fecha_inicio":"2026-10-16","fecha_fin":"2026-10-18","partidos":[{"home_team":"Necaxa","away_team":"Atlas"},{"home_team":"Atlante","away_team":"Pumas UNAM"},{"home_team":"Tijuana","away_team":"Puebla"},{"home_team":"Guadalajara","away_team":"Tigres UANL"},{"home_team":"Santos","away_team":"Querétaro"},{"home_team":"León","away_team":"América"},{"home_team":"Toluca","away_team":"Atlético de San Luis"},{"home_team":"Cruz Azul","away_team":"FC Juarez"},{"home_team":"Monterrey","away_team":"Pachuca"}]},{"jornada":13,"fecha_inicio":"2026-10-20","fecha_fin":"2026-10-21","partidos":[{"home_team":"Atlético de San Luis","away_team":"Querétaro"},{"home_team":"FC Juarez","away_team":"Atlante"},{"home_team":"Tigres UANL","away_team":"León"},{"home_team":"Guadalajara","away_team":"Necaxa"},{"home_team":"Puebla","away_team":"Monterrey"},{"home_team":"Atlas","away_team":"América"},{"home_team":"Toluca","away_team":"Tijuana"},{"home_team":"Pachuca","away_team":"Cruz Azul"},{"home_team":"Santos","away_team":"Pumas UNAM"}]},{"jornada":14,"fecha_inicio":"2026-10-23","fecha_fin":"2026-10-25","partidos":[{"home_team":"Necaxa","away_team":"FC Juarez"},{"home_team":"Atlante","away_team":"Atlético de San Luis"},{"home_team":"León","away_team":"Toluca"},{"home_team":"Monterrey","away_team":"Guadalajara"},{"home_team":"Pumas UNAM","away_team":"Tigres UANL"},{"home_team":"Atlas","away_team":"Puebla"},{"home_team":"América","away_team":"Pachuca"},{"home_team":"Querétaro","away_team":"Cruz Azul"},{"home_team":"Tijuana","away_team":"Santos"}]},{"jornada":15,"fecha_inicio":"2026-10-30","fecha_fin":"2026-11-01","partidos":[{"home_team":"Atlético de San Luis","away_team":"Atlas"},{"home_team":"FC Juarez","away_team":"Querétaro"},{"home_team":"Puebla","away_team":"Pumas UNAM"},{"home_team":"Pachuca","away_team":"Tigres UANL"},{"home_team":"Guadalajara","away_team":"Atlante"},{"home_team":"Monterrey","away_team":"Tijuana"},{"home_team":"América","away_team":"Toluca"},{"home_team":"Santos","away_team":"Necaxa"},{"home_team":"Cruz Azul","away_team":"León"}]},{"jornada":16,"fecha_inicio":"2026-11-06","fecha_fin":"2026-11-08","partidos":[{"home_team":"Atlético de San Luis","away_team":"FC Juarez"},{"home_team":"Necaxa","away_team":"Tijuana"},{"home_team":"Atlante","away_team":"Santos"},{"home_team":"Atlas","away_team":"Pachuca"},{"home_team":"Tigres UANL","away_team":"Cruz Azul"},{"home_team":"Toluca","away_team":"Monterrey"},{"home_team":"Pumas UNAM","away_team":"América"},{"home_team":"Querétaro","away_team":"Puebla"},{"home_team":"León","away_team":"Guadalajara"}]},{"jornada":17,"fecha_inicio":"2026-11-20","fecha_fin":"2026-11-22","partidos":[{"home_team":"Puebla","away_team":"Atlético de San Luis"},{"home_team":"FC Juarez","away_team":"Atlas"},{"home_team":"Tijuana","away_team":"Atlante"},{"home_team":"Santos","away_team":"León"},{"home_team":"Pachuca","away_team":"Toluca"},{"home_team":"Pumas UNAM","away_team":"Monterrey"},{"home_team":"Tigres UANL","away_team":"América"},{"home_team":"Guadalajara","away_team":"Cruz Azul"},{"home_team":"Querétaro","away_team":"Necaxa"}]}]')

def cargar_calendario(path: Path = CALENDARIO_PATH) -> List[Dict[str, Any]]:
    """
    Carga data/calendario.json (o usa fallback incrustado inline).
    """
    # Intentar cargar desde archivo
    p = Path(path)
    if p.exists() and p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list):
                salida = [j for j in data if isinstance(j, dict) and "jornada" in j and isinstance(j.get("partidos"), list)]
                if salida:
                    return salida
        except (json.JSONDecodeError, OSError):
            pass
    
    # Fallback: usar datos incrustados inline (SIEMPRE funciona)
    return [j for j in _CALENDARIO_INLINE if isinstance(j, dict) and "jornada" in j and isinstance(j.get("partidos"), list)]

def main() -> int:
    try:
        import fuentes_datos
    except ImportError:  # pragma: no cover
        from src import fuentes_datos  # type: ignore

    print("📅 Planificador de temporada Survivor (PlayDoit)...")
    calendario = cargar_calendario()
    if not calendario:
        print("⚠️  No hay calendario completo en data/calendario.json.")
        print(
            '    Esquema esperado: [{"jornada": 1, "partidos": [{"home_team": "...", "away_team": "..."}, ...]}, ...]'
        )
        print("    El calendario del Apertura 2026 se publica cerca del 17-jul;")
        print("    cuando lo tengas, guárdalo ahí y vuelve a correr esto.")
        return 0

    datos = fuentes_datos.obtener_resultados(meses=18)
    try:
        fuerzas = pm.calcular_fuerzas(datos["resultados"])
    except ValueError:
        print("⚠️  Sin histórico suficiente para estimar fuerzas.")
        return 0

    r = planificar(calendario, fuerzas)
    print(f"Fuente: {datos['fuente']} | jornadas: {r['jornadas_total']} | equipos: {r['equipos_disponibles']}")
    print(
        f"Prob. de sobrevivir TODA la temporada: {r['prob_supervivencia_total_pct']}% | "
        f"victorias esperadas: {r['victorias_esperadas']}"
    )
    for p in r["plan"]:
        print(
            f"  J{p['jornada']:>2}: {p['equipo']} ({p['condicion']} vs {p['rival']}) "
            f"— ganar {p['prob_ganar_pct']}% / no-perder {p['no_perder_pct']}% [{p['nivel']}]"
        )
    if r["jornadas_riesgosas"]:
        print(f"⚠️  Jornadas riesgosas: {r['jornadas_riesgosas']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
