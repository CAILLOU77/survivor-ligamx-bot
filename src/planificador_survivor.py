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


_CALENDARIO_FALLBACK_B85 = """TYDmEZ*p#7WMLvYATcZ;B4%Y{XklMzZfRp_Zz4J%A~G;CHZ3qWEipDCEFdCgWn*YzUuJ1;B03-<GB7eWEigANF*qVDAR=&Ka&&2AZ*w9#AX|GPXm4$0Uvy<*Z6Z1#B2HyvVR&I8EFdCbcVT&7bY)>}B03-<L3C_kZggcLeJmh*B4}@IWnXk<VQnHhAR<(0YIR|5VInLbB4Kx7d0%v8VQnHhAR<(0XL4n8AXPz5Od@?OAbTQcZ*65?bY)>}B03-<L3C_fbuchxIdo}bZy;o4AX8y(AWU^>b0RDtB4Kx7d0%v8VQnHhAR<F@b$TE{dUb3feJmh*B4}@IWnXk<VQnHhAR<g<Ty-!oW;1RgEFdCbcVT&7bY)>}B03-<L3C_kb0U2#AbTQcZ*65?bY)>}B03-<MnfP<bzyR4dLk?!B4Kx7d0%v8VQnHhAR<t8Wnye$B7H0%dm?CWZDn6{Wnpb1Iv^rYb!}mDAXQF5O(HBHB4Kx7d0%v8VQnHhAR<s<V`z0_VIqAjAbTQcZ*65?bY)>}B03-<M|ELjVQgV)VRB(2EFdCbcVT&7bY)>}B03-<RBvo`V__nFEFgO#Xm4$0Uvy<*Z6Z1#B28~@bY*gKWqBejAR=LRVR>J4Wnpb1Iv^rbVQzG9b0U2#AbTQcZ*65?bY)>}B03-<QFUc<Ty-!oWjS<Va&ICmAR=LRVR>J4Wnpb1Iv^rJZCrIQFl9M%X=7m`eO-MlAbTQeZ*p#7WMLvYATlf<B4%Y{XklMzZfRp_Zz4J%A~G;CHZ3qWEiy48EFdCgWn*YzUuJ1;B03-<GB7eWEigANGBzSCAR=&Ka&&2AZ*w9#AX|GPXm4$0Uvy<*Z6Z1#B13X@dLTi1b!;LmAR=LRVR>J4Wnpb1Iv^rYb!B2~VIqAjAbTQcZ*65?bY)>}B03-<RBvo`V__mJAR=LRVR>J4Wnpb1Iv^rYb!}mDAXQF5O(K0PAbTQcZ*65?bY)>}B03-<RB2~&Wpf}^K~78}EFdCbcVT&7bY)>}B03-<L3C_fbuchxIdo}bZy;o4AX8y(AWU^>b0U2#AbTQcZ*65?bY)>}B03-<L3C_kZggcLEFdCbcVT&7bY)>}B03-<L2X=hFfe5~a%p2>B7H0%dm?CWZDn6{Wnpb1Iv^rcX=-(0Zeb!UAR=LRVR>J4Wnpb1Iv^rUWn6VIFlIAuB7H0%dm?CWZDn6{Wnpb1Iv^rPbzx*-Y+-6)a$zDYAR=LRVR>J4Wnpb1Iv^rOLm*0ZVRB`9B7H0%dm?CWZDn6{Wnpb1Iv^rbVQzG9b0RDtB4Kx7d0%v8VQnHhAR<9@Y+-XEeJmh*B4}@IWnXk<VQnHhAR<m>V_|q<A}k;xVRvD9Uvy<*Z6Z1#B28~@bY*gKWqBffEFgO#Xm4$0Uvy<*Z6Z1#B2ZytXmw*@A}k;xVRvD9Uvy<*Z6Z1#B2jf^a$I#VFl9M(VRCOGeO-MlAbTQeZ*p#7WMLvYATul=B4%Y{XklMzZfRp_Zz4J%A~G;CHZ3qWEi*A9EFdCgWn*YzUuJ1;B03-<GB7eWEigDOFft-6AR=&Ka&&2AZ*w9#AX|GPXm4$0Uvy<*Z6Z1#B2aZ@Vr*d|EFdCbcVT&7bY)>}B03-<M|ELjVQgV)VRB(2eJmh*B4}@IWnXk<VQnHhAR<9@Y+Q9PFl9M(X=867WMv>zVQwHyb!l@VEFdCbcVT&7bY)>}B03-<RB38;VQyg}eJmh*B4}@IWnXk<VQnHhAR<OXAWC&%a%FlVEFdCbcVT&7bY)>}B03-<P<3r#b0AetK}{lkEFgO#Xm4$0Uvy<*Z6Z1#B2jf^a$I#VFl9M(VRCOGEFdCbcVT&7bY)>}B03-<RB2~&Wpf}^K~78}eJmh*B4}@IWnXk<VQnHhAR<g<Ty-!oW;1RgEFdCbcVT&7bY)>}B03-<P+?<ebz@;7eJmh*B4}@IWnXk<VQnHhAR<9@Y+-XEEFdCbcVT&7bY)>}B03-<O>b^=WpZ+5c_Mu*AbTQcZ*65?bY)>}B03-<LvnR`AVGR{Y$7ZmB4Kx7d0%v8VQnHhAR<9@Y+-J6Wg>knAbTQcZ*65?bY)>}B03-<L2X=hFfe5~a%p2>A}k;xVRvD9Uvy<*Z6Z1#B2!^*bZ>JaeJmh*B4}@IWnXk<VQnHhAR<(6Y;|K{A}k;xVRvD9Uvy<*Z6Z1#B2HyvVR&I8eO-MlAbTQeZ*p#7WMLvYAT%r>B4%Y{XklMzZfRp_Zz4J%A~G;CHZ3qXEipABEFdCgWn*YzUuJ1;B03-<GB7eWEigDOF*hPCAR=&Ka&&2AZ*w9#AX|GPXm4$0Uvy<*Z6Z1#B0+R)VQzF~A}k;xVRvD9Uvy<*Z6Z1#B2;f|bz@;7eJmh*B4}@IWnXk<VQnHhAR<j~ZggdGa%FiUEFdCbcVT&7bY)>}B03-<MnfP<bzyR4dLn%+AbTQcZ*65?bY)>}B03-<L3C_kb0RDtB4Kx7d0%v8VQnHhAR<(0XL4n8AXPz5Od@?OAbTQcZ*65?bY)>}B03-<P<3r#b0AetK}{koAR=LRVR>J4Wnpb1Iv^rZb!Bo~buchxIdoxiZz6pxAbTQcZ*65?bY)>}B03-<L2X=hFfe5~a%p2>A}k;xVRvD9Uvy<*Z6Z1#B0+R)Ty-!oWjS<dV{ag2Wgt^wZXir`X>%fdEFgO#Xm4$0Uvy<*Z6Z1#B2!^*bZ>JaEFdCbcVT&7bY)>}B03-<M|ELjVQgV)VRB(2eJmh*B4}@IWnXk<VQnHhAR<(0YIR|5VInLbB4Kx7d0%v8VQnHhAR<F@b$TE{dUb3feJmh*B4}@IWnXk<VQnHhAR<m>V_|q<A}k;xVRvD9Uvy<*Z6Z1#B1~mmbuchyGj1Y%EFgO#Xm4$0Uvy<*Z6Z1#B2ZytXmw*@A}k;xVRvD9Uvy<*Z6Z1#B2aZ@Vr*d|eO-MlAbTQeZ*p#7WMLvYAT=x?B4%Y{XklMzZfRp_Zz4J%A~G;CHZ3qXEiy48EFdCgWn*YzUuJ1;B03-<GB7eWEigDOGBYA9AR=&Ka&&2AZ*w9#AX|GPXm4$0Uvy<*Z6Z1#B2aZ@Vr*d|EFdCbcVT&7bY)>}B03-<Q(<m&Z*wAjEFgO#Xm4$0Uvy<*Z6Z1#B1S_XN_Am!WqKkkAR=LRVR>J4Wnpb1Iv^rJZCrIQFl9M%X=7m`eJmh*B4}@IWnXk<VQnHhAR<w9WpZ3~Ffe5~bYXIDA}k;xVRvD9Uvy<*Z6Z1#B2;f|bz@;7eJmh*B4}@IWnXk<VQnHhAR<R~VPs)!VQOJ=VInLbB4Kx7d0%v8VQnHhAR<(0YIR|5VIqAjAbTQcZ*65?bY)>}B03-<Ol4ekFfe8_ZXzroB4Kx7d0%v8VQnHhAR<j~ZggdGa%FiUeJmh*B4}@IWnXk<VQnHhAR<(0XL4n8AXPz5Od>2GB4Kx7d0%v8VQnHhAR<9@Y+-J6Wg>knAbTQcZ*65?bY)>}B03-<LvnR`AVGR{Y$7ZmB4Kx7d0%v8VQnHhAR<9@Y+-XEeJmh*B4}@IWnXk<VQnHhAR<9@Y+Q9PFl9M(X=867WMv>zVQwHyb!l@VEFdCbcVT&7bY)>}B03-<P+?<ebz@;7eJmh*B4}@IWnXk<VQnHhAR<t8ZDDgDRZc-oA}k;xVRvD9Uvy<*Z6Z1#B2HyvVR&I8eO-MlAbTQeZ*p#7WMLvYAT}%@B4%Y{XklMzZfRp_Zz4J%A~G;CHZ3qXEiyPFEFdCgWn*YzUuJ1;B03-<GB7eWEigDOGcY17AR=&Ka&&2AZ*w9#AX|GPXm4$0Uvy<*Z6Z1#B2HyvVR&I8EFdCbcVT&7bY)>}B03-<LvnR`AVGR{Y$AOuAbTQcZ*65?bY)>}B03-<L3C_kZggcLEFdCbcVT&7bY)>}B03-<Ol4ekFfe8_ZX$gwAbTQcZ*65?bY)>}B03-<RB38;VQyg}EFdCbcVT&7bY)>}B03-<P<3r#b0AetK}{lkEFgO#Xm4$0Uvy<*Z6Z1#B0+R)VRIrZAR=LRVR>J4Wnpb1Iv^rZb!Bo~buchxIdoxiZz6pxAbTQcZ*65?bY)>}B03-<P+?<ebz@;7EFdCbcVT&7bY)>}B03-<M|ELjVQgV)VRB(2eJmh*B4}@IWnXk<VQnHhAR<9+Ty-!oWjS(bV__mJAR=LRVR>J4Wnpb1Iv^rYb!B2~VIqAjAbTQcZ*65?bY)>}B03-<Q(<m&Z*w9nAR=LRVR>J4Wnpb1Iv^rcX=id}b0AegPD~<wEFgO#Xm4$0Uvy<*Z6Z1#B2;f|bz@;7EFdCbcVT&7bY)>}B03-<MnfP<bzyR4dLn%+AbTQcZ*65?bY)>}B03-<O>b^=WpZ+5c_J(zB4Kx7d0%v8VQnHhAR<9@Y+Q9PFl9M(X=867WMv>zVQwHyb!l@VeO-MlAbTQeZ*p#7WMLvYAU7-^B4%Y{XklMzZfRp_Zz4J%A~G;CHZ3qYEig19EFdCgWn*YzUuJ1;B03-<GB7eWEigGPFg7AAAR=&Ka&&2AZ*w9#AX|GPXm4$0Uvy<*Z6Z1#B2aZ@Vr*d|EFdCbcVT&7bY)>}B03-<RBvo`V__nFEFgO#Xm4$0Uvy<*Z6Z1#B1S_XN_Am!WqKkkAR=LRVR>J4Wnpb1Iv^rYVPj}@V__nFEFgO#Xm4$0Uvy<*Z6Z1#B0+R)Ty-!oWjS<dV{ag2Wgt^wZXir`X>%ehAR=LRVR>J4Wnpb1Iv^rPbzx*-Y+-6)a$zEUEFgO#Xm4$0Uvy<*Z6Z1#B2jf^a$I#VFl9M(VRCOGEFdCbcVT&7bY)>}B03-<O>b^=WpZ+5c_Mu*AbTQcZ*65?bY)>}B03-<RB2~&Wpf}^K~78}EFdCbcVT&7bY)>}B03-<PGw_Zcwr)aEFgO#Xm4$0Uvy<*Z6Z1#B0+6jbuchxIdW-ZVInLbB4Kx7d0%v8VQnHhAR<(0YIR|5VIqAjAbTQcZ*65?bY)>}B03-<L3C_kb0RDtB4Kx7d0%v8VQnHhAR<9@Y+-J6Wg>knAbTQcZ*65?bY)>}B03-<P<3r#b0AetK}{koAR=LRVR>J4Wnpb1Iv^rUWn6VIFlIAuB7H0%dm?CWZDn6{Wnpb1Iv^rLa&>wjL3(v;A}k;xVRvD9Uvy<*Z6Z1#B2!^*bZ>JaeO-MlAbTQeZ*p#7WMLvYAUG@_B4%Y{XklMzZfRp_Zz4J%A~G;CHZ3qYEio}7EFdCgWn*YzUuJ1;B03-<GB7eWEigGPF*718AR=&Ka&&2AZ*w9#AX|GPXm4$0Uvy<*Z6Z1#B2HyvVR&I8EFdCbcVT&7bY)>}B03-<P<3TuY+)jOEFgO#Xm4$0Uvy<*Z6Z1#B0+R)VQzF~A}k;xVRvD9Uvy<*Z6Z1#B2ZytXmw*@B7H0%dm?CWZDn6{Wnpb1Iv^rcX=-(0Zeb!UAR=LRVR>J4Wnpb1Iv^rZb!Bo~buchxIdoxiZz6pxAbTQcZ*65?bY)>}B03-<Ol4ekFfe8_ZXzroB4Kx7d0%v8VQnHhAR<9@Y+Q9PFl9M(X=867WMv>zVQwHyb!l@VeJmh*B4}@IWnXk<VQnHhAR<(6Y;|K{A}k;xVRvD9Uvy<*Z6Z1#B0+R)VRIsVEFgO#Xm4$0Uvy<*Z6Z1#B13X@dLTi1b!;LmAR=LRVR>J4Wnpb1Iv^rJZCrIQFl9M%X=7m`eJmh*B4}@IWnXk<VQnHhAR<#?Zgg*RA}k;xVRvD9Uvy<*Z6Z1#B1S_XN_Am!WqKlgEFgO#Xm4$0Uvy<*Z6Z1#B1d&$WMOP!YGHC=A}k;xVRvD9Uvy<*Z6Z1#B2aa0VRIl=PC-o~eJmh*B4}@IWnXk<VQnHhAR<j~ZggdGa%FiUEFdCbcVT&7bY)>}B03-<RB2~&Wpf}^K~78}eO-MlAbTQeZ*p#7WMLvYAUP}`B4%Y{XklMzZfRp_Zz4J%A~G;CHZ3qYEipJEEFdCgWn*YzUuJ1;B03-<GB7eWEigGPGB6@6AR=&Ka&&2AZ*w9#AX|GPXm4$0Uvy<*Z6Z1#B2aZ@Vr*d|EFdCbcVT&7bY)>}B03-<L3C_kZggcLeJmh*B4}@IWnXk<VQnHhAR<OXAWC&%a%FlVEFdCbcVT&7bY)>}B03-<RB2~&Wpf}^K~78}eJmh*B4}@IWnXk<VQnHhAR<9@Y+-XEEFdCbcVT&7bY)>}B03-<P<3r#b0AetK}{lkEFgO#Xm4$0Uvy<*Z6Z1#B0+R)Ty-!oWjS<dV{ag2Wgt^wZXir`X>%ehAR=LRVR>J4Wnpb1Iv^rWWn*D@VIqAjAbTQcZ*65?bY)>}B03-<O>b^=WpZ+5c_J(zB4Kx7d0%v8VQnHhAR<F@b$TE{dUb3feJmh*B4}@IWnXk<VQnHhAR<9+Ty-!oWjS(bV__mJAR=LRVR>J4Wnpb1Iv^rPbzx*-Y+-6)a$zEUEFgO#Xm4$0Uvy<*Z6Z1#B2ZytXmw*@A}k;xVRvD9Uvy<*Z6Z1#B2;N=bzyE{B7H0%dm?CWZDn6{Wnpb1Iv^rcZ)|mAVInLbB4Kx7d0%v8VQnHhAR<#?Zgg*RB7H0%dm?CWZDn6{Wnpb1Iv^rZb!Bo~buchxIdoxiZz3!pB4Kx7d0%v8VQnHhAR<g<Ty-!oW;1RgeO-MlAbTQeZ*p#7WMLvYATcm3AR=aEV`yPtX>Ms_X>TGrAR;m_GBzzRIW00ZA}k;xW@Te&VP9rxZX!A$A~G;CHZ3qYEiyMEEFdCqVRCe7WN&jKIv`tnB4}@IWnXk<VQnHhAR<9@Y+-J6Wg;vfB4Kx7d0%v8VQnHhAR<j~ZggdGa%FiUeJmh*B4}@IWnXk<VQnHhAR<(0YIR|5VInLbB4Kx7d0%v8VQnHhAR<9@Y+-XEeJmh*B4}@IWnXk<VQnHhAR<R~VPs)!VQOJ=VInLbB4Kx7d0%v8VQnHhAR<w9WpZ3~Ffe5~bYXIDB7H0%dm?CWZDn6{Wnpb1Iv^rbVQzG9b0RDtB4Kx7d0%v8VQnHhAR<s<V`z0_VIqAjAbTQcZ*65?bY)>}B03-<RB2~&Wpf}^K~78}EFdCbcVT&7bY)>}B03-<P<3TuY+)jOEFgO#Xm4$0Uvy<*Z6Z1#B13X@dLTi1b!;LmAR=LRVR>J4Wnpb1Iv^rcZ)|mAVIqAjAbTQcZ*65?bY)>}B03-<P<3r#b0AetK}{koAR=LRVR>J4Wnpb1Iv^rJbZlI8Ffe5~bZKL6AY^4AQ(<l(Om%5<B7H0%dm?CWZDn6{Wnpb1Iv^rUWn6VIFlIAuA}k;xVRvD9Uvy<*Z6Z1#B1S_XN_Am!WqKlgEFgO#Xm4$0Uvy<*Z6Z1#B2HyvVR&I8EFdCbcVT&7bY)>}B03-<L2X=hFfe5~a%p2>B7I$bEFgO#YHxCGVPs(<Iv_DIEFdCgWn*YzUukY>V`*<9Iv^r4FfukRF)%GKIU+0|B4%Y{XklMwX>KAqAR;m_GBzzSFfB1LA}k;xaA9(EX=HD6B03;jdm?CWZDn6{Wnpb1Iv^rZb!Bo~buchxIdoxiZz3!pB4Kx7d0%v8VQnHhAR<9@Y+-J6Wg>knAbTQcZ*65?bY)>}B03-<P<3TuY+)iSAR=LRVR>J4Wnpb1Iv^rUWn6VIFlIAuB7H0%dm?CWZDn6{Wnpb1Iv^rcX=id}b0AegPD~;!AR=LRVR>J4Wnpb1Iv^rcZ)|mAVIqAjAbTQcZ*65?bY)>}B03-<MnfP<bzyR4dLk?!B4Kx7d0%v8VQnHhAR<(0YIR|5VIqAjAbTQcZ*65?bY)>}B03-<L3C_kb0RDtB4Kx7d0%v8VQnHhAR<R~VPs)!VQOJ=VIqAjAbTQcZ*65?bY)>}B03-<L2X=hFfe5~a%p2>A}k;xVRvD9Uvy<*Z6Z1#B28~@bY*gKWqBffEFgO#Xm4$0Uvy<*Z6Z1#B2ZytXmw*@A}k;xVRvD9Uvy<*Z6Z1#B2HyvVR&I8eJmh*B4}@IWnXk<VQnHhAR<9@Y+Q9PFl9M(X=867WMv>zVQwHyb!l@VEFdCbcVT&7bY)>}B03-<Q(<m&Z*wAjEFgO#Xm4$0Uvy<*Z6Z1#B2aa0VRIl=PC-o~EFdCbcVT&7bY)>}B03-<LvnR`AVGR{Y$APKeJmh*B5H4PZee6$B03;3GAtk>W@Te&VP9!(X=7<`B03-<GB7eWEio`HF*YJBAR=aEV`yPtW@&CBIv^r4FfukRF)%GLI3g?{B5+}HbZKO7b0Rt*TYDmCZ*65?bY)>}B03-<PGw_Zcwr(eAR=LRVR>J4Wnpb1Iv^rJbZlXBB7H0%dm?CWZDn6{Wnpb1Iv^rJbZlX6bY&teAR=LRVR>J4Wnpb1Iv^rYb!}mDAXQF5O(K0PAbTQcZ*65?bY)>}B03-<RB38;VQyg}EFdCbcVT&7bY)>}B03-<P<3TuY+)jOEFgO#Xm4$0Uvy<*Z6Z1#B1d&$WMOP!YGHC=A}k;xVRvD9Uvy<*Z6Z1#B2;N-a%FQMRY6WnB7H0%dm?CWZDn6{Wnpb1Iv^rbVQzG9b0RDtB4Kx7d0%v8VQnHhAR<w9WpZ3~Ffe5~bYXIDB7H0%dm?CWZDn6{Wnpb1Iv^rUWn6VIFlIAuA}k;xVRvD9Uvy<*Z6Z1#B0+6jbuchxIdW-ZVIqAjAbTQcZ*65?bY)>}B03-<RBvo`V__mJAR=LRVR>J4Wnpb1Iv^rJbZlI8Ffe5~bZKL6AY^4AQ(<l(Om%5<B7H0%dm?CWZDn6{Wnpb1Iv^rLa&>wjL3(v;A}k;xVRvD9Uvy<*Z6Z1#B1S_XN_Am!WqKlgEFgO#Xm4$0Uvy<*Z6Z1#B28~@bY*gKWqBejAR=LRVR>J4Wnpb1Iv^rYVPj}@V__nFU41Mddm?IYa&BQ{VIn#pF*7V6B4%Y{XklMzZfRp_Zz4J%A~G;CHZ3tQEiy17EFdCgWn*YzUuJ1;B03-<GB7eWEio`HGBF}7AR=&Ka&&2AZ*w9#AX|GPXm4$0Uvy<*Z6Z1#B0+R)Ty-!oWjS<dV{ag2Wgt^wZXir`X>%ehAR=LRVR>J4Wnpb1Iv^rZb!Bo~buchxIdoxiZz6pxAbTQcZ*65?bY)>}B03-<MnfP<bzyR4dLk?!B4Kx7d0%v8VQnHhAR<9@Y+-J6Wg>knAbTQcZ*65?bY)>}B03-<RB2~&Wpf}^K~78}EFdCbcVT&7bY)>}B03-<Ol4ekFfe8_ZX$gwAbTQcZ*65?bY)>}B03-<M|ELjVQgV)VRB(2EFdCbcVT&7bY)>}B03-<PGw_Zcwr)aEFgO#Xm4$0Uvy<*Z6Z1#B2aZ@Vr*d|EFdCbcVT&7bY)>}B03-<O>b^=WpZ+5c_Mu*AbTQcZ*65?bY)>}B03-<L3C_kb0RDtB4Kx7d0%v8VQnHhAR<9+Ty-!oWjS(bV__nFEFgO#Xm4$0Uvy<*Z6Z1#B2;f|bz@;7EFdCbcVT&7bY)>}B03-<RB38;VQyg}eJmh*B4}@IWnXk<VQnHhAR<s<V`z0_VInLbB4Kx7d0%v8VQnHhAR<F@b$TE{dUb3feJmh*B4}@IWnXk<VQnHhAR<#?Zgg*RA}k;xVRvD9Uvy<*Z6Z1#B2aa0VRIl=PC-o~eO-MlAbTQeZ*p#7WMLvYATcy7AR=aEV`yPtX>Ms_X>TGrAR;m_GBzzSFfB4OA}k;xW@Te&VP9rxZX!A$A~G;CHZ3tQEiyGCEFdCqVRCe7WN&jKIv`tnB4}@IWnXk<VQnHhAR<m>V_|q<A}k;xVRvD9Uvy<*Z6Z1#B1S_XN_Am!WqKlgEFgO#Xm4$0Uvy<*Z6Z1#B0+R)VQzF~A}k;xVRvD9Uvy<*Z6Z1#B0+R)Ty-!oWjS<dV{ag2Wgt^wZXir`X>%fdEFgO#Xm4$0Uvy<*Z6Z1#B1~mmbuchyGj1X*AR=LRVR>J4Wnpb1Iv^rcZ)|mAVIqAjAbTQcZ*65?bY)>}B03-<O>b^=WpZ+5c_J(zB4Kx7d0%v8VQnHhAR<R~VPs)!VQOJ=VIqAjAbTQcZ*65?bY)>}B03-<P<3r#b0AetK}{koAR=LRVR>J4Wnpb1Iv^rcX=id}b0AegPD~<wEFgO#Xm4$0Uvy<*Z6Z1#B0+R)VRIrZAR=LRVR>J4Wnpb1Iv^rYb!B2~VIqAjAbTQcZ*65?bY)>}B03-<L2X=hFfe5~a%p2>A}k;xVRvD9Uvy<*Z6Z1#B2ZytXmw*@B7H0%dm?CWZDn6{Wnpb1Iv^rZb!Bo~buchxIdoxiZz3!pB4Kx7d0%v8VQnHhAR<F@b$TE{dUb3feJmh*B4}@IWnXk<VQnHhAR<(0YIR|5VInLbB4Kx7d0%v8VQnHhAR<#?Zgg*RB7I$bEFgO#YHxCGVPs(<Iv_DMEFdCgWn*YzUukY>V`*<9Iv^r4FfukRF)%GNFd{4<B4%Y{XklMwX>KAqAR;m_GBzzSF)c7LA}k;xaA9(EX=HD6B03;jdm?CWZDn6{Wnpb1Iv^rJbZlI8Ffe5~bZKL6AY^4AQ(<l(Om%5<A}k;xVRvD9Uvy<*Z6Z1#B0+R)VRIsVEFgO#Xm4$0Uvy<*Z6Z1#B1S_XN_Am!WqKkkAR=LRVR>J4Wnpb1Iv^rZb!Bo~buchxIdoxiZz6pxAbTQcZ*65?bY)>}B03-<P<3TuY+)iSAR=LRVR>J4Wnpb1Iv^rYb!}mDAXQF5O(K0PAbTQcZ*65?bY)>}B03-<P+?<ebz@;7EFdCbcVT&7bY)>}B03-<RB2~&Wpf}^K~78}eJmh*B4}@IWnXk<VQnHhAR<R~VPs)!VQOJ=VInLbB4Kx7d0%v8VQnHhAR<9@Y+-J6Wg>knAbTQcZ*65?bY)>}B03-<O>b^=WpZ+5c_J(zB4Kx7d0%v8VQnHhAR<(0YIR|5VIqAjAbTQcZ*65?bY)>}B03-<L2X=hFfe5~a%p2>A}k;xVRvD9Uvy<*Z6Z1#B2;f|bz@;7eJmh*B4}@IWnXk<VQnHhAR<#?Zgg*RA}k;xVRvD9Uvy<*Z6Z1#B2HyvVR&I8eJmh*B4}@IWnXk<VQnHhAR<F@b$TE{dUb3fEFdCbcVT&7bY)>}B03-<Ol4ekFfe8_ZX$hMeJmh*B5H4PZee6$B03;3HY^|_W@Te&VP9!(X=7<`B03-<GB7eWEio}IFg7AAAR=aEV`yPtW@&CBIv^r4FfukRF)=MLI3g?{B5+}HbZKO7b0Rt*TYDmCZ*65?bY)>}B03-<L3C_fbuchxIdo}bZy;o4AX8y(AWU^>b0RDtB4Kx7d0%v8VQnHhAR<OXAWC&%a%FlVeJmh*B4}@IWnXk<VQnHhAR<m>V_|q<A}k;xVRvD9Uvy<*Z6Z1#B2;N=bzyE{B7H0%dm?CWZDn6{Wnpb1Iv^rJbZlX6bY&teAR=LRVR>J4Wnpb1Iv^rbVQzG9b0U2#AbTQcZ*65?bY)>}B03-<L3C_kb0RDtB4Kx7d0%v8VQnHhAR<s<V`z0_VIqAjAbTQcZ*65?bY)>}B03-<RB2~&Wpf}^K~78}EFdCbcVT&7bY)>}B03-<LvnR`AVGR{Y$AOuAbTQcZ*65?bY)>}B03-<RBvo`V__mJAR=LRVR>J4Wnpb1Iv^rVZ*FvDa&l#PB7H0%dm?CWZDn6{Wnpb1Iv^rYb!}mDAXQF5O(HBHB4Kx7d0%v8VQnHhAR<9+Ty-!oWjS(bV__nFEFgO#Xm4$0Uvy<*Z6Z1#B2jf^a$I#VFl9M(VRCOGEFdCbcVT&7bY)>}B03-<P<3TuY+)jOEFgO#Xm4$0Uvy<*Z6Z1#B1~mmbuchyGj1X*AR=LRVR>J4Wnpb1Iv^rPbzx*-Y+-6)a$zEUU41Mddm?IYa&BQ{VIn#pF*htAB4%Y{XklMzZfRp_Zz4J%A~G;CHZ3tREiy17EFdCgWn*YzUuJ1;B03-<GB7eWEio}IGBP48AR=&Ka&&2AZ*w9#AX|GPXm4$0Uvy<*Z6Z1#B2aZ@Vr*d|EFdCbcVT&7bY)>}B03-<L3C_fbuchxIdo}bZy;o4AX8y(AWU^>b0U2#AbTQcZ*65?bY)>}B03-<MnfP<bzyR4dLk?!B4Kx7d0%v8VQnHhAR<9@Y+-XEeJmh*B4}@IWnXk<VQnHhAR<(0YIR|5VInLbB4Kx7d0%v8VQnHhAR<9@Y+-J6Wg>knAbTQcZ*65?bY)>}B03-<Q(<m&Z*w9nAR=LRVR>J4Wnpb1Iv^rUWn6VIFlIAuB7H0%dm?CWZDn6{Wnpb1Iv^rYVPj}@V__mJAR=LRVR>J4Wnpb1Iv^rcZ)|mAVIqAjAbTQcZ*65?bY)>}B03-<P<3r#b0AetK}{koAR=LRVR>J4Wnpb1Iv^rVZ*FvDa&l#PB7H0%dm?CWZDn6{Wnpb1Iv^rcX=id}b0AegPD~;!AR=LRVR>J4Wnpb1Iv^rJZCrIQFl9M%X=7m`eJmh*B4}@IWnXk<VQnHhAR<R~VPs)!VQOJ=VInLbB4Kx7d0%v8VQnHhAR<F@b$TE{dUb3feJmh*B4}@IWnXk<VQnHhAR<w9WpZ3~Ffe5~bYXIDA}k;xVRvD9Uvy<*Z6Z1#B2HyvVR&I8eO-NB"""
"""Calendario incrustado (base85) para que el plan funcione aunque Docker no copie data/calendario.json."""

def cargar_calendario(path: Path = CALENDARIO_PATH) -> List[Dict[str, Any]]:
    """
    Carga data/calendario.json (o fallback incrustado).
    Busca en path (CALENDARIO_PATH) y en data/calendario.json (CWD).
    Si no encuentra archivo, usa los datos incrustados en _CALENDARIO_FALLBACK_B85.
    Devuelve [] solo si no hay datos (no deberia pasar nunca).
    """
    for p in [Path(path), Path("data/calendario.json")]:
        if p.exists() and p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    salida = [j for j in data if isinstance(j, dict) and "jornada" in j and isinstance(j.get("partidos"), list)]
                    if salida:
                        return salida
            except (json.JSONDecodeError, OSError):
                continue
    # Fallback: datos incrustados (siempre funcionan)
    try:
        data = json.loads(base64.b85decode(_CALENDARIO_FALLBACK_B85).decode())
        if isinstance(data, list):
            return [j for j in data if isinstance(j, dict) and "jornada" in j and isinstance(j.get("partidos"), list)]
    except Exception:
        pass
    return []


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
