#!/usr/bin/env python3
"""Registra, verifica o elimina el webhook y menú del bot de Telegram.

Uso:
    python3 scripts/set_telegram_webhook.py --url https://survivor-ligamx-bot.onrender.com
    python3 scripts/set_telegram_webhook.py --info
    python3 scripts/set_telegram_webhook.py --borrar

Render ejecuta esta misma sincronización automáticamente durante el arranque.
Nunca se imprimen el token ni el secreto.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

from src.telegram.configuracion import diagnosticar_telegram, sincronizar_telegram


def _api(token: str, metodo: str) -> str:
    return f"https://api.telegram.org/bot{token}/{metodo}"


def _mostrar_diagnostico(info: dict) -> None:
    print(f"Estado: {'✅ correcto' if info.get('ok') else '⚠️ requiere atención'}")
    if info.get("error"):
        print(f"Error: {info['error']}")
        return
    print(f"Webhook correcto: {bool(info.get('webhook_correcto'))}")
    print(f"Menú correcto: {bool(info.get('menu_correcto'))}")
    print(f"Updates pendientes: {int(info.get('pending_update_count') or 0)}")
    if info.get("ultimo_error"):
        print(f"Último error de Telegram: {info['ultimo_error']}")
    print(f"Comandos: {', '.join(info.get('comandos') or []) or '(ninguno)'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sincroniza webhook y menú de Telegram.")
    parser.add_argument("--url", help="Base pública del servicio (sin /telegram/webhook).")
    parser.add_argument("--info", action="store_true", help="Muestra webhook, menú y último error.")
    parser.add_argument("--borrar", action="store_true", help="Elimina el webhook.")
    args = parser.parse_args()

    if requests is None:
        print("⚠️ Falta 'requests' (pip install requests).")
        return 1

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("⚠️ Falta TELEGRAM_BOT_TOKEN en el entorno / .env.")
        return 1

    if args.info:
        info = diagnosticar_telegram()
        _mostrar_diagnostico(info)
        return 0 if info.get("ok") else 1

    if args.borrar:
        try:
            respuesta = requests.get(_api(token, "deleteWebhook"), timeout=20)
            data = respuesta.json()
        except Exception as exc:
            print(f"⚠️ No se pudo eliminar el webhook: {type(exc).__name__}")
            return 1
        print("✅ Webhook eliminado." if data.get("ok") else f"⚠️ {str(data.get('description'))[:200]}")
        return 0 if data.get("ok") else 1

    if not args.url:
        print("Uso: --url https://tu-servicio.onrender.com  (o --info / --borrar)")
        return 2

    resultado = sincronizar_telegram(args.url)
    _mostrar_diagnostico(resultado)
    return 0 if resultado.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
