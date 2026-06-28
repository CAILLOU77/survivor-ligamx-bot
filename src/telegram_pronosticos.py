#!/usr/bin/env python3
"""
telegram_pronosticos.py — Alertas de Telegram con PRONÓSTICOS REALES.

Reemplaza las alertas de "EV>5% / apuesta ya" (basadas en momios inventados)
por un resumen honesto de las **predicciones del modelo** (datos reales de ESPN):
pick de Survivor + 1X2/Over-Under/BTTS por partido.

Envío propio vía la API de Telegram (no importa la capa de DB/Postgres).
Mensaje informativo, con disclaimer de revisión humana. No es consejo de apuesta.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

try:
    import motor_pronosticos as motor
except ImportError:  # pragma: no cover
    from src import motor_pronosticos as motor  # type: ignore

DISCLAIMER = "ℹ️ Informativo / revisión humana. No es consejo de apuesta."
_MAX_PARTIDOS = 9


def construir_mensaje(resultado: Dict[str, Any], equipos_usados: Optional[List[str]] = None) -> str:
    """Arma el mensaje (HTML) de pronósticos a partir de la salida del motor."""
    pronosticos = resultado.get("pronosticos", [])
    fuente = resultado.get("fuente_datos", "?")
    fecha = resultado.get("generado_utc", "")

    lineas = [
        "🔮 <b>PRONÓSTICOS LIGA MX</b> (modelo · datos ESPN)",
        f"<i>Fuente: {fuente} · {fecha}</i>",
        "",
    ]

    pick = motor.mejor_pick_survivor(pronosticos, equipos_usados)
    if pick:
        lineas.append(
            f"🎯 <b>SURVIVOR sugerido:</b> {pick['equipo']} "
            f"({pick['condicion']} vs {pick['rival']}) — no perder {pick['no_perder_pct']}%"
        )
        lineas.append("")

    if pronosticos:
        lineas.append("<b>Partidos:</b>")
        for p in pronosticos[:_MAX_PARTIDOS]:
            lineas.append(
                f"⚽ {p['local']} vs {p['visitante']} → <b>{p['pick_1x2']}</b> "
                f"(L{p['prob_local_pct']}/E{p['prob_empate_pct']}/V{p['prob_visitante_pct']})"
            )
            lineas.append(
                f"    {p['pick_ou']} 2.5 · BTTS {p['pick_btts']} · marcador {p['marcador_mas_probable']}"
            )
    else:
        lineas.append("Sin pronósticos disponibles (faltan datos de ESPN o fixtures).")

    lineas += ["", DISCLAIMER]
    return "\n".join(lineas)


def enviar_mensaje(mensaje: str) -> bool:
    """Envía un mensaje a Telegram. Devuelve True si se envió (200)."""
    if requests is None:
        print("⚠️ 'requests' no instalado; no se envía.")
        return False
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("⚠️ Telegram no configurado (faltan TELEGRAM_BOT_TOKEN/CHAT_ID).")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(
            url, data={"chat_id": chat_id, "text": mensaje, "parse_mode": "HTML"}, timeout=20
        )
        return resp.status_code == 200
    except Exception as exc:  # pragma: no cover
        print(f"Error enviando Telegram: {exc}")
        return False


def enviar_pronosticos(equipos_usados: Optional[List[str]] = None) -> Dict[str, Any]:
    """Genera pronósticos reales y los envía por Telegram."""
    resultado = motor.generar_pronosticos()
    mensaje = construir_mensaje(resultado, equipos_usados)
    enviado = enviar_mensaje(mensaje)
    return {
        "enviado": enviado,
        "total_pronosticos": resultado.get("total_pronosticos", 0),
        "fuente": resultado.get("fuente_datos"),
    }


if __name__ == "__main__":
    res = enviar_pronosticos()
    print(f"Enviado: {res['enviado']} | pronósticos: {res['total_pronosticos']} | fuente: {res['fuente']}")
