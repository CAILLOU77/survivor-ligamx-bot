#!/usr/bin/env python3
"""
telegram_webhook.py — Comandos del bot por Telegram (webhook).

Permite operar el Survivor desde el celular respondiéndole al bot, sin llamar a
la API a mano:

  /usado <equipo>   -> marca un equipo como YA usado (se excluye del pick/plan)
  /usados           -> lista los equipos usados
  /quitar <equipo>  -> quita un equipo de la lista de usados
  /reset            -> vacía la lista (nueva temporada)
  /pick             -> genera y envía el pronóstico + pick recomendado ahora
  /ayuda            -> muestra esta ayuda

Seguridad: el endpoint solo atiende mensajes del TELEGRAM_CHAT_ID configurado
(el dueño) y, si se define TELEGRAM_WEBHOOK_SECRET, valida el header secreto de
Telegram. Este módulo NO decide picks ni apuesta: solo registra estado y dispara
el envío informativo. INFORMATIVO / REVISIÓN HUMANA.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

AYUDA = (
    "🤖 <b>Comandos Survivor</b>\n"
    "/pick (o /picks) — pronóstico + pick recomendado de la jornada\n"
    "/seguir — lista de seguimiento: candidatos por hora para decidir secuencial\n"
    "/usado &lt;equipo&gt; — marca un equipo como usado (lo excluye)\n"
    "/usados — lista tus equipos usados\n"
    "/quitar &lt;equipo&gt; — quita un equipo de la lista\n"
    "/reset — reinicia la lista (nueva temporada)\n"
    "/ayuda — esta ayuda\n\n"
    "ℹ️ Informativo / revisión humana. No es consejo de apuesta."
)

# Comandos que disparan la generación/envío del pronóstico (pesado -> background).
CMDS_PICK = {"pick", "picks", "survivor", "jornada", "pronostico", "pronosticos"}

# Comandos de la lista de seguimiento secuencial (pesado -> background).
CMDS_SEGUIMIENTO = {"seguir", "seguimiento", "candidatos", "watchlist"}


def parsear_comando(texto: str) -> Tuple[Optional[str], str]:
    """
    Extrae (comando, argumento) de un texto de Telegram. Devuelve (None, "") si
    no es un comando (no empieza con '/'). Soporta sufijo @bot y colapsa espacios.
    """
    t = (texto or "").strip()
    if not t.startswith("/"):
        return (None, "")
    partes = t.split(maxsplit=1)
    cmd = partes[0].lstrip("/").split("@")[0].lower()
    arg = partes[1].strip() if len(partes) > 1 else ""
    return (cmd, arg)


def _db():
    try:
        import database as db
    except ImportError:  # pragma: no cover
        from src import database as db  # type: ignore
    return db


def responder(cmd: Optional[str], arg: str) -> str:
    """
    Ejecuta un comando (que NO sea de pick) y devuelve el texto de respuesta.
    Las acciones de estado (usados) tocan la BD. Tolerante a fallos.
    """
    if cmd in (None, "start", "ayuda", "help"):
        return AYUDA

    db = _db()

    if cmd in ("usado", "uso", "use"):
        if not arg:
            return "Uso: <code>/usado &lt;equipo&gt;</code> (ej. /usado América)"
        try:
            agregado = db.add_equipo_usado(arg)
            usados = db.get_equipos_usados()
        except Exception as exc:  # pragma: no cover - BD no disponible
            return f"⚠️ No se pudo registrar: {exc}"
        cab = "✅ Registrado" if agregado else "ℹ️ Ya estaba"
        return f"{cab}: <b>{arg}</b>\nUsados ({len(usados)}): {', '.join(usados) or '—'}"

    if cmd in ("usados", "lista", "list"):
        try:
            usados = db.get_equipos_usados()
        except Exception as exc:  # pragma: no cover
            return f"⚠️ No se pudo leer: {exc}"
        return f"🔒 Equipos usados ({len(usados)}): {', '.join(usados) or '—'}"

    if cmd in ("quitar", "borrar", "remove"):
        if not arg:
            return "Uso: <code>/quitar &lt;equipo&gt;</code>"
        try:
            filas = db.remove_equipo_usado(arg)
            usados = db.get_equipos_usados()
        except Exception as exc:  # pragma: no cover
            return f"⚠️ No se pudo quitar: {exc}"
        cab = "✅ Quitado" if filas else "ℹ️ No estaba en la lista"
        return f"{cab}: <b>{arg}</b>\nUsados ({len(usados)}): {', '.join(usados) or '—'}"

    if cmd in ("reset", "reiniciar"):
        try:
            borrados = db.clear_equipos_usados()
        except Exception as exc:  # pragma: no cover
            return f"⚠️ No se pudo reiniciar: {exc}"
        return f"♻️ Lista de usados reiniciada ({borrados} borrados). Nueva temporada."

    return "❓ Comando no reconocido. Usa /ayuda"


def extraer_mensaje(update: Dict[str, Any]) -> Tuple[Optional[int], str]:
    """
    De un update de Telegram saca (chat_id, texto). Soporta 'message' y
    'edited_message'. Devuelve (None, "") si no hay mensaje de texto.
    """
    msg = update.get("message") or update.get("edited_message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    texto = msg.get("text", "") or ""
    try:
        chat_id = int(chat_id) if chat_id is not None else None
    except (TypeError, ValueError):
        chat_id = None
    return (chat_id, texto)
