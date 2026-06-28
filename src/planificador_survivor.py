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
from typing import Any, Dict, List, Optional, Sequence, Tuple

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
    return pm._norm(t)


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
                    "equipo": equipo, "rival": rival,
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
) -> Dict[str, Any]:
    """
    Plan óptimo de temporada: qué equipo usar en cada jornada, sin repetir,
    maximizando supervivencia (no perder) y victorias.

    `calendario`: [{jornada:int, partidos:[{home_team, away_team}, ...]}, ...]
    `equipos_usados`: equipos ya gastados (se excluyen del pool).
    `peso_victoria`: cuánto premiar ganar vs solo no-perder (0 = solo sobrevivir).
    `odds_por_partido`: opcional {(home_norm, away_norm): (p_local,p_empate,p_visita)}.
    """
    from scipy.optimize import linear_sum_assignment  # lazy import (dep ya fijada)
    import numpy as np

    usados = {_norm(e) for e in (equipos_usados or [])}
    jornadas, equipos_all, celdas = _opciones_por_jornada(
        calendario, fuerzas, odds_por_partido, peso_modelo
    )
    equipos = [e for e in equipos_all if e not in usados]

    if not jornadas or not equipos:
        return {
            "plan": [], "jornadas_total": len(jornadas), "equipos_disponibles": len(equipos),
            "calendario_incompleto": True,
            "mensaje": "Faltan jornadas o equipos (¿calendario vacío o sin histórico?).",
            "decision": DEC_INFORMATIVA,
        }

    n_j, n_e = len(jornadas), len(equipos)
    NEG = -1e9
    valor = np.full((n_j, n_e), NEG, dtype=float)
    for i, jnum in enumerate(jornadas):
        for k, eq in enumerate(equipos):
            c = celdas.get((jnum, eq))
            if c is None:
                continue  # ese equipo no juega esa jornada (o sin histórico)
            npd = max(c["p_no_perder"], _PROB_FLOOR)
            valor[i, k] = math.log(npd) + peso_victoria * c["p_ganar"]

    # Maximizar valor == minimizar -valor.
    filas, cols = linear_sum_assignment(-valor)

    plan: List[Dict[str, Any]] = []
    jornadas_sin_equipo: List[int] = []
    asignados: set = set()
    asign = dict(zip(filas.tolist(), cols.tolist()))
    for i, jnum in enumerate(jornadas):
        k = asign.get(i)
        if k is None or valor[i, k] <= NEG / 2:
            jornadas_sin_equipo.append(jnum)
            continue
        eq = equipos[k]
        c = celdas[(jnum, eq)]
        asignados.add(eq)
        plan.append({
            "jornada": jnum,
            "equipo": c["equipo"],
            "rival": c["rival"],
            "condicion": c["condicion"],
            "prob_ganar_pct": round(100.0 * c["p_ganar"], 1),
            "prob_empate_pct": round(100.0 * c["p_empate"], 1),
            "no_perder_pct": round(100.0 * c["p_no_perder"], 1),
            "nivel": _nivel(c["p_no_perder"], c["p_ganar"]),
        })

    plan.sort(key=lambda p: p["jornada"])
    prob_superv = 1.0
    for p in plan:
        prob_superv *= p["no_perder_pct"] / 100.0
    vict_esp = sum(p["prob_ganar_pct"] / 100.0 for p in plan)
    emp_esp = sum(p["prob_empate_pct"] / 100.0 for p in plan)
    riesgosas = [p["jornada"] for p in plan if p["nivel"] == "RIESGOSA"]
    no_usados = [e for e in equipos if e not in asignados]

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

    momios = momios_crudos if momios_crudos is not None else cm.obtener_momios_liga_mx()
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
            out[(_norm(home), _norm(away))] = (
                dv["prob_local"], dv["prob_empate"], dv["prob_visita"]
            )
    return out


def cargar_calendario(path: Path = CALENDARIO_PATH) -> List[Dict[str, Any]]:
    """
    Carga data/calendario.json con el esquema:
        [{"jornada": 1, "partidos": [{"home_team","away_team"}, ...]}, ...]
    Devuelve [] si no existe o no tiene el esquema esperado (no rompe).
    """
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    salida = []
    for j in data:
        if isinstance(j, dict) and "jornada" in j and isinstance(j.get("partidos"), list):
            salida.append(j)
    return salida


def main() -> int:
    try:
        import fuentes_datos
    except ImportError:  # pragma: no cover
        from src import fuentes_datos  # type: ignore

    print("📅 Planificador de temporada Survivor (PlayDoit)...")
    calendario = cargar_calendario()
    if not calendario:
        print("⚠️  No hay calendario completo en data/calendario.json.")
        print("    Esquema esperado: [{\"jornada\": 1, \"partidos\": "
              "[{\"home_team\": \"...\", \"away_team\": \"...\"}, ...]}, ...]")
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
    print(f"Fuente: {datos['fuente']} | jornadas: {r['jornadas_total']} | "
          f"equipos: {r['equipos_disponibles']}")
    print(f"Prob. de sobrevivir TODA la temporada: {r['prob_supervivencia_total_pct']}% | "
          f"victorias esperadas: {r['victorias_esperadas']}")
    for p in r["plan"]:
        print(f"  J{p['jornada']:>2}: {p['equipo']} ({p['condicion']} vs {p['rival']}) "
              f"— ganar {p['prob_ganar_pct']}% / no-perder {p['no_perder_pct']}% [{p['nivel']}]")
    if r["jornadas_riesgosas"]:
        print(f"⚠️  Jornadas riesgosas: {r['jornadas_riesgosas']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
