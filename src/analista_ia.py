#!/usr/bin/env python3
"""
analista_ia.py — Capa de IA OPCIONAL que analiza noticias REALES.

Backends soportados (por orden de preferencia):
1) Proxy local CLIProxyAPI (AntiGravity/Claude/OpenAI/Gemini): se activa si hay
   PROXY_API_KEY en el entorno. Default: http://127.0.0.1:8317/v1
2) Groq: se activa si hay GROQ_API_KEY y no hay proxy. Default Groq.

Reglas:
- NO inventa datos. Solo usa los titulares provistos.
- Si no hay señal, lo dice.
- NUNCA cambia el pick por sí solo: es contexto informativo.

Config:
    PROXY_API_KEY      (obligatoria si querés usar el proxy local)
    PROXY_BASE_URL     (default http://127.0.0.1:8317/v1)
    PROXY_MODEL        (default claude-opus-4-6-thinking)
    GROQ_API_KEY | GROQ_API_KEY_PRIMARY | GROQ_API_KEY_BACKUP
    GROQ_MODEL         (default meta-llama/llama-4-scout-17b-16e-instruct)
    GROQ_ENABLED       ('0'/'false' fuerza apagado aunque haya key)
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List
import logging

logger = logging.getLogger(__name__)

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Backend 1: Proxy local (CLIProxyAPI / AntiGravity / OpenAI-compatible)
# ---------------------------------------------------------------------------
_PROXY_URL = os.getenv("PROXY_BASE_URL", "http://127.0.0.1:8317/v1").rstrip("/") + "/chat/completions"
_PROXY_KEY = os.getenv("PROXY_API_KEY", "").strip()
_PROXY_MODEL = os.getenv("PROXY_MODEL", "claude-opus-4-6-thinking").strip()

# ---------------------------------------------------------------------------
# Backend 2: Groq
# ---------------------------------------------------------------------------
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "llama-3.3-70b-versatile"
DECISION = "INFORMATIVO / REVISIÓN HUMANA"

_SYSTEM = (
    "Eres un analista de riesgo de la Liga MX. Trabajas SOLO con los titulares y "
    "descripciones de noticias que te doy; está PROHIBIDO inventar o suponer datos "
    "que no estén en esas notas. Busca señales de riesgo (lesión, suspensión, duda, "
    "baja, rotación/suplentes) que afecten a los equipos indicados. Para cada señal "
    "cita el titular exacto de donde salió. Si no hay señales claras en las notas, "
    "responde sin_senales=true. Responde ÚNICAMENTE en JSON válido con el esquema: "
    '{"riesgos":[{"equipo":"","tipo":"lesion|suspension|duda|rotacion|otro",'
    '"jugador":"","resumen":"","titulo_fuente":""}],"sin_senales":false}'
)


def _groq_api_key() -> str:
    for var in ("GROQ_API_KEY", "GROQ_API_KEY_PRIMARY", "GROQ_API_KEY_BACKUP"):
        v = os.getenv(var, "").strip()
        if v:
            return v
    return ""


def habilitado() -> bool:
    """True si hay proxy local configurado O key de Groq activa."""
    if _PROXY_KEY and requests is not None:
        return True
    if os.getenv("GROQ_ENABLED", "").strip().lower() in ("0", "false", "no", "off"):
        return False
    return bool(_groq_api_key()) and requests is not None


def _backend() -> str:
    if _PROXY_KEY:
        return "proxy"
    return "groq"


def _modelo() -> str:
    if _backend() == "proxy":
        return _PROXY_MODEL
    return os.getenv("GROQ_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _buscar_web(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Busca en ESPN y otras fuentes deportivas info actualizada. Retorna [{title, url, snippet}]."""
    resultados: List[Dict[str, str]] = []
    try:
        # ESPN site search
        resp = requests.get(
            "https://site.api.espn.com/apis/v2/sports/search",
            params={"query": query, "limit": max_results},
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0 (compatible; LigaMXBot/1.0)"},
        )
        if resp.status_code == 200:
            data = resp.json()
            for item in (data.get("items") or [])[:max_results]:
                if isinstance(item, dict):
                    resultados.append(
                        {
                            "title": item.get("headline", "") or item.get("title", ""),
                            "url": item.get("links", {}).get("web", {}).get("href", "") or item.get("url", ""),
                            "snippet": item.get("description", "") or item.get("summary", ""),
                        }
                    )
    except Exception:
        logger.debug("Exception silenciada en _buscar_web", exc_info=True)
    # Fallback: Google News RSS via requests
    if not resultados:
        try:
            resp = requests.get(
                "https://news.google.com/rss/search",
                params={"q": query, "hl": "es", "gl": "MX"},
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code == 200:
                import re as _re

                items = _re.findall(r"<item>(.*?)</item>", resp.text, _re.DOTALL)
                for item in items[:max_results]:
                    titulo = _re.search(r"<title>(.*?)</title>", item, _re.DOTALL)
                    link = _re.search(r"<link/>(.*?)$", item, _re.MULTILINE)
                    desc = _re.search(r"<description>(.*?)</description>", item, _re.DOTALL)
                    url = ""
                    if link:
                        url = link.group(1).strip()
                    if titulo:
                        resultados.append(
                            {
                                "title": _re.sub(r"<[^>]+>", "", titulo.group(1)).strip(),
                                "url": url,
                                "snippet": _re.sub(r"<[^>]+>", "", desc.group(1)).strip() if desc else "",
                            }
                        )
        except Exception:
            logger.debug("Exception silenciada en _buscar_web", exc_info=True)
    # Tercer fallback: obtener contenido completo de las URLs encontradas
    for r in resultados[:3]:
        if r.get("url") and not r.get("snippet"):
            try:
                page_resp = requests.get(r["url"], timeout=8, headers={"User-Agent": "Mozilla/5.0"})
                if page_resp.status_code == 200:
                    import re as _re2

                    texto = _re2.sub(r"<[^>]+>", " ", page_resp.text)
                    texto = " ".join(texto.split())
                    r["snippet"] = texto[:500]
            except Exception:
                logger.debug("Exception silenciada en _buscar_web", exc_info=True)
    return resultados


def _texto_noticias(noticias: List[Dict[str, Any]], max_n: int = 12) -> str:
    """Aplana las noticias a un texto compacto (titulo + fuente) para el prompt."""
    lineas = []
    for n in (noticias or [])[:max_n]:
        if not isinstance(n, dict):
            continue
        titulo = n.get("titulo") or n.get("title") or ""
        fuente = n.get("fuente") or n.get("source") or ""
        if titulo:
            lineas.append(f"- [{fuente}] {titulo}")
    return "\n".join(lineas)


def _enriquecer_con_busqueda_web(equipos: List[str], noticias: List[Dict[str, Any]]) -> str:
    """Busca en web info actualizada sobre lesiones/suspensiones y la agrega al contexto."""
    consultas = []
    # Búsquedas generales por equipo
    for eq in (equipos or [])[:2]:
        consultas.append(f"Liga MX {eq} lesion suspension baja 2026")
        consultas.append(f"Liga MX {eq} alineacion probable rotacion 2026")
        consultas.append(f"{eq} resultado último partido 2026")
    # Búsquedas específicas por jugadores mencionados en las noticias
    jugadores_mencionados: set = set()
    for n in noticias or []:
        if not isinstance(n, dict):
            continue
        titulo = n.get("titulo") or n.get("title") or ""
        for token in titulo.replace("_", " ").replace("-", " ").split():
            if len(token) >= 4 and token[0].isupper():
                jugadores_mencionados.add(token)
    for jug in list(jugadores_mencionados)[:4]:
        consultas.append(f"{jug} equipo actual 2026 Liga MX")
        consultas.append(f"{jug} lesion suspension 2026")
    resultados_txt = []
    for q in consultas[:8]:
        resultados = _buscar_web(q, max_results=3)
        if resultados:
            resultados_txt.append(f"\n🔍 Búsqueda web: {q}")
            for r in resultados:
                titulo = r.get("title", "")
                snippet = r.get("snippet", "")
                if titulo or snippet:
                    resultados_txt.append(f"- {titulo}: {snippet[:200]}")
    return "\n".join(resultados_txt) if resultados_txt else ""


def analizar_noticias(equipos: List[str], noticias: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Pide al backend configurado que extraiga señales de riesgo de las noticias dadas
    para los `equipos`. Backend: proxy local (preferido) o Groq (fallback).
    Tolerante: si no hay key, no hay noticias o falla la llamada,
    devuelve {disponible: False}. NUNCA lanza.
    """
    if not habilitado():
        return {"disponible": False, "motivo": "IA desactivada (sin PROXY_API_KEY ni GROQ_API_KEY)."}
    texto = _texto_noticias(noticias)
    if not texto:
        return {"disponible": False, "motivo": "Sin noticias para analizar."}

    user = (
        f"Equipos del partido: {', '.join(equipos)}.\n\n"
        f"Noticias recientes (úsalas SOLO como fuente, no inventes):\n{texto}\n\n"
    )

    # Enriquecer con búsqueda web si hay equipos definidos
    web_ctx = ""
    if equipos:
        web_ctx = _enriquecer_con_busqueda_web(equipos, noticias)
    if web_ctx:
        user += f"Información adicional de búsqueda web (también usala SOLO como fuente):\n{web_ctx}\n\n"

    user += "Devuelve el JSON con las señales de riesgo relevantes a esos equipos."

    payload = {
        "model": _modelo(),
        "messages": [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
        "max_tokens": 700,
    }

    backend = _backend()
    url = _PROXY_URL if backend == "proxy" else GROQ_URL
    headers = {"Authorization": f"Bearer {_PROXY_KEY if backend == 'proxy' else _groq_api_key()}"}

    try:
        resp = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=60 if backend == "proxy" else 30,
        )
        if resp.status_code != 200:
            return {"disponible": False, "motivo": f"{backend.upper()} HTTP {resp.status_code}."}
        contenido = ""
        try:
            contenido = resp.json()["choices"][0]["message"]["content"]
        except Exception:
            try:
                contenido = resp.json().get("message", {}).get("content", "")
            except Exception:
                contenido = ""
        if not contenido:
            return {"disponible": False, "motivo": f"{backend.upper()} respuesta vacía."}
        try:
            data = json.loads(contenido)
        except Exception:
            texto_limpio = str(contenido).strip()
            if "```json" in texto_limpio:
                texto_limpio = texto_limpio.split("```json", 1)[1].split("```", 1)[0].strip()
            elif "```" in texto_limpio:
                texto_limpio = texto_limpio.split("```", 1)[1].split("```", 1)[0].strip()
            try:
                data = json.loads(texto_limpio)
            except Exception:
                return {
                    "disponible": True,
                    "modelo": _modelo(),
                    "backend": backend,
                    "riesgos": [],
                    "sin_senales": True,
                    "decision": DECISION,
                    "motivo": "Respuesta no-JSON; sin señales.",
                }
    except Exception as exc:  # pragma: no cover - red/parseo
        return {"disponible": False, "motivo": f"Error IA ({backend}): {str(exc)[:120]}"}

    riesgos = data.get("riesgos") if isinstance(data, dict) else None
    if not isinstance(riesgos, list):
        riesgos = []
    # Saneo: solo campos esperados, recortados.
    limpios = []
    for r in riesgos[:10]:
        if not isinstance(r, dict):
            continue
        limpios.append(
            {
                "equipo": str(r.get("equipo", ""))[:40],
                "tipo": str(r.get("tipo", "otro"))[:20],
                "jugador": str(r.get("jugador", ""))[:60],
                "resumen": str(r.get("resumen", ""))[:200],
                "titulo_fuente": str(r.get("titulo_fuente", ""))[:200],
            }
        )
    return {
        "disponible": True,
        "modelo": _modelo(),
        "backend": backend,
        "riesgos": limpios,
        "sin_senales": bool(data.get("sin_senales")) if not limpios else False,
        "decision": DECISION,
    }


def analizar_partido(home: str, away: str) -> Dict[str, Any]:
    """
    Analiza el riesgo (por noticias) de un partido: baja las noticias de ambos
    equipos vía la Liga MX API y las pasa por el LLM. Tolerante.
    Ahora también busca en web información actualizada sobre lesiones,
    suspensiones, dudas o rotación.
    """
    if not habilitado():
        return {"disponible": False, "motivo": "IA desactivada (sin PROXY_API_KEY ni GROQ_API_KEY)."}
    try:
        try:
            import ligamx_api as lmx
        except ImportError:  # pragma: no cover
            from src import ligamx_api as lmx  # type: ignore
        noticias = lmx.noticias_de_equipos([home, away], limit=10)
    except Exception:  # pragma: no cover
        noticias = []
    return analizar_noticias([home, away], noticias)
