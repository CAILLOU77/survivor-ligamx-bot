#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


BASE_DIR = Path(__file__).resolve().parents[1]
JORNADAS_PATH = BASE_DIR / "data" / "jornadas.json"
CONFIG_SURVIVOR_PATH = BASE_DIR / "data" / "config_survivor.json"

LOCAL_KEYS = ["local", "equipo_local", "home", "home_team", "casa"]
VISITANTE_KEYS = ["visitante", "equipo_visitante", "away", "away_team", "visita"]


def normalizar(texto: str) -> str:
    texto = texto or ""
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return texto.lower().strip()


def cargar_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def buscar_valor(obj: Dict[str, Any], keys: List[str]) -> str:
    for key in keys:
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


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


def parsear_avances_desde_log(log_text: str) -> Dict[str, float]:
    avances: Dict[str, float] = {}

    patron = re.compile(
        r"AVANCE SURVIVOR \(No perder\):\s*(.+?):\s*([0-9.]+)%\s*\|\s*(.+?):\s*([0-9.]+)%",
        flags=re.IGNORECASE,
    )

    for match in patron.finditer(log_text):
        equipo_a = match.group(1).strip()
        prob_a = float(match.group(2))
        equipo_b = match.group(3).strip()
        prob_b = float(match.group(4))

        avances[normalizar(equipo_a)] = prob_a
        avances[normalizar(equipo_b)] = prob_b

    return avances


def construir_candidatos(data: Any, log_text: str) -> List[Dict[str, Any]]:
    partidos = extraer_partidos(data)
    avances = parsear_avances_desde_log(log_text)
    bloqueados_norm = {normalizar(x) for x in obtener_bloqueados(data)}

    candidatos: List[Dict[str, Any]] = []

    for partido in partidos:
        local = buscar_valor(partido, LOCAL_KEYS)
        visitante = buscar_valor(partido, VISITANTE_KEYS)
        riesgo = partido.get("riesgo_sorpresa", {})

        if not isinstance(riesgo, dict):
            riesgo = {}

        riesgo_score = float(riesgo.get("score", 50))
        riesgo_etiqueta = str(riesgo.get("etiqueta", "No calculado"))
        riesgo_recomendacion = str(riesgo.get("recomendacion", ""))

        for equipo, rival, condicion in [
            (local, visitante, "Local"),
            (visitante, local, "Visitante"),
        ]:
            equipo_norm = normalizar(equipo)

            if not equipo_norm:
                continue

            if equipo_norm in bloqueados_norm:
                continue

            avance = avances.get(equipo_norm)

            if avance is None:
                continue

            penalizacion_riesgo = min(40.0, riesgo_score * 0.38)
            score_ajustado = avance - penalizacion_riesgo

            if riesgo_score >= 85:
                score_ajustado -= 8

            if avance < 60:
                score_ajustado -= 10

            if condicion == "Visitante":
                score_ajustado -= 4

            if riesgo_score >= 65:
                decision_candidato = "ALTO_RIESGO"
            elif avance >= 75:
                decision_candidato = "CANDIDATO_FUERTE"
            elif avance >= 68:
                decision_candidato = "CANDIDATO_MEDIO"
            else:
                decision_candidato = "DEBIL"

            candidatos.append(
                {
                    "equipo": equipo,
                    "rival": rival,
                    "condicion": condicion,
                    "avance_no_perder": round(avance, 1),
                    "riesgo_score": round(riesgo_score, 1),
                    "riesgo_etiqueta": riesgo_etiqueta,
                    "riesgo_recomendacion": riesgo_recomendacion,
                    "score_ajustado": round(score_ajustado, 2),
                    "decision_candidato": decision_candidato,
                }
            )

    candidatos.sort(key=lambda x: x["score_ajustado"], reverse=True)
    return candidatos


