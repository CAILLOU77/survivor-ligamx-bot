#!/usr/bin/env python3
"""
routers/api_ligamx.py — API pública unificada de Liga MX (gratis, sin key).

Consolida en un solo namespace REST (`/api/v1/...`) todo lo que el proyecto ya
recolecta de fuentes públicas GRATUITAS y normaliza:

  - ESPN (gratis, sin key)            -> resultados reales y tabla
  - TheSportsDB (respaldo gratis)     -> redundancia (vía fuentes_datos)
  - data/calendario.json (nuestro)    -> calendario oficial del torneo
  - modelo Poisson/Dixon-Coles        -> predicciones y fuerzas por equipo

Todo es READ-ONLY, cacheado en memoria, sin API key y SIN inventar datos
(REGLA MÁXIMA). Cada respuesta lleva la etiqueta INFORMATIVO / REVISIÓN HUMANA.

⚠️ NO CONFUNDIR con `src/ligamx_api.py`: aquel es un CLIENTE que CONSUME la API
externa hermana (`ligamx-api.onrender.com`). Este módulo hace lo contrario:
EXPONE una API pública propia (`/api/v1`) con los datos de ESTE bot.

Endpoints:
  GET /api/v1                              -> índice/catálogo
  GET /api/v1/equipos                      -> equipos del torneo (+ tiene_modelo)
  GET /api/v1/equipos/{equipo}             -> ficha de un equipo
  GET /api/v1/equipos/{equipo}/calendario  -> todos los partidos del equipo
  GET /api/v1/calendario                   -> calendario completo (17 jornadas)
  GET /api/v1/calendario/{jornada}         -> una jornada (?predicciones=true)
  GET /api/v1/resultados?meses=2           -> resultados reales recientes (ESPN)
  GET /api/v1/tabla                        -> tabla general + motivación
  GET /api/v1/predicciones                 -> predicciones de la jornada próxima
  GET /api/v1/h2h?local=&visitante=        -> head-to-head histórico + modelo
"""
from __future__ import annotations

import unicodedata
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query

try:
    import poisson_model as pm
except ImportError:  # pragma: no cover
    from src import poisson_model as pm  # type: ignore

try:
    import fuentes_datos as fuentes_mod
except ImportError:  # pragma: no cover
    from src import fuentes_datos as fuentes_mod  # type: ignore

try:
    import planificador_survivor as plan_mod
except ImportError:  # pragma: no cover
    from src import planificador_survivor as plan_mod  # type: ignore

router = APIRouter(prefix="/api/v1", tags=["API Liga MX"])

DEC = "INFORMATIVO / REVISIÓN HUMANA"
_TTL_MIN = 30
_MESES_HISTORICO = 18

# Caché en memoria (resultados + fuerzas son lo más pesado de calcular).
_CACHE: Dict[str, Any] = {"datos": None, "fuerzas": None, "ts": None}


# ---------------------------------------------------------------------------
# Helpers de datos (con caché)
# ---------------------------------------------------------------------------
def _fresco(ts: Optional[datetime], ttl_min: int = _TTL_MIN) -> bool:
    return bool(ts) and (datetime.utcnow() - ts < timedelta(minutes=ttl_min))


