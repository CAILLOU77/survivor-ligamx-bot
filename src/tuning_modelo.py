#!/usr/bin/env python3
"""
tuning_modelo.py — Afina los hiperparámetros del modelo Poisson/Dixon-Coles
contra el histórico real, minimizando el Brier (calibración), SIN trampa.

Los tres parámetros del modelo (hoy puestos a mano) son:
  - half_life_dias : cuánto pesan los partidos recientes (recencia)
  - shrink         : regularización hacia el promedio de liga (equipos con pocos datos)
  - rho            : corrección Dixon-Coles (empates / marcadores bajos)

Método honesto (partición temporal en 3):
  1) TRAIN (60% más antiguo): estima fuerzas.
  2) VALIDACIÓN (20% medio): se elige la combinación con MENOR Brier aquí.
  3) HOLDOUT (20% más nuevo): se CONFIRMA la mejora vs los valores actuales, en
     datos que el tuning nunca vio (evita el autoengaño de elegir y evaluar en lo
     mismo).

Menor Brier = probabilidades mejor calibradas. Informativo / revisión humana.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Sequence, Tuple

try:
    import poisson_model as pm
    from backtesting import brier_score
except ImportError:  # pragma: no cover
    from src import poisson_model as pm  # type: ignore
    from src.backtesting import brier_score  # type: ignore

DEC_INFORMATIVA = "INFORMATIVO / REVISIÓN HUMANA"

GRID_HALF_LIFE: Tuple[float, ...] = (180.0, 365.0, 550.0, 730.0)
GRID_SHRINK: Tuple[float, ...] = (2.0, 4.0, 6.0, 10.0)
GRID_RHO: Tuple[float, ...] = (-0.18, -0.12, -0.08, -0.03)

# Mejora MÍNIMA de Brier en holdout para recomendar cambiar el modelo. Por debajo
# de esto la "mejora" es ruido del split y cambiar sería falsa precisión.
MEJORA_MINIMA_BRIER: float = 0.005


def _resultado_1x2(hg: int, ag: int) -> int:
    if hg > ag:
        return 1
    if hg == ag:
        return 2
    return 3


def _brier_conjunto(
    train: Sequence[Dict[str, Any]],
    evalset: Sequence[Dict[str, Any]],
    half_life: Optional[float],
    shrink: float,
    rho: float,
) -> Tuple[Optional[float], int]:
    """Brier promedio prediciendo `evalset` con fuerzas entrenadas en `train`."""
    try:
        fuerzas = pm.calcular_fuerzas(train, half_life_dias=half_life, shrink=shrink)
    except ValueError:
        return (None, 0)
    eq = fuerzas.get("equipos", {})
    total = 0.0
    n = 0
    for m in evalset:
        h, a = m.get("home_team", ""), m.get("away_team", "")
        if pm._norm(h) not in eq or pm._norm(a) not in eq:
            continue
        try:
            hg, ag = int(m["home_goals"]), int(m["away_goals"])
        except (KeyError, TypeError, ValueError):
            continue
        pr = pm.pronostico(h, a, fuerzas, rho=rho)
        probs = [pr["prob_local_pct"] / 100.0, pr["prob_empate_pct"] / 100.0,
                 pr["prob_visitante_pct"] / 100.0]
        total += brier_score(probs, _resultado_1x2(hg, ag))
        n += 1
    return (total / n if n else None, n)


def tunear_hiperparametros(
    resultados: Sequence[Dict[str, Any]],
    grid_half: Sequence[float] = GRID_HALF_LIFE,
    grid_shrink: Sequence[float] = GRID_SHRINK,
    grid_rho: Sequence[float] = GRID_RHO,
) -> Dict[str, Any]:
    """
    Busca (half_life, shrink, rho) que minimizan el Brier en validación y confirma
    la mejora vs los valores ACTUALES en un holdout no visto.
    """
    ordenados = sorted(resultados, key=lambda r: str(r.get("fecha", "")))
    n = len(ordenados)
    if n < 120:
        return {"n": n, "mensaje": "Datos insuficientes para afinar (se necesitan ~120+).",
                "decision": DEC_INFORMATIVA}
    a, b = int(n * 0.6), int(n * 0.8)
    train, val, holdout = ordenados[:a], ordenados[a:b], ordenados[b:]

    mejor: Optional[Dict[str, Any]] = None
    for hl in grid_half:
        for sk in grid_shrink:
            for rho in grid_rho:
                br, cnt = _brier_conjunto(train, val, hl, sk, rho)
                if br is None or cnt == 0:
                    continue
                if mejor is None or br < mejor["brier_val"]:
                    mejor = {"half_life_dias": hl, "shrink": sk, "rho": rho,
                             "brier_val": round(br, 4)}
    if mejor is None:
        return {"n": n, "mensaje": "No se pudo evaluar ninguna combinación.",
                "decision": DEC_INFORMATIVA}

    # Confirmación en holdout: sugeridos vs actuales (entrenando en train+val).
    trainval = ordenados[:b]
    br_sug, _ = _brier_conjunto(trainval, holdout, mejor["half_life_dias"],
                                mejor["shrink"], mejor["rho"])
    br_act, _ = _brier_conjunto(trainval, holdout, pm.RECENCIA_HALF_LIFE_DIAS,
                                pm.SHRINK_PRIOR, pm.RHO_DIXON_COLES)
    mejora = (round(br_act - br_sug, 4) if (br_sug is not None and br_act is not None)
              else None)
    return {
        "n": n,
        "actuales": {"half_life_dias": pm.RECENCIA_HALF_LIFE_DIAS,
                     "shrink": pm.SHRINK_PRIOR, "rho": pm.RHO_DIXON_COLES},
        "sugeridos": {"half_life_dias": mejor["half_life_dias"],
                      "shrink": mejor["shrink"], "rho": mejor["rho"]},
        "brier_holdout_actual": round(br_act, 4) if br_act is not None else None,
        "brier_holdout_sugerido": round(br_sug, 4) if br_sug is not None else None,
        "mejora_holdout": mejora,
        "mejora_minima": MEJORA_MINIMA_BRIER,
        # Solo recomendar cambiar si la mejora supera el umbral de ruido.
        "aplicar": bool(mejora is not None and mejora > MEJORA_MINIMA_BRIER),
        "decision": DEC_INFORMATIVA,
    }


def _brier_altitud(
    train: Sequence[Dict[str, Any]],
    evalset: Sequence[Dict[str, Any]],
    k_altitud: float,
) -> Tuple[Optional[float], int]:
    """Brier prediciendo `evalset` con el modelo + ajuste de altitud (coef k)."""
    try:
        import altitud as alt
    except ImportError:  # pragma: no cover
        from src import altitud as alt  # type: ignore
    try:
        fuerzas = pm.calcular_fuerzas(train)
    except ValueError:
        return (None, 0)
    eq = fuerzas.get("equipos", {})
    total = 0.0
    n = 0
    for m in evalset:
        h, a = m.get("home_team", ""), m.get("away_team", "")
        if pm._norm(h) not in eq or pm._norm(a) not in eq:
            continue
        try:
            hg, ag = int(m["home_goals"]), int(m["away_goals"])
        except (KeyError, TypeError, ValueError):
            continue
        pr = pm.pronostico(h, a, fuerzas)
        if k_altitud > 0:
            pl, pe, pv = alt.ajustar_1x2_por_altitud(pr, k=k_altitud)
        else:
            pl, pe, pv = pr["prob_local_pct"], pr["prob_empate_pct"], pr["prob_visitante_pct"]
        probs = [pl / 100.0, pe / 100.0, pv / 100.0]
        total += brier_score(probs, _resultado_1x2(hg, ag))
        n += 1
    return (total / n if n else None, n)


def medir_altitud(
    resultados: Sequence[Dict[str, Any]],
    grid_k: Sequence[float] = (0.0, 0.03, 0.06, 0.10, 0.15),
) -> Dict[str, Any]:
    """
    ¿Ayuda el factor de altitud? Elige el coeficiente k en validación (Brier) y
    confirma en holdout no visto vs SIN altitud (k=0). Aplica solo si mejora real.
    """
    ordenados = sorted(resultados, key=lambda r: str(r.get("fecha", "")))
    n = len(ordenados)
    if n < 120:
        return {"n": n, "mensaje": "Datos insuficientes.", "decision": DEC_INFORMATIVA}
    a, b = int(n * 0.6), int(n * 0.8)
    train, val, holdout = ordenados[:a], ordenados[a:b], ordenados[b:]

    mejor_k, mejor_br = 0.0, None
    for k in grid_k:
        br, cnt = _brier_altitud(train, val, k)
        if br is None or cnt == 0:
            continue
        if mejor_br is None or br < mejor_br:
            mejor_k, mejor_br = k, br

    trainval = ordenados[:b]
    br_alt, _ = _brier_altitud(trainval, holdout, mejor_k)
    br_off, _ = _brier_altitud(trainval, holdout, 0.0)
    mejora = (round(br_off - br_alt, 4) if (br_alt is not None and br_off is not None)
              else None)
    return {
        "n": n,
        "k_sugerido": mejor_k,
        "brier_holdout_sin_altitud": round(br_off, 4) if br_off is not None else None,
        "brier_holdout_con_altitud": round(br_alt, 4) if br_alt is not None else None,
        "mejora_holdout": mejora,
        "aplicar": bool(mejora is not None and mejora > MEJORA_MINIMA_BRIER and mejor_k > 0),
        "decision": DEC_INFORMATIVA,
    }


def main() -> int:
    try:
        import fuentes_datos
    except ImportError:  # pragma: no cover
        from src import fuentes_datos  # type: ignore
    print("🔧 Afinando parámetros del modelo (historial largo, minimiza Brier)...")
    datos = fuentes_datos.obtener_historico_largo()
    r = tunear_hiperparametros(datos["resultados"])
    if r.get("mensaje"):
        print(f"⚠️ {r['mensaje']}")
        return 1
    print(f"Partidos: {r['n']}")
    print(f"Actuales:  {r['actuales']}")
    print(f"Sugeridos: {r['sugeridos']}")
    print(f"Brier holdout — actual: {r['brier_holdout_actual']} | "
          f"sugerido: {r['brier_holdout_sugerido']} | mejora: {r['mejora_holdout']}")
    if r["aplicar"]:
        print(f"¿Aplicar?: SÍ (mejora {r['mejora_holdout']} > umbral {r['mejora_minima']})")
    else:
        print(f"¿Aplicar?: NO — la mejora ({r['mejora_holdout']}) es ruido; el modelo "
              "ya está bien calibrado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
