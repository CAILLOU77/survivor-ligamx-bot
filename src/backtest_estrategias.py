#!/usr/bin/env python3
"""
backtest_estrategias.py — ¿Qué estrategia de Survivor sobrevive MÁS? (datos reales).

El simulador clásico (simulador_survivor) prueba una estrategia INGENUA: elige
siempre el mayor "no-perder". Pero el bot recomienda con la estrategia REAL
(motor_pronosticos.mejores_picks_estrategico): penaliza al favorito visitante,
va cauteloso en el arranque y premia ganar. Este módulo mide, con datos reales
(walk-forward, sin trampas), si esa estrategia REAL sobrevive más que la ingenua.

Diferencias clave vs el simulador clásico:
  1) Reproduce la estrategia REAL del bot (no una simplificación).
  2) REINICIA los equipos usados en cada TORNEO (un Survivor son ~17 jornadas y
     se reinicia; no es un juego infinito). Detecta torneos por el hueco de
     fechas entre jornadas (Apertura/Clausura).
  3) Compara varias estrategias lado a lado sobre las MISMAS temporadas.

Todo se deriva del modelo (poisson_model) + resultados reales. Sin inventar nada.
INFORMATIVO / REVISIÓN HUMANA.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Sequence

try:
    import poisson_model as pm
    import motor_pronosticos as mp
    from simulador_survivor import (
        MIN_TRAIN,
        _no_perder_candidatos,
        _semana_iso,
        _sobrevive,
        agrupar_jornadas,
    )
except ImportError:  # pragma: no cover
    from src import poisson_model as pm  # type: ignore
    from src import motor_pronosticos as mp  # type: ignore
    from src.simulador_survivor import (  # type: ignore
        MIN_TRAIN,
        _no_perder_candidatos,
        _semana_iso,
        _sobrevive,
        agrupar_jornadas,
    )

DEC_INFORMATIVA = "INFORMATIVO / REVISIÓN HUMANA"
GAP_TORNEO_DIAS = 28  # hueco de calendario que separa un torneo del siguiente
JORNADAS_REGULARES = 17  # Liga MX: 17 jornadas de fase regular (objetivo del Survivor)

# Una estrategia recibe (partidos, fuerzas, usados, partidos_jugados_torneo) y
# devuelve el candidato elegido {equipo, rival, es_local, partido, no_perder_pct}
# o None si no hay pick posible esa jornada.
Estrategia = Callable[
    [Sequence[Dict[str, Any]], Dict[str, Any], set, int], Optional[Dict[str, Any]]
]


# ---------------------------------------------------------------------------
# Helpers de torneo (dividir la historia en torneos por hueco de fechas)
# ---------------------------------------------------------------------------
def _fecha_semana_iso(wk: str) -> Optional[date]:
    """Primer día (lunes) de una semana ISO 'YYYY-Www'."""
    try:
        y, w = str(wk).split("-W")
        return date.fromisocalendar(int(y), int(w), 1)
    except (ValueError, TypeError):
        return None


def _gano(partido: Dict[str, Any], es_local: bool) -> bool:
    """True si el equipo elegido GANÓ (no solo no-perdió)."""
    try:
        hg, ag = int(partido["home_goals"]), int(partido["away_goals"])
    except (KeyError, TypeError, ValueError):
        return False
    return hg > ag if es_local else ag > hg


# ---------------------------------------------------------------------------
# Estrategias
# ---------------------------------------------------------------------------
def estrategia_ingenua(
    partidos: Sequence[Dict[str, Any]],
    fuerzas: Dict[str, Any],
    usados: set,
    partidos_jugados_torneo: int = 0,
) -> Optional[Dict[str, Any]]:
    """Baseline: el mayor 'no-perder' disponible (lo que hace simulador_survivor)."""
    cands = [
        c for c in _no_perder_candidatos(partidos, fuerzas)
        if pm._norm(c["equipo"]) not in usados
    ]
    if not cands:
        return None
    return max(cands, key=lambda c: c["no_perder_pct"])


def _localizar_partido(
    equipo_norm: str, es_local: bool, partidos: Sequence[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Encuentra el partido donde `equipo_norm` juega con esa condición."""
    for p in partidos:
        if es_local and pm._norm(p.get("home_team", "")) == equipo_norm:
            return p
        if not es_local and pm._norm(p.get("away_team", "")) == equipo_norm:
            return p
    return None