def _datos_y_fuerzas() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Resultados históricos (ESPN) + fuerzas del modelo, cacheados."""
    if not (_CACHE["fuerzas"] and _fresco(_CACHE["ts"])):
        datos = fuentes_mod.obtener_resultados(meses=_MESES_HISTORICO)
        try:
            fuerzas = pm.calcular_fuerzas(datos.get("resultados", []))
        except ValueError:
            fuerzas = {"avg_home": 0.0, "avg_away": 0.0, "equipos": {}}
        _CACHE["datos"] = datos
        _CACHE["fuerzas"] = fuerzas
        _CACHE["ts"] = datetime.utcnow()
    return _CACHE["datos"], _CACHE["fuerzas"]


def _calendario() -> List[Dict[str, Any]]:
    return plan_mod.cargar_calendario()


# Resolución de nombres tolerante (ignora acentos + alias comunes). SOLO para
# encontrar el nombre canónico; el modelo sigue usando pm._norm exacto.
_ALIASES = {
    "chivas": "guadalajara",
    "club america": "america",
    "aguilas": "america",
    "pumas": "pumas unam",
    "unam": "pumas unam",
    "tigres": "tigres uanl",
    "uanl": "tigres uanl",
    "san luis": "atletico de san luis",
    "atletico san luis": "atletico de san luis",
    "asl": "atletico de san luis",
    "juarez": "fc juarez",
    "santos laguna": "santos",
    "xolos": "tijuana",
    "club tijuana": "tijuana",
    "rayados": "monterrey",
    "mazatlan": "mazatlan fc",
    "la maquina": "cruz azul",
}


def _slug(s: Any) -> str:
    """Minúsculas + sin acentos + espacios colapsados (solo para búsqueda)."""
    t = unicodedata.normalize("NFKD", str(s or ""))
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return " ".join(t.lower().split())


def _equipos_del_torneo(calendario: List[Dict[str, Any]]) -> List[str]:
    """Nombres (display) de los equipos que aparecen en el calendario oficial."""
    vistos: Dict[str, str] = {}  # norm -> display
    for j in calendario:
        for p in j.get("partidos", []):
            for t in (p.get("home_team", ""), p.get("away_team", "")):
                if t:
                    vistos.setdefault(pm._norm(t), t)
    return sorted(vistos.values(), key=lambda s: s.lower())


def _mapa_slug_a_display(
    calendario: List[Dict[str, Any]], fuerzas: Dict[str, Any], datos: Optional[Dict[str, Any]] = None
) -> Dict[str, str]:
    """Resuelve cualquier nombre (slug) a un display name conocido."""
    mapa: Dict[str, str] = {}
    for j in calendario:
        for p in j.get("partidos", []):
            for t in (p.get("home_team", ""), p.get("away_team", "")):
                if t:
                    mapa.setdefault(_slug(t), t)
    if datos:
        for r in datos.get("resultados", []):
            for t in (r.get("home_team", ""), r.get("away_team", "")):
                if t:
                    mapa.setdefault(_slug(t), t)
    for norm in fuerzas.get("equipos", {}):
        mapa.setdefault(_slug(norm), norm)
    return mapa


def _resolver_equipo(
    q: str, calendario: List[Dict[str, Any]], fuerzas: Dict[str, Any], datos: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    mapa = _mapa_slug_a_display(calendario, fuerzas, datos)
    s = _slug(q)
    s = _ALIASES.get(s, s)
    return mapa.get(s)


def _tiene_modelo(equipo: str, fuerzas: Dict[str, Any]) -> bool:
    return pm._norm(equipo) in fuerzas.get("equipos", {})


def _prediccion_partido(home: str, away: str, fuerzas: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Pronóstico del modelo si AMBOS equipos tienen histórico; si no, None."""
    if not (_tiene_modelo(home, fuerzas) and _tiene_modelo(away, fuerzas)):
        return None
    pr = pm.pronostico(home, away, fuerzas)
    return {
        "prob_local_pct": pr["prob_local_pct"],
        "prob_empate_pct": pr["prob_empate_pct"],
        "prob_visitante_pct": pr["prob_visitante_pct"],
        "marcador_mas_probable": pr["marcador_mas_probable"],
        "pick_1x2": pr["pick_1x2"],
        "prob_over_pct": pr["prob_over_pct"],
        "prob_under_pct": pr["prob_under_pct"],
        "prob_btts_si_pct": pr["prob_btts_si_pct"],
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("", summary="Índice de la API pública de Liga MX")
def indice() -> Dict[str, Any]:
    return {
        "nombre": "API Liga MX (Apertura 2026) — gratis, sin key",
        "fuentes": ["ESPN (gratis)", "TheSportsDB (respaldo)", "calendario oficial", "modelo Poisson/Dixon-Coles"],
        "endpoints": {
            "/api/v1/equipos": "Equipos del torneo (+ si tienen modelo)",
            "/api/v1/equipos/{equipo}": "Ficha de un equipo (fuerzas + calendario)",
            "/api/v1/equipos/{equipo}/calendario": "Todos los partidos del equipo",
            "/api/v1/calendario": "Calendario completo (17 jornadas)",
            "/api/v1/calendario/{jornada}": "Una jornada (?predicciones=true)",
            "/api/v1/jornada-actual": "Jornada actual/próxima según la fecha (?fecha=&predicciones=)",
            "/api/v1/resultados?meses=2": "Resultados reales recientes (ESPN)",
            "/api/v1/tabla": "Tabla general + motivación por equipo",
            "/api/v1/predicciones": "Predicciones de la jornada próxima",
            "/api/v1/h2h?local=&visitante=": "Head-to-head histórico + modelo",
        },
        "decision": DEC,
    }


@router.get("/equipos", summary="Equipos del torneo")
def equipos() -> Dict[str, Any]:
    calendario = _calendario()
    _, fuerzas = _datos_y_fuerzas()
    lista = _equipos_del_torneo(calendario)
    out = [{"equipo": e, "tiene_modelo": _tiene_modelo(e, fuerzas)} for e in lista]
    return {
        "total": len(out),
        "equipos": out,
        "nota": "tiene_modelo=false => sin histórico aún (p.ej. Atlante, recién ascendido); "
                "el modelo lo omite hasta acumular partidos reales.",
        "calendario_disponible": bool(calendario),
        "decision": DEC,
    }


@router.get("/equipos/{equipo}", summary="Ficha de un equipo")
def equipo_detalle(equipo: str) -> Dict[str, Any]:
    calendario = _calendario()
    datos, fuerzas = _datos_y_fuerzas()
    nombre = _resolver_equipo(equipo, calendario, fuerzas, datos)
    if not nombre:
        raise HTTPException(status_code=404, detail=f"Equipo no encontrado: {equipo}")

    norm = pm._norm(nombre)
    factores = fuerzas.get("equipos", {}).get(norm)
    fuerza = None
    if factores:
        fuerza = {k: round(v, 3) for k, v in factores.items()}

    partidos = _partidos_de_equipo(nombre, calendario, fuerzas)
    return {
        "equipo": nombre,
        "tiene_modelo": bool(factores),
        "fuerza_modelo": fuerza,
        "partidos_calendario": len(partidos),
        "calendario": partidos,
        "decision": DEC,
    }


def _partidos_de_equipo(nombre: str, calendario: List[Dict[str, Any]], fuerzas: Dict[str, Any]) -> List[Dict[str, Any]]:
    norm = pm._norm(nombre)
    salida: List[Dict[str, Any]] = []
    for j in sorted(calendario, key=lambda x: int(x.get("jornada", 0))):
        jnum = int(j.get("jornada", 0))
        for p in j.get("partidos", []):
            home, away = p.get("home_team", ""), p.get("away_team", "")
            if pm._norm(home) == norm or pm._norm(away) == norm:
                es_local = pm._norm(home) == norm
                rival = away if es_local else home
                pred = _prediccion_partido(home, away, fuerzas)
                item = {
                    "jornada": jnum,
                    "fecha_inicio": j.get("fecha_inicio"),
                    "fecha_fin": j.get("fecha_fin"),
                    "condicion": "Local" if es_local else "Visitante",
                    "rival": rival,
                }
                if pred:
                    item["prob_ganar_pct"] = pred["prob_local_pct"] if es_local else pred["prob_visitante_pct"]
                    item["prob_empate_pct"] = pred["prob_empate_pct"]
                salida.append(item)
                break
    return salida


def _calcular_jornada_actual(calendario: List[Dict[str, Any]], hoy: date) -> Dict[str, Any]:
    """Determina, para una fecha dada, el estado del torneo y la jornada objetivo.

    estado: pretemporada | en_curso | entre_jornadas | temporada_terminada | sin_fechas
    jornada_objetivo = la jornada para la que conviene hacer el pick (la que está
    en curso, o si no, la próxima).
    """
    js: List[Dict[str, Any]] = []
    for j in sorted(calendario, key=lambda x: int(x.get("jornada", 0))):
        ini, fin = j.get("fecha_inicio"), j.get("fecha_fin")
        if not ini or not fin:
            continue
        try:
            js.append({"jornada": int(j.get("jornada", 0)),
                       "ini": date.fromisoformat(ini), "fin": date.fromisoformat(fin), "raw": j})
        except ValueError:
            continue
    if not js:
        return {"estado": "sin_fechas", "jornada_actual": None, "jornada_proxima": None,
                "jornada_objetivo": None, "ultima_jugada": None, "dias_para_proxima": None}

    actual = next((x for x in js if x["ini"] <= hoy <= x["fin"]), None)
    proxima = next((x for x in js if x["ini"] > hoy), None)
    ultima = None
    for x in js:
        if x["fin"] < hoy:
            ultima = x

    if actual:
        estado = "en_curso"
        objetivo = actual
    elif hoy < js[0]["ini"]:
        estado = "pretemporada"
        objetivo = js[0]
    elif proxima is None:
        estado = "temporada_terminada"
        objetivo = None
    else:
        estado = "entre_jornadas"
        objetivo = proxima

    dias = (proxima["ini"] - hoy).days if proxima else None
    return {
        "estado": estado,
        "jornada_actual": actual["jornada"] if actual else None,
        "jornada_proxima": proxima["jornada"] if proxima else None,
        "ultima_jugada": ultima["jornada"] if ultima else None,
        "jornada_objetivo": objetivo,  # dict con 'raw' o None
        "dias_para_proxima": dias,
    }


@router.get("/equipos/{equipo}/calendario", summary="Calendario de un equipo")
def equipo_calendario(equipo: str) -> Dict[str, Any]:
    calendario = _calendario()
    datos, fuerzas = _datos_y_fuerzas()
    nombre = _resolver_equipo(equipo, calendario, fuerzas, datos)
    if not nombre:
        raise HTTPException(status_code=404, detail=f"Equipo no encontrado: {equipo}")
    partidos = _partidos_de_equipo(nombre, calendario, fuerzas)
    return {"equipo": nombre, "total": len(partidos), "calendario": partidos, "decision": DEC}


@router.get("/calendario", summary="Calendario completo del torneo")
def calendario_completo() -> Dict[str, Any]:
    calendario = _calendario()
    if not calendario:
        return {"jornadas": [], "calendario_disponible": False,
                "mensaje": "Falta data/calendario.json.", "decision": DEC}
    return {
        "torneo": "Apertura 2026",
        "jornadas_total": len(calendario),
        "jornadas": sorted(calendario, key=lambda x: int(x.get("jornada", 0))),
        "decision": DEC,
    }


@router.get("/calendario/{jornada}", summary="Una jornada del calendario")
def calendario_jornada(jornada: int, predicciones: bool = Query(False)) -> Dict[str, Any]:
    calendario = _calendario()
    objetivo = next((j for j in calendario if int(j.get("jornada", 0)) == jornada), None)
    if objetivo is None:
        raise HTTPException(status_code=404, detail=f"Jornada {jornada} no encontrada")
    _, fuerzas = _datos_y_fuerzas()
    partidos: List[Dict[str, Any]] = []
    for p in objetivo.get("partidos", []):
        home, away = p.get("home_team", ""), p.get("away_team", "")
        item: Dict[str, Any] = {"home_team": home, "away_team": away}
        if predicciones:
            pred = _prediccion_partido(home, away, fuerzas)
            item["prediccion"] = pred  # None si algún equipo no tiene modelo
        partidos.append(item)
    return {"jornada": jornada, "partidos": partidos,
            "predicciones_incluidas": predicciones, "decision": DEC}


@router.get("/resultados", summary="Resultados reales recientes (ESPN)")
def resultados(meses: int = Query(2, ge=1, le=24)) -> Dict[str, Any]:
    datos = fuentes_mod.obtener_resultados(meses=meses)
    res = datos.get("resultados", [])
    return {
        "fuente": datos.get("fuente"),
        "meses": meses,
        "total": len(res),
        "resultados": res,
        "decision": DEC,
    }


@router.get("/tabla", summary="Tabla general + motivación")
def tabla() -> Dict[str, Any]:
    try:
        from src.routers.predicciones import _obtener_tabla
        data = _obtener_tabla()
    except Exception as exc:  # pragma: no cover - fallback defensivo de red
        return {"tabla": [], "error": str(exc), "decision": DEC}
    return {**data, "decision": DEC}


@router.get("/predicciones", summary="Predicciones de la jornada próxima")
def predicciones_jornada() -> Dict[str, Any]:
    try:
        from src.routers.predicciones import _obtener
        return _obtener()
    except Exception as exc:  # pragma: no cover - fallback defensivo de red
        return {"pronosticos": [], "error": str(exc), "decision": DEC}


@router.get("/h2h", summary="Head-to-head histórico + predicción del modelo")
def head_to_head(
    local: str = Query(..., description="Equipo local"),
    visitante: str = Query(..., description="Equipo visitante"),
) -> Dict[str, Any]:
    calendario = _calendario()
    datos, fuerzas = _datos_y_fuerzas()
    nl = _resolver_equipo(local, calendario, fuerzas, datos)
    nv = _resolver_equipo(visitante, calendario, fuerzas, datos)
    if not nl or not nv:
        faltan = [q for q, r in ((local, nl), (visitante, nv)) if not r]
        raise HTTPException(status_code=404, detail=f"Equipo(s) no encontrado(s): {faltan}")
    if pm._norm(nl) == pm._norm(nv):
        raise HTTPException(status_code=400, detail="local y visitante no pueden ser el mismo equipo")

    norm_l, norm_v = pm._norm(nl), pm._norm(nv)
    enfrentamientos: List[Dict[str, Any]] = []
    g_l = g_v = empates = 0  # victorias contadas desde la perspectiva de `local`
    for r in datos.get("resultados", []):
        h, a = pm._norm(r.get("home_team", "")), pm._norm(r.get("away_team", ""))
        if {h, a} != {norm_l, norm_v}:
            continue
        try:
            hg, ag = int(r.get("home_goals")), int(r.get("away_goals"))
        except (TypeError, ValueError):
            continue
        enfrentamientos.append({
            "fecha": r.get("fecha"),
            "home_team": r.get("home_team"), "away_team": r.get("away_team"),
            "marcador": f"{hg}-{ag}",
        })
        # ganador real -> perspectiva de `local` (nl)
        if hg == ag:
            empates += 1
        else:
            ganador = h if hg > ag else a
            if ganador == norm_l:
                g_l += 1
            else:
                g_v += 1

    pred = _prediccion_partido(nl, nv, fuerzas)
    return {
        "local": nl,
        "visitante": nv,
        "historico": {
            "partidos": len(enfrentamientos),
            f"victorias_{nl}": g_l,
            f"victorias_{nv}": g_v,
            "empates": empates,
            "detalle": sorted(enfrentamientos, key=lambda x: str(x.get("fecha") or ""), reverse=True),
        },
        "prediccion_modelo": pred,  # None si algún equipo no tiene histórico
        "fuente_datos": datos.get("fuente"),
        "decision": DEC,
    }



@router.get("/jornada-actual", summary="Jornada actual/próxima según la fecha")
def jornada_actual(
    fecha: Optional[str] = Query(None, description="Fecha hipotética YYYY-MM-DD (default: hoy)"),
    predicciones: bool = Query(False),
) -> Dict[str, Any]:
    calendario = _calendario()
    if fecha:
        try:
            hoy = date.fromisoformat(fecha)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Fecha inválida: {fecha}") from exc
    else:
        hoy = datetime.utcnow().date()

    info = _calcular_jornada_actual(calendario, hoy)
    objetivo = info.pop("jornada_objetivo", None)

    salida: Dict[str, Any] = {
        "fecha_consulta": hoy.isoformat(),
        "torneo": "Apertura 2026",
        **info,
        "decision": DEC,
    }

    if objetivo is not None:
        raw = objetivo["raw"]
        _, fuerzas = _datos_y_fuerzas()
        partidos: List[Dict[str, Any]] = []
        for p in raw.get("partidos", []):
            home, away = p.get("home_team", ""), p.get("away_team", "")
            item: Dict[str, Any] = {"home_team": home, "away_team": away}
            if predicciones:
                item["prediccion"] = _prediccion_partido(home, away, fuerzas)
            partidos.append(item)
        salida["jornada_objetivo"] = {
            "jornada": objetivo["jornada"],
            "fecha_inicio": objetivo["ini"].isoformat(),
            "fecha_fin": objetivo["fin"].isoformat(),
            "partidos": partidos,
        }
    else:
        salida["jornada_objetivo"] = None

    return salida
