#!/usr/bin/env python3
"""
comparador_mercado.py — Capa OPCIONAL de comparación modelo vs mercado.

El modelo (ESPN + Poisson) es la FUENTE DE VERDAD. Esta capa es un extra
informativo: si hay una API de momios configurada, compara las probabilidades
del modelo contra las del mercado (sin vig) y señala dónde el modelo ve "valor"
(diferencia a favor), siempre con disclaimer de revisión humana.

Gating: si no hay key (`ODDS_API_IO_KEY`), TODO queda en no-op y las
predicciones pasan sin cambios. NUNCA dice "apuesta"; solo marca diferencias
para revisión humana.

Fuente opcional: odds-api.io (tier gratis, cubre Liga MX). Sin scraping, sin
bypass. La red va aislada y es defensiva (cualquier fallo => sin comparación).
"""
from __future__ import annotations

import os
import unicodedata
from typing import Any, Dict, List, Optional, Sequence

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

# --- Configuración (todo por env, apagado por defecto) ---------------------
ENV_KEY = "ODDS_API_IO_KEY"
BASE_URL = os.getenv("ODDS_API_IO_URL", "https://api.odds-api.io/v3")
# Filtro de liga: por nombre (se compara normalizado, "contiene").
LIGA_FILTRO = os.getenv("ODDS_API_IO_LIGA", "liga mx")

# Diferencia mínima (en proporción) para marcar "valor" del modelo vs mercado.
UMBRAL_VALOR = 0.05

DISCLAIMER = "ℹ️ Informativo / revisión humana. No es consejo de apuesta."


def _norm(texto: str) -> str:
    base = unicodedata.normalize("NFKD", str(texto or "")).lower()
    base = "".join(c for c in base if not unicodedata.combining(c))
    return " ".join(base.split())


def mercado_habilitado() -> bool:
    """True solo si hay key configurada para la API de momios."""
    return bool(os.getenv(ENV_KEY, "").strip())


# ---------------------------------------------------------------------------
# Matemática pura (sin red): vig y comparación. Esto es lo testeable y útil.
# ---------------------------------------------------------------------------
def quitar_vig(momio_local: float, momio_empate: float, momio_visita: float) -> Dict[str, float]:
    """
    Convierte momios decimales 1X2 en probabilidades implícitas SIN vig.

    Devuelve {prob_local, prob_empate, prob_visita, vig}. Lanza ValueError si
    algún momio no es > 1.
    """
    momios = [float(momio_local), float(momio_empate), float(momio_visita)]
    if any(m <= 1.0 for m in momios):
        raise ValueError("Los momios decimales deben ser > 1.0.")
    implicitas = [1.0 / m for m in momios]
    suma = sum(implicitas)
    vig = suma - 1.0
    sin_vig = [p / suma for p in implicitas]
    return {
        "prob_local": sin_vig[0],
        "prob_empate": sin_vig[1],
        "prob_visita": sin_vig[2],
        "vig": vig,
    }


def comparar(
    prob_modelo: Sequence[float],
    momio_local: float,
    momio_empate: float,
    momio_visita: float,
    *,
    umbral: float = UMBRAL_VALOR,
) -> Dict[str, Any]:
    """
    Compara las probabilidades del modelo (1X2, en proporción [0-1] o %) con las
    del mercado sin vig. Marca dónde el modelo ve VALOR (prob_modelo supera a la
    de mercado por al menos `umbral`).

    `prob_modelo` = [p_local, p_empate, p_visita]. Acepta % (se normaliza si la
    suma es ~100). Devuelve diffs por resultado, el mejor "valor" y disclaimer.
    """
    pm = [float(x) for x in prob_modelo]
    if len(pm) != 3:
        raise ValueError("prob_modelo debe tener 3 valores (1X2).")
    if sum(pm) > 1.5:  # viene en porcentaje
        pm = [x / 100.0 for x in pm]

    mercado = quitar_vig(momio_local, momio_empate, momio_visita)
    pmkt = [mercado["prob_local"], mercado["prob_empate"], mercado["prob_visita"]]
    etiquetas = ["local", "empate", "visita"]

    diffs = [round(pm[i] - pmkt[i], 4) for i in range(3)]
    # Mejor "valor": mayor diferencia positiva del modelo sobre el mercado.
    mejor_i = max(range(3), key=lambda i: diffs[i])
    hay_valor = diffs[mejor_i] >= umbral

    return {
        "prob_modelo_pct": [round(p * 100, 2) for p in pm],
        "prob_mercado_pct": [round(p * 100, 2) for p in pmkt],
        "vig_pct": round(mercado["vig"] * 100, 2),
        "diff_pct": [round(d * 100, 2) for d in diffs],
        "valor_en": etiquetas[mejor_i] if hay_valor else None,
        "hay_valor": hay_valor,
        "decision": DISCLAIMER,
    }


