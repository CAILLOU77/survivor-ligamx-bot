#!/usr/bin/env python3
"""
telegram_notifier.py — Notificador (cliente) de PRONÓSTICOS REALES por Telegram.

Antes consultaba el viejo endpoint /picks/latest (picks de "alto EV" basados en
momios inventados). Ahora consulta el endpoint REAL /predicciones (ESPN +
Poisson) de la API desplegada y envía un resumen informativo, reutilizando el
mismo constructor de mensaje que src/telegram_pronosticos.py (DRY).

Informativo / revisión humana. No es consejo de apuesta.
"""
import asyncio
import os

import httpx
from dotenv import load_dotenv

try:
    import telegram_pronosticos
except ImportError:  # pragma: no cover
    from src import telegram_pronosticos  # type: ignore

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
API_BASE = os.getenv("API_BASE", "https://survivor-ligamx-bot.onrender.com")


async def notify_predicciones():
    """Consulta /predicciones (datos reales) y envía el resumen por Telegram."""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ Faltan credenciales en .env (TELEGRAM_BOT_TOKEN/CHAT_ID).")
        return

    print("📡 Consultando predicciones reales (ESPN + Poisson)...")
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(f"{API_BASE}/predicciones")
            resp.raise_for_status()
            data = resp.json()

        if not data.get("pronosticos"):
            print("ℹ️ Sin pronósticos disponibles ahora (faltan fixtures o datos).")
            return

        mensaje = telegram_pronosticos.construir_mensaje(data)
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        async with httpx.AsyncClient(timeout=20.0) as tg:
            await tg.post(url, json={"chat_id": CHAT_ID, "text": mensaje, "parse_mode": "HTML"})
        print(f"✅ Enviado: {data.get('total_pronosticos', len(data['pronosticos']))} pronósticos.")
    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    asyncio.run(notify_predicciones())
