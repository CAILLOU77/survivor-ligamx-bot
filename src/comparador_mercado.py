#!/usr/bin/env python3
"""
comparador_mercado.py — Capa OPCIONAL de comparación modelo vs mercado.

El modelo (ESPN + Poisson) es la FUENTE DE VERDAD. Esta capa es un extra
informativo: si hay una API de momios configurada, baja las cuotas reales del
mercado y las compara con las probabilidades del modelo para señalar:

- 1X2: favorito y dónde el modelo ve "valor" (diferencia a su favor).
- Over/Under: si el mercado ve el partido EXPLOSIVO (Over barato / favorito el
  Over) o CAUTELOSO (Under), y valor en Over/Under.
- Hándicap (asiático): qué tan FAVORITO es un equipo según la línea.
- Empate: se muestra como referencia, marcado NO accionable para Survivor.

Gating: sin key (`ODDS_API_IO_KEY`) TODO queda en no-op y las predicciones
pasan sin cambios. NUNCA dice "apuesta"; solo marca diferencias para revisión
humana. Fuente: odds-api.io (tier gratis, cubre Liga MX). Sin scraping.
"""
from __future__ import annotations

import os
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

# --- Configuración (todo por env, apagado por defecto) ---------------------
ENV_KEY = "ODDS_API_IO_KEY"
BASE_URL = os.getenv("ODDS_API_IO_URL", "https://api.odds-api.io/v3")
# Slug de Liga MX en odds-api.io (confirmado: "mexico-liga-mx-apertura").
LIGA_SLUG = os.getenv("ODDS_API_IO_LIGA", "mexico-liga-mx-apertura")
SPORT_SLUG = os.getenv("ODDS_API_IO_SPORT", "football")
# Tope de partidos a consultar por ciclo (cuida el límite del tier gratis).
MAX_EVENTOS = int(os.getenv("ODDS_API_IO_MAX_EVENTOS", "20"))
# Ventana de fechas hacia adelante (días). Liga MX puede arrancar en >14 días
# (el default de la API es 14), así que la ampliamos para captar la próxima
# jornada en pretemporada.
VENTANA_DIAS = int(os.getenv("ODDS_API_IO_VENTANA_DIAS", "120"))
# Casas a consultar (la API exige el parámetro `bookmakers` en /odds, máx 30).
# Lista de casas globales que suelen cubrir Liga MX; se intersecta con las
# casas ACTIVAS reales de la API. Override con ODDS_API_IO_BOOKMAKERS.
BOOKMAKERS_PRIORIDAD = [
    "Bet365", "Pinnacle", "1xBet", "Unibet", "William Hill", "Betfair",
    "Bwin", "888sport", "Betsson", "Marathonbet", "Betway", "Dafabet",
    "Betano", "Codere", "Caliente", "Betcris", "Betsafe", "Sportingbet",
    "10Bet", "22Bet", "Megapari", "1win", "Betobet", "Parimatch",
    "Pinnacle Sports", "Stake", "BetWinner", "Melbet", "888", "Vbet",
]
_BOOKMAKERS_OVERRIDE = os.getenv("ODDS_API_IO_BOOKMAKERS", "").strip()

# Diferencia mínima (proporción) para marcar "valor" del modelo vs mercado.
UMBRAL_VALOR = 0.05
# Línea de goles de referencia del modelo.
LINEA_GOLES = 2.5

DISCLAIMER = "ℹ️ Informativo / revisión humana. No es consejo de apuesta."


def _norm(texto: str) -> str:
    base = unicodedata.normalize("NFKD", str(texto or "")).lower()
    base = "".join(c for c in base if not unicodedata.combining(c))
    return " ".join(base.split())


def mercado_habilitado() -> bool:
    """True solo si hay key configurada para la API de momios."""
    return bool(os.getenv(ENV_KEY, "").strip())


# ---------------------------------------------------------------------------
# Matemática pura: quitar vig y comparar. Esto es lo testeable y útil.
# ---------------------------------------------------------------------------
def quitar_vig(momio_local: float, momio_empate: float, momio_visita: float) -> Dict[str, float]:
    """Momios decimales 1X2 -> probabilidades implícitas SIN vig (+ vig)."""
    momios = [float(momio_local), float(momio_empate), float(momio_visita)]
    if any(m <= 1.0 for m in momios):
        raise ValueError("Los momios decimales deben ser > 1.0.")
    implicitas = [1.0 / m for m in momios]
    suma = sum(implicitas)
    return {
        "prob_local": implicitas[0] / suma,
        "prob_empate": implicitas[1] / suma,
        "prob_visita": implicitas[2] / suma,
        "vig": suma - 1.0,
    }