def estrategia_real(
    partidos: Sequence[Dict[str, Any]],
    fuerzas: Dict[str, Any],
    usados: set,
    partidos_jugados_torneo: int = 0,
) -> Optional[Dict[str, Any]]:
    """
    La estrategia REAL del bot: construye los pronósticos de la jornada y usa
    motor_pronosticos.mejores_picks_estrategico (penaliza favorito visitante,
    cautela de arranque, premia ganar). Toma el pick #1.
    """
    pronos: List[Dict[str, Any]] = []
    for p in partidos:
        pr = mp.pronosticar_partido(p.get("home_team", ""), p.get("away_team", ""), fuerzas)
        if pr:
            pronos.append(pr)
    if not pronos:
        return None
    res = mp.mejores_picks_estrategico(
        pronos,
        equipos_usados=list(usados),
        partidos_jugados_torneo=partidos_jugados_torneo,
        n=1,
    )
    picks = res.get("picks") or []
    if not picks:
        return None
    pick = picks[0]
    es_local = pick.get("condicion") == "Local"
    equipo_norm = pm._norm(pick.get("equipo", ""))
    partido = _localizar_partido(equipo_norm, es_local, partidos)
    if partido is None:
        return None
    # Adjunta lo que el MODELO veía del partido (para el análisis de derrotas).
    prono = next(
        (pr for pr in pronos
         if pm._norm(pr.get("local", "")) == pm._norm(partido.get("home_team", ""))
         and pm._norm(pr.get("visitante", "")) == pm._norm(partido.get("away_team", ""))),
        None,
    )
    goles_esp = None
    if prono is not None:
        gl = prono.get("goles_esperados_local")
        gv = prono.get("goles_esperados_visitante")
        if gl is not None and gv is not None:
            goles_esp = round(float(gl) + float(gv), 2)
    return {
        "equipo": pick.get("equipo"),
        "rival": pick.get("rival"),
        "es_local": es_local,
        "partido": partido,
        "no_perder_pct": pick.get("no_perder_pct"),
        "prob_victoria_pct": pick.get("prob_victoria_pct"),
        "prob_empate_pct": pick.get("prob_empate_pct"),
        "nivel": pick.get("nivel"),
        "nivel_alerta": (prono or {}).get("nivel_alerta"),
        "motivos_alerta": (prono or {}).get("motivos_alerta") or [],
        "goles_esperados": goles_esp,
    }


ESTRATEGIAS: Dict[str, Estrategia] = {
    "ingenua": estrategia_ingenua,
    "real": estrategia_real,
}


# ---------------------------------------------------------------------------
# Simulación walk-forward por torneo
# ---------------------------------------------------------------------------
def _nuevo_torneo(torneo_id: Optional[str] = None) -> Dict[str, Any]:
    return {"torneo_id": torneo_id, "jugadas": 0, "sobrevividas": 0, "victorias": 0,
            "eliminado_en": None, "parcial": False, "detalle": []}


def _torneo_id(f: Optional[date]) -> Optional[str]:
    """
    Identifica el torneo de Liga MX por la fecha: Apertura (jul-dic) o Clausura
    (ene-jun), por año. Ej: 2025-08-... -> '2025A'; 2026-03-... -> '2026C'.
    Es más robusto que detectar por hueco de fechas (el descanso invierno es corto).
    """
    if f is None:
        return None
    return f"{f.year}{'A' if f.month >= 7 else 'C'}"


def simular_estrategia(
    resultados: Sequence[Dict[str, Any]],
    estrategia: Estrategia = estrategia_real,
    min_train: int = MIN_TRAIN,
) -> Dict[str, Any]:
    """
    Corre Survivor sobre los resultados reales (walk-forward), reiniciando los
    equipos usados en cada TORNEO (Apertura/Clausura, por semestre). Devuelve el
    desglose por torneo y agregados.
    """
    return _agregar(_correr(resultados, estrategia, min_train), estrategia)


