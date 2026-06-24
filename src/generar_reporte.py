#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


BASE_DIR = Path(__file__).resolve().parents[1]
JORNADAS_PATH = BASE_DIR / "data" / "jornadas.json"
CONFIG_SURVIVOR_PATH = BASE_DIR / "data" / "config_survivor.json"
BAJAS_IA_PATH = BASE_DIR / "data" / "bajas_ia_ultimo.json"


LOCAL_KEYS = ["local", "equipo_local", "home", "home_team", "casa"]
VISITANTE_KEYS = ["visitante", "equipo_visitante", "away", "away_team", "visita"]


def cargar_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def buscar_valor(obj: Dict[str, Any], keys: List[str], default: str = "") -> str:
    for key in keys:
        value = obj.get(key)
        if value not in ("", None, [], {}):
            return str(value)
    return default


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


def obtener_bloqueados(data: Any) -> List[str]:
    config = cargar_json(CONFIG_SURVIVOR_PATH, {})
    if isinstance(config, dict) and isinstance(config.get("equipos_bloqueados"), list):
        return [str(x) for x in config["equipos_bloqueados"]]

    if isinstance(data, dict):
        for key in ["equipos_bloqueados", "bloqueados_survivor", "bloqueados", "equipos_usados"]:
            value = data.get(key)
            if isinstance(value, list):
                return [str(x) for x in value]

    return []


def extraer_pick_desde_log(texto: str) -> Dict[str, str]:
    pick = {
        "equipo": "NO DETECTADO",
        "rival": "NO DETECTADO",
        "probabilidad": "NO DETECTADA",
        "estado_auditor": "NO DETECTADO",
    }

    m = re.search(r"SELECCIONAR A:\s*(.+)", texto)
    if m:
        pick["equipo"] = m.group(1).strip()

    m = re.search(r"Enfrentando a:\s*(.+)", texto)
    if m:
        pick["rival"] = m.group(1).strip()

    m = re.search(r"Probabilidad matemática de avanzar de jornada:\s*([0-9.]+%)", texto)
    if m:
        pick["probabilidad"] = m.group(1).strip()

    estados = re.findall(r"ESTADO:\s*(.+)", texto)
    if estados:
        pick["estado_auditor"] = estados[-1].strip()

    return pick


def formatear_bajas(partido: Dict[str, Any]) -> str:
    lesiones = partido.get("lesiones", [])
    suspendidos = partido.get("suspendidos", [])

    partes = []

    if isinstance(lesiones, list):
        for item in lesiones:
            if isinstance(item, dict):
                jugador = item.get("jugador", "Jugador sin nombre")
                detalle = item.get("detalle", "")
                partes.append(f"Lesión: {jugador} — {detalle}".strip())

    if isinstance(suspendidos, list):
        for item in suspendidos:
            if isinstance(item, dict):
                jugador = item.get("jugador", "Jugador sin nombre")
                detalle = item.get("detalle", "")
                partes.append(f"Suspensión: {jugador} — {detalle}".strip())

    if partes:
        return "; ".join(partes)

    if partido.get("bajas_revisadas"):
        return "Revisadas por IA, sin bajas confirmadas"

    return "No revisadas"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--main-log", default="")
    parser.add_argument("--output", default=str(BASE_DIR / "reports" / "reporte_survivor_ultimo.txt"))
    args = parser.parse_args()

    data = cargar_json(JORNADAS_PATH, {})
    partidos = extraer_partidos(data)
    bajas_ia = cargar_json(BAJAS_IA_PATH, {})
    bloqueados = obtener_bloqueados(data)

    log_text = ""
    if args.main_log and Path(args.main_log).exists():
        log_text = Path(args.main_log).read_text(encoding="utf-8", errors="ignore")

    pick = extraer_pick_desde_log(log_text)

    salida = []
    salida.append("REPORTE SURVIVOR LIGA MX — SATCHEL")
    salida.append("=" * 60)
    salida.append(f"Generado: {datetime.now().isoformat(timespec='seconds')}")
    salida.append("")

    salida.append("PICK OFICIAL")
    salida.append("-" * 60)
    salida.append(f"Equipo: {pick['equipo']}")
    salida.append(f"Rival: {pick['rival']}")
    salida.append(f"Probabilidad avanzar: {pick['probabilidad']}")
    salida.append(f"Estado auditor: {pick['estado_auditor']}")
    salida.append("")

    pick_ajustado_path = BASE_DIR / "reports" / "pick_ajustado_ultimo.txt"
    if pick_ajustado_path.exists():
        salida.append("PICK AJUSTADO ANTI-TUMBA")
        salida.append("-" * 60)
        salida.extend(pick_ajustado_path.read_text(encoding="utf-8", errors="ignore").strip().splitlines())
        salida.append("")

    salida.append("SURVIVOR")
    salida.append("-" * 60)
    salida.append(f"Equipos bloqueados: {', '.join(bloqueados) if bloqueados else 'No detectados'}")
    salida.append("")

    salida.append("BAJAS IA")
    salida.append("-" * 60)
    bajas = bajas_ia.get("bajas", []) if isinstance(bajas_ia, dict) else []
    resumen = bajas_ia.get("resumen", "") if isinstance(bajas_ia, dict) else ""

    salida.append(f"Resumen IA: {resumen or 'Sin resumen'}")
    salida.append(f"Bajas detectadas en último reporte: {len(bajas) if isinstance(bajas, list) else 0}")
    salida.append("")

    salida.append("PARTIDOS")
    salida.append("-" * 60)

    for idx, partido in enumerate(partidos, start=1):
        local = buscar_valor(partido, LOCAL_KEYS, "LOCAL?")
        visitante = buscar_valor(partido, VISITANTE_KEYS, "VISITANTE?")
        estadio = partido.get("estadio", "PENDIENTE")
        ciudad = partido.get("ciudad", "PENDIENTE")
        fecha = partido.get("fecha", "PENDIENTE")
        hora = partido.get("hora", "PENDIENTE")
        bajas_txt = formatear_bajas(partido)
        riesgo = partido.get("riesgo_sorpresa", {}) if isinstance(partido.get("riesgo_sorpresa", {}), dict) else {}
        riesgo_etiqueta = riesgo.get("etiqueta", "No calculado")
        riesgo_score = riesgo.get("score", "N/A")
        riesgo_recomendacion = riesgo.get("recomendacion", "Sin recomendación")

        salida.append(f"{idx}. {local} vs {visitante}")
        salida.append(f"   Estadio: {estadio}")
        salida.append(f"   Ciudad: {ciudad}")
        salida.append(f"   Fecha/hora: {fecha} {hora}")
        salida.append(f"   Bajas: {bajas_txt}")
        salida.append(f"   Riesgo sorpresa: {riesgo_etiqueta} | Score: {riesgo_score}/100")
        salida.append(f"   Recomendación riesgo: {riesgo_recomendacion}")
        salida.append("")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(salida) + "\n", encoding="utf-8")

    print(f"✅ Reporte generado: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