def quitar_vig_2(momio_a: float, momio_b: float) -> Dict[str, float]:
    """Mercado de 2 vías (ej. Over/Under) -> probabilidades sin vig (+ vig)."""
    a, b = float(momio_a), float(momio_b)
    if a <= 1.0 or b <= 1.0:
        raise ValueError("Los momios decimales deben ser > 1.0.")
    ia, ib = 1.0 / a, 1.0 / b
    suma = ia + ib
    return {"prob_a": ia / suma, "prob_b": ib / suma, "vig": suma - 1.0}


def comparar_1x2(
    prob_modelo: Sequence[float],
    momio_local: float,
    momio_empate: float,
    momio_visita: float,
    *,
    umbral: float = UMBRAL_VALOR,
) -> Dict[str, Any]:
    """
    Compara el 1X2 del modelo vs mercado (sin vig). Marca el favorito del
    mercado y dónde el modelo ve valor. El empate se marca NO accionable.
    `prob_modelo` = [local, empate, visita] (acepta % o proporción).
    """
    pmod = [float(x) for x in prob_modelo]
    if len(pmod) != 3:
        raise ValueError("prob_modelo debe tener 3 valores (1X2).")
    if sum(pmod) > 1.5:
        pmod = [x / 100.0 for x in pmod]

    mercado = quitar_vig(momio_local, momio_empate, momio_visita)
    pmkt = [mercado["prob_local"], mercado["prob_empate"], mercado["prob_visita"]]
    etiquetas = ["local", "empate", "visita"]

    favorito = etiquetas[max(range(3), key=lambda i: pmkt[i])]
    diffs = [round(pmod[i] - pmkt[i], 4) for i in range(3)]
    mejor_i = max(range(3), key=lambda i: diffs[i])
    hay_valor = diffs[mejor_i] >= umbral
    valor_en = etiquetas[mejor_i] if hay_valor else None

    return {
        "favorito_mercado": favorito,
        "prob_modelo_pct": [round(p * 100, 2) for p in pmod],
        "prob_mercado_pct": [round(p * 100, 2) for p in pmkt],
        "vig_pct": round(mercado["vig"] * 100, 2),
        "diff_pct": [round(d * 100, 2) for d in diffs],
        "valor_en": valor_en,
        "hay_valor": hay_valor,
        "empate_accionable": False,  # en Survivor el empate no se elige
    }


def comparar_totales(
    prob_over_modelo: float,
    momio_over: float,
    momio_under: float,
    linea: float = LINEA_GOLES,
    *,
    umbral: float = UMBRAL_VALOR,
) -> Dict[str, Any]:
    """
    Compara Over/Under del modelo vs mercado. Indica si el mercado ve el partido
    EXPLOSIVO (favorece Over) o CAUTELOSO (favorece Under), y dónde hay valor.
    `prob_over_modelo` en % o proporción.
    """
    p_over = float(prob_over_modelo)
    if p_over > 1.5:
        p_over /= 100.0
    mkt = quitar_vig_2(momio_over, momio_under)
    p_over_mkt = mkt["prob_a"]

    diff = round(p_over - p_over_mkt, 4)
    if abs(diff) >= umbral:
        valor_en = "Over" if diff > 0 else "Under"
    else:
        valor_en = None

    return {
        "linea": linea,
        "mercado_ve": "explosivo" if p_over_mkt >= 0.5 else "cauteloso",
        "prob_over_modelo_pct": round(p_over * 100, 2),
        "prob_over_mercado_pct": round(p_over_mkt * 100, 2),
        "diff_over_pct": round(diff * 100, 2),
        "vig_pct": round(mkt["vig"] * 100, 2),
        "valor_en": valor_en,
        "hay_valor": valor_en is not None,
    }


def resumen_handicap(linea: float, momio_local: float, momio_visita: float) -> Dict[str, Any]:
    """
    Interpreta el hándicap asiático (línea desde la perspectiva del local).
    Línea negativa => el local es favorito (da goles). Magnitud alta => muy
    favorito. Informativo.
    """
    ln = float(linea)
    favorito = "local" if ln < 0 else ("visitante" if ln > 0 else "parejo")
    magnitud = abs(ln)
    if magnitud >= 1.5:
        fuerza = "muy favorito"
    elif magnitud >= 0.75:
        fuerza = "favorito claro"
    elif magnitud > 0:
        fuerza = "ligero favorito"
    else:
        fuerza = "parejo"
    return {
        "linea": ln,
        "favorito": favorito,
        "fuerza": fuerza,
        "momio_local": round(float(momio_local), 2),
        "momio_visita": round(float(momio_visita), 2),
    }