def _correr(
    resultados: Sequence[Dict[str, Any]],
    estrategia: Estrategia = estrategia_real,
    min_train: int = MIN_TRAIN,
) -> List[Dict[str, Any]]:
    """
    Motor walk-forward: devuelve la lista de torneos con su `detalle` (cada pick
    y su resultado). Base para _agregar (métricas) y analizar_derrotas (postmortem).

    Para cada jornada entrena la fuerza SOLO con lo anterior, deja que la
    estrategia elija, y revisa qué pasó de verdad (ganó / empató / perdió).
    Un torneo se marca `parcial` cuando NO se pudo evaluar desde su inicio (sin
    histórico suficiente); esos no cuentan para la tasa de supervivencia.
    """
    jornadas = agrupar_jornadas(resultados)
    ordenados = sorted(resultados, key=lambda r: str(r.get("fecha", "")))

    historico: List[Dict[str, Any]] = []
    idx = 0
    usados: set = set()
    jugados_torneo = 0
    eliminado_flag = False

    torneos: List[Dict[str, Any]] = []
    cur = _nuevo_torneo()
    cur_id: Optional[str] = None
    jugo_en_cur = False

    for j in jornadas:
        f = _fecha_semana_iso(j["jornada"])
        tid = _torneo_id(f)
        # ¿Nuevo torneo? (cambió el semestre Apertura/Clausura)
        if cur_id is None:
            cur_id = tid
            cur = _nuevo_torneo(tid)
        elif tid is not None and tid != cur_id:
            torneos.append(cur)
            cur = _nuevo_torneo(tid)
            cur_id = tid
            usados = set()
            jugados_torneo = 0
            eliminado_flag = False
            jugo_en_cur = False

        # Avanza el histórico con todo lo ANTERIOR a esta jornada.
        while idx < len(ordenados) and _semana_iso(ordenados[idx].get("fecha")) < j["jornada"]:
            historico.append(ordenados[idx])
            idx += 1

        n_partidos = len(j["partidos"])

        # Sin histórico suficiente al inicio del torneo => no evaluable => parcial.
        if len(historico) < min_train:
            if not jugo_en_cur:
                cur["parcial"] = True
            jugados_torneo += n_partidos
            continue
        if eliminado_flag:
            jugados_torneo += n_partidos
            continue
        try:
            fuerzas = pm.calcular_fuerzas(historico)
        except ValueError:
            if not jugo_en_cur:
                cur["parcial"] = True
            jugados_torneo += n_partidos
            continue

        cand = estrategia(j["partidos"], fuerzas, usados, jugados_torneo)
        jugados_torneo += n_partidos
        if cand is None:
            continue

        jugo_en_cur = True
        vivo = _sobrevive(cand["partido"], cand["es_local"])
        cur["jugadas"] += 1
        usados.add(pm._norm(cand["equipo"]))
        p_ = cand["partido"]
        gano = _gano(p_, cand["es_local"]) if vivo else False
        cur["detalle"].append({
            "torneo": cur_id,
            "jornada": j["jornada"],
            "pick": cand["equipo"],
            "condicion": "Local" if cand["es_local"] else "Visitante",
            "rival": cand.get("rival"),
            "no_perder_pct": cand.get("no_perder_pct"),
            "prob_victoria_pct": cand.get("prob_victoria_pct"),
            "prob_empate_pct": cand.get("prob_empate_pct"),
            "nivel_alerta": cand.get("nivel_alerta"),
            "motivos_alerta": cand.get("motivos_alerta") or [],
            "goles_esperados": cand.get("goles_esperados"),
            "resultado": f"{p_.get('home_team')} {p_.get('home_goals')}-"
                         f"{p_.get('away_goals')} {p_.get('away_team')}",
            "sobrevivio": vivo,
            "gano": gano,
        })
        if vivo:
            cur["sobrevividas"] += 1
            if gano:
                cur["victorias"] += 1
        else:
            cur["eliminado_en"] = j["jornada"]
            eliminado_flag = True
            # Contrafactual HONESTO: ¿había otra opción libre que sobrevivía Y que
            # el modelo veía IGUAL O MÁS segura que el pick? (evitar sesgo
            # retrospectivo: en toda jornada sobrevive alguien, pero eso no
            # significa que fuera predecible). `usados` ya incluye el pick actual.
            todos = _no_perder_candidatos(j["partidos"], fuerzas)
            seguros_disp = sorted(
                [c for c in todos
                 if pm._norm(c["equipo"]) not in usados and _sobrevive(c["partido"], c["es_local"])],
                key=lambda c: c["no_perder_pct"], reverse=True,
            )
            pick_np = cand.get("no_perder_pct") or 0.0
            mejor = seguros_disp[0] if seguros_disp else None
            d_ult = cur["detalle"][-1]
            d_ult["habia_seguro_disponible"] = bool(seguros_disp)
            d_ult["mejor_alternativa"] = (
                {"equipo": mejor["equipo"],
                 "condicion": "Local" if mejor["es_local"] else "Visitante",
                 "no_perder_pct": mejor["no_perder_pct"]} if mejor else None
            )
            # "Evitable de verdad": la opción segura era IGUAL o MÁS confiable que
            # el pick (el modelo pudo haberla preferido). Si era menos confiable,
            # fue MALA SUERTE (el bot eligió lo más seguro y aun así perdió).
            d_ult["evitable"] = bool(mejor and float(mejor["no_perder_pct"] or 0) >= pick_np)

    torneos.append(cur)
    # Descarta torneos "fantasma" (sin actividad y sin marca de parcial).
    return [t for t in torneos if t["jugadas"] > 0 or t.get("parcial")]