def construir_decision(candidatos: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not candidatos:
        return {
            "decision": "NO_ENVIAR",
            "pick": None,
            "mensaje": "No hay candidatos disponibles después de aplicar bloqueados Survivor.",
        }

    mejor = candidatos[0]

    if mejor["riesgo_score"] >= 65:
        decision = "ESPERAR / NO ENVIAR"
        mensaje = (
            f"El mejor candidato por score ajustado es {mejor['equipo']}, "
            f"pero el partido está marcado como {mejor['riesgo_etiqueta']}. "
            "En Survivor no conviene cerrar automático; usar solo si estás obligado a elegir."
        )
    elif mejor["avance_no_perder"] >= 75:
        decision = "CERRAR"
        mensaje = "Candidato fuerte: buena probabilidad de no perder y riesgo controlado."
    else:
        decision = "ESPERAR"
        mensaje = "No hay candidato suficientemente fuerte; esperar momios, XI, bajas y mercado."

    return {
        "decision": decision,
        "pick": mejor,
        "mensaje": mensaje,
    }


def escribir_texto(decision: Dict[str, Any], candidatos: List[Dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append("PICK AJUSTADO ANTI-TUMBA QUINIELAS")
    lines.append("-" * 60)
    lines.append(f"Decisión: {decision['decision']}")
    lines.append(f"Mensaje: {decision['mensaje']}")
    lines.append("")

    pick = decision.get("pick")

    if pick:
        lines.append("Pick ajustado / emergencia:")
        lines.append(f"Equipo: {pick['equipo']} ({pick['condicion']})")
        lines.append(f"Rival: {pick['rival']}")
        lines.append(f"Avance no perder: {pick['avance_no_perder']}%")
        lines.append(f"Riesgo: {pick['riesgo_etiqueta']} | Score {pick['riesgo_score']}/100")
        lines.append(f"Score ajustado: {pick['score_ajustado']}")
        lines.append("")

    lines.append("Ranking ajustado:")
    for idx, c in enumerate(candidatos[:8], start=1):
        lines.append(
            f"{idx}. {c['equipo']} vs {c['rival']} | "
            f"No perder {c['avance_no_perder']}% | "
            f"Riesgo {c['riesgo_score']}/100 | "
            f"Ajustado {c['score_ajustado']}"
        )

    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--main-log", required=True)
    parser.add_argument("--output-json", default=str(BASE_DIR / "data" / "pick_ajustado_survivor.json"))
    parser.add_argument("--output-text", default=str(BASE_DIR / "reports" / "pick_ajustado_ultimo.txt"))
    args = parser.parse_args()

    data = cargar_json(JORNADAS_PATH, {})
    log_path = Path(args.main_log)

    if not log_path.exists():
        raise SystemExit(f"ERROR: No existe log: {log_path}")

    log_text = log_path.read_text(encoding="utf-8", errors="ignore")

    candidatos = construir_candidatos(data, log_text)
    decision = construir_decision(candidatos)

    resultado = {
        "generado_en": datetime.now().isoformat(timespec="seconds"),
        "decision": decision,
        "candidatos": candidatos,
        "criterio": "Survivor Liga MX: priorizar no perder, castigar empate/sorpresa/rivalidad/bajas/volatilidad.",
    }

    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    escribir_texto(decision, candidatos, Path(args.output_text))

    print("🧨 PICK AJUSTADO ANTI-TUMBA QUINIELAS")
    print("=" * 60)
    print(f"Decisión: {decision['decision']}")
    print(decision["mensaje"])

    pick = decision.get("pick")
    if pick:
        print(f"Pick ajustado/emergencia: {pick['equipo']} vs {pick['rival']}")
        print(f"No perder: {pick['avance_no_perder']}%")
        print(f"Riesgo: {pick['riesgo_etiqueta']} | {pick['riesgo_score']}/100")

    print(f"✅ JSON guardado: {output_json}")
    print(f"✅ Texto guardado: {args.output_text}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