def anotar_pronostico(pron: Dict[str, Any], mercado: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Devuelve una COPIA del pronóstico con un bloque 'mercado' (1x2 + totales +
    handicap) si hay momios; si no, mercado=None.
    `mercado` = salida de parsear_mercado: {ml, totals, handicap}.
    """
    salida = dict(pron)
    if not mercado:
        salida["mercado"] = None
        return salida

    bloque: Dict[str, Any] = {"decision": DISCLAIMER}
    try:
        ml = mercado.get("ml")
        if ml:
            bloque["1x2"] = comparar_1x2(
                [pron["prob_local_pct"], pron["prob_empate_pct"], pron["prob_visitante_pct"]],
                ml["local"], ml["empate"], ml["visita"],
            )
    except (KeyError, ValueError, TypeError):
        pass
    try:
        tot = mercado.get("totals")
        if tot and "prob_over_pct" in pron:
            bloque["over_under"] = comparar_totales(
                pron["prob_over_pct"], tot["over"], tot["under"], tot.get("linea", LINEA_GOLES),
            )
    except (KeyError, ValueError, TypeError):
        pass
    try:
        hcp = mercado.get("handicap")
        if hcp:
            bloque["handicap"] = resumen_handicap(hcp["linea"], hcp["local"], hcp["visita"])
    except (KeyError, ValueError, TypeError):
        pass

    salida["mercado"] = bloque if len(bloque) > 1 else None
    return salida


def _clave_partido(local: str, visitante: str) -> str:
    return f"{_norm(local)}|{_norm(visitante)}"


_PALABRAS_COMUNES = {"club", "cf", "fc", "deportivo", "real", "atletico", "atletico", "de", "the"}


def _token_significativo(nombre: str) -> set:
    return {t for t in _norm(nombre).split() if len(t) >= 4 and t not in _PALABRAS_COMUNES}


def _equipos_coinciden(a: str, b: str) -> bool:
    """Empareja nombres de equipo de forma flexible (ESPN vs odds-api.io)."""
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    return bool(_token_significativo(a) & _token_significativo(b))


def _buscar_mercado(
    home: str, away: str, momios: Dict[str, Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Encuentra el mercado de un partido por clave exacta o por nombres flexibles."""
    clave = _clave_partido(home, away)
    if clave in momios:
        return momios[clave]
    for k, mercado in momios.items():
        h_key, _, a_key = k.partition("|")
        if _equipos_coinciden(home, h_key) and _equipos_coinciden(away, a_key):
            return mercado
    return None


def anotar_pronosticos(
    pronosticos: Sequence[Dict[str, Any]],
    momios_por_partido: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Anota una lista de pronósticos con la comparación de mercado disponible."""
    momios_por_partido = momios_por_partido or {}
    salida = []
    for p in pronosticos:
        mercado = _buscar_mercado(p.get("local", ""), p.get("visitante", ""), momios_por_partido)
        salida.append(anotar_pronostico(p, mercado))
    return salida


# ---------------------------------------------------------------------------
# Parseo del formato real de odds-api.io (función pura, defensiva).
# bookmakers = {casa: [ {name, odds:[{...}]}, ... ]}. Markets: ML, Over/Under,
# Asian Handicap, etc. Promediamos entre casas.
# ---------------------------------------------------------------------------
def _f(valor: Any) -> Optional[float]:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def parsear_mercado(odds_response: Any) -> Dict[str, Any]:
    """
    De la respuesta /odds extrae promedios de mercado:
        {ml: {local, empate, visita},
         totals: {linea, over, under},
         handicap: {linea, local, visita}}
    Promedia entre casas. Para totales prefiere la línea 2.5. Devuelve {} si no
    hay nada utilizable.
    """
    if not isinstance(odds_response, dict):
        return {}
    bookmakers = odds_response.get("bookmakers")
    if not isinstance(bookmakers, dict) or not bookmakers:
        return {}

    ml_h: List[float] = []; ml_d: List[float] = []; ml_a: List[float] = []
    # totales agrupados por línea: {linea: {"over": [...], "under": [...]}}
    tot = defaultdict(lambda: {"over": [], "under": []})
    hdp_line: List[float] = []; hdp_h: List[float] = []; hdp_a: List[float] = []

    for markets in bookmakers.values():
        if not isinstance(markets, list):
            continue
        for m in markets:
            if not isinstance(m, dict):
                continue
            nombre = _norm(m.get("name"))
            odds_list = m.get("odds") or []
            if not isinstance(odds_list, list) or not odds_list:
                continue
            o = odds_list[0]
            if not isinstance(o, dict):
                continue
            if nombre == "ml":
                h, d, a = _f(o.get("home")), _f(o.get("draw")), _f(o.get("away"))
                if h and d and a and h > 1 and d > 1 and a > 1:
                    ml_h.append(h); ml_d.append(d); ml_a.append(a)
            elif nombre in ("over/under", "totals", "total goals"):
                linea = _f(o.get("max")) or _f(o.get("hdp")) or _f(o.get("line"))
                ov, un = _f(o.get("over")), _f(o.get("under"))
                if linea is not None and ov and un and ov > 1 and un > 1:
                    tot[round(linea, 2)]["over"].append(ov)
                    tot[round(linea, 2)]["under"].append(un)
            elif nombre in ("asian handicap", "handicap", "spread"):
                linea = _f(o.get("hdp"))
                h, a = _f(o.get("home")), _f(o.get("away"))
                if linea is not None and h and a and h > 1 and a > 1:
                    hdp_line.append(linea); hdp_h.append(h); hdp_a.append(a)

    prom = lambda xs: sum(xs) / len(xs)
    out: Dict[str, Any] = {}
    if ml_h:
        out["ml"] = {"local": prom(ml_h), "empate": prom(ml_d), "visita": prom(ml_a)}
    if tot:
        # Preferir la línea 2.5; si no, la línea con más casas.
        if 2.5 in tot and tot[2.5]["over"]:
            linea = 2.5
        else:
            linea = max(tot, key=lambda k: len(tot[k]["over"]))
        if tot[linea]["over"]:
            out["totals"] = {
                "linea": linea,
                "over": prom(tot[linea]["over"]),
                "under": prom(tot[linea]["under"]),
            }
    if hdp_line:
        out["handicap"] = {
            "linea": prom(hdp_line), "local": prom(hdp_h), "visita": prom(hdp_a),
        }
    return out


# ---------------------------------------------------------------------------
# Red (gated, defensiva): odds-api.io. Sin key => {} y todo queda en no-op.
# ---------------------------------------------------------------------------
def _get(url: str, params: Dict[str, Any]) -> Any:
    if requests is None:
        raise RuntimeError("La dependencia 'requests' no está instalada.")
    resp = requests.get(url, params=params, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"odds-api.io respondió HTTP {resp.status_code} en {url}.")
    return resp.json()


_BOOKMAKERS_CACHE: Optional[str] = None


def _bookmakers_consulta() -> str:
    """
    Cadena de casas (máx 30) para el parámetro `bookmakers` de /odds.
    Si hay override por env, se usa tal cual. Si no, se intersecta la lista de
    prioridad con las casas ACTIVAS reales (endpoint /bookmakers, sin auth) y se
    rellena hasta 30 con otras activas. Cacheado.
    """
    global _BOOKMAKERS_CACHE
    if _BOOKMAKERS_OVERRIDE:
        return _BOOKMAKERS_OVERRIDE
    if _BOOKMAKERS_CACHE is not None:
        return _BOOKMAKERS_CACHE
    try:
        data = _get(f"{BASE_URL}/bookmakers", {})
        activas = [b.get("name") for b in data
                   if isinstance(b, dict) and b.get("active") and b.get("name")]
    except RuntimeError:
        activas = []
    if not activas:
        _BOOKMAKERS_CACHE = ",".join(BOOKMAKERS_PRIORIDAD[:30])
        return _BOOKMAKERS_CACHE
    activas_norm = {_norm(n): n for n in activas}
    elegidas: List[str] = []
    for pref in BOOKMAKERS_PRIORIDAD:
        real = activas_norm.get(_norm(pref))
        if real and real not in elegidas:
            elegidas.append(real)
    for n in activas:  # rellenar hasta 30 con otras activas
        if len(elegidas) >= 30:
            break
        if n not in elegidas:
            elegidas.append(n)
    _BOOKMAKERS_CACHE = ",".join(elegidas[:30])
    return _BOOKMAKERS_CACHE


def _listar_eventos(key: str) -> List[Dict[str, Any]]:
    """Eventos próximos de Liga MX (ventana ampliada, solo no jugados)."""
    hasta = (datetime.now(timezone.utc) + timedelta(days=VENTANA_DIAS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    eventos = _get(f"{BASE_URL}/events", {
        "apiKey": key, "sport": SPORT_SLUG, "league": LIGA_SLUG,
        "status": "pending", "to": hasta,
    })
    if not isinstance(eventos, list):
        return []
    out = []
    for ev in eventos:
        if not isinstance(ev, dict):
            continue
        slug = _norm((ev.get("league") or {}).get("slug", ""))
        if LIGA_SLUG and slug and _norm(LIGA_SLUG) not in slug:
            continue
        if ev.get("id") is not None and ev.get("home") and ev.get("away"):
            out.append(ev)
    return out


def _odds_multi(key: str, ids: List[Any], bookmakers: str) -> List[Dict[str, Any]]:
    """Odds para hasta 10 eventos en una sola llamada (/odds/multi)."""
    if not ids:
        return []
    data = _get(f"{BASE_URL}/odds/multi", {
        "apiKey": key,
        "eventIds": ",".join(str(i) for i in ids[:10]),
        "bookmakers": bookmakers,
    })
    return data if isinstance(data, list) else []


def obtener_momios_liga_mx() -> Dict[str, Dict[str, Any]]:
    """
    Baja momios de Liga MX desde odds-api.io. Devuelve
    {clave_partido: {ml, totals, handicap}}. Sin key o ante cualquier fallo
    devuelve {} (no-op). Limita a MAX_EVENTOS por ciclo (tier gratis).
    """
    if not mercado_habilitado():
        return {}
    key = os.getenv(ENV_KEY, "").strip()
    out: Dict[str, Dict[str, Any]] = {}
    try:
        eventos = _listar_eventos(key)[:MAX_EVENTOS]
        if not eventos:
            return {}
        bookmakers = _bookmakers_consulta()
        for i in range(0, len(eventos), 10):
            lote = eventos[i:i + 10]
            ids = [e["id"] for e in lote]
            try:
                respuestas = _odds_multi(key, ids, bookmakers)
            except RuntimeError:
                continue
            for odds in respuestas:
                home, away = odds.get("home", ""), odds.get("away", "")
                if not home or not away:
                    continue
                mercado = parsear_mercado(odds)
                if mercado:
                    out[_clave_partido(home, away)] = mercado
    except RuntimeError:
        return {}
    return out


def diagnostico_mercado() -> Dict[str, Any]:
    """
    Diagnóstico en vivo de la conexión a odds-api.io (para depurar). Devuelve
    conteos y muestras SIN exponer la key. No lanza: captura errores.
    """
    info: Dict[str, Any] = {
        "habilitado": mercado_habilitado(),
        "liga_slug": LIGA_SLUG, "sport": SPORT_SLUG, "ventana_dias": VENTANA_DIAS,
    }
    if not info["habilitado"]:
        info["nota"] = "Sin ODDS_API_IO_KEY: capa apagada (no-op)."
        return info
    key = os.getenv(ENV_KEY, "").strip()
    try:
        eventos = _listar_eventos(key)
        info["n_eventos"] = len(eventos)
        info["eventos_muestra"] = [
            {"id": e.get("id"), "home": e.get("home"), "away": e.get("away"),
             "date": e.get("date"), "liga": (e.get("league") or {}).get("slug")}
            for e in eventos[:5]
        ]
        info["bookmakers_usadas"] = _bookmakers_consulta()[:300]
        if eventos:
            ids = [e["id"] for e in eventos[:3]]
            respuestas = _odds_multi(key, ids, _bookmakers_consulta())
            info["n_odds_respuestas"] = len(respuestas)
            if respuestas:
                primera = respuestas[0]
                casas = list((primera.get("bookmakers") or {}).keys())
                mercados = []
                if casas:
                    mercados = [m.get("name") for m in (primera.get("bookmakers") or {})[casas[0]]
                                if isinstance(m, dict)]
                info["odds_muestra"] = {
                    "evento": f"{primera.get('home')} vs {primera.get('away')}",
                    "casas": casas[:10],
                    "mercados_primera_casa": mercados,
                    "parseado": parsear_mercado(primera),
                }
    except RuntimeError as exc:
        info["error"] = str(exc)
    return info


def comparar_pronosticos(pronosticos: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Punto de entrada de alto nivel: anota los pronósticos con la comparación de
    mercado si está habilitada. Si no, devuelve los pronósticos sin cambios.
    """
    habilitado = mercado_habilitado()
    momios = obtener_momios_liga_mx() if habilitado else {}
    return {
        "mercado_habilitado": habilitado,
        "fuente_mercado": "odds-api.io" if habilitado else None,
        "partidos_con_momios": len(momios),
        "pronosticos": anotar_pronosticos(pronosticos, momios),
        "decision": DISCLAIMER,
    }