def _agregar(torneos: List[Dict[str, Any]], estrategia: Estrategia) -> Dict[str, Any]:
    """
    Métricas agregadas SOLO sobre torneos completos (los parciales se reportan
    aparte pero no cuentan para la tasa de supervivencia: no se jugaron enteros).
    """
    nombre = getattr(estrategia, "__name__", "estrategia")
    completos = [t for t in torneos if not t.get("parcial") and t["jugadas"] > 0]
    parciales = [t for t in torneos if t.get("parcial")]
    n = len(completos)
    if n == 0:
        return {
            "estrategia": nombre,
            "torneos_evaluados": 0,
            "torneos_parciales": len(parciales),
            "mensaje": "Sin torneos COMPLETOS evaluables (histórico corto para "
                       "empezar desde el inicio del torneo). Se necesita más "
                       "temporadas para un veredicto confiable.",
            "decision": DEC_INFORMATIVA,
        }
    sobrevividos = sum(1 for t in completos if t["eliminado_en"] is None)
    total_sobre = sum(t["sobrevividas"] for t in completos)
    total_jug = sum(t["jugadas"] for t in completos)
    total_vict = sum(t["victorias"] for t in completos)
    return {
        "estrategia": nombre,
        "torneos_evaluados": n,
        "torneos_parciales": len(parciales),
        "torneos_sobrevividos_completos": sobrevividos,
        "tasa_supervivencia_torneo_pct": round(100.0 * sobrevividos / n, 1),
        "jornadas_sobrevividas_prom": round(total_sobre / n, 2),
        "victorias_prom_por_torneo": round(total_vict / n, 2),
        "jornadas_jugadas_total": total_jug,
        "jornadas_sobrevividas_total": total_sobre,
        "victorias_total": total_vict,
        "por_torneo": [
            {"torneo": t.get("torneo_id"), "jornadas": t["jugadas"],
             "sobrevividas": t["sobrevividas"], "victorias": t["victorias"],
             "eliminado_en": t["eliminado_en"]}
            for t in completos
        ],
        "decision": DEC_INFORMATIVA,
    }


def comparar_estrategias(
    resultados: Sequence[Dict[str, Any]],
    min_train: int = MIN_TRAIN,
    estrategias: Optional[Dict[str, Estrategia]] = None,
) -> Dict[str, Any]:
    """
    Corre varias estrategias sobre las MISMAS temporadas y las compara. Sirve
    para responder honestamente: ¿la estrategia REAL sobrevive más que la ingenua?
    """
    estr = estrategias or ESTRATEGIAS
    salida: Dict[str, Any] = {"por_estrategia": {}, "decision": DEC_INFORMATIVA}
    for nombre, fn in estr.items():
        salida["por_estrategia"][nombre] = simular_estrategia(
            resultados, estrategia=fn, min_train=min_train
        )
    # Veredicto simple: quién sobrevive más torneos completos (desempate: victorias).
    ranking = sorted(
        salida["por_estrategia"].items(),
        key=lambda kv: (
            kv[1].get("tasa_supervivencia_torneo_pct", 0.0),
            kv[1].get("victorias_prom_por_torneo", 0.0),
        ),
        reverse=True,
    )
    salida["mejor"] = ranking[0][0] if ranking else None
    return salida


# ---------------------------------------------------------------------------
# Postmortem: aprender de las DERROTAS (en qué partido cayó y por qué)
# ---------------------------------------------------------------------------
def _lecciones_derrotas(pat: Dict[str, Any], n: int) -> List[str]:
    """Lecciones accionables, SOLO si los números las sostienen (no opinión)."""
    L: List[str] = []
    evi = pat.get("evitables")
    mala = pat.get("mala_suerte")
    if evi is not None:
        if evi > 0:
            L.append(f"{evi} de {n} derrotas eran EVITABLES de verdad: había una opción "
                     "IGUAL o MÁS segura que sí sobrevivió. Ahí sí se puede mejorar la elección.")
        if mala:
            L.append(f"{mala} de {n} fueron MALA SUERTE: el bot eligió su opción más confiable "
                     "y aun así perdió. Otro equipo sobrevivió, pero el modelo lo veía MENOS "
                     "seguro: no era predecible. Así es el Survivor.")
    if pat.get("fueron_visitante_pct") is not None and pat["fueron_visitante_pct"] >= 40:
        L.append(f"El {pat['fueron_visitante_pct']}% de las eliminaciones fueron con pick "
                 "VISITANTE: de visita hay más sorpresas, prioriza locales.")
    tva = pat.get("tenian_alerta_pct")
    if tva is not None and tva >= 50:
        L.append(f"El {tva}% de las derrotas YA traían señal de alerta del modelo: "
                 "cuando hay alerta, conviene buscar otro equipo.")
    elif tva is not None and tva <= 25:
        L.append("La mayoría de las derrotas fueron SORPRESAS sin alerta previa: el fútbol "
                 "es así; por eso una sola derrota elimina y hay que ir seguro.")
    if pat.get("no_perder_promedio_al_perder") is not None:
        L.append(f"El bot perdió aun con picks de ~{pat['no_perder_promedio_al_perder']}% "
                 "de no-perder: ningún pick es 100% seguro.")
    rivales = pat.get("rivales_que_mas_eliminaron") or []
    if rivales and rivales[0][1] >= 2:
        L.append(f"Ojo con {rivales[0][0]} como rival: eliminó {rivales[0][1]} veces "
                 "en el histórico.")
    if not L:
        L.append("No hay un patrón claro en las derrotas; fueron variadas.")
    return L


