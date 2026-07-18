#!/usr/bin/env python3
"""
scheduler.py — Autoprogramado SEMANAL del análisis de jornada.

Arranca un hilo en segundo plano (librería estándar, sin dependencias extra)
que cada domingo a las 23:00 hora de CDMX corre `enviar_analisis_jornada()`
que analiza la jornada y la manda por Telegram.

Esto es un RESPALDO cómodo si no querés crear un Cron Job de Render. Lo más
robusto sigue siendo un Cron Job de Render que llame a POST /cron/analisis-semanal.

Config (entorno, opcional):
    SCHEDULER_ENABLED   "1"/"true" para activar (default: off, para no sorprender).
    SCHEDULER_HOUR     hora local CDMX de disparo (default 23).
    SCHEDULER_MINUTE   minuto de disparo (default 0).
    SCHEDULER_WEEKDAY  día de la semana 0= Lun ... 6= Dom (default 6 = domingo).
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, time as dtime

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - muy viejo
    ZoneInfo = None  # type: ignore


def _habilitado() -> bool:
    return os.getenv("SCHEDULER_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def _zona() :
    """Zona horaria CDMX (America/Mexico_City)."""
    if ZoneInfo is not None:
        try:
            return ZoneInfo("America/Mexico_City")
        except Exception:
            pass
    return None


def _proximo_disparo() -> float:
    """Segundos hasta el próximo domingo a la hora/configurada (hora CDMX)."""
    hora = int(os.getenv("SCHEDULER_HOUR", "23") or "23")
    minuto = int(os.getenv("SCHEDULER_MINUTE", "0") or "0")
    dia = int(os.getenv("SCHEDULER_WEEKDAY", "6") or "6")  # domingo
    tz = _zona()
    ahora = datetime.now(tz) if tz else datetime.now()
    # Calcular próximo día objetivo
    dias_espera = (dia - ahora.weekday()) % 7
    if dias_espera == 0 and (ahora.hour, ahora.minute, ahora.second) >= (hora, minuto, 0):
        dias_espera = 7
    prox = ahora.replace(hour=hora, minute=minuto, second=0, microsecond=0)
    from datetime import timedelta
    prox = prox + timedelta(days=dias_espera)
    return max(0.0, (prox - ahora).total_seconds())


def _loop() -> None:
    from src.telegram_pronosticos import enviar_analisis_jornada
    while True:
        espera = _proximo_disparo()
        time.sleep(espera)
        try:
            enviar_analisis_jornada()
        except Exception:
            pass
        # Pequeña pausa para no disparar dos veces el mismo minuto
        time.sleep(60)


def arrancar() -> None:
    """Arranca el hilo del scheduler si está habilitado. Idempotente."""
    if not _habilitado():
        return
    t = threading.Thread(target=_loop, name="analisis-semanal-scheduler", daemon=True)
    t.start()