def anotar_pronostico(pron: Dict[str, Any], momios: Optional[Dict[str, float]]) -> Dict[str, Any]:
    """
    Devuelve una COPIA del pronóstico con un bloque 'mercado' si hay momios
    válidos ({local, empate, visita}); si no, deja mercado=None (sin tocar nada).
    """
    salida = dict(pron)
    if not momios:
        salida["mercado"] = None
        return salida
    try:
        prob_modelo = [
            pron["prob_local_pct"], pron["prob_empate_pct"], pron["prob_visitante_pct"],
        ]
        salida["mercado"] = comparar(
            prob_modelo, momios["local"], momios["empate"], momios["visita"]
        )
    except (KeyError, ValueError, TypeError):
        salida["mercado"] = None
    return salida


def _clave_partido(local: str, visitante: str) -> str:
    return f"{_norm(local)}|{_norm(visitante)}"


def anotar_pronosticos(
    pronosticos: Sequence[Dict[str, Any]],
    momios_por_partido: Optional[Dict[str, Dict[str, float]]] = None,
) -> List[Dict[str, Any]]:
    """Anota una lista de pronósticos con la comparación de mercado disponible."""
    momios_por_partido = momios_por_partido or {}
    salida = []
    for p in pronosticos:
        clave = _clave_partido(p.get("local", ""), p.get("visitante", ""))
        salida.append(anotar_pronostico(p, momios_por_partido.get(clave)))
    return salida


# ---------------------------------------------------------------------------
# Red (gated, defensiva): odds-api.io. Sin key => {} y todo queda en no-op.
# ---------------------------------------------------------------------------
def parsear_odds_1x2(bookmakers: Any) -> Optional[Dict[str, float]]:
    """
    De un dict de bookmakers de odds-api.io extrae el PROMEDIO de momios 1X2
    (home/draw/away) entre las casas disponibles. Función pura, defensiva.
    """
    if not isinstance(bookmakers, dict) or not bookmakers:
        return None
    locales: List[float] = []
    empates: List[float] = []
    visitas: List[float] = []
    for casa in bookmakers.values():
        if not isinstance(casa, dict):
            continue
        try:
            h = float(casa.get("home"))
            d = float(casa.get("draw"))
            a = float(casa.get("away"))
        except (TypeError, ValueError):
            continue
        if h > 1 and d > 1 and a > 1:
            locales.append(h); empates.append(d); visitas.append(a)
    if not locales:
        return None
    prom = lambda xs: sum(xs) / len(xs)
    return {"local": prom(locales), "empate": prom(empates), "visita": prom(visitas)}


def _get(url: str, params: Dict[str, Any]) -> Any:
    if requests is None:
        raise RuntimeError("La dependencia 'requests' no está instalada.")
    resp = requests.get(url, params=params, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"odds-api.io respondió HTTP {resp.status_code}.")
    return resp.json()


def obtener_momios_liga_mx() -> Dict[str, Dict[str, float]]:
    """
    Baja momios 1X2 de Liga MX desde odds-api.io. Devuelve
    {clave_partido: {local, empate, visita}}. Si no hay key o algo falla,
    devuelve {} (no-op: el resto del bot sigue funcionando sin mercado).
    """
    if not mercado_habilitado():
        return {}
    key = os.getenv(ENV_KEY, "").strip()
    out: Dict[str, Dict[str, float]] = {}
    try:
        eventos = _get(f"{BASE_URL}/events", {"apiKey": key, "sport": "football", "limit": 100})
        if not isinstance(eventos, list):
            return {}
        for ev in eventos:
            if not isinstance(ev, dict):
                continue
            liga = _norm((ev.get("league") or {}).get("name", ""))
            if LIGA_FILTRO and _norm(LIGA_FILTRO) not in liga:
                continue
            ev_id = ev.get("id")
            home, away = ev.get("home", ""), ev.get("away", "")
            if ev_id is None or not home or not away:
                continue
            try:
                odds = _get(f"{BASE_URL}/odds", {"apiKey": key, "eventId": ev_id})
            except RuntimeError:
                continue
            book = odds.get("bookmakers") if isinstance(odds, dict) else None
            momios = parsear_odds_1x2(book)
            if momios:
                out[_clave_partido(home, away)] = momios
    except RuntimeError:
        return {}
    return out


def comparar_pronosticos(pronosticos: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Punto de entrada de alto nivel: anota los pronósticos con la comparación de
    mercado si está habilitada. Si no, devuelve los pronósticos sin cambios.
    """
    habilitado = mercado_habilitado()
    momios = obtener_momios_liga_mx() if habilitado else {}
    return {
        "mercado_habilitado": habilitado,
        "partidos_con_momios": len(momios),
        "pronosticos": anotar_pronosticos(pronosticos, momios),
        "decision": DISCLAIMER,
    }