def analizar_derrotas(
    resultados: Sequence[Dict[str, Any]],
    min_train: int = MIN_TRAIN,
    estrategia: Estrategia = estrategia_real,
) -> Dict[str, Any]:
    """
    Postmortem: revisa EN QUÉ partidos exactos la estrategia quedó eliminada
    (el pick que perdió) y busca patrones para aprender. Por cada derrota guarda
    qué equipo se eligió, si era local/visitante, qué veía el modelo (prob. de
    ganar, si había alerta) y el marcador real. Deriva lecciones de esos números.
    """
    torneos = _correr(resultados, estrategia, min_train)
    derrotas: List[Dict[str, Any]] = []
    for t in torneos:
        if t.get("eliminado_en") is None:
            continue
        perdidos = [d for d in t["detalle"] if not d.get("sobrevivio")]
        if not perdidos:
            continue
        d = perdidos[-1]
        derrotas.append({
            "torneo": t.get("torneo_id"),
            "jornada": d.get("jornada"),
            "pick": d.get("pick"),
            "condicion": d.get("condicion"),
            "rival": d.get("rival"),
            "no_perder_pct": d.get("no_perder_pct"),
            "prob_victoria_pct": d.get("prob_victoria_pct"),
            "nivel_alerta": d.get("nivel_alerta"),
            "motivos_alerta": d.get("motivos_alerta") or [],
            "resultado": d.get("resultado"),
            "tenia_alerta": bool(d.get("motivos_alerta")),
            "fue_visitante": d.get("condicion") == "Visitante",
            "evitable": bool(d.get("evitable")),
            "habia_seguro_disponible": bool(d.get("habia_seguro_disponible")),
            "mejor_alternativa": d.get("mejor_alternativa"),
        })
    n = len(derrotas)
    if n == 0:
        return {"total_derrotas": 0, "derrotas": [],
                "mensaje": "No hubo eliminaciones evaluables (¿historial corto?).",
                "decision": DEC_INFORMATIVA}

    vis = sum(1 for d in derrotas if d["fue_visitante"])
    con_alerta = sum(1 for d in derrotas if d["tenia_alerta"])
    evitables = sum(1 for d in derrotas if d["evitable"])
    mala_suerte = sum(1 for d in derrotas if not d["evitable"] and d.get("habia_seguro_disponible"))
    npd = [d["no_perder_pct"] for d in derrotas if d["no_perder_pct"] is not None]
    rivales = Counter(d["rival"] for d in derrotas if d.get("rival"))
    patrones = {
        "fueron_visitante_pct": round(100.0 * vis / n, 1),
        "tenian_alerta_pct": round(100.0 * con_alerta / n, 1),
        # evitable = había opción IGUAL o MÁS segura que el pick (predecible).
        "evitables": evitables,
        # mala_suerte = el bot eligió lo más seguro y aun así perdió (azar).
        "mala_suerte": mala_suerte,
        "evitables_pct": round(100.0 * evitables / n, 1),
        "no_perder_promedio_al_perder": round(sum(npd) / len(npd), 1) if npd else None,
        "rivales_que_mas_eliminaron": rivales.most_common(3),
    }
    return {
        "total_derrotas": n,
        "derrotas": derrotas,
        "patrones": patrones,
        "lecciones": _lecciones_derrotas(patrones, n),
        "decision": DEC_INFORMATIVA,
    }


