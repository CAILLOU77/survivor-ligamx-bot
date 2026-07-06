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
    return {
        "equipo": pick.get("equipo"),
        "rival": pick.get("rival"),
        "es_local": es_local,
        "partido": partido,
        "no_perder_pct": pick.get("no_perder_pct"),
    }


ESTRATEGIAS: Dict[str, Estrategia] = {
    "ingenua": estrategia_ingenua,
    "real": estrategia_real,
}


# ---------------------------------------------------------------------------
# Simulación walk-forward por torneo
# ---------------------------------------------------------------------------
def _nuevo_torneo() -> Dict[str, Any]:
    return {"jugadas": 0, "sobrevividas": 0, "victorias": 0,
            "eliminado_en": None, "detalle": []}


def simular_estrategia(
    resultados: Sequence[Dict[str, Any]],
    estrategia: Estrategia = estrategia_real,
    min_train: int = MIN_TRAIN,
    gap_torneo_dias: int = GAP_TORNEO_DIAS,
) -> Dict[str, Any]:
    """
    Corre Survivor sobre los resultados reales (walk-forward), reiniciando los
    equipos usados en cada torneo. Devuelve el desglose por torneo y agregados.

    Para cada jornada entrena la fuerza SOLO con lo anterior, deja que la
    estrategia elija, y revisa qué pasó de verdad (ganó / empató / perdió).
    """
    jornadas = agrupar_jornadas(resultados)
    ordenados = sorted(resultados, key=lambda r: str(r.get("fecha", "")))

    historico: List[Dict[str, Any]] = []
    idx = 0
    usados: set = set()
    prev_f: Optional[date] = None
    jugados_torneo = 0
    eliminado_flag = False

    torneos: List[Dict[str, Any]] = []
    cur = _nuevo_torneo()
    torneo_iniciado = False

    for j in jornadas:
        f = _fecha_semana_iso(j["jornada"])
        # ¿Nuevo torneo? (hueco de fechas grande)
        if prev_f is not None and f is not None and (f - prev_f).days > gap_torneo_dias:
            if torneo_iniciado:
                torneos.append(cur)
            cur = _nuevo_torneo()
            usados = set()
            jugados_torneo = 0
            eliminado_flag = False
            torneo_iniciado = False
        prev_f = f or prev_f

        # Avanza el histórico con todo lo ANTERIOR a esta jornada.
        while idx < len(ordenados) and _semana_iso(ordenados[idx].get("fecha")) < j["jornada"]:
            historico.append(ordenados[idx])
            idx += 1

        n_partidos = len(j["partidos"])
        if eliminado_flag or len(historico) < min_train:
            jugados_torneo += n_partidos
            continue
        try:
            fuerzas = pm.calcular_fuerzas(historico)
        except ValueError:
            jugados_torneo += n_partidos
            continue

        cand = estrategia(j["partidos"], fuerzas, usados, jugados_torneo)
        jugados_torneo += n_partidos
        if cand is None:
            continue

        torneo_iniciado = True
        vivo = _sobrevive(cand["partido"], cand["es_local"])
        cur["jugadas"] += 1
        usados.add(pm._norm(cand["equipo"]))
        p_ = cand["partido"]
        gano = _gano(p_, cand["es_local"]) if vivo else False
        cur["detalle"].append({
            "jornada": j["jornada"],
            "pick": cand["equipo"],
            "condicion": "Local" if cand["es_local"] else "Visitante",
            "rival": cand.get("rival"),
            "no_perder_pct": cand.get("no_perder_pct"),
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

    if torneo_iniciado:
        torneos.append(cur)

    return _agregar(torneos, estrategia)


def _agregar(torneos: List[Dict[str, Any]], estrategia: Estrategia) -> Dict[str, Any]:
    """Métricas agregadas sobre todos los torneos evaluados."""
    n = len(torneos)
    if n == 0:
        return {
            "torneos_evaluados": 0,
            "mensaje": "Sin torneos evaluables (¿histórico corto o min_train alto?).",
            "decision": DEC_INFORMATIVA,
        }
    completos = sum(1 for t in torneos if t["eliminado_en"] is None and t["jugadas"] > 0)
    total_sobre = sum(t["sobrevividas"] for t in torneos)
    total_jug = sum(t["jugadas"] for t in torneos)
    total_vict = sum(t["victorias"] for t in torneos)
    nombre = getattr(estrategia, "__name__", "estrategia")
    return {
        "estrategia": nombre,
        "torneos_evaluados": n,
        "torneos_sobrevividos_completos": completos,
        "tasa_supervivencia_torneo_pct": round(100.0 * completos / n, 1),
        "jornadas_sobrevividas_prom": round(total_sobre / n, 2),
        "victorias_prom_por_torneo": round(total_vict / n, 2),
        "jornadas_jugadas_total": total_jug,
        "jornadas_sobrevividas_total": total_sobre,
        "victorias_total": total_vict,
        "por_torneo": [
            {"jornadas": t["jugadas"], "sobrevividas": t["sobrevividas"],
             "victorias": t["victorias"], "eliminado_en": t["eliminado_en"]}
            for t in torneos
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


def main() -> int:
    try:
        import fuentes_datos
    except ImportError:  # pragma: no cover
        from src import fuentes_datos  # type: ignore
    print("🧪 Comparando estrategias de Survivor (datos reales ESPN, por torneo)...")
    datos = fuentes_datos.obtener_resultados(meses=18)
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
