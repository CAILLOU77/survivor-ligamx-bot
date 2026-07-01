#!/usr/bin/env python3
"""
analisis_riesgo.py — ¿Cuándo falla el favorito del modelo? (datos reales ESPN).

Responde con NÚMEROS REALES la intuición de Survivor: "cuidado con los favoritos
en partidos cerrados (pocos goles / 'under') y de visitante". No opina: mide.

Método (walk-forward honesto, igual que simulador_survivor):
- Agrupa los resultados reales por jornada (semana ISO), en orden cronológico.
- Para cada jornada (tras suficiente histórico) entrena la fuerza de equipos SOLO
  con lo anterior, pronostica cada partido y determina el "favorito" del modelo
  (el equipo con mayor probabilidad de ganar). Luego revisa qué pasó de verdad:
  el favorito GANÓ, EMPATÓ o PERDIÓ.
- Agrega tasas de fallo (no ganó / perdió) por condición (local vs visitante),
  por nivel de confianza y por "partido cerrado" (pocos goles esperados).

Todo se deriva del modelo (poisson_model) + resultados reales. Sin inventar nada.
INFORMATIVO / REVISIÓN HUMANA.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Sequence

try:
    import poisson_model as pm
    from simulador_survivor import MIN_TRAIN, _semana_iso, agrupar_jornadas
except ImportError:  # pragma: no cover
    from src import poisson_model as pm  # type: ignore
    from src.simulador_survivor import (  # type: ignore
        MIN_TRAIN,
        _semana_iso,
        agrupar_jornadas,
    )

DEC_INFORMATIVA = "INFORMATIVO / REVISIÓN HUMANA"

# Umbral de "partido cerrado": goles totales esperados (λ_local + λ_visita) por
# debajo de esto => juego de pocos goles, más propenso a empate/sorpresa ("under").
UMBRAL_PARTIDO_CERRADO: float = 2.5

# Cortes de confianza (probabilidad de victoria del favorito, en %).
CORTES_CONFIANZA: Sequence[float] = (55.0, 65.0, 75.0)

# "Muy favorito" del modelo: prob. de victoria alta (tu caso Toluca-Mazatlán).
CONF_MUY_FAVORITO: float = 70.0
# Arranque de torneo: primeras N jornadas tras un hueco largo de calendario.
JORNADAS_ARRANQUE: int = 3
GAP_TORNEO_DIAS: int = 28


def _fecha_semana_iso(wk: str):
    """Primer día de una semana ISO 'YYYY-Www' -> date (o None)."""
    try:
        y, w = str(wk).split("-W")
        return date.fromisocalendar(int(y), int(w), 1)
    except (ValueError, TypeError):
        return None


def _labels_arranque(jornadas: Sequence[Dict[str, Any]],
                     n: int = JORNADAS_ARRANQUE, gap_dias: int = GAP_TORNEO_DIAS) -> set:
    """
    Etiquetas de jornada que son 'arranque de torneo' (las primeras `n` tras un
    hueco de calendario > `gap_dias`, típico entre Apertura/Clausura). Detecta el
    inicio de cada torneo por el salto de fechas entre jornadas consecutivas.
    """
    arranque: set = set()
    prev = None
    idx = 0
    for j in jornadas:
        f = _fecha_semana_iso(j.get("jornada"))
        if f is None:
            prev = None
            continue
        if prev is None or (f - prev).days > gap_dias:
            idx = 1  # nuevo torneo
        else:
            idx += 1
        if idx <= n:
            arranque.add(j.get("jornada"))
        prev = f
    return arranque


def _bucket_confianza(conf_pct: float) -> str:
    if conf_pct < CORTES_CONFIANZA[0]:
        return "<55% (sin claro favorito)"
    if conf_pct < CORTES_CONFIANZA[1]:
        return "55-65%"
    if conf_pct < CORTES_CONFIANZA[2]:
        return "65-75%"
    return ">=75%"


def _outcome_favorito(partido: Dict[str, Any], favorito_local: bool) -> Optional[str]:
    """'gano' | 'empato' | 'perdio' para el favorito; None si no hay marcador."""
    try:
        hg, ag = int(partido["home_goals"]), int(partido["away_goals"])
    except (KeyError, TypeError, ValueError):
        return None
    if hg == ag:
        return "empato"
    local_gano = hg > ag
    if favorito_local:
        return "gano" if local_gano else "perdio"
    return "gano" if not local_gano else "perdio"


def _evaluar_partido(partido: Dict[str, Any], fuerzas: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Evalúa un partido: quién era el favorito del modelo y cómo le fue."""
    h, a = partido.get("home_team", ""), partido.get("away_team", "")
    if pm._norm(h) not in fuerzas.get("equipos", {}) or pm._norm(a) not in fuerzas.get("equipos", {}):
        return None
    pr = pm.pronostico(h, a, fuerzas)
    favorito_local = pr["prob_local_pct"] >= pr["prob_visitante_pct"]
    conf = pr["prob_local_pct"] if favorito_local else pr["prob_visitante_pct"]
    outcome = _outcome_favorito(partido, favorito_local)
    if outcome is None:
        return None
    goles_esperados = pr["lambda_local"] + pr["lambda_visitante"]
    return {
        "favorito": h if favorito_local else a,
        "rival": a if favorito_local else h,
        "favorito_local": favorito_local,
        "confianza_pct": round(conf, 2),
        "prob_empate_pct": pr["prob_empate_pct"],
        "goles_esperados": round(goles_esperados, 2),
        "partido_cerrado": goles_esperados < UMBRAL_PARTIDO_CERRADO,
        "outcome": outcome,  # gano | empato | perdio
        "fallo": outcome != "gano",  # en Survivor "ganar" un favorito que no gana = riesgo
    }


