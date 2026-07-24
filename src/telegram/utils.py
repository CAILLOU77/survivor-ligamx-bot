from __future__ import annotations
from typing import Any
from datetime import datetime


def _pct(v: Any) -> str:
    """Porcentaje legible en móvil: sin decimales de ruido (55.0 -> '55')."""
    try:
        return str(int(round(float(v))))
    except (TypeError, ValueError):
        return str(v)


def _fecha_mx(generado_utc: str) -> str:
    """Fecha/hora en horario de Ciudad de México, sin segundos. Fallback a UTC."""
    s = str(generado_utc or "")
    try:
        from zoneinfo import ZoneInfo

        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(ZoneInfo("America/Mexico_City")).strftime("%d/%m/%Y %H:%M") + " h (CDMX)"
    except Exception:
        return s.replace("T", " ").replace("Z", " UTC")
