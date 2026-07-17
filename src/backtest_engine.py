#!/usr/bin/env python3
"""
backtest_engine.py — Validación HONESTA del modelo (NO inventa resultados).

ANTES: liquidaba los picks con un volado aleatorio (60% win simulado), lo que
contaminaba /stats y /dashboard con métricas FALSAS de win-rate y profit.

AHORA: corre la validación real del modelo Poisson contra resultados REALES de
ESPN (accuracy / Brier / baseline), vía validacion_modelo. No simula apuestas,
no fabrica nada. Informativo / revisión humana.
"""

from __future__ import annotations

from typing import Any, Dict

try:
    import fuentes_datos
    import validacion_modelo
except ImportError:  # pragma: no cover - contexto de paquete (web)
    from src import fuentes_datos, validacion_modelo  # type: ignore


def run_backtest(meses: int = 18) -> Dict[str, Any]:
    """
    Evalúa el modelo contra resultados reales de ESPN (train/test por fecha).
    Devuelve accuracy, Brier, baseline y si supera al baseline. NO inventa
    resultados ni liquida apuestas.
    """
    datos = fuentes_datos.obtener_resultados(meses=meses)
    resultado = validacion_modelo.evaluar_modelo(datos.get("resultados", []))
    resultado["fuente_datos"] = datos.get("fuente")
    resultado["nota"] = "Validación real del modelo vs ESPN (sin simular apuestas)."
    return resultado


if __name__ == "__main__":
    import json

    print(json.dumps(run_backtest(), ensure_ascii=False, indent=2))
