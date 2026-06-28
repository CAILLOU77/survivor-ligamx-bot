#!/usr/bin/env python3
"""
validacion_modelo.py — ¿Qué tan bueno es el modelo? (backtesting honesto).

Valida el modelo Poisson contra resultados REALES de ESPN, sin trampas:
- Ordena los partidos por fecha.
- Entrena la fuerza de equipos con la parte ANTIGUA (train).
- Predice la parte RECIENTE (test) y compara con lo que de verdad pasó.

Métricas:
- accuracy: % de aciertos del pick 1X2.
- brier_promedio: calibración de probabilidades (menor = mejor; 0 = perfecto).
- baseline_local: accuracy de "siempre gana local" (para comparar si el modelo
  aporta sobre lo trivial).

Sin red propia (recibe resultados) ni momios. Informativo.
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence

try:
    import poisson_model as pm
    from backtesting import brier_score
except ImportError:  # pragma: no cover
    from src import poisson_model as pm  # type: ignore
    from src.backtesting import brier_score  # type: ignore


def _resultado_1x2(home_goals: int, away_goals: int) -> int:
    if home_goals > away_goals:
        return 1
    if home_goals == away_goals:
        return 2
    return 3


def evaluar_modelo(
    resultados: Sequence[Dict[str, Any]],
    fraccion_test: float = 0.3,
) -> Dict[str, Any]:
    """
    Entrena con los partidos antiguos y evalúa con los recientes.
    Requiere suficientes partidos; si no, devuelve n_evaluados=0.
    """
    ordenados = sorted(resultados, key=lambda r: str(r.get("fecha", "")))
    n = len(ordenados)
    if n < 10:
        return {"n_evaluados": 0, "mensaje": "Datos insuficientes para validar."}

    corte = int(n * (1 - fraccion_test))
    train, test = ordenados[:corte], ordenados[corte:]
    if not train or not test:
        return {"n_evaluados": 0, "mensaje": "Partición vacía."}

    try:
        fuerzas = pm.calcular_fuerzas(train)
    except ValueError:
        return {"n_evaluados": 0, "mensaje": "No se pudieron estimar fuerzas."}

    eq = fuerzas.get("equipos", {})
    aciertos = 0
    aciertos_local = 0
    n_eval = 0
    brier_total = 0.0

    for m in test:
        home, away = m.get("home_team", ""), m.get("away_team", "")
        if pm._norm(home) not in eq or pm._norm(away) not in eq:
            continue
        try:
            hg, ag = int(m["home_goals"]), int(m["away_goals"])
        except (KeyError, TypeError, ValueError):
            continue
        actual = _resultado_1x2(hg, ag)
        pron = pm.pronostico(home, away, fuerzas)
        probs = [
            pron["prob_local_pct"] / 100.0,
            pron["prob_empate_pct"] / 100.0,
            pron["prob_visitante_pct"] / 100.0,
        ]
        pick = max(range(3), key=lambda i: probs[i]) + 1
        if pick == actual:
            aciertos += 1
        if actual == 1:
            aciertos_local += 1
        brier_total += brier_score(probs, actual)
        n_eval += 1

    if n_eval == 0:
        return {"n_evaluados": 0, "mensaje": "Sin partidos evaluables en test."}

    return {
        "n_train": len(train),
        "n_evaluados": n_eval,
        "accuracy": round(aciertos / n_eval, 4),
        "brier_promedio": round(brier_total / n_eval, 4),
        "baseline_local": round(aciertos_local / n_eval, 4),
        "mejor_que_baseline": (aciertos / n_eval) > (aciertos_local / n_eval),
        "decision": "INFORMATIVO / REVISIÓN HUMANA",
    }


def main() -> int:
    try:
        import fuentes_datos
    except ImportError:  # pragma: no cover
        from src import fuentes_datos  # type: ignore
    print("📏 Validando modelo contra resultados reales de ESPN...")
    datos = fuentes_datos.obtener_resultados(meses=8)
    r = evaluar_modelo(datos["resultados"])
    if r.get("n_evaluados", 0) == 0:
        print(f"⚠️ {r.get('mensaje')}")
        return 1
    print(f"Fuente: {datos['fuente']} | train: {r['n_train']} | test: {r['n_evaluados']}")
    print(f"Accuracy 1X2: {r['accuracy']*100:.1f}%  (baseline 'siempre local': {r['baseline_local']*100:.1f}%)")
    print(f"Brier promedio: {r['brier_promedio']}  (menor = mejor)")
    print(f"¿Mejor que baseline?: {'SÍ' if r['mejor_que_baseline'] else 'NO'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
