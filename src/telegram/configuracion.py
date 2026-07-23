"""Configuración operativa del webhook y menú de comandos de Telegram.

La sincronización es idempotente y nunca imprime ni devuelve el token o el
secreto. En Render se ejecuta en segundo plano para no retrasar el arranque.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError:  # pragma: no cover - requests es dependencia de producción
    requests = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

COMANDOS_BOT: List[Dict[str, str]] = [
    {"command": "mipick", "description": "Mi racha, equipos usados y pick actual"},
    {"command": "pick", "description": "Generar recomendación de la jornada"},
    {"command": "plan", "description": "Ver el plan estratégico de temporada"},
    {"command": "confirmar", "description": "Confirmar: /confirmar jornada equipo"},
    {"command": "bloquear", "description": "Bloquear: /bloquear jornada"},
    {"command": "resolver", "description": "Resolver: /resolver jornada resultado"},
    {"command": "usados", "description": "Ver los equipos ya utilizados"},
    {"command": "ayuda", "description": "Mostrar todos los comandos"},
]

_sincronizacion_iniciada = False
_sincronizacion_lock = threading.Lock()
_ultimo_estado: Dict[str, Any] = {"estado": "no_iniciada", "ok": False}


def _guardar_estado(resultado: Dict[str, Any], estado: str) -> None:
    global _ultimo_estado
    with _sincronizacion_lock:
        _ultimo_estado = {
            **resultado,
            "estado": estado,
            "actualizado_en": datetime.now(timezone.utc).isoformat(),
        }


def estado_sincronizacion_telegram() -> Dict[str, Any]:
    """Último estado local, sanitizado, para healthchecks."""
    with _sincronizacion_lock:
        return dict(_ultimo_estado)


def _error_seguro(exc: Exception, operacion: str) -> str:
    """Evita que requests filtre la URL que contiene el token del bot."""
    if isinstance(exc, RuntimeError):
        return str(exc)
    return f"{operacion} no disponible ({type(exc).__name__})"


def obtener_secreto_webhook() -> str:
    """Usa el secreto explícito o deriva uno estable sin exponer credenciales.

    El derivado permite recuperar instalaciones antiguas que ya tienen
    ``API_KEY`` y ``TELEGRAM_BOT_TOKEN`` pero no configuraron una tercera clave.
    """
    explicito = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if explicito:
        return explicito

    api_key = os.getenv("API_KEY", "").strip()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not api_key or not token:
        return ""
    return hmac.new(api_key.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def _api(token: str, metodo: str) -> str:
    return f"https://api.telegram.org/bot{token}/{metodo}"


def _base_publica(base_url: Optional[str] = None) -> str:
    return (
        str(base_url or "").strip()
        or os.getenv("API_BASE", "").strip()
        or os.getenv("RENDER_EXTERNAL_URL", "").strip()
        or "https://survivor-ligamx-bot.onrender.com"
    ).rstrip("/")


def _resultado(respuesta: Any, operacion: str) -> Dict[str, Any]:
    try:
        data = respuesta.json()
    except Exception as exc:
        raise RuntimeError(f"Telegram devolvió una respuesta inválida al ejecutar {operacion}.") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Telegram devolvió una respuesta inválida al ejecutar {operacion}.")
    if respuesta.status_code != 200 or not data.get("ok"):
        descripcion = str(data.get("description") or f"HTTP {respuesta.status_code}")[:200]
        raise RuntimeError(f"Telegram rechazó {operacion}: {descripcion}")
    return dict(data)


def diagnosticar_telegram(base_url: Optional[str] = None) -> Dict[str, Any]:
    """Consulta estado remoto sin devolver token ni secreto."""
    if requests is None:
        return {"ok": False, "error": "requests no disponible"}
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN no configurado"}
    try:
        webhook = _resultado(requests.get(_api(token, "getWebhookInfo"), timeout=20), "getWebhookInfo").get(
            "result", {}
        )
        comandos = _resultado(requests.get(_api(token, "getMyCommands"), timeout=20), "getMyCommands").get("result", [])
    except Exception as exc:
        return {"ok": False, "error": _error_seguro(exc, "diagnóstico de Telegram")}

    esperada = _base_publica(base_url) + "/telegram/webhook"
    actuales = {str(item.get("command")) for item in comandos if isinstance(item, dict)}
    esperados = {item["command"] for item in COMANDOS_BOT}
    return {
        "ok": webhook.get("url") == esperada and esperados.issubset(actuales) and not webhook.get("last_error_message"),
        "webhook_correcto": webhook.get("url") == esperada,
        "menu_correcto": esperados.issubset(actuales),
        "pending_update_count": int(webhook.get("pending_update_count") or 0),
        "ultimo_error": webhook.get("last_error_message"),
        "comandos": sorted(actuales),
    }


def sincronizar_telegram(base_url: Optional[str] = None) -> Dict[str, Any]:
    """Registra webhook seguro y menú; luego verifica ambos en Telegram."""
    if requests is None:
        return {"ok": False, "error": "requests no disponible"}
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    secreto = obtener_secreto_webhook()
    if not token or not chat_id:
        return {"ok": False, "error": "faltan TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID"}
    if not secreto:
        return {"ok": False, "error": "falta TELEGRAM_WEBHOOK_SECRET o API_KEY para derivarlo"}

    hook = _base_publica(base_url) + "/telegram/webhook"
    try:
        _resultado(
            requests.post(
                _api(token, "setWebhook"),
                json={
                    "url": hook,
                    "secret_token": secreto,
                    "allowed_updates": ["message", "edited_message"],
                    "drop_pending_updates": False,
                },
                timeout=20,
            ),
            "setWebhook",
        )
        _resultado(
            requests.post(_api(token, "setMyCommands"), json={"commands": COMANDOS_BOT}, timeout=20),
            "setMyCommands",
        )
    except Exception as exc:
        return {"ok": False, "error": _error_seguro(exc, "sincronización de Telegram")}

    diagnostico = diagnosticar_telegram(base_url)
    diagnostico["secreto"] = "explicito" if os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip() else "derivado"
    return diagnostico


def iniciar_sincronizacion_telegram() -> bool:
    """Inicia una única sincronización no bloqueante por proceso en Render."""
    auto_raw = os.getenv("TELEGRAM_AUTO_CONFIGURE", "").strip().lower()
    habilitada = auto_raw in {"1", "true", "yes"} if auto_raw else bool(os.getenv("RENDER"))
    if not habilitada or not os.getenv("TELEGRAM_BOT_TOKEN", "").strip():
        return False

    global _sincronizacion_iniciada
    with _sincronizacion_lock:
        if _sincronizacion_iniciada:
            return False
        _sincronizacion_iniciada = True

    def _ejecutar() -> None:
        global _sincronizacion_iniciada
        _guardar_estado({"ok": False}, "sincronizando")
        resultado: Dict[str, Any] = {"ok": False, "error": "sin ejecutar"}
        for intento, espera in enumerate((0, 2, 10, 30), start=1):
            if espera:
                time.sleep(espera)
            resultado = sincronizar_telegram()
            if resultado.get("ok"):
                _guardar_estado(resultado, "ok")
                logger.info("Webhook y menú de Telegram sincronizados correctamente")
                return
            logger.warning(
                "Intento %s de sincronización Telegram falló: %s",
                intento,
                resultado.get("error") or "verificación incompleta",
            )
        _guardar_estado(resultado, "error")
        with _sincronizacion_lock:
            _sincronizacion_iniciada = False
        logger.error("Telegram siguió sin sincronizar después de los reintentos")

    threading.Thread(target=_ejecutar, name="telegram-config", daemon=True).start()
    return True
