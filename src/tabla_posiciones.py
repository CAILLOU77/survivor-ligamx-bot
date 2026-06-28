#!/usr/bin/env python3
"""
tabla_posiciones.py — Tabla de Liga MX (ESPN) + MOTIVACIÓN por equipo.

Baja la tabla general desde la API pública de ESPN (sin key, sin scraping) y
deriva, para cada equipo, su situación de clasificación y un nivel de
"motivación" deportiva, usando las reglas vigentes de src/reglas_liga_mx.py:

- zona: 'directo' (top 6) / 'play_in' (7–10) / 'fuera'.
- jornadas_restantes y máximo de puntos alcanzable.
- vivo_para_liguilla: si todavía puede llegar a la postemporada.
- liguilla_asegurada: si ya nadie de abajo lo puede sacar (aprox. conservadora).
- motivacion_nivel: 'alta' / 'media' / 'baja' (o 'n/a' si no ha iniciado).

Esto da contexto para Survivor (un equipo que pelea liguilla suele venir más
motivado que uno ya eliminado o ya clasificado holgado). Informativo; no cierra
ni envía picks.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

try:
    import reglas_liga_mx as rl
except ImportError:  # pragma: no cover
    from src import reglas_liga_mx as rl  # type: ignore

LIGA_CODE = "mex.1"
STANDINGS_URL = f"https://site.api.espn.com/apis/v2/sports/soccer/{LIGA_CODE}/standings"

# Fase regular de Liga MX: 17 jornadas (cada equipo juega 17 partidos).
JORNADAS_FASE_REGULAR = 17


def _stat(entry: Dict[str, Any], nombre: str) -> float:
    """Lee un stat numérico por 'name' dentro de la entrada de ESPN."""
    for s in entry.get("stats", []) or []:
        if isinstance(s, dict) and s.get("name") == nombre:
            try:
                return float(s.get("value"))
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def parsear_standings(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convierte la respuesta de ESPN en una tabla limpia. Función pura (sin red).

    Devuelve {'torneo': str, 'tabla': [ {posicion, equipo, puntos, jugados,
    ganados, empatados, perdidos, goles_favor, goles_contra, diferencia} ]}
    ordenada por posición.
    """
    children = data.get("children") or []
    if not children:
        return {"torneo": "", "tabla": []}
    ch = children[0]
    torneo = ch.get("name", "")
    entries = (ch.get("standings") or {}).get("entries", []) or []

    tabla: List[Dict[str, Any]] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        equipo = (e.get("team") or {}).get("displayName", "")
        if not equipo:
            continue
        tabla.append({
            "posicion": int(_stat(e, "rank")),
            "equipo": equipo,
            "puntos": int(_stat(e, "points")),
            "jugados": int(_stat(e, "gamesPlayed")),
            "ganados": int(_stat(e, "wins")),
            "empatados": int(_stat(e, "ties")),
            "perdidos": int(_stat(e, "losses")),
            "goles_favor": int(_stat(e, "pointsFor")),
            "goles_contra": int(_stat(e, "pointsAgainst")),
            "diferencia": int(_stat(e, "pointDifferential")),
        })

    tabla.sort(key=lambda r: r["posicion"] if r["posicion"] > 0 else 999)
    return {"torneo": torneo, "tabla": tabla}


def _motivacion_fila(
    fila: Dict[str, Any], tabla: List[Dict[str, Any]], torneo: str
) -> Dict[str, Any]:
    """Calcula la situación/motivación de un equipo dentro de la tabla (pura)."""
    pos = int(fila["posicion"])
    pts = int(fila["puntos"])
    jugados = int(fila["jugados"])
    restantes = max(0, JORNADAS_FASE_REGULAR - jugados)
    max_pts = pts + 3 * restantes
    zona = rl.zona_clasificacion(pos, torneo)
    cupos = rl.cupos_postemporada(torneo)

    info: Dict[str, Any] = {
        "zona": zona,
        "jornadas_restantes": restantes,
        "max_puntos_posibles": max_pts,
    }

    if jugados == 0:
        info.update(
            vivo_para_liguilla=True,
            liguilla_asegurada=False,
            motivacion_nivel="n/a",
            motivacion="Temporada no iniciada.",
        )
        return info

    # Corte: puntos del equipo en el último cupo de postemporada.
    corte = tabla[cupos - 1]["puntos"] if len(tabla) >= cupos and cupos > 0 else 0
    vivo = max_pts >= corte

    # ¿Asegurado? El primer equipo FUERA de cupos no puede alcanzarlo ni con
    # todos sus puntos restantes (aproximación conservadora).
    asegurado = False
    if len(tabla) > cupos:
        primero_fuera = tabla[cupos]
        max_primero_fuera = int(primero_fuera["puntos"]) + 3 * max(
            0, JORNADAS_FASE_REGULAR - int(primero_fuera["jugados"])
        )
        asegurado = pts > max_primero_fuera
    elif len(tabla) == cupos:
        asegurado = True  # no hay nadie fuera que lo alcance

    if not vivo:
        nivel, desc = "baja", "Sin opciones de liguilla (eliminado)."
    elif asegurado:
        nivel, desc = "media", "Liguilla asegurada; juega por posición/seeding."
    else:
        objetivo = "liguilla directa" if zona == "directo" else "liguilla/Play-In"
        nivel, desc = "alta", f"En pelea por {objetivo}."

    info.update(
        vivo_para_liguilla=vivo,
        liguilla_asegurada=asegurado,
        motivacion_nivel=nivel,
        motivacion=desc,
    )
    return info


def tabla_con_motivacion(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """Anota cada fila de la tabla con su situación/motivación (pura)."""
    torneo = parsed.get("torneo", "")
    tabla = parsed.get("tabla", [])
    anotada = [{**fila, **_motivacion_fila(fila, tabla, torneo)} for fila in tabla]
    return {"torneo": torneo, "tabla": anotada}


def motivacion_de(parsed: Dict[str, Any], equipo: str) -> Optional[Dict[str, Any]]:
    """Devuelve la situación/motivación de un equipo por nombre (None si no está)."""
    objetivo = rl._norm(equipo)
    tabla = parsed.get("tabla", [])
    for fila in tabla:
        if rl._norm(fila["equipo"]) == objetivo:
            return _motivacion_fila(fila, tabla, parsed.get("torneo", ""))
    return None


def _fetch_standings() -> Dict[str, Any]:
    if requests is None:
        raise RuntimeError("La dependencia 'requests' no está instalada.")
    resp = requests.get(STANDINGS_URL, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"ESPN standings respondió HTTP {resp.status_code}.")
    return resp.json()


def obtener_tabla() -> Dict[str, Any]:
    """Baja la tabla actual de Liga MX desde ESPN y la anota con motivación."""
    return tabla_con_motivacion(parsear_standings(_fetch_standings()))


def main() -> int:
    print("📊 Bajando tabla Liga MX (ESPN)...")
    try:
        data = obtener_tabla()
    except RuntimeError as exc:
        print(f"⚠️ No se pudo consultar ESPN: {exc}")
        return 1
    print(f"Torneo: {data['torneo']} | equipos: {len(data['tabla'])}")
    for f in data["tabla"]:
        print(f"  {f['posicion']:>2}. {f['equipo']:<18} {f['puntos']:>2} pts "
              f"({f['jugados']}J) — {f['zona']} · {f['motivacion_nivel']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
