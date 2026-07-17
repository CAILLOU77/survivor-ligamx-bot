#!/usr/bin/env python3
"""
main.py — Orquestador del bot Survivor Liga MX (path REAL: ESPN + Poisson).

Reemplaza la versión vieja (que usaba scraper/momios). Ahora:
1. Genera pronósticos reales con el motor (datos de ESPN + modelo Poisson).
2. Calcula el mejor pick de Survivor (no perder), excluyendo equipos usados.
3. Guarda data/pronosticos.json e imprime un resumen.
4. Opcional: envía el resumen por Telegram (--telegram).

Informativo / revisión humana. No cierra ni envía apuestas por sí solo.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

# Configurar logging estructurado ANTES de importar módulos que loguean
from src.logging_setup import setup_logging, get_logger

setup_logging()

import motor_pronosticos as motor  # noqa: E402

logger = get_logger(__name__)


def ejecutar(excluir=None, enviar_telegram=False) -> int:
    logger.info("🤖 SURVIVOR LIGA MX — pronósticos reales (ESPN + Poisson)")
    logger.info("=" * 60)

    resultado = motor.generar_pronosticos()
    motor.guardar_pronosticos(resultado)

    logger.info(
        f"Fuente: {resultado['fuente_datos']} | "
        f"histórico: {resultado['total_resultados_historicos']} | "
        f"pronósticos: {resultado['total_pronosticos']}"
    )
    for p in resultado["pronosticos"]:
        logger.info(
            f"  {p['local']} vs {p['visitante']}: {p['pick_1x2']} "
            f"(L{p['prob_local_pct']}/E{p['prob_empate_pct']}/V{p['prob_visitante_pct']}) "
            f"| {p['pick_ou']} 2.5 | marcador {p['marcador_mas_probable']}"
        )

    usados = [e.strip() for e in (excluir or "").split(",") if e.strip()]
    try:
        motivacion = motor.motivacion_por_equipo()
    except Exception:
        motivacion = {}
    pick = motor.mejor_pick_survivor(resultado["pronosticos"], usados, motivacion)
    if pick:
        extra = f" · rival motivación: {pick['rival_motivacion']}" if pick.get("rival_motivacion") else ""
        logger.info(
            f"\n🎯 Survivor sugerido: {pick['equipo']} "
            f"({pick['condicion']} vs {pick['rival']}) — no perder {pick['no_perder_pct']}%{extra}"
        )
    else:
        logger.info("\nℹ️ Sin pick de Survivor (faltan fixtures o datos).")

    logger.info(f"\n{resultado['decision']}")

    if enviar_telegram:
        try:
            import telegram_pronosticos as tp

            envio = tp.enviar_pronosticos(usados)
            logger.info(f"📲 Telegram: enviado={envio['enviado']} ({envio.get('total_pronosticos', 0)} pronósticos)")
        except Exception as exc:  # pragma: no cover - dependencia/credenciales
            logger.warning(f"⚠️ No se pudo enviar Telegram: {exc}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Bot Survivor Liga MX (ESPN + Poisson).")
    parser.add_argument("--telegram", action="store_true", help="Enviar el resumen por Telegram.")
    parser.add_argument("--excluir", default="", help="Equipos ya usados (coma).")
    args = parser.parse_args()
    return ejecutar(excluir=args.excluir, enviar_telegram=args.telegram)


if __name__ == "__main__":
    raise SystemExit(main())
