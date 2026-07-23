#!/usr/bin/env python3
"""Cliente asíncrono para publicar pronósticos reales por Telegram.

Consulta ``/predicciones`` y delega la entrega al transportador común de
``src.telegram``. Así comparte validación HTTP, particionado e idempotencia con
el resto del bot y nunca informa éxito antes de que Telegram confirme el envío.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from typing import Any

import httpx
from dotenv import load_dotenv

from src import telegram_pronosticos

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
API_BASE = os.getenv("API_BASE", "https://survivor-ligamx-bot.onrender.com")


def _clave_predicciones(data: dict[str, Any]) -> str:
    """Genera una llave estable para no reenviar el mismo lote de pronósticos."""
    canonico = json.dumps(
        data.get("pronosticos", []),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    digest = hashlib.sha256(canonico.encode("utf-8")).hexdigest()[:24]
    return f"notifier:predicciones:{digest}"


async def notify_predicciones() -> bool:
    """Consulta datos reales y confirma si la entrega común terminó con éxito."""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ Faltan credenciales en .env (TELEGRAM_BOT_TOKEN/CHAT_ID).")
        return False

    print("📡 Consultando predicciones reales (ESPN + Poisson)...")
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(f"{API_BASE}/predicciones")
            resp.raise_for_status()
            data = resp.json()

        if not isinstance(data, dict):
            print("❌ La API devolvió un formato de predicciones inválido.")
            return False
        pronosticos = data.get("pronosticos")
        if not isinstance(pronosticos, list) or not pronosticos:
            print("ℹ️ Sin pronósticos disponibles ahora (faltan fixtures o datos).")
            return False

        mensaje = telegram_pronosticos.construir_mensaje(data)
        clave = _clave_predicciones(data)
        enviado = await asyncio.to_thread(
            telegram_pronosticos.enviar_mensaje,
            mensaje,
            idempotency_key=clave,
        )
        if not enviado:
            print("❌ Telegram no confirmó la entrega de los pronósticos.")
            return False

        total = data.get("total_pronosticos", len(pronosticos))
        print(f"✅ Enviado: {total} pronósticos.")
        return True
    except Exception as exc:
        # No imprimir la excepción completa: algunas bibliotecas incluyen URLs
        # y credenciales en sus mensajes de error.
        print(f"❌ Error consultando o enviando pronósticos ({type(exc).__name__}).")
        return False


if __name__ == "__main__":
    asyncio.run(notify_predicciones())
