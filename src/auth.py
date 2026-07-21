"""Autenticación por API key (header ``X-API-Key``) para endpoints protegidos.

La clave se lee del entorno (``API_KEY``; en Render / GitHub secret). No hay
default público: si no está configurada, los endpoints protegidos fallan en
cerrado (503) en lugar de quedar abiertos.

Vive en su propio módulo (y no en ``api.py``) para que los routers puedan
reutilizar ``verify_api_key`` sin provocar un import circular, ya que
``api.py`` importa los routers.
"""
import os
from typing import Optional

from fastapi import Header, HTTPException

# Sin default público: la clave DEBE venir del entorno (Render / GitHub secret).
API_KEY = os.getenv("API_KEY", "").strip()


def verify_api_key(x_api_key: Optional[str] = Header(None)) -> str:
    """Dependencia de FastAPI que valida el header ``X-API-Key``.

    - 503 si el servidor no tiene ``API_KEY`` configurada (fail-closed).
    - 403 si la clave enviada falta o no coincide.
    """
    if not API_KEY:
        raise HTTPException(
            status_code=503,
            detail="API_KEY no configurada en el servidor",
        )
    if not x_api_key or x_api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Clave API inválida o faltante")
    return x_api_key
