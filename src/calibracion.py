#!/usr/bin/env python3
"""
calibracion.py — Calibración de probabilidades del modelo (honesta, medible).

Se midió que el favorito del modelo gana ~52%: señal de que las probabilidades
pueden ser algo OPTIMISTAS (poco calibradas). Este módulo mide y corrige eso con
"shrinkage hacia la tasa base":

    p_calibrada = (1 - alpha) * p_modelo + alpha * tasa_base

donde `tasa_base` es la distribución real de resultados 1X2 de la liga (local/
empate/visita). alpha=0 => sin cambio; alpha alto => arrastra hacia el promedio
(menos confianza). El mejor alpha se AJUSTA minimizando el Brier score sobre
predicciones fuera de muestra (walk-forward), y se reporta cuánto mejora.

Filosofía del proyecto: no inventa nada, todo se deriva de resultados reales, y
la calibración es OPT-IN (por defecto desactivada): se activa solo cuando los
datos muestran que mejora la calibración. Informativo / revisión humana.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple, cast

try:
    import poisson_model as pm
    from backtesting import brier_score
    from simulador_survivor import MIN_TRAIN, _semana_iso, agrupar_jornadas
except ImportError:  # pragma: no cover
    from src import poisson_model as pm  # type: ignore
    from src.backtesting import brier_score  # type: ignore
    from src.simulador_survivor import (  # type: ignore
        MIN_TRAIN,
        _semana_iso,
        agrupar_jornadas,
    )

DEC_INFORMATIVA = "INFORMATIVO / REVISIÓN HUMANA"
GRID_ALPHA: Tuple[float, ...] = tuple(round(i * 0.05, 2) for i in range(0, 13))  # 0..0.60


def _resultado_1x2(hg: int, ag: int) -> int:
    if hg > ag:
        return 1
    if hg == ag:
        return 2
    return 3


def tasa_base(resultados: Sequence[Dict[str, Any]]) -> Tuple[float, float, float]:
    """Distribución real de resultados 1X2 (p_local, p_empate, p_visita)."""
    n = c1 = c2 = c3 = 0
    for r in resultados:
        try:
            hg, ag = int(r["home_goals"]), int(r["away_goals"])
        except (KeyError, TypeError, ValueError):
            continue
        res = _resultado_1x2(hg, ag)
        c1 += res == 1
        c2 += res == 2
        c3 += res == 3
        n += 1
    if n == 0:
        return (1 / 3, 1 / 3, 1 / 3)
    return (c1 / n, c2 / n, c3 / n)


def calibrar_probs(
    probs: Sequence[float],
    alpha: float,
    base: Sequence[float],
) -> List[float]:
    """
    Shrinkage hacia la tasa base: (1-alpha)*probs + alpha*base, renormalizado.
    alpha en [0,1]. alpha=0 => sin cambio.
    """
    if len(probs) != len(base):
        raise ValueError("probs y base deben tener el mismo largo.")
    a = max(0.0, min(1.0, float(alpha)))
    mez = [(1.0 - a) * float(p) + a * float(b) for p, b in zip(probs, base)]
    s = sum(mez)
    if s <= 0:
        raise ValueError("Mezcla no positiva.")
    return [x / s for x in mez]


def ajustar_alpha(
    muestras: Sequence[Dict[str, Any]],
    base: Sequence[float],
    grid: Sequence[float] = GRID_ALPHA,
) -> Dict[str, Any]:
    """
    Busca el alpha que MINIMIZA el Brier promedio sobre las muestras.
    Cada muestra: {"probs": [p1,p2,p3], "resultado": 1|2|3}.
    """
    if not muestras:
        return {"alpha": 0.0, "brier_base": None, "brier_calibrado": None, "n": 0}

    def brier_con(alpha: float) -> float:
        tot = 0.0
        for m in muestras:
            pc = calibrar_probs(m["probs"], alpha, base)
            tot += brier_score(pc, int(m["resultado"]))
        return tot / len(muestras)

    brier0 = brier_con(0.0)
    mejor_alpha, mejor_brier = 0.0, brier0
    for a in grid:
        b = brier_con(a)
        if b < mejor_brier:
            mejor_alpha, mejor_brier = a, b
    return {
        "alpha": round(mejor_alpha, 3),
        "brier_base": round(brier0, 4),
        "brier_calibrado": round(mejor_brier, 4),
        "mejora_brier": round(brier0 - mejor_brier, 4),
        "n": len(muestras),
    }


def _muestras_walkforward(
    resultados: Sequence[Dict[str, Any]],
    min_train: int = MIN_TRAIN,
) -> List[Dict[str, Any]]:
    """
    Predicciones FUERA DE MUESTRA (walk-forward): por jornada, entrena con lo
    anterior y predice cada partido. Devuelve [{probs, resultado, fecha}].
    """
    jornadas = agrupar_jornadas(resultados)
    ordenados = sorted(resultados, key=lambda r: str(r.get("fecha", "")))
    muestras: List[Dict[str, Any]] = []
    historico: List[Dict[str, Any]] = []
    idx = 0
    for j in jornadas:
        while idx < len(ordenados) and _semana_iso(ordenados[idx].get("fecha")) < j["jornada"]:
            historico.append(ordenados[idx])
            idx += 1
        if len(historico) < min_train:
            continue
        try:
            fuerzas = pm.calcular_fuerzas(historico)
        except ValueError:
            continue
        eq = fuerzas.get("equipos", {})
        for p in j["partidos"]:
            h, a = p.get("home_team", ""), p.get("away_team", "")
            if pm._norm(h) not in eq or pm._norm(a) not in eq:
                continue
            try:
                hg, ag = int(p["home_goals"]), int(p["away_goals"])
            except (KeyError, TypeError, ValueError):
                continue
            pr = pm.pronostico(h, a, fuerzas)
            muestras.append(
                {
                    "probs": [
                        pr["prob_local_pct"] / 100.0,
                        pr["prob_empate_pct"] / 100.0,
                        pr["prob_visitante_pct"] / 100.0,
                    ],
                    "resultado": _resultado_1x2(hg, ag),
                    "fecha": str(p.get("fecha", "")),
                }
            )
    return muestras


def evaluar_calibracion(
    resultados: Sequence[Dict[str, Any]],
    min_train: int = MIN_TRAIN,
) -> Dict[str, Any]:
    """
    Mide si calibrar mejora el modelo, SIN trampas: genera predicciones
    fuera de muestra (walk-forward), parte en dos por tiempo, AJUSTA alpha en la
    1ª mitad y REPORTA el Brier (base vs calibrado) en la 2ª mitad. Así el alpha
    no se evalúa sobre los mismos datos donde se ajustó.
    """
    muestras = _muestras_walkforward(resultados, min_train)
    if len(muestras) < 20:
        return {
            "n_muestras": len(muestras),
            "mensaje": "Muestras insuficientes para calibrar.",
            "decision": DEC_INFORMATIVA,
        }

    muestras.sort(key=lambda m: m["fecha"])
    corte = len(muestras) // 2
    ajuste_set, eval_set = muestras[:corte], muestras[corte:]

    base = tasa_base(resultados)
    fit = ajustar_alpha(ajuste_set, base)
    alpha = fit["alpha"]

    def brier_prom(mset: Sequence[Dict[str, Any]], a: float) -> float:
        return cast(
            float, sum(brier_score(calibrar_probs(m["probs"], a, base), int(m["resultado"])) for m in mset) / len(mset)
        )

    brier_base_eval = round(brier_prom(eval_set, 0.0), 4)
    brier_cal_eval = round(brier_prom(eval_set, alpha), 4)
    return {
        "n_muestras": len(muestras),
        "tasa_base": {"local": round(base[0], 3), "empate": round(base[1], 3), "visita": round(base[2], 3)},
        "alpha_sugerido": alpha,
        "brier_sin_calibrar_eval": brier_base_eval,
        "brier_calibrado_eval": brier_cal_eval,
        "mejora_brier_eval": round(brier_base_eval - brier_cal_eval, 4),
        "calibracion_ayuda": brier_cal_eval < brier_base_eval,
        "ajuste_en_1a_mitad": fit,
        "decision": DEC_INFORMATIVA,
    }


def calibrar_pronostico(
    pron: Dict[str, Any],
    alpha: float,
    base: Sequence[float],
) -> Dict[str, Any]:
    """
    Devuelve una COPIA del pronóstico (formato motor_pronosticos) con el 1X2
    calibrado por shrinkage. Recalcula pick, no-perder y nivel de confianza 1X2.
    OPT-IN: con alpha=0 devuelve el pronóstico sin cambios (salvo marca).
    """
    out = dict(pron)
    try:
        probs = [pron["prob_local_pct"] / 100.0, pron["prob_empate_pct"] / 100.0, pron["prob_visitante_pct"] / 100.0]
    except (KeyError, TypeError):
        return out
    pc = calibrar_probs(probs, alpha, base)
    pl, pe, pv = (round(x * 100.0, 2) for x in pc)
    if pl >= pe and pl >= pv:
        pick = "Gana Local"
    elif pv >= pl and pv >= pe:
        pick = "Gana Visitante"
    else:
        pick = "Empate"
    out.update(
        {
            "prob_local_pct": pl,
            "prob_empate_pct": pe,
            "prob_visitante_pct": pv,
            "prob_pick_pct": round(max(pl, pe, pv), 2),
            "pick_1x2": pick,
            "no_perder_local_pct": round(pl + pe, 2),
            "no_perder_visitante_pct": round(pv + pe, 2),
            "calibrado": {"alpha": round(float(alpha), 3)},
        }
    )
    return out


def main() -> int:
    from src import fuentes_datos

    print("📐 Midiendo calibración del modelo (walk-forward, historial largo)...")
    datos = fuentes_datos.obtener_historico_largo()
    r = evaluar_calibracion(datos["resultados"])
    if r.get("n_muestras", 0) < 20:
        print(f"⚠️ {r.get('mensaje')}")
        return 1
    print(f"Muestras: {r['n_muestras']} | tasa base: {r['tasa_base']}")
    print(f"alpha sugerido: {r['alpha_sugerido']}")
    print(
        f"Brier (eval)  sin calibrar: {r['brier_sin_calibrar_eval']} | "
        f"calibrado: {r['brier_calibrado_eval']} | mejora: {r['mejora_brier_eval']}"
    )
    print(f"¿Calibrar ayuda?: {'SÍ' if r['calibracion_ayuda'] else 'NO'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
