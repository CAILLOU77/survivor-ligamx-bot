#!/usr/bin/env python3
from __future__ import annotations

import json
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


BASE_DIR = Path(__file__).resolve().parents[1]
JORNADAS_PATH = BASE_DIR / "data" / "jornadas.json"


INFO_EQUIPOS = {
    "club america": {
        "estadio": "Estadio Ciudad de los Deportes",
        "ciudad": "Ciudad de México",
        "pais": "México",
        "coordenadas_estadio": {"lat": 19.3833, "lon": -99.1781},
    },
    "america": {
        "estadio": "Estadio Ciudad de los Deportes",
        "ciudad": "Ciudad de México",
        "pais": "México",
        "coordenadas_estadio": {"lat": 19.3833, "lon": -99.1781},
    },
    "cruz azul": {
        "estadio": "Estadio Ciudad de los Deportes",
        "ciudad": "Ciudad de México",
        "pais": "México",
        "coordenadas_estadio": {"lat": 19.3833, "lon": -99.1781},
    },
    "pumas unam": {
        "estadio": "Estadio Olímpico Universitario",
        "ciudad": "Ciudad de México",
        "pais": "México",
        "coordenadas_estadio": {"lat": 19.3320, "lon": -99.1920},
    },
    "toluca": {
        "estadio": "Estadio Nemesio Diez",
        "ciudad": "Toluca",
        "pais": "México",
        "coordenadas_estadio": {"lat": 19.2873, "lon": -99.6662},
    },
    "chivas guadalajara": {
        "estadio": "Estadio Akron",
        "ciudad": "Zapopan",
        "pais": "México",
        "coordenadas_estadio": {"lat": 20.6819, "lon": -103.4622},
    },
    "guadalajara": {
        "estadio": "Estadio Akron",
        "ciudad": "Zapopan",
        "pais": "México",
        "coordenadas_estadio": {"lat": 20.6819, "lon": -103.4622},
    },
    "tijuana": {
        "estadio": "Estadio Caliente",
        "ciudad": "Tijuana",
        "pais": "México",
        "coordenadas_estadio": {"lat": 32.5076, "lon": -116.9931},
    },
    "tigres": {
        "estadio": "Estadio Universitario",
        "ciudad": "San Nicolás de los Garza",
        "pais": "México",
        "coordenadas_estadio": {"lat": 25.7228, "lon": -100.3120},
    },
    "monterrey": {
        "estadio": "Estadio BBVA",
        "ciudad": "Guadalupe",
        "pais": "México",
        "coordenadas_estadio": {"lat": 25.6683, "lon": -100.2440},
    },
    "pachuca": {
        "estadio": "Estadio Hidalgo",
        "ciudad": "Pachuca",
        "pais": "México",
        "coordenadas_estadio": {"lat": 20.1054, "lon": -98.7551},
    },
    "leon": {
        "estadio": "Estadio León",
        "ciudad": "León",
        "pais": "México",
        "coordenadas_estadio": {"lat": 21.1151, "lon": -101.6579},
    },
    "atlas": {
        "estadio": "Estadio Jalisco",
        "ciudad": "Guadalajara",
        "pais": "México",
        "coordenadas_estadio": {"lat": 20.7035, "lon": -103.3286},
    },
    "santos laguna": {
        "estadio": "Estadio Corona",
        "ciudad": "Torreón",
        "pais": "México",
        "coordenadas_estadio": {"lat": 25.5775, "lon": -103.4420},
    },
    "necaxa": {
        "estadio": "Estadio Victoria",
        "ciudad": "Aguascalientes",
        "pais": "México",
        "coordenadas_estadio": {"lat": 21.8900, "lon": -102.2960},
    },
    "puebla": {
        "estadio": "Estadio Cuauhtémoc",
        "ciudad": "Puebla",
        "pais": "México",
        "coordenadas_estadio": {"lat": 19.0780, "lon": -98.1646},
    },
    "queretaro": {
        "estadio": "Estadio Corregidora",
        "ciudad": "Querétaro",
        "pais": "México",
        "coordenadas_estadio": {"lat": 20.5773, "lon": -100.3669},
    },
    "mazatlan": {
        "estadio": "Estadio El Encanto",
        "ciudad": "Mazatlán",
        "pais": "México",
        "coordenadas_estadio": {"lat": 23.2494, "lon": -106.4111},
    },
    "juarez": {
        "estadio": "Estadio Olímpico Benito Juárez",
        "ciudad": "Ciudad Juárez",
        "pais": "México",
        "coordenadas_estadio": {"lat": 31.7430, "lon": -106.4380},
    },
    "atletico san luis": {
        "estadio": "Estadio Alfonso Lastras",
        "ciudad": "San Luis Potosí",
        "pais": "México",
        "coordenadas_estadio": {"lat": 22.1263, "lon": -100.9290},
    },
}


