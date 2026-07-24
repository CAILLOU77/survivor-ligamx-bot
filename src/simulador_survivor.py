#!/usr/bin/env python3
"""
simulador_survivor.py — Backtest del JUEGO de Survivor (no de apuestas).

Pregunta honesta: "si hubiéramos jugado Survivor toda la temporada usando el
modelo, ¿cuántas jornadas habríamos sobrevivido?".

Método (walk-forward, sin trampas):
- Agrupa los resultados reales por jornada (semana ISO).
- Para cada jornada (a partir de tener suficiente histórico), entrena la fuerza
  de equipos SOLO con lo anterior, elige el equipo con mayor probabilidad de
  NO perder (excluyendo los ya usados en Survivor) y revisa qué pasó de verdad:
  si ese equipo NO perdió, sobrevive; si perdió, eliminado.

Reutiliza poisson_model (mismo modelo del bot). Informativo / revisión humana.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Sequence

from src import poisson_model as pm

DEC_INFORMATIVA = "INFORMATIVO / REVISIÓN HUMANA"
MIN_TRAIN = 30  # partidos mínimos de histórico antes de empezar a "jugar"


def _semana_iso(fecha: Any) -> Optional[str]:
    """'YYYY-Www' (año-semana ISO) para agrupar partidos en jornadas."""
    s = str(fecha or "")[:10]
    try:
        y, m, d = s.split("-")
        iso = date(int(y), int(m), int(d)).isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    except (ValueError, TypeError):
        return None


def agrupar_jornadas(resultados: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Agrupa partidos por semana ISO, en orden cronológico. [{jornada, partidos}]."""
    grupos: Dict[str, List[Dict[str, Any]]] = {}
    for r in resultados:
        wk = _semana_iso(r.get("fecha"))
        if wk is None:
            continue
        grupos.setdefault(wk, []).append(r)
    return [{"jornada": wk, "partidos": grupos[wk]} for wk in sorted(grupos)]


def _no_perder_candidatos(partidos: Sequence[Dict[str, Any]], fuerzas: Dict[str, Any]):
    """Por cada equipo de la jornada (con histórico), su prob. de NO perder."""
    cands = []
    eq = fuerzas.get("equipos", {})
    for p in partidos:
        h, a = p.get("home_team", ""), p.get("away_team", "")
        if pm._norm(h) not in eq or pm._norm(a) not in eq:
            continue
        pr = pm.pronostico(h, a, fuerzas)
        cands.append(
            {
                "equipo": h,
                "rival": a,
                "es_local": True,
                "partido": p,
                "no_perder_pct": round(pr["prob_local_pct"] + pr["prob_empate_pct"], 2),
            }
        )
        cands.append(
            {
                "equipo": a,
                "rival": h,
                "es_local": False,
                "partido": p,
                "no_perder_pct": round(pr["prob_visitante_pct"] + pr["prob_empate_pct"], 2),
            }
        )
    return cands


def _sobrevive(partido: Dict[str, Any], es_local: bool) -> bool:
    """True si el equipo elegido NO perdió (ganó o empató)."""
    try:
        hg, ag = int(partido["home_goals"]), int(partido["away_goals"])
    except (KeyError, TypeError, ValueError):
        return False
    return hg >= ag if es_local else ag >= hg


def simular_temporada(
    resultados: Sequence[Dict[str, Any]],
    min_train: int = MIN_TRAIN,
) -> Dict[str, Any]:
    """
    Simula una corrida de Survivor sobre los resultados reales (walk-forward).
    Devuelve racha de jornadas sobrevividas, en qué jornada cayó y el detalle.
    """
    jornadas = agrupar_jornadas(resultados)
    ordenados = sorted(resultados, key=lambda r: str(r.get("fecha", "")))
    usados: set = set()
    detalle: List[Dict[str, Any]] = []
    jugadas = sobrevividas = 0
    eliminado_en: Optional[str] = None

    historico: List[Dict[str, Any]] = []
    idx = 0
    for j in jornadas:
        # histórico = todo lo ANTERIOR a esta jornada
        while idx < len(ordenados) and _semana_iso(ordenados[idx].get("fecha")) < j["jornada"]:
            historico.append(ordenados[idx])
            idx += 1
        if len(historico) < min_train:
            continue
        try:
            fuerzas = pm.calcular_fuerzas(historico)
        except ValueError:
            continue
        cands = [c for c in _no_perder_candidatos(j["partidos"], fuerzas) if pm._norm(c["equipo"]) not in usados]
        if not cands:
            continue
        elegido = max(cands, key=lambda c: c["no_perder_pct"])
        vivo = _sobrevive(elegido["partido"], elegido["es_local"])
        jugadas += 1
        usados.add(pm._norm(elegido["equipo"]))
        p_ = elegido["partido"]
        detalle.append(
            {
                "jornada": j["jornada"],
                "pick": elegido["equipo"],
                "condicion": "Local" if elegido["es_local"] else "Visitante",
                "rival": elegido["rival"],
                "no_perder_pct": elegido["no_perder_pct"],
                "partido": f"{p_.get('home_team')} {p_.get('home_goals')}-{p_.get('away_goals')} {p_.get('away_team')}",
                "sobrevivio": vivo,
            }
        )
        if vivo:
            sobrevividas += 1
        else:
            eliminado_en = j["jornada"]
            break

    return {
        "jornadas_jugadas": jugadas,
        "jornadas_sobrevividas": sobrevividas,
        "racha_maxima": sobrevividas,
        "eliminado_en": eliminado_en,
        "detalle": detalle,
        "decision": DEC_INFORMATIVA,
    }


def main() -> int:
    from src import fuentes_datos

    print("🎮 Simulando temporada de Survivor con el modelo (datos reales ESPN)...")
    datos = fuentes_datos.obtener_resultados(meses=18)
    r = simular_temporada(datos["resultados"])
    print(
        f"Fuente: {datos['fuente']} | jornadas jugadas: {r['jornadas_jugadas']} | "
        f"sobrevividas: {r['jornadas_sobrevividas']}"
    )
    if r["eliminado_en"]:
        print(f"💀 Eliminado en la jornada {r['eliminado_en']}")
    else:
        print("🏆 Sobrevivió todas las jornadas evaluadas")
    for d in r["detalle"]:
        ico = "✅" if d["sobrevivio"] else "💀"
        print(
            f"  {ico} {d['jornada']}: {d['pick']} ({d['condicion']}, no-perder {d['no_perder_pct']}%) — {d['partido']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
