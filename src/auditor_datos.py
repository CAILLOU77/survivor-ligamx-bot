#!/usr/bin/env python3
"""
auditor_datos.py

Auditor de calidad para data/jornadas.json del bot Survivor Liga MX.

Revisa:
- Local / visitante
- Estadio
- Ciudad
- Fecha / hora
- Clima
- Momios
- Lesiones / suspensiones
- Equipos bloqueados de Survivor

Uso:
    python3 src/auditor_datos.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


BASE_DIR = Path(__file__).resolve().parents[1]
JORNADAS_PATH = BASE_DIR / "data" / "jornadas.json"
CONFIG_SURVIVOR_PATH = BASE_DIR / "data" / "config_survivor.json"


LOCAL_KEYS = ["local", "equipo_local", "home", "home_team", "casa"]
VISITANTE_KEYS = ["visitante", "equipo_visitante", "away", "away_team", "visita"]
ESTADIO_KEYS = ["estadio", "stadium", "sede"]
CIUDAD_KEYS = ["ciudad", "city", "localidad"]
FECHA_KEYS = ["fecha", "date", "dia"]
HORA_KEYS = ["hora", "time", "kickoff"]
CLIMA_KEYS = ["clima", "weather", "temperatura"]
MOMIOS_KEYS = ["momios", "odds", "mercado", "apuestas"]
LESIONES_KEYS = ["lesiones", "lesionados", "bajas", "bajas_ia"]
SUSPENSIONES_KEYS = ["suspendidos", "suspensiones", "sancionados"]


def cargar_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"No existe {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def buscar_valor(obj: Dict[str, Any], keys: List[str]) -> Optional[Any]:
    for key in keys:
        if key in obj and obj[key] not in ("", None, [], {}):
            return obj[key]
    return None


def extraer_partidos(data: Any) -> List[Dict[str, Any]]:
    """
    Soporta estructuras flexibles:
    - data/jornadas.json como lista directa
    - {"partidos": [...]}
    - {"jornadas": [{"partidos": [...]}]}
    - {"jornada_1": [...]}
    """
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


def contar_bajas(data: Any, partido: Dict[str, Any]) -> int:
    total = 0

    for keys in (LESIONES_KEYS, SUSPENSIONES_KEYS):
        valor = buscar_valor(partido, keys)
        if isinstance(valor, list):
            total += len(valor)
        elif isinstance(valor, dict):
            total += len(valor)

    if isinstance(data, dict):
        bajas_ia = data.get("bajas_ia", [])
        if isinstance(bajas_ia, list):
            for bloque in bajas_ia:
                if isinstance(bloque, dict):
                    bajas = bloque.get("bajas", [])
                    if isinstance(bajas, list):
                        total += len(bajas)

    return total


def detectar_bloqueados_survivor(data: Any) -> List[str]:
    if CONFIG_SURVIVOR_PATH.exists():
        try:
            config = json.loads(CONFIG_SURVIVOR_PATH.read_text(encoding="utf-8"))
            valor = config.get("equipos_bloqueados", [])
            if isinstance(valor, list):
                return [str(x) for x in valor]
        except Exception:
            pass

    if not isinstance(data, dict):
        return []

    posibles_keys = [
        "bloqueados_survivor",
        "equipos_bloqueados",
        "bloqueados",
        "usados_survivor",
        "equipos_usados",
    ]

    for key in posibles_keys:
        valor = data.get(key)
        if isinstance(valor, list):
            return [str(x) for x in valor]
        if isinstance(valor, dict):
            return [str(x) for x in valor.keys()]

    return []


def auditar_partido(data: Any, partido: Dict[str, Any], idx: int) -> Dict[str, Any]:
    local = buscar_valor(partido, LOCAL_KEYS)
    visitante = buscar_valor(partido, VISITANTE_KEYS)
    estadio = buscar_valor(partido, ESTADIO_KEYS)
    ciudad = buscar_valor(partido, CIUDAD_KEYS)
    fecha = buscar_valor(partido, FECHA_KEYS)
    hora = buscar_valor(partido, HORA_KEYS)
    clima = buscar_valor(partido, CLIMA_KEYS)
    momios = buscar_valor(partido, MOMIOS_KEYS)
    bajas = contar_bajas(data, partido)
    bajas_revisadas = bool(partido.get("bajas_revisadas", False))

    errores = []
    avisos = []

    if not local:
        errores.append("Falta equipo local")
    if not visitante:
        errores.append("Falta equipo visitante")

    if not estadio:
        avisos.append("Falta estadio")
    if not ciudad:
        avisos.append("Falta ciudad")
    if not fecha:
        avisos.append("Falta fecha")
    if not hora:
        avisos.append("Falta hora")
    if not clima:
        avisos.append("Falta clima o temperatura")
    if not momios:
        avisos.append("Faltan momios / mercado")
    if bajas == 0 and not bajas_revisadas:
        avisos.append("No hay lesiones/suspensiones registradas para este partido")

    nombre = f"{local or 'LOCAL?'} vs {visitante or 'VISITANTE?'}"

    return {
        "idx": idx,
        "nombre": nombre,
        "local": local,
        "visitante": visitante,
        "estadio": estadio,
        "ciudad": ciudad,
        "fecha": fecha,
        "hora": hora,
        "clima": clima,
        "momios": bool(momios),
        "bajas_detectadas": bajas,
        "bajas_revisadas": bajas_revisadas,
        "errores": errores,
        "avisos": avisos,
    }


def main() -> int:
    print("🔎 AUDITOR DE DATOS — SURVIVOR LIGA MX")
    print("=" * 60)

    try:
        data = cargar_json(JORNADAS_PATH)
    except Exception as exc:
        print(f"❌ ERROR: No pude leer data/jornadas.json: {exc}")
        return 1

    partidos = extraer_partidos(data)

    if not partidos:
        print("❌ ERROR: No encontré partidos dentro de data/jornadas.json")
        print("   Revisa que exista una lista llamada partidos o jornadas.")
        return 1

    bloqueados = detectar_bloqueados_survivor(data)

    print(f"📁 Archivo revisado: {JORNADAS_PATH}")
    print(f"⚽ Partidos encontrados: {len(partidos)}")

    if bloqueados:
        print(f"🚫 Equipos bloqueados Survivor: {', '.join(bloqueados)}")
    else:
        print("⚠️ Equipos bloqueados Survivor: no detectados")

    print("-" * 60)

    total_errores = 0
    total_avisos = 0

    for idx, partido in enumerate(partidos, start=1):
        reporte = auditar_partido(data, partido, idx)

        print(f"\n#{idx} {reporte['nombre']}")

        if reporte["errores"]:
            total_errores += len(reporte["errores"])
            for err in reporte["errores"]:
                print(f"   ❌ {err}")
        else:
            print("   ✅ Local / visitante OK")

        if reporte["estadio"]:
            print(f"   🏟️ Estadio: {reporte['estadio']}")
        else:
            print("   ⚠️ Estadio: faltante")

        if reporte["ciudad"]:
            print(f"   📍 Ciudad: {reporte['ciudad']}")
        else:
            print("   ⚠️ Ciudad: faltante")

        if reporte["fecha"] or reporte["hora"]:
            print(f"   🕒 Fecha/hora: {reporte['fecha'] or '?'} {reporte['hora'] or '?'}")
        else:
            print("   ⚠️ Fecha/hora: faltante")

        if reporte["clima"]:
            print(f"   ⛅ Clima: detectado")
        else:
            print("   ⚠️ Clima: faltante o fallback")

        if reporte["momios"]:
            print("   🎰 Momios: detectados")
        else:
            print("   ⚠️ Momios: no detectados")

        if reporte["bajas_detectadas"] > 0:
            print(f"   🏥 Lesiones/suspensiones: {reporte['bajas_detectadas']} detectadas")
        elif reporte.get("bajas_revisadas"):
            print("   ✅ Lesiones/suspensiones: revisadas, sin bajas confirmadas")
        else:
            print("   ⚠️ Lesiones/suspensiones: ninguna registrada")

        total_avisos += len(reporte["avisos"])

    print("\n" + "=" * 60)
    print("📋 RESUMEN FINAL")

    if total_errores == 0:
        print("✅ Campos críticos local/visitante: OK")
    else:
        print(f"❌ Errores críticos: {total_errores}")

    if total_avisos == 0:
        print("✅ Sin avisos pendientes")
    else:
        print(f"⚠️ Avisos pendientes: {total_avisos}")

    if total_errores == 0 and total_avisos == 0:
        print("🏁 ESTADO: LISTO PARA USO REAL")
        return 0

    if total_errores == 0:
        print("🟡 ESTADO: FUNCIONAL, PERO FALTAN DATOS PARA ESTAR 100% ACTUALIZADO")
        return 0

    print("🔴 ESTADO: FALTAN CAMPOS CRÍTICOS")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
