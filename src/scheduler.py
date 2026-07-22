#!/usr/bin/env python3
"""
scheduler.py — Autoprogramado SEMANAL del análisis de jornada (GRATIS).

Arranca un hilo en segundo plano (librería estándar, sin dependencias extra)
que cada domingo a las 23:00 hora de CDMX corre `enviar_analisis_jornada()`
que analiza la jornada y la manda por Telegram.

Para sortear que el free tier de Render se duerme: ~10 min antes del disparo
hace un "wake-up ping" a /health (localhost y API_BASE) para que el Web Service
y la API de 365scores (que también se duermen) estén calientes a la hora de analizar.

Activado por defecto. Para APAGARLO: SCHEDULER_ENABLED=false.
Config (entorno, opcional):
    SCHEDULER_HOUR     hora local CDMX de disparo (default 23).
    SCHEDULER_MINUTE   minuto de disparo (default 0).
    SCHEDULER_WEEKDAY  día 0=Lun..6=Dom (default 6 = domingo).
    SCHEDULER_WAKEUP_MINUTES  minutos antes del disparo para el ping (default 10).
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - muy viejo
    ZoneInfo = None  # type: ignore


def _habilitado() -> bool:
    # ON por defecto; solo se apaga con "false"/"0"/"off".
    return os.getenv("SCHEDULER_ENABLED", "1").strip().lower() not in ("false", "0", "off", "no")


def _zona():
    if ZoneInfo is not None:
        try:
            return ZoneInfo("America/Mexico_City")
        except Exception:
            logger.debug("Exception silenciada en _zona", exc_info=True)
    return None


def _proximo_disparo() -> float:
    """Segundos hasta el próximo domingo a la hora/configurada (hora CDMX)."""
    hora = int(os.getenv("SCHEDULER_HOUR", "23") or "23")
    minuto = int(os.getenv("SCHEDULER_MINUTE", "0") or "0")
    dia = int(os.getenv("SCHEDULER_WEEKDAY", "6") or "6")  # domingo
    tz = _zona()
    ahora = datetime.now(tz) if tz else datetime.now()
    dias_espera = (dia - ahora.weekday()) % 7
    if dias_espera == 0 and (ahora.hour, ahora.minute, ahora.second) >= (hora, minuto, 0):
        dias_espera = 7
    prox = ahora.replace(hour=hora, minute=minuto, second=0, microsecond=0) + timedelta(days=dias_espera)
    return max(0.0, (prox - ahora).total_seconds())


def _wake_up() -> None:
    """Ping a /health para despertar el Web Service y la API de 365scores."""
    import requests

    port = os.getenv("PORT", "8000")
    api_base = os.getenv("API_BASE", "").strip().rstrip("/")
    urls = [f"http://127.0.0.1:{port}/health"]
    if api_base:
        urls.append(f"{api_base}/health")
    for url in urls:
        try:
            requests.get(url, timeout=10)
        except Exception:
            logger.debug("Exception silenciada en _wake_up", exc_info=True)


def _loop() -> None:
    from src.telegram_pronosticos import enviar_analisis_jornada

    wakeup = int(os.getenv("SCHEDULER_WAKEUP_MINUTES", "10") or "10")
    while True:
        espera = _proximo_disparo()
        # Si falta más que el wakeup, dormir hasta el wakeup; si falta menos,
        # dormir lo que falte y ya disparar.
        if espera > wakeup * 60:
            time.sleep(max(0.0, espera - wakeup * 60))
            _wake_up()
            time.sleep(wakeup * 60)
        else:
            time.sleep(espera)
        try:
            enviar_analisis_jornada()
        except Exception:
            logger.debug("Exception silenciada en _loop", exc_info=True)
        time.sleep(120)  # evitar doble disparo en el mismo minuto


def arrancar() -> None:
    """Arranca el hilo del scheduler si está habilitado. Idempotente."""
    if not _habilitado():
        return
    t = threading.Thread(target=_loop, name="analisis-semanal-scheduler", daemon=True)
    t.start()
