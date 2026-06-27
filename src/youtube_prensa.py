#!/usr/bin/env python3
"""
youtube_prensa.py — Conferencias de prensa Liga MX vía YouTube Data API v3.

Rol: NEWS_RISK (señal de contexto, no verdad de mercado). Detecta videos de
conferencias/ruedas de prensa publicados recientemente (<24h por defecto) para
sumar contexto (lesiones, ánimo, alineación probable) al análisis de riesgo.

Usa la API OFICIAL de YouTube (canal público y permitido), con clave en .env.
NO hace scraping, NO descarga video, NO guarda credenciales en código.
Desactivado por defecto (YOUTUBE_ENABLED=false). Decisión operativa siempre:
ESPERAR / NO ENVIAR.
"""
from __future__ import annotations

import os
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

try:
    import requests
except ImportError:  # pragma: no cover - dependencia opcional ausente
    requests = None  # type: ignore[assignment]

DEC_ESPERAR = "ESPERAR / NO ENVIAR"
_API_URL = "https://www.googleapis.com/youtube/v3/search"

# Palabras clave que identifican una conferencia / rueda de prensa relevante.
_KEYWORDS = (
    "conferencia", "rueda de prensa", "declaracion", "declaraciones",
    "previa", "conferencia de prensa", "en vivo conferencia",
)


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


def youtube_habilitado() -> bool:
    _cargar_env()
    return os.getenv("YOUTUBE_ENABLED", "false").strip().lower() == "true"


def _quitar_acentos(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _es_relevante(titulo: str) -> bool:
    """True si el título parece una conferencia/rueda de prensa."""
    t = _quitar_acentos(titulo).lower()
    return any(kw in t for kw in _KEYWORDS)


def _parsear_published(value: str) -> datetime:
    """Parsea la fecha ISO de YouTube ('...Z') a datetime con tz UTC."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _parsear_respuesta(
    data: Dict[str, Any],
    cutoff: datetime,
    solo_relevantes: bool = True,
) -> List[Dict[str, Any]]:
    """
    Convierte la respuesta de la YouTube API en registros limpios, filtrando
    por fecha (>= cutoff) y, opcionalmente, por relevancia de conferencia.
    Función pura: no hace red.
    """
    registros: List[Dict[str, Any]] = []
    for item in data.get("items", []):
        if not isinstance(item, dict):
            continue
        snippet = item.get("snippet", {})
        video_id = (item.get("id", {}) or {}).get("videoId")
        titulo = snippet.get("title", "")
        if not video_id or not titulo:
            continue
        try:
            publicado = _parsear_published(snippet.get("publishedAt", ""))
        except (ValueError, TypeError):
            continue
        if publicado < cutoff:
            continue
        if solo_relevantes and not _es_relevante(titulo):
            continue
        registros.append({
            "fuente": "YouTube",
            "titulo": titulo,
            "canal": snippet.get("channelTitle", ""),
            "publicado": publicado.isoformat(),
            "video_id": video_id,
            "link": f"https://www.youtube.com/watch?v={video_id}",
        })
    return registros


def buscar_conferencias(
    query: str = "conferencia de prensa Liga MX",
    horas: int = 24,
    max_resultados: int = 10,
    solo_relevantes: bool = True,
) -> List[Dict[str, Any]]:
    """
    Busca conferencias recientes vía la YouTube Data API. Requiere
    YOUTUBE_API_KEY en el entorno. No imprime la clave. No descarga video.
    """
    _cargar_env()
    if requests is None:
        raise RuntimeError(
            "La dependencia 'requests' no está instalada; YouTube no disponible."
        )
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("No hay YOUTUBE_API_KEY configurada en .env.")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=horas)
    params = {
        "key": api_key,
        "part": "snippet",
        "q": query,
        "type": "video",
        "order": "date",
        "maxResults": max(1, min(int(max_resultados), 50)),
        "regionCode": "MX",
        "relevanceLanguage": "es",
        "publishedAfter": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    resp = requests.get(_API_URL, params=params, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"YouTube API respondió HTTP {resp.status_code}.")

    return _parsear_respuesta(resp.json(), cutoff, solo_relevantes)


def resumen_conferencias(registros: List[Dict[str, Any]]) -> str:
    """Resumen legible (sin secretos) con la decisión operativa fija."""
    lineas = [
        "# CONFERENCIAS DE PRENSA LIGA MX (YouTube)",
        "",
        "Rol: NEWS_RISK (contexto, no verdad de mercado).",
        f"Conferencias recientes detectadas: {len(registros)}",
        "",
    ]
    for r in registros:
        lineas.append(f"- [{r['canal']}] {r['titulo']} ({r['publicado']})")
        lineas.append(f"  {r['link']}")
    if not registros:
        lineas.append("(Sin conferencias relevantes en la ventana consultada.)")
    lineas += [
        "",
        "DECISIÓN GENERAL:",
        f"- {DEC_ESPERAR}.",
        "- Señal de contexto. No cierra ni envía picks.",
    ]
    return "\n".join(lineas) + "\n"


if __name__ == "__main__":
    print("YOUTUBE_ENABLED =", youtube_habilitado())
