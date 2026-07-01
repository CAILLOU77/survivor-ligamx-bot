#!/usr/bin/env python3
"""
set_telegram_webhook.py — Registra (o borra) el webhook de comandos en Telegram.

Apunta el bot de Telegram al endpoint POST /telegram/webhook del servicio para
poder operarlo por chat (/usado, /usados, /pick, ...). Usa TELEGRAM_BOT_TOKEN y,
si existe, TELEGRAM_WEBHOOK_SECRET (se envía como secret_token).

Uso:
    python3 scripts/set_telegram_webhook.py --url https://survivor-ligamx-bot.onrender.com
    python3 scripts/set_telegram_webhook.py --info        # ver estado actual
    python3 scripts/set_telegram_webhook.py --borrar      # quitar el webhook

No imprime el token ni el secreto. INFORMATIVO / REVISIÓN HUMANA.
"""
from __future__ import annotations

import argparse
import os
import sys

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # pragma: no cover
    pass


def _api(token: str, metodo: str) -> str:
    return f"https://api.telegram.org/bot{token}/{metodo}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Registra el webhook de Telegram.")
    parser.add_argument("--url", help="Base pública del servicio (sin /telegram/webhook).")
    parser.add_argument("--info", action="store_true", help="Muestra el estado del webhook.")
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
        r = requests.get(_api(token, "getWebhookInfo"), timeout=20)
        info = r.json().get("result", {})
        print(f"URL configurada: {info.get('url') or '(ninguna)'}")
        print(f"pending_update_count: {info.get('pending_update_count')}")
        if info.get("last_error_message"):
            print(f"último error: {info.get('last_error_message')}")
        return 0

    if args.borrar:
        r = requests.get(_api(token, "deleteWebhook"), timeout=20)
        print("✅ Webhook eliminado." if r.json().get("ok") else f"⚠️ {r.text[:200]}")
        return 0

    if not args.url:
        print("Uso: --url https://tu-servicio.onrender.com  (o --info / --borrar)")
        return 2

    hook = args.url.rstrip("/") + "/telegram/webhook"
    payload = {"url": hook, "allowed_updates": ["message"]}
    secreto = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if secreto:
        payload["secret_token"] = secreto

    r = requests.post(_api(token, "setWebhook"), json=payload, timeout=20)
    data = r.json()
    if data.get("ok"):
        print(f"✅ Webhook registrado en {hook}"
              + (" (con secreto)" if secreto else " (sin secreto)"))
        return 0
    print(f"⚠️ No se pudo registrar: {data.get('description', r.text[:200])}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
