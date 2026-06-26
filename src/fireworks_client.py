#!/usr/bin/env python3
"""
fireworks_client.py — Clasificador de riesgo opcional vía Fireworks AI.

Rol: BACKUP_AI_CLASSIFIER.
NUNCA genera, cierra ni envía picks. Solo:
- resume noticias
- clasifica lesiones
- detecta cambios de alineación
- extrae señales de riesgo

Desactivado por defecto (FIREWORKS_ENABLED=false).
La decisión operativa SIEMPRE sigue en ESPERAR / NO ENVIAR.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

import requests


def _cargar_env() -> None:
    root = Path(__file__).resolve().parents[1]
    env_path = root / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def fireworks_habilitado() -> bool:
    _cargar_env()
    return os.getenv("FIREWORKS_ENABLED", "false").strip().lower() == "true"


def clasificar_riesgo_fireworks(texto_noticias: str, system_prompt: str = "") -> Dict[str, Any]:
    """Clasifica señales de riesgo. No produce decisiones de apuesta."""
    _cargar_env()
    api_key = os.getenv("FIREWORKS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("No hay FIREWORKS_API_KEY.")

    base = os.getenv("FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1").rstrip("/")
    model = os.getenv("FIREWORKS_MODEL", "accounts/fireworks/models/gpt-oss-120b")
    endpoint = f"{base}/chat/completions"

    sys_msg = system_prompt or (
        "Eres un clasificador de riesgo de Liga MX. Resumes noticias, clasificas "
        "lesiones, detectas cambios de alineacion y senales de riesgo. NUNCA generas "
        "picks, NUNCA recomiendas apostar, NUNCA decides CERRAR ni ENVIAR. "
        "Responde solo en JSON con: resumen, lesiones, cambios_alineacion, senales_riesgo."
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": texto_noticias},
        ],
        "temperature": 0.2,
    }

    resp = requests.post(
        endpoint,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=40,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Fireworks respondio HTTP {resp.status_code}.")

    contenido = resp.json()["choices"][0]["message"]["content"]
    try:
        data = json.loads(contenido)
    except json.JSONDecodeError:
        data = {"raw": contenido}
    data.setdefault("proveedor_ia", "fireworks")
    data.setdefault("modelo", model)
    data.setdefault("decision_operativa", "ESPERAR / NO ENVIAR")
    return data


if __name__ == "__main__":
    print("FIREWORKS_ENABLED =", fireworks_habilitado())
