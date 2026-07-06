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
        })
    n = len(derrotas)
    if n == 0:
        return {"total_derrotas": 0, "derrotas": [],
                "mensaje": "No hubo eliminaciones evaluables (¿historial corto?).",
                "decision": DEC_INFORMATIVA}

    vis = sum(1 for d in derrotas if d["fue_visitante"])
    con_alerta = sum(1 for d in derrotas if d["tenia_alerta"])
    npd = [d["no_perder_pct"] for d in derrotas if d["no_perder_pct"] is not None]
    rivales = Counter(d["rival"] for d in derrotas if d.get("rival"))
    patrones = {
        "fueron_visitante_pct": round(100.0 * vis / n, 1),
        "tenian_alerta_pct": round(100.0 * con_alerta / n, 1),
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