LOCAL_KEYS = ["local", "equipo_local", "home", "home_team", "casa"]
VISITANTE_KEYS = ["visitante", "equipo_visitante", "away", "away_team", "visita"]


def normalizar(texto: str) -> str:
    texto = texto or ""
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return texto.lower().strip()


def buscar_valor(obj: Dict[str, Any], keys: List[str]) -> Any:
    for key in keys:
        if key in obj and obj[key] not in ("", None, [], {}):
            return obj[key]
    return None


def extraer_partidos(data: Any) -> List[Dict[str, Any]]:
    partidos: List[Dict[str, Any]] = []

    if isinstance(data, list):
        return [p for p in data if isinstance(p, dict)]

    if not isinstance(data, dict):
        return partidos

    if isinstance(data.get("partidos"), list):
        partidos.extend([p for p in data["partidos"] if isinstance(p, dict)])

    if isinstance(data.get("jornadas"), list):
        for jornada in data["jornadas"]:
            if isinstance(jornada, dict) and isinstance(jornada.get("partidos"), list):
                partidos.extend([p for p in jornada["partidos"] if isinstance(p, dict)])

    for key, value in data.items():
        if key.startswith("jornada") and isinstance(value, list):
            partidos.extend([p for p in value if isinstance(p, dict)])

    return partidos


def obtener_info_equipo(nombre: str) -> Dict[str, Any]:
    n = normalizar(nombre)

    if n in INFO_EQUIPOS:
        return INFO_EQUIPOS[n]

    for key, value in INFO_EQUIPOS.items():
        if key in n or n in key:
            return value

    return {}


def enriquecer_partido(partido: Dict[str, Any]) -> bool:
    cambio = False

    local = buscar_valor(partido, LOCAL_KEYS)
    visitante = buscar_valor(partido, VISITANTE_KEYS)

    if not local:
        return False

    info_local = obtener_info_equipo(str(local))

    for campo in ["estadio", "ciudad", "pais", "coordenadas_estadio"]:
        if campo not in partido or partido[campo] in ("", None, [], {}):
            if campo in info_local:
                partido[campo] = info_local[campo]
                cambio = True

    if "fecha" not in partido or not partido["fecha"]:
        partido["fecha"] = "PENDIENTE_CONFIRMAR"
        cambio = True

    if "hora" not in partido or not partido["hora"]:
        partido["hora"] = "PENDIENTE_CONFIRMAR"
        cambio = True

    if "momios" not in partido or not partido["momios"]:
        partido["momios"] = {
            "estado": "mercado_no_publicado",
            "fuente": "The Odds API",
            "nota": "Se actualizará automáticamente cuando el mercado esté abierto.",
        }
        cambio = True

    if "clima" not in partido or not partido["clima"]:
        partido["clima"] = {
            "estado": "fallback_local",
            "temperatura_c": 20.0,
            "nota": "Pendiente de actualización por contexto.py.",
        }
        cambio = True

    if "lesiones" not in partido:
        partido["lesiones"] = []
        cambio = True

    if "suspendidos" not in partido:
        partido["suspendidos"] = []
        cambio = True

    if "bajas_revisadas" not in partido:
        partido["bajas_revisadas"] = False
        cambio = True

    if "metadata_partido" not in partido:
        partido["metadata_partido"] = {}

    partido["metadata_partido"]["local_confirmado"] = True
    partido["metadata_partido"]["visitante_confirmado"] = bool(visitante)
    partido["metadata_partido"]["ultima_normalizacion"] = datetime.now().isoformat(timespec="seconds")

    return cambio


def main() -> int:
    if not JORNADAS_PATH.exists():
        raise SystemExit(f"ERROR: No existe {JORNADAS_PATH}")

    data = json.loads(JORNADAS_PATH.read_text(encoding="utf-8"))

    backup = JORNADAS_PATH.with_suffix(
        f".backup-enriquecer-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    )
    backup.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    partidos = extraer_partidos(data)
    cambios = 0

    for partido in partidos:
        if enriquecer_partido(partido):
            cambios += 1

    if isinstance(data, dict):
        if "equipos_bloqueados" not in data or not data["equipos_bloqueados"]:
            data["equipos_bloqueados"] = ["Toluca"]

        data["_metadata"] = {
            "actualizado_por": "src/enriquecer_jornadas.py",
            "actualizado_en": datetime.now().isoformat(timespec="seconds"),
            "partidos_enriquecidos": cambios,
            "nota": "Campos estructurales agregados. Fechas, horas, momios reales y bajas reales deben confirmarse antes de uso oficial.",
        }

    JORNADAS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"✅ Partidos encontrados: {len(partidos)}")
    print(f"✅ Partidos enriquecidos: {cambios}")
    print(f"✅ Backup creado: {backup}")
    print(f"✅ Archivo actualizado: {JORNADAS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