def _tasas(eventos: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Cuenta y tasas (ganó/empató/perdió/no-ganó) sobre una lista de evaluaciones."""
    n = len(eventos)
    if n == 0:
        return {"n": 0, "gano_pct": None, "empato_pct": None,
                "perdio_pct": None, "no_gano_pct": None}
    gano = sum(1 for e in eventos if e["outcome"] == "gano")
    empato = sum(1 for e in eventos if e["outcome"] == "empato")
    perdio = sum(1 for e in eventos if e["outcome"] == "perdio")
    return {
        "n": n,
        "gano_pct": round(100.0 * gano / n, 1),
        "empato_pct": round(100.0 * empato / n, 1),
        "perdio_pct": round(100.0 * perdio / n, 1),
        "no_gano_pct": round(100.0 * (n - gano) / n, 1),
    }


def _recomendaciones(por_cond: Dict[str, Any], cerrado: Dict[str, Any],
                     abierto: Dict[str, Any], arranque_vs_resto: Optional[Dict[str, Any]] = None,
                     muy_favorito: Optional[Dict[str, Any]] = None) -> List[str]:
    """Conclusiones accionables, SOLO si los números las sostienen (no opinión)."""
    recs: List[str] = []
    loc, vis = por_cond.get("local", {}), por_cond.get("visitante", {})
    if loc.get("n") and vis.get("n") and loc["no_gano_pct"] is not None and vis["no_gano_pct"] is not None:
        if vis["no_gano_pct"] - loc["no_gano_pct"] >= 5.0:
            recs.append(
                f"El favorito VISITANTE no gana el {vis['no_gano_pct']}% de las veces, "
                f"vs {loc['no_gano_pct']}% del favorito local: prioriza favoritos LOCALES."
            )
    if cerrado.get("n") and abierto.get("n") and cerrado["no_gano_pct"] is not None and abierto["no_gano_pct"] is not None:
        if cerrado["no_gano_pct"] - abierto["no_gano_pct"] >= 5.0:
            recs.append(
                f"En partidos CERRADOS (pocos goles esperados, 'under') el favorito no gana "
                f"el {cerrado['no_gano_pct']}%, vs {abierto['no_gano_pct']}% en partidos abiertos: "
                f"evita esos partidos para el pick de Survivor."
            )
    # Arranque de torneo (el caso Toluca-Mazatlán semana 1).
    if arranque_vs_resto:
        a = arranque_vs_resto.get("arranque_j1a3", {})
        r = arranque_vs_resto.get("resto_temporada", {})
        if a.get("n") and r.get("n") and a["no_gano_pct"] is not None and r["no_gano_pct"] is not None:
            if a["no_gano_pct"] - r["no_gano_pct"] >= 5.0:
                recs.append(
                    f"En el ARRANQUE (J1-3) el favorito no gana el {a['no_gano_pct']}% "
                    f"(n={a['n']}), vs {r['no_gano_pct']}% en el resto: EXTRA cuidado las "
                    f"primeras jornadas (como Toluca-Mazatlán); guarda equipos fuertes."
                )
    # Muy favoritos que igual fallan.
    if muy_favorito:
        mg = muy_favorito.get("global", {})
        if mg.get("n") and mg.get("no_gano_pct") is not None and mg["no_gano_pct"] >= 20.0:
            recs.append(
                f"Incluso los MUY favoritos (>= {muy_favorito.get('umbral_confianza_pct')}% del modelo) "
                f"no ganan el {mg['no_gano_pct']}% de las veces (n={mg['n']}): 'muy favorito' NO es "
                f"seguro en Survivor."
            )
    if not recs:
        recs.append("No hay diferencias grandes y consistentes en los datos disponibles; "
                    "usa la confianza del modelo y revisa caso por caso.")
    return recs


def analizar_riesgo_favoritos(
    resultados: Sequence[Dict[str, Any]],
    min_train: int = MIN_TRAIN,
) -> Dict[str, Any]:
    """
    Analiza, sobre los resultados reales, cuándo y por qué falla el favorito del
    modelo. Devuelve tasas globales y desgloses por condición, confianza y
    "partido cerrado", más recomendaciones derivadas de esos números.
    """
    jornadas = agrupar_jornadas(resultados)
    ordenados = sorted(resultados, key=lambda r: str(r.get("fecha", "")))
    labels_arranque = _labels_arranque(jornadas)

    eventos: List[Dict[str, Any]] = []
    historico: List[Dict[str, Any]] = []
    idx = 0
    for j in jornadas:
        while idx < len(ordenados) and _semana_iso(ordenados[idx].get("fecha")) < j["jornada"]:
            historico.append(ordenados[idx]); idx += 1
        if len(historico) < min_train:
            continue
        try:
            fuerzas = pm.calcular_fuerzas(historico)
        except ValueError:
            continue
        es_arranque = j["jornada"] in labels_arranque
        for p in j["partidos"]:
            ev = _evaluar_partido(p, fuerzas)
            if ev is not None:
                ev["arranque"] = es_arranque
                eventos.append(ev)

    por_condicion = {
        "local": _tasas([e for e in eventos if e["favorito_local"]]),
        "visitante": _tasas([e for e in eventos if not e["favorito_local"]]),
    }
    por_confianza: Dict[str, Any] = {}
    for e in eventos:
        b = _bucket_confianza(e["confianza_pct"])
        por_confianza.setdefault(b, []).append(e)
    por_confianza = {b: _tasas(evs) for b, evs in por_confianza.items()}

    cerrado = _tasas([e for e in eventos if e["partido_cerrado"]])
    abierto = _tasas([e for e in eventos if not e["partido_cerrado"]])

    # Muy favoritos del modelo (conf. alta): ¿cuánto fallan? (tu caso Toluca).
    muy_fav = [e for e in eventos if e["confianza_pct"] >= CONF_MUY_FAVORITO]
    muy_favorito = {
        "umbral_confianza_pct": CONF_MUY_FAVORITO,
        "global": _tasas(muy_fav),
        "local": _tasas([e for e in muy_fav if e["favorito_local"]]),
        "visitante": _tasas([e for e in muy_fav if not e["favorito_local"]]),
    }

    # Arranque de torneo (J1-3) vs resto: ¿las sorpresas son peores al inicio?
    arr = [e for e in eventos if e.get("arranque")]
    resto = [e for e in eventos if not e.get("arranque")]
    arranque_vs_resto = {
        "arranque_j1a3": _tasas(arr),
        "resto_temporada": _tasas(resto),
        "muy_favorito_en_arranque": _tasas([e for e in muy_fav if e.get("arranque")]),
    }

    # De los fallos: ¿cómo se reparten? (responde "qué les faltó / local-visitante").
    fallos = [e for e in eventos if e["fallo"]]
    perfil_fallos = {
        "total_fallos": len(fallos),
        "fueron_visitantes_pct": round(100.0 * sum(1 for e in fallos if not e["favorito_local"]) / len(fallos), 1) if fallos else None,
        "fueron_partido_cerrado_pct": round(100.0 * sum(1 for e in fallos if e["partido_cerrado"]) / len(fallos), 1) if fallos else None,
        "terminaron_en_empate_pct": round(100.0 * sum(1 for e in fallos if e["outcome"] == "empato") / len(fallos), 1) if fallos else None,
    }

    return {
        "partidos_evaluados": len(eventos),
        "global": _tasas(eventos),
        "por_condicion": por_condicion,
        "por_confianza": por_confianza,
        "por_tipo_partido": {"cerrado_under": cerrado, "abierto": abierto},
        "muy_favorito": muy_favorito,
        "arranque_vs_resto": arranque_vs_resto,
        "perfil_de_los_fallos": perfil_fallos,
        "umbral_partido_cerrado_goles": UMBRAL_PARTIDO_CERRADO,
        "recomendaciones": _recomendaciones(por_condicion, cerrado, abierto,
                                            arranque_vs_resto, muy_favorito),
        "decision": DEC_INFORMATIVA,
    }


def main() -> int:
    try:
        import fuentes_datos
    except ImportError:  # pragma: no cover
        from src import fuentes_datos  # type: ignore
    print("🔎 Analizando cuándo falla el favorito del modelo (datos reales ESPN)...")
    datos = fuentes_datos.obtener_resultados(meses=18)
    r = analizar_riesgo_favoritos(datos["resultados"])
    g = r["global"]
    print(f"Fuente: {datos['fuente']} | partidos evaluados: {r['partidos_evaluados']}")
    if g["n"]:
        print(f"Favorito: ganó {g['gano_pct']}% | empató {g['empato_pct']}% | "
              f"perdió {g['perdio_pct']}% (no ganó {g['no_gano_pct']}%)")
    loc = r["por_condicion"]["local"]; vis = r["por_condicion"]["visitante"]
    print(f"  Local    (n={loc['n']}): no gana {loc['no_gano_pct']}%")
    print(f"  Visitante(n={vis['n']}): no gana {vis['no_gano_pct']}%")
    cer = r["por_tipo_partido"]["cerrado_under"]; abi = r["por_tipo_partido"]["abierto"]
    print(f"  Cerrado/under (n={cer['n']}): no gana {cer['no_gano_pct']}%")
    print(f"  Abierto       (n={abi['n']}): no gana {abi['no_gano_pct']}%")
    print("Por confianza del modelo:")
    for b in ("<55% (sin claro favorito)", "55-65%", "65-75%", ">=75%"):
        t = r["por_confianza"].get(b)
        if t and t["n"]:
            print(f"  {b}: no gana {t['no_gano_pct']}% (n={t['n']})")
    mf = r.get("muy_favorito", {}).get("global", {})
    if mf.get("n"):
        print(f"MUY favoritos (>= {r['muy_favorito']['umbral_confianza_pct']}%): "
              f"no ganan {mf['no_gano_pct']}% (n={mf['n']})")
    avr = r.get("arranque_vs_resto", {})
    a, rest = avr.get("arranque_j1a3", {}), avr.get("resto_temporada", {})
    if a.get("n") and rest.get("n"):
        print(f"Arranque J1-3: no gana {a['no_gano_pct']}% (n={a['n']}) | "
              f"resto: {rest['no_gano_pct']}% (n={rest['n']})")
    print("Recomendaciones (según TUS datos):")
    for rec in r["recomendaciones"]:
        print(f"  • {rec}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
