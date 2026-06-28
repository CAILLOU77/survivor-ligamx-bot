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


def _resumen_mercado(mercado: Optional[Dict[str, Any]]) -> Optional[str]:
    """Línea concisa con lo que ve el mercado (favorito, O/U, hándicap, valor)."""
    if not mercado:
        return None
    partes: List[str] = []
    o = mercado.get("1x2")
    if o and o.get("favorito_mercado"):
        partes.append(f"fav {o['favorito_mercado']}")
        if o.get("hay_valor") and o.get("valor_en"):
            partes.append(f"valor {o['valor_en']}")
    ou = mercado.get("over_under")
    if ou and ou.get("mercado_ve"):
        partes.append(ou["mercado_ve"])  # explosivo / cauteloso
        if ou.get("hay_valor") and ou.get("valor_en"):
            partes.append(f"valor {ou['valor_en']}")
    h = mercado.get("handicap")
    if h and h.get("favorito"):
        partes.append(f"hcp {h['favorito']} {h['linea']}")
    return " · ".join(partes) if partes else None


def construir_mensaje(
    resultado: Dict[str, Any],
    equipos_usados: Optional[List[str]] = None,
    motivacion: Optional[Dict[str, Dict[str, Any]]] = None,
) -> str:
    """Arma el mensaje (HTML) de pronósticos a partir de la salida del motor."""
    pronosticos = resultado.get("pronosticos", [])
    fuente = resultado.get("fuente_datos", "?")
    fecha = resultado.get("generado_utc", "")

    lineas = [
        "🔮 <b>PRONÓSTICOS LIGA MX</b> (modelo · datos ESPN)",
        f"<i>Fuente: {fuente} · {fecha}</i>",
        "",
    ]

    pick = motor.mejor_pick_survivor(pronosticos, equipos_usados, motivacion)
    if pick:
        linea_pick = (
            f"🎯 <b>SURVIVOR sugerido:</b> {pick['equipo']} "
            f"({pick['condicion']} vs {pick['rival']}) — no perder {pick['no_perder_pct']}%"
        )
        if pick.get("rival_motivacion"):
            linea_pick += f" · rival motivación: {pick['rival_motivacion']}"
        lineas.append(linea_pick)
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
            resumen = _resumen_mercado(p.get("mercado"))
            if resumen:
                lineas.append(f"    💰 Mercado: {resumen}")
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
    """
    Genera pronósticos reales y los envía por Telegram, enriquecidos con:
    - momios/valor del mercado (si hay ODDS_API_IO_KEY; si no, no-op), y
    - motivación de la tabla (defensivo; {} si no hay red).
    """
    resultado = motor.generar_pronosticos()
    pronosticos = resultado.get("pronosticos", [])

    # Momios/valor (gated por key; sin key no toca nada).
    con_momios = 0
    try:
        try:
            import comparador_mercado as cm
        except ImportError:  # pragma: no cover
            from src import comparador_mercado as cm  # type: ignore
        comp = cm.comparar_pronosticos(pronosticos)
        resultado["pronosticos"] = comp.get("pronosticos", pronosticos)
        con_momios = comp.get("partidos_con_momios", 0)
    except Exception:  # pragma: no cover - nunca debe tumbar el envío
        pass

    # Motivación de la tabla (contexto/desempate Survivor).
    try:
        motivacion = motor.motivacion_por_equipo()
    except Exception:  # pragma: no cover
        motivacion = {}

    mensaje = construir_mensaje(resultado, equipos_usados, motivacion)
    enviado = enviar_mensaje(mensaje)
    return {
        "enviado": enviado,
        "total_pronosticos": resultado.get("total_pronosticos", 0),
        "partidos_con_momios": con_momios,
        "fuente": resultado.get("fuente_datos"),
    }


if __name__ == "__main__":
    res = enviar_pronosticos()
    print(f"Enviado: {res['enviado']} | pronósticos: {res['total_pronosticos']} | fuente: {res['fuente']}")