# ---------------------------------------------------------------------------
# "Survivor perfecto" (oráculo): con los resultados ya sabidos, ¿existía una
# combinación de picks que sobreviviera TODO el torneo? ¿Cuántas victorias?
# ---------------------------------------------------------------------------
def _oracle_torneo(jornadas: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Con diario del futuro (resultados ya sabidos), calcula la MEJOR corrida
    posible del torneo: asigna a cada jornada un equipo distinto que NO perdió
    (emparejamiento óptimo). Devuelve si existía una corrida perfecta (sobrevivir
    todas las jornadas) y, de existir, el máximo de victorias posible.
    """
    import numpy as np
    from scipy.optimize import linear_sum_assignment

    equipos = sorted({
        pm._norm(e)
        for j in jornadas for m in j.get("partidos", [])
        for e in (m.get("home_team", ""), m.get("away_team", ""))
        if e
    })
    n_j, n_t = len(jornadas), len(equipos)
    if n_j == 0 or n_t == 0:
        return {"jornadas": n_j, "completo": False, "max_supervivencia": 0, "oracle_wins": None}
    tidx = {t: i for i, t in enumerate(equipos)}

    NEG = -1e9
    surv = np.zeros((n_j, n_t), dtype=float)   # 1 si el equipo NO perdió esa jornada
    win = np.full((n_j, n_t), NEG, dtype=float)  # 1 gana, 0 empata, NEG pierde/no juega
    for i, j in enumerate(jornadas):
        for m in j.get("partidos", []):
            try:
                hg, ag = int(m["home_goals"]), int(m["away_goals"])
            except (KeyError, TypeError, ValueError):
                continue
            h, a = pm._norm(m.get("home_team", "")), pm._norm(m.get("away_team", ""))
            if h in tidx:
                surv[i][tidx[h]] = 1.0 if hg >= ag else 0.0
                win[i][tidx[h]] = 1.0 if hg > ag else (0.0 if hg == ag else NEG)
            if a in tidx:
                surv[i][tidx[a]] = 1.0 if ag >= hg else 0.0
                win[i][tidx[a]] = 1.0 if ag > hg else (0.0 if ag == hg else NEG)

    # Máxima supervivencia: emparejar jornadas ↔ equipos que sobrevivieron.
    r, c = linear_sum_assignment(-surv)
    max_surv = int(surv[r, c].sum())
    completo = max_surv == n_j

    oracle_wins = None
    if completo:
        r2, c2 = linear_sum_assignment(-win)
        vals = win[r2, c2]
        if (vals > NEG / 2).all():
            oracle_wins = int((vals == 1.0).sum())
    return {"jornadas": n_j, "completo": completo,
            "max_supervivencia": max_surv, "oracle_wins": oracle_wins}


def _oracle_asignacion(jornadas: Sequence[Dict[str, Any]]) -> Dict[Any, str]:
    """{jornada_label: equipo_norm} de una corrida ÓPTIMA de supervivencia (oráculo)."""
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    equipos = sorted({
        pm._norm(e) for j in jornadas for m in j.get("partidos", [])
        for e in (m.get("home_team", ""), m.get("away_team", "")) if e
    })
    n_j, n_t = len(jornadas), len(equipos)
    if n_j == 0 or n_t == 0:
        return {}
    tidx = {t: i for i, t in enumerate(equipos)}
    surv = np.zeros((n_j, n_t), dtype=float)
    for i, j in enumerate(jornadas):
        for m in j.get("partidos", []):
            try:
                hg, ag = int(m["home_goals"]), int(m["away_goals"])
            except (KeyError, TypeError, ValueError):
                continue
            h, a = pm._norm(m.get("home_team", "")), pm._norm(m.get("away_team", ""))
            if h in tidx and hg >= ag:
                surv[i][tidx[h]] = 1.0
            if a in tidx and ag >= hg:
                surv[i][tidx[a]] = 1.0
    r, c = linear_sum_assignment(-surv)
    labels = [j["jornada"] for j in jornadas]
    return {labels[i]: equipos[k] for i, k in zip(r.tolist(), c.tolist()) if surv[i][k] == 1.0}


def analizar_patron_ganador(
    resultados: Sequence[Dict[str, Any]],
    min_train: int = MIN_TRAIN,
) -> Dict[str, Any]:
    """
    ¿Hay un PATRÓN copiable en las corridas ganadoras (oráculo)? Para cada pick de
    la corrida óptima de supervivencia, mide qué veía el MODELO en ese momento:
    ¿era el más seguro (top-1 no-perder)?, ¿top-3?, ¿local? Si los picks ganadores
    eran los que el bot YA elegiría, el patrón es "elegir seguro" (lo que hace) y
    la diferencia es varianza. Si eran sorpresas de bajo no-perder, no es copiable.
    """
    jornadas = agrupar_jornadas(resultados)
    ordenados = sorted(resultados, key=lambda r: str(r.get("fecha", "")))
    torneos_j: List[Any] = []
    for j in jornadas:
        tid = _torneo_id(_fecha_semana_iso(j["jornada"]))
        if not torneos_j or torneos_j[-1][0] != tid:
            torneos_j.append((tid, []))
        torneos_j[-1][1].append(j)

    historico: List[Dict[str, Any]] = []
    idx = 0
    picks: List[Dict[str, Any]] = []
    for _tid, jlist in torneos_j:
        asign = _oracle_asignacion(jlist)
        for j in jlist:
            while idx < len(ordenados) and _semana_iso(ordenados[idx].get("fecha")) < j["jornada"]:
                historico.append(ordenados[idx])
                idx += 1
            eq = asign.get(j["jornada"])
            if eq is None or len(historico) < min_train:
                continue
            try:
                fuerzas = pm.calcular_fuerzas(historico)
            except ValueError:
                continue
            cands = sorted(_no_perder_candidatos(j["partidos"], fuerzas),
                           key=lambda c: c["no_perder_pct"], reverse=True)
            match = next((c for c in cands if pm._norm(c["equipo"]) == eq), None)
            if match is None:
                continue
            rank = cands.index(match) + 1
            picks.append({"no_perder": match["no_perder_pct"], "es_local": match["es_local"],
                          "rank": rank, "top1": rank == 1, "top3": rank <= 3})
    n = len(picks)
    if n == 0:
        return {"picks_analizados": 0, "mensaje": "Sin corridas ganadoras evaluables.",
                "decision": DEC_INFORMATIVA}
    return {
        "picks_analizados": n,
        "no_perder_promedio_de_los_ganadores": round(sum(p["no_perder"] for p in picks) / n, 1),
        "pct_local": round(100.0 * sum(1 for p in picks if p["es_local"]) / n, 1),
        "pct_eran_el_mas_seguro_top1": round(100.0 * sum(1 for p in picks if p["top1"]) / n, 1),
        "pct_estaban_en_top3": round(100.0 * sum(1 for p in picks if p["top3"]) / n, 1),
        "rank_promedio_en_no_perder": round(sum(p["rank"] for p in picks) / n, 1),
        "decision": DEC_INFORMATIVA,
    }


def analizar_ganadores(
    resultados: Sequence[Dict[str, Any]],
    min_train: int = MIN_TRAIN,
) -> Dict[str, Any]:
    """
    Compara la corrida REAL del bot (walk-forward, sin ver el futuro) contra el
    "Survivor perfecto" (oráculo, con los resultados ya sabidos), por torneo.
    Responde: ¿existía un camino ganador? ¿qué tan lejos quedó el bot? Saca
    conclusiones sobre la brecha (que es, esencialmente, la incertidumbre).
    """
    torneos_bot = _correr(resultados, estrategia_real, min_train)
    jornadas = agrupar_jornadas(resultados)
    por_torneo: Dict[Optional[str], List[Dict[str, Any]]] = {}
    for j in jornadas:
        tid = _torneo_id(_fecha_semana_iso(j["jornada"]))
        por_torneo.setdefault(tid, []).append(j)

    comparacion: List[Dict[str, Any]] = []
    for t in torneos_bot:
        if t.get("parcial") or t["jugadas"] == 0:
            continue
        tid = t.get("torneo_id")
        orac = _oracle_torneo(por_torneo.get(tid, []))
        # "camino perfecto" = el óptimo pudo sobrevivir las 17 de fase regular.
        # (No exigimos cubrir cada semana ISO: los partidos entre semana y la
        # liguilla generan semanas extra que no son parte del objetivo.)
        camino = orac["max_supervivencia"] >= JORNADAS_REGULARES
        comparacion.append({
            "torneo": tid,
            "bot_sobrevividas": t["sobrevividas"],
            "bot_victorias": t["victorias"],
            "bot_completo": t["eliminado_en"] is None,
            "oracle_jornadas": orac["jornadas"],
            "oracle_completo": camino,
            "oracle_max_supervivencia": orac["max_supervivencia"],
        })
    n = len(comparacion)
    if n == 0:
        return {"torneos": 0, "comparacion": [],
                "mensaje": "Sin torneos completos para comparar.",
                "decision": DEC_INFORMATIVA}

    con_camino = sum(1 for c in comparacion if c["oracle_completo"])
    bot_completos = sum(1 for c in comparacion if c["bot_completo"])
    bot_prom = round(sum(c["bot_sobrevividas"] for c in comparacion) / n, 1)
    orac_prom = round(sum(c["oracle_max_supervivencia"] for c in comparacion) / n, 1)
    lecciones = [
        f"En {con_camino} de {n} torneos SÍ existía un camino perfecto (sobrevivir todo) "
        "— pero solo visible DESPUÉS, con los resultados ya sabidos.",
        f"El bot (sin ver el futuro) completó {bot_completos}/{n} y aguantó ~{bot_prom} "
        f"jornadas; el camino perfecto daba ~{orac_prom}. Esa brecha ES la incertidumbre.",
        "Conclusión: casi siempre HAY una jugada ganadora, pero es imposible saberla de "
        "antemano. El bot no falla por elegir mal, sino porque el futuro no se conoce.",
    ]
    return {
        "torneos": n,
        "con_camino_perfecto": con_camino,
        "bot_completos": bot_completos,
        "bot_jornadas_prom": bot_prom,
        "oracle_jornadas_prom": orac_prom,
        "comparacion": comparacion,
        "lecciones": lecciones,
        "decision": DEC_INFORMATIVA,
    }


def analizar_causas_derrotas(
    resultados: Sequence[Dict[str, Any]],
    min_train: int = MIN_TRAIN,
    umbral_cerrado: float = 2.3,
    umbral_favorito: float = 55.0,
) -> Dict[str, Any]:
    """
    Clasifica POR QUÉ cae el bot en cada eliminación:
      - partido CERRADO/under (pocos goles esperados: propenso a sorpresa/empate),
      - era FAVORITO fuerte que igual perdió,
      - era de VISITANTE,
      - ya traía ALERTA del modelo.
    Un mismo caso puede tener varias etiquetas. Responde "¿under o favorito?".
    """
    torneos = _correr(resultados, estrategia_real, min_train)
    derrotas: List[Dict[str, Any]] = []
    for t in torneos:
        perdidos = [d for d in t["detalle"] if not d.get("sobrevivio")]
        if perdidos:
            derrotas.append(perdidos[-1])
    n = len(derrotas)
    if n == 0:
        return {"total_derrotas": 0, "mensaje": "Sin eliminaciones.", "decision": DEC_INFORMATIVA}

    def _pct(cond) -> float:
        return round(100.0 * sum(1 for d in derrotas if cond(d)) / n, 1)

    cerrado = _pct(lambda d: d.get("goles_esperados") is not None
                   and d["goles_esperados"] < umbral_cerrado)
    favorito = _pct(lambda d: (d.get("prob_victoria_pct") or 0) >= umbral_favorito)
    visitante = _pct(lambda d: d.get("condicion") == "Visitante")
    con_alerta = _pct(lambda d: bool(d.get("motivos_alerta")))

    causa_dominante = max(
        [("partido cerrado/under", cerrado), ("favorito que perdió", favorito),
         ("de visitante", visitante)],
        key=lambda kv: kv[1],
    )[0]
    return {
        "total_derrotas": n,
        "en_partido_cerrado_pct": cerrado,
        "era_favorito_fuerte_pct": favorito,
        "de_visitante_pct": visitante,
        "con_alerta_previa_pct": con_alerta,
        "causa_dominante": causa_dominante,
        "detalle": [
            {"torneo": d.get("torneo"), "pick": d.get("pick"),
             "condicion": d.get("condicion"), "rival": d.get("rival"),
             "goles_esperados": d.get("goles_esperados"),
             "prob_victoria_pct": d.get("prob_victoria_pct"),
             "resultado": d.get("resultado")}
            for d in derrotas
        ],
        "decision": DEC_INFORMATIVA,
    }


def estrategia_supervivencia(
    partidos: Sequence[Dict[str, Any]],
    fuerzas: Dict[str, Any],
    usados: set,
    partidos_jugados_torneo: int = 0,
) -> Optional[Dict[str, Any]]:
    """
    PURO SOBREVIVIR: elige el mayor no-perder (ganar+empatar), pero con el castigo
    al favorito VISITANTE (los locales sorprenden menos). NO premia ganar: el único
    objetivo es no ser eliminado. Prueba la idea del usuario: ¿maximizar
    supervivencia (sin importar victorias) aguanta más el Survivor?
    """
    PEN = 4.0
    cands = _no_perder_candidatos(partidos, fuerzas)
    disp = [c for c in cands if pm._norm(c["equipo"]) not in usados]
    if not disp:
        return None

    def _score(c):
        pen = 0.0 if c["es_local"] else PEN
        return c["no_perder_pct"] - pen

    elegido = max(disp, key=_score)
    return {
        "equipo": elegido["equipo"], "rival": elegido["rival"],
        "es_local": elegido["es_local"], "partido": elegido["partido"],
        "no_perder_pct": elegido["no_perder_pct"],
    }


def main() -> int:
    try:
        import fuentes_datos
    except ImportError:  # pragma: no cover
        from src import fuentes_datos  # type: ignore
    print("🧪 Comparando estrategias de Survivor (historial largo, por torneo)...")
    datos = fuentes_datos.obtener_historico_largo()
    print(f"Fuente historial: {datos.get('fuente')} | partidos: {datos.get('total')}")
    r = comparar_estrategias(datos["resultados"])
    print(f"Fuente: {datos['fuente']}")
    for nombre, res in r["por_estrategia"].items():
        if res.get("torneos_evaluados", 0) == 0:
            print(f"  {nombre}: {res.get('mensaje')}")
            continue
        print(f"  [{nombre}] torneos={res['torneos_evaluados']} | "
              f"sobrevividos completos={res['torneos_sobrevividos_completos']} "
              f"({res['tasa_supervivencia_torneo_pct']}%) | "
              f"jornadas sobrev. prom={res['jornadas_sobrevividas_prom']} | "
              f"victorias prom={res['victorias_prom_por_torneo']}")
    if r.get("mejor"):
        print(f"🏆 Mejor estrategia (por supervivencia): {r['mejor']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
