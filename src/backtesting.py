#!/usr/bin/env python3
"""
backtesting.py — Métricas de backtesting de momios (Survivor Liga MX).

Matemática pura para evaluar qué tan buenos habrían sido los pronósticos vs.
resultados reales: ROI, Win Rate, Brier score (calibración de true_prob vs
modelo) y distribución del VIG.

Convención 1X2: resultado/pick en {1: local, 2: empate, 3: visitante}.

Sin red, sin I/O. NO cierra ni envía picks. Decisión operativa: ESPERAR / NO ENVIAR.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

DEC_ESPERAR = "ESPERAR / NO ENVIAR"


def ganancia_apuesta(odds: float, gano: bool, stake: float = 1.0) -> float:
    """Ganancia neta de una apuesta a cuota decimal (stake plano)."""
    if odds <= 1.0:
        raise ValueError("La cuota decimal debe ser > 1.0.")
    return stake * (odds - 1.0) if gano else -stake


def roi(apuestas: Sequence[Dict[str, Any]], stake: float = 1.0) -> float:
    """
    ROI = ganancia_neta_total / total_apostado.
    Cada apuesta: {"odds": float, "gano": bool}.
    """
    if not apuestas:
        return 0.0
    ganancia = sum(ganancia_apuesta(a["odds"], a["gano"], stake) for a in apuestas)
    return ganancia / (stake * len(apuestas))


def win_rate(apuestas: Sequence[Dict[str, Any]]) -> float:
    """Proporción de apuestas ganadas (0-1)."""
    if not apuestas:
        return 0.0
    return sum(1 for a in apuestas if a["gano"]) / len(apuestas)


def brier_score(prob: Sequence[float], resultado: int) -> float:
    """
    Brier score multiclase para un pronóstico 1X2.
    prob = [p1, p2, p3]; resultado en {1,2,3}. Menor = mejor calibrado.
    """
    if len(prob) != 3:
        raise ValueError("prob debe tener 3 valores (1X2).")
    if resultado not in (1, 2, 3):
        raise ValueError("resultado debe ser 1, 2 o 3.")
    objetivo = [1.0 if (i + 1) == resultado else 0.0 for i in range(3)]
    return sum((p - o) ** 2 for p, o in zip(prob, objetivo))


def brier_promedio(pronosticos: Sequence[Dict[str, Any]]) -> float:
    """
    Brier promedio sobre varios pronósticos.
    Cada item: {"prob": [p1,p2,p3], "resultado": 1|2|3}.
    """
    if not pronosticos:
        return 0.0
    total = sum(brier_score(p["prob"], p["resultado"]) for p in pronosticos)
    return total / len(pronosticos)


def estrategia_favorito(fila: Dict[str, Any]) -> int:
    """Elige el resultado con mayor true_prob (1, 2 o 3)."""
    probs = [
        float(fila.get("true_prob_1", 0)),
        float(fila.get("true_prob_2", 0)),
        float(fila.get("true_prob_3", 0)),
    ]
    return max(range(3), key=lambda i: probs[i]) + 1


def _odds_de(fila: Dict[str, Any], pick: int) -> float:
    return float(fila[f"momio_{pick}"])


def evaluar_dataset(
    filas: Sequence[Dict[str, Any]],
    estrategia=estrategia_favorito,
    stake: float = 1.0,
) -> Dict[str, Any]:
    """
    Evalúa una estrategia sobre filas con resultado real.

    Cada fila debe traer momio_1/2/3, true_prob_1/2/3 y 'resultado' (1|2|3).
    Las filas sin 'resultado' se ignoran (partidos no jugados).
    """
    apuestas: List[Dict[str, Any]] = []
    brier_items: List[Dict[str, Any]] = []

    for fila in filas:
        resultado = fila.get("resultado")
        try:
            resultado = int(resultado)
        except (TypeError, ValueError):
            continue
        if resultado not in (1, 2, 3):
            continue

        pick = estrategia(fila)
        odds = _odds_de(fila, pick)
        apuestas.append({"odds": odds, "gano": pick == resultado})
        brier_items.append({
            "prob": [
                float(fila.get("true_prob_1", 0)),
                float(fila.get("true_prob_2", 0)),
                float(fila.get("true_prob_3", 0)),
            ],
            "resultado": resultado,
        })

    ganancia = sum(ganancia_apuesta(a["odds"], a["gano"], stake) for a in apuestas)
    return {
        "n_apuestas": len(apuestas),
        "aciertos": sum(1 for a in apuestas if a["gano"]),
        "win_rate": round(win_rate(apuestas), 4),
        "roi": round(roi(apuestas, stake), 4),
        "ganancia_neta": round(ganancia, 4),
        "brier_promedio": round(brier_promedio(brier_items), 4),
        "decision": DEC_ESPERAR,
    }


def distribucion_vig(
    valores: Sequence[float],
    bins: Sequence[float] = (0, 3, 5, 7, 10, 15),
) -> List[Dict[str, Any]]:
    """
    Histograma del VIG (%). Devuelve [{rango, conteo}] por cada bin [lo, hi).
    El último bin incluye el límite superior.
    """
    limites = list(bins)
    conteos = [0] * (len(limites) - 1)
    for v in valores:
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        for i in range(len(limites) - 1):
            lo, hi = limites[i], limites[i + 1]
            ultimo = i == len(limites) - 2
            if (lo <= x < hi) or (ultimo and x == hi):
                conteos[i] += 1
                break
    return [
        {"rango": f"{limites[i]}-{limites[i + 1]}%", "conteo": conteos[i]}
        for i in range(len(conteos))
    ]


def resumen_trend(filas: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    """Cuenta subió/bajó/estable por mercado (trend_1/2/3)."""
    salida = {
        "trend_1": {"subio": 0, "bajo": 0, "estable": 0},
        "trend_2": {"subio": 0, "bajo": 0, "estable": 0},
        "trend_3": {"subio": 0, "bajo": 0, "estable": 0},
    }
    mapa = {1: "subio", -1: "bajo", 0: "estable"}
    for fila in filas:
        for col in ("trend_1", "trend_2", "trend_3"):
            try:
                v = int(fila.get(col, 0))
            except (TypeError, ValueError):
                v = 0
            salida[col][mapa.get(v, "estable")] += 1
    return salida
