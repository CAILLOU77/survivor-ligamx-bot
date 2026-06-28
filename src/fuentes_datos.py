#!/usr/bin/env python3
"""
fuentes_datos.py — Capa multi-fuente con redundancia para datos Liga MX.

Objetivo: que el proyecto NO dependa de una sola fuente. Cadena de respaldo:
    1) ESPN (site.api.espn.com)        — primaria, rica (resultados completos).
    2) TheSportsDB (free key)          — respaldo si ESPN falla.
    3) Caché local (resultados_historicos.json) — último recurso si todo falla.

Todas son APIs públicas/gratuitas. Sin scraping, sin bypass, sin credenciales
privadas. Devuelve resultados en el formato del modelo Poisson
(home_team, away_team, home_goals, away_goals, fecha).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

try:
    import espn_data
except ImportError:  # pragma: no cover
    from src import espn_data  # type: ignore

BASE_DIR = Path(__file__).resolve().parents[1]
CACHE_PATH = BASE_DIR / "data" / "resultados_historicos.json"

# TheSportsDB: key pública gratuita "3", Liga MX league id 4350.
TSDB_KEY = "3"
TSDB_LIGAMX_ID = "4350"
TSDB_URL = f"https://www.thesportsdb.com/api/v1/json/{TSDB_KEY}/eventspastleague.php"

# Mínimo de partidos para considerar una fuente "suficiente".
MIN_ACEPTABLE = 10


def parsear_thesportsdb(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parser puro de la respuesta de TheSportsDB (eventos pasados con marcador)."""
    salida: List[Dict[str, Any]] = []
    for e in (data.get("events") or []):
        if not isinstance(e, dict):
            continue
        home = e.get("strHomeTeam")
        away = e.get("strAwayTeam")
        hs = e.get("intHomeScore")
        as_ = e.get("intAwayScore")
        if not home or not away or hs is None or as_ is None:
            continue
        try:
            hg, ag = int(hs), int(as_)
        except (TypeError, ValueError):
            continue
        salida.append({
            "home_team": home,
            "away_team": away,
            "home_goals": hg,
            "away_goals": ag,
            "fecha": e.get("dateEvent", ""),
        })
    return salida


def _fetch_thesportsdb() -> Dict[str, Any]:
    if requests is None:
        raise RuntimeError("La dependencia 'requests' no está instalada.")
    resp = requests.get(TSDB_URL, params={"id": TSDB_LIGAMX_ID}, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"TheSportsDB respondió HTTP {resp.status_code}.")
    return resp.json()


def obtener_resultados_thesportsdb() -> List[Dict[str, Any]]:
    return parsear_thesportsdb(_fetch_thesportsdb())


def leer_cache(path: Path = CACHE_PATH) -> List[Dict[str, Any]]:
    if not Path(path).exists():
        return []
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def guardar_cache(resultados: List[Dict[str, Any]], path: Path = CACHE_PATH) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(resultados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def obtener_resultados(meses: int = 6, minimo: int = MIN_ACEPTABLE) -> Dict[str, Any]:
    """
    Devuelve resultados con redundancia: {fuente, resultados, total}.

    Cadena: ESPN -> TheSportsDB -> caché local. La fuente que tenga suficientes
    datos gana; el resultado elegido se cachea para futuros respaldos.
    """
    # 1) ESPN (primaria)
    try:
        espn = espn_data.obtener_resultados(meses)
    except Exception:
        espn = []
    if len(espn) >= minimo:
        guardar_cache(espn)
        return {"fuente": "ESPN", "resultados": espn, "total": len(espn)}

    # 2) TheSportsDB (respaldo)
    try:
        tsdb = obtener_resultados_thesportsdb()
    except Exception:
        tsdb = []
    # Combinar ESPN parcial + TheSportsDB (dedup por equipos+fecha).
    combinado = _combinar(espn, tsdb)
    if combinado:
        guardar_cache(combinado)
        fuente = "ESPN+TheSportsDB" if espn else "TheSportsDB"
        return {"fuente": fuente, "resultados": combinado, "total": len(combinado)}

    # 3) Caché local (último recurso)
    cache = leer_cache()
    return {"fuente": "cache", "resultados": cache, "total": len(cache)}


def _combinar(a: List[Dict[str, Any]], b: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    vistos = set()
    out: List[Dict[str, Any]] = []
    for fuente in (a, b):
        for r in fuente:
            clave = (str(r.get("home_team")).lower(), str(r.get("away_team")).lower(), str(r.get("fecha")))
            if clave in vistos:
                continue
            vistos.add(clave)
            out.append(r)
    return out


if __name__ == "__main__":
    res = obtener_resultados()
    print(f"Fuente usada: {res['fuente']} | resultados: {res['total']}")
