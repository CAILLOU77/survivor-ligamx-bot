#!/usr/bin/env python3
"""
routers/predicciones.py — Endpoints de predicciones REALES (ESPN + Poisson).

Expone en la web las predicciones legítimas basadas en datos reales de ESPN
(vía el motor), en lugar de los momios inventados. Read-only, con caché en
memoria (TTL) para no golpear ESPN en cada request.

- GET /predicciones  -> 1X2 / Over-Under / BTTS / marcador por partido próximo.
- GET /survivor      -> mejor equipo "no perder" de la jornada (excluye usados).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict

from fastapi import APIRouter

try:
    import motor_pronosticos as motor
except ImportError:  # pragma: no cover - contexto de paquete (web)
    from src import motor_pronosticos as motor  # type: ignore

try:
    import tabla_posiciones as tabla_mod
except ImportError:  # pragma: no cover
    from src import tabla_posiciones as tabla_mod  # type: ignore

try:
    import comparador_mercado as mercado_mod
except ImportError:  # pragma: no cover
    from src import comparador_mercado as mercado_mod  # type: ignore

try:
    import fuentes_datos as fuentes_mod
except ImportError:  # pragma: no cover
    from src import fuentes_datos as fuentes_mod  # type: ignore

try:
    import analisis_riesgo as riesgo_mod
except ImportError:  # pragma: no cover
    from src import analisis_riesgo as riesgo_mod  # type: ignore

try:
    import planificador_survivor as plan_mod
except ImportError:  # pragma: no cover
    from src import planificador_survivor as plan_mod  # type: ignore

try:
    import poisson_model as pm
except ImportError:  # pragma: no cover
    from src import poisson_model as pm  # type: ignore

try:
    import ligamx_api as lmx
except ImportError:  # pragma: no cover
    from src import ligamx_api as lmx  # type: ignore

router = APIRouter(tags=["Predicciones"])

_CACHE: Dict[str, Any] = {"data": None, "ts": None}
_CACHE_TABLA: Dict[str, Any] = {"data": None, "ts": None}
_CACHE_RIESGO: Dict[str, Any] = {"data": None, "ts": None}
_CACHE_PLAN: Dict[str, Any] = {"data": None, "ts": None}
_TTL_MIN = 30
_TTL_RIESGO_MIN = 360  # el histórico cambia lento; análisis pesado => caché larga


def _fresco() -> bool:
    return bool(_CACHE["data"]) and bool(_CACHE["ts"]) and (
        datetime.utcnow() - _CACHE["ts"] < timedelta(minutes=_TTL_MIN)
    )


def _obtener() -> Dict[str, Any]:
    if not _fresco():
        _CACHE["data"] = motor.generar_pronosticos()
        _CACHE["ts"] = datetime.utcnow()
    return _CACHE["data"]


def _obtener_tabla() -> Dict[str, Any]:
    fresco = bool(_CACHE_TABLA["data"]) and bool(_CACHE_TABLA["ts"]) and (
        datetime.utcnow() - _CACHE_TABLA["ts"] < timedelta(minutes=_TTL_MIN)
    )
    if not fresco:
        _CACHE_TABLA["data"] = tabla_mod.obtener_tabla()
        _CACHE_TABLA["ts"] = datetime.utcnow()
    return _CACHE_TABLA["data"]


def _contexto_pick(pick: Dict[str, Any]) -> Dict[str, Any]:
    """
    Dossier compacto de la Liga MX API para un pick de Survivor. Deriva
    local/visitante desde `condicion` y consulta `ligamx_api.resumen_partido`.
    Tolerante: ante cualquier fallo devuelve {} (no rompe /jornada).
    """
    try:
        equipo = pick.get("equipo", "")
        rival = pick.get("rival", "")
        if pick.get("condicion") == "Local":
            home, away = equipo, rival
        else:
            home, away = rival, equipo
        return lmx.resumen_partido(home, away)
    except Exception:  # pragma: no cover - fallback defensivo de red
        return {}


def _usados_combinados(excluir: str) -> list:
    """
    Combina los equipos usados PERSISTIDOS (BD) con los que lleguen en el
    parámetro `excluir`. Así el pick/plan excluye automáticamente lo ya gastado,
    aunque no se pase nada. Tolerante: si la BD falla, usa solo el parámetro.
    """
    manual = [e.strip() for e in (excluir or "").split(",") if e.strip()]
    persistidos: list = []
    try:
        from src.database import get_equipos_usados
        persistidos = get_equipos_usados()
    except Exception:  # pragma: no cover - BD no disponible
        persistidos = []
    # Dedup preservando orden (persistidos primero).
    vistos, out = set(), []
    for e in persistidos + manual:
        k = e.strip().lower()
        if k and k not in vistos:
            vistos.add(k)
            out.append(e.strip())
    return out


@router.get("/predicciones", summary="Predicciones reales (ESPN + Poisson)")
def predicciones() -> Dict[str, Any]:
    """1X2 / Over-Under / BTTS / marcador por cada partido próximo."""
    return _obtener()


@router.get("/survivor", summary="Mejor pick de Survivor (no perder)")
def survivor(excluir: str = "") -> Dict[str, Any]:
    """
    Mejor equipo para Survivor (mayor prob. de no perder). `excluir`: equipos
    ya usados, separados por coma (ej. ?excluir=America,Toluca).
    """
    data = _obtener()
    usados = _usados_combinados(excluir)
    pick = motor.mejor_pick_survivor(data.get("pronosticos", []), usados)
    return {
        "generado_utc": data.get("generado_utc"),
        "fuente_datos": data.get("fuente_datos"),
        "equipos_excluidos": usados,
        "pick_survivor": pick,
        "decision": data.get("decision"),
    }


@router.get("/jornada", summary="Vista de jornada: predicciones + pick + top-3 + motivación + momios")
def jornada(excluir: str = "", contexto: bool = False) -> Dict[str, Any]:
    """
    Todo-en-uno para decidir la semana: predicciones, mejor pick de Survivor +
    top-3, motivación de la tabla y comparación vs mercado (si hay momios).

    `contexto=true` adjunta al pick #1 un dossier de la Liga MX API (predicción,
    forma, tarjetas/jugadores en riesgo, h2h). Es una llamada extra a la API
    externa (puede tardar si está dormida); por eso está apagado por defecto.
    """
    data = _obtener()
    pronos = data.get("pronosticos", [])
    comp = mercado_mod.comparar_pronosticos(pronos)  # momios gated (no-op sin key)
    pronos = comp.get("pronosticos", pronos)
    try:
        motivacion = motor.motivacion_por_equipo()
    except Exception:  # pragma: no cover - fallback defensivo de red
        motivacion = {}
    usados = _usados_combinados(excluir)
    top = motor.mejores_picks_survivor(pronos, usados, motivacion, n=3)
    pick = top[0] if top else None
    if contexto and pick:
        pick = {**pick, "contexto_api": _contexto_pick(pick)}
    return {
        "generado_utc": data.get("generado_utc"),
        "fuente_datos": data.get("fuente_datos"),
        "equipos_excluidos": usados,
        "pick_survivor": pick,
        "top_picks": top,
        "mercado_habilitado": comp.get("mercado_habilitado", False),
        "partidos_con_momios": comp.get("partidos_con_momios", 0),
        "pronosticos": pronos,
        "decision": data.get("decision"),
    }


@router.get("/tabla", summary="Tabla Liga MX (ESPN) + motivación por equipo")
def tabla() -> Dict[str, Any]:
    """Tabla general con zona de clasificación y motivación por equipo."""
    try:
        data = _obtener_tabla()
    except Exception as exc:  # pragma: no cover - fallback defensivo de red
        return {"torneo": "", "tabla": [], "error": str(exc),
                "decision": "INFORMATIVO / REVISIÓN HUMANA"}
    return {**data, "decision": "INFORMATIVO / REVISIÓN HUMANA"}


@router.get("/valor", summary="Predicciones + comparación vs mercado (opcional)")
def valor() -> Dict[str, Any]:
    """
    Predicciones del modelo anotadas con comparación vs mercado (dónde el modelo
    ve 'valor'). SOLO activa si hay key de momios configurada (ODDS_API_IO_KEY);
    si no, devuelve las predicciones sin comparación (mercado_habilitado=False).
    Informativo: el modelo es la fuente de verdad; no es consejo de apuesta.
    """
    data = _obtener()
    comp = mercado_mod.comparar_pronosticos(data.get("pronosticos", []))
    return {
        "generado_utc": data.get("generado_utc"),
        "fuente_datos": data.get("fuente_datos"),
        **comp,
    }


@router.get("/valor/diagnostico", summary="Diagnóstico de la conexión a momios (debug)")
def valor_diagnostico() -> Dict[str, Any]:
    """Muestra qué devuelve odds-api.io (eventos/casas/mercados) sin exponer la key."""
    return mercado_mod.diagnostico_mercado()


@router.get("/health/fuentes", summary="Salud de las fuentes de datos (ESPN/TheSportsDB/odds)")
def health_fuentes() -> Dict[str, Any]:
    """Ping a cada fuente para detectar caídas antes de la jornada."""
    return fuentes_mod.estado_fuentes()


@router.get("/analisis/riesgo", summary="¿Cuándo falla el favorito? (análisis de upsets, datos reales)")
def analisis_riesgo() -> Dict[str, Any]:
    """
    Mide, sobre el histórico real (walk-forward), cuándo y por qué falla el
    favorito del modelo: por condición (local vs visitante), nivel de confianza
    y partidos cerrados ('under'). Útil para no quemar el Survivor con un
    favorito engañoso. Análisis pesado => caché de 6 horas.
    """
    fresco = bool(_CACHE_RIESGO["data"]) and bool(_CACHE_RIESGO["ts"]) and (
        datetime.utcnow() - _CACHE_RIESGO["ts"] < timedelta(minutes=_TTL_RIESGO_MIN)
    )
    if not fresco:
        try:
            datos = fuentes_mod.obtener_resultados(meses=18)
            _CACHE_RIESGO["data"] = riesgo_mod.analizar_riesgo_favoritos(datos["resultados"])
            _CACHE_RIESGO["data"]["fuente_datos"] = datos.get("fuente")
        except Exception as exc:  # pragma: no cover - fallback defensivo de red
            return {"partidos_evaluados": 0, "error": str(exc),
                    "decision": "INFORMATIVO / REVISIÓN HUMANA"}
        _CACHE_RIESGO["ts"] = datetime.utcnow()
    return _CACHE_RIESGO["data"]


@router.get("/plan-survivor", summary="Estrategia de temporada: qué equipo usar en cada jornada")
def plan_survivor(excluir: str = "", peso_victoria: float = 0.5, usar_momios: bool = True) -> Dict[str, Any]:
    """
    Plan ÓPTIMO de Survivor para toda la temporada (PlayDoit): asigna 1 equipo por
    jornada, sin repetir, maximizando supervivencia (no perder) y victorias.

    Requiere `data/calendario.json` con el calendario completo de las 17 jornadas
    (se publica cerca del arranque). Sin él, responde `calendario_incompleto`.
    `excluir`: equipos ya gastados (coma). `peso_victoria`: 0 = solo sobrevivir.
    `usar_momios`: mezcla momios reales (odds-api.io) si hay key y cobertura.
    Análisis pesado => caché de 6 horas (con filtros por defecto).
    """
    usados = _usados_combinados(excluir)
    usar_cache = not usados and abs(peso_victoria - 0.5) < 1e-9 and usar_momios
    if usar_cache:
        fresco = bool(_CACHE_PLAN["data"]) and bool(_CACHE_PLAN["ts"]) and (
            datetime.utcnow() - _CACHE_PLAN["ts"] < timedelta(minutes=_TTL_RIESGO_MIN)
        )
        if fresco:
            return _CACHE_PLAN["data"]

    calendario = plan_mod.cargar_calendario()
    if not calendario:
        return {
            "plan": [], "calendario_incompleto": True,
            "mensaje": "Falta data/calendario.json con las 17 jornadas. El calendario "
                       "del Apertura 2026 se publica cerca del 17-jul; guárdalo y reintenta.",
            "decision": "INFORMATIVO / REVISIÓN HUMANA",
        }
    try:
        datos = fuentes_mod.obtener_resultados(meses=18)
        fuerzas = pm.calcular_fuerzas(datos["resultados"])
        odds = plan_mod.construir_odds_por_partido(calendario) if usar_momios else None
        resultado = plan_mod.planificar(calendario, fuerzas, equipos_usados=usados,
                                        peso_victoria=peso_victoria, odds_por_partido=odds)
        resultado["fuente_datos"] = datos.get("fuente")
        resultado["momios_integrados"] = len(odds) if odds else 0
    except Exception as exc:  # pragma: no cover - fallback defensivo
        return {"plan": [], "error": str(exc),
                "decision": "INFORMATIVO / REVISIÓN HUMANA"}
    if usar_cache:
        _CACHE_PLAN["data"] = resultado
        _CACHE_PLAN["ts"] = datetime.utcnow()
    return resultado


@router.get("/analisis-partido", summary="Dossier de un partido (Liga MX API): predicción + forma + tarjetas + h2h")
def analisis_partido(home: str, away: str, prediccion: bool = True) -> Dict[str, Any]:
    """
    Dossier enriquecido de un partido usando la Liga MX API (proyecto hermano):
    predictor de la API, forma reciente, disciplina/tarjetas (jugadores en riesgo
    de suspensión), rachas y resumen head-to-head. Por NOMBRE de equipo
    (ej. ?home=America&away=Toluca).

    Tolerante: cada señal que la API aún no tenga (pretemporada) llega en null.
    Informativo; el modelo local (ESPN + Poisson) sigue siendo la fuente de verdad
    del pick.
    """
    if not home or not away:
        return {"error": "Faltan parámetros 'home' y 'away'.",
                "decision": "INFORMATIVO / REVISIÓN HUMANA"}
    try:
        return lmx.analisis_partido(home, away, incluir_prediccion=prediccion)
    except Exception as exc:  # pragma: no cover - fallback defensivo de red
        return {"home": home, "away": away, "error": str(exc),
                "decision": "INFORMATIVO / REVISIÓN HUMANA"}


@router.get("/jugadores-riesgo", summary="Jugadores en riesgo de suspensión (Liga MX API)")
def jugadores_riesgo(limit: int = 20) -> Dict[str, Any]:
    """
    Jugadores de toda la liga en riesgo de suspensión por acumulación de tarjetas
    (vía Liga MX API /players/discipline). Contexto de riesgo para el pick.
    En pretemporada viene vacío. Informativo.
    """
    try:
        return {**lmx.jugadores_en_riesgo_liga(limit=limit),
                "decision": "INFORMATIVO / REVISIÓN HUMANA"}
    except Exception as exc:  # pragma: no cover - fallback defensivo de red
        return {"count": 0, "jugadores": [], "error": str(exc),
                "decision": "INFORMATIVO / REVISIÓN HUMANA"}


@router.get("/noticias", summary="Noticias Liga MX (fichajes/lesiones/bajas) vía Liga MX API")
def noticias(limit: int = 10) -> Dict[str, Any]:
    """
    Noticias recientes de Liga MX (365Scores + Google News) tomadas de la Liga MX
    API: fichajes, lesiones, bajas y boletines. Compacto (título, fuente, fecha,
    link). Informativo; útil como contexto de riesgo para el pick.
    """
    try:
        items = lmx.noticias_recientes(limit=limit)
        return {"total": len(items), "noticias": items,
                "decision": "INFORMATIVO / REVISIÓN HUMANA"}
    except Exception as exc:  # pragma: no cover - fallback defensivo de red
        return {"total": 0, "noticias": [], "error": str(exc),
                "decision": "INFORMATIVO / REVISIÓN HUMANA"}
