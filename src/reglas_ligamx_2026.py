#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional


BASE_DIR = Path(__file__).resolve().parents[1]
JORNADAS_PATH = BASE_DIR / "data" / "jornadas.json"
OUTPUT_JSON = BASE_DIR / "data" / "reglas_ligamx_2026_ultimo.json"
OUTPUT_TXT = BASE_DIR / "reports" / "reglas_ligamx_2026_ultimo.txt"


def cargar_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def guardar_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def extraer_partidos(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [p for p in data if isinstance(p, dict)]

    if isinstance(data, dict) and isinstance(data.get("partidos"), list):
        return [p for p in data["partidos"] if isinstance(p, dict)]

    return []


def nombre_partido(partido: Dict[str, Any]) -> str:
    local = partido.get("home_team") or partido.get("local") or "LOCAL?"
    visitante = partido.get("away_team") or partido.get("visitante") or "VISITANTE?"
    return f"{local} vs {visitante}"


def parse_fecha(value: Any) -> Optional[date]:
    raw = str(value or "").strip()

    if not raw or "PENDIENTE" in raw.upper():
        return None

    try:
        return datetime.fromisoformat(raw[:10]).date()
    except Exception:
        return None


def detectar_jornada(partido: Dict[str, Any]) -> Optional[int]:
    campos = [
        partido.get("jornada"),
        partido.get("round"),
        partido.get("nombre_jornada"),
        partido.get("competition_round"),
        partido.get("grupo"),
    ]

    for campo in campos:
        raw = str(campo or "")
        match = re.search(r"jornada\s*(\d+)|round\s*(\d+)|fecha\s*(\d+)", raw, flags=re.I)
        if match:
            for g in match.groups():
                if g:
                    return int(g)

        if raw.strip().isdigit():
            return int(raw.strip())

    return None


def nivel_por_score(score: float) -> Dict[str, str]:
    if score >= 70:
        return {
            "nivel": "ROJO",
            "etiqueta": "🔴 TUMBA QUINIELAS",
            "recomendacion": "NO ENVIAR salvo que haya mercado real muy fuerte y confirmación final.",
        }

    if score >= 50:
        return {
            "nivel": "AMARILLO",
            "etiqueta": "🟡 RIESGO MEDIO",
            "recomendacion": "Usar solo si la probabilidad de no perder es claramente superior a las alternativas.",
        }

    return {
        "nivel": "VERDE",
        "etiqueta": "🟢 RIESGO BAJO",
        "recomendacion": "Candidato aceptable si también lidera en probabilidad de no perder.",
    }


def evaluar_reglas(partido: Dict[str, Any]) -> Dict[str, Any]:
    fecha = parse_fecha(partido.get("fecha"))
    jornada = detectar_jornada(partido)

    ajuste = 0.0
    razones: List[str] = []
    avisos: List[str] = []

    # Nueva estructura competitiva: sin Play-In, top 8 directo.
    avisos.append(
        "Formato 2026: sin Play-In; la pelea por top 8 pesa más en fase regular."
    )

    # Inicio de torneo: modelos menos estables, planteles nuevos, pretemporada.
    if jornada is not None and jornada <= 3:
        ajuste += 5
        razones.append(
            f"Jornada {jornada}: inicio de torneo con mayor incertidumbre de ritmo, XI y ajustes tácticos."
        )
    elif fecha and date(2026, 7, 16) <= fecha <= date(2026, 8, 3):
        ajuste += 5
        razones.append(
            "Ventana inicial del Apertura 2026: mayor incertidumbre por arranque de torneo."
        )

    # Calendario cargado / contexto 2026.
    if fecha and date(2026, 7, 24) <= fecha <= date(2026, 8, 10):
        ajuste += 4
        razones.append(
            "Ventana con posible carga de calendario/torneos paralelos: sube riesgo de rotación."
        )

    # Si más adelante agregamos standings, aquí ya queda listo.
    for lado in ["local", "visitante", "home_team", "away_team"]:
        pos_key = f"posicion_{lado}"
        try:
            posicion = int(partido.get(pos_key))
        except Exception:
            continue

        if 7 <= posicion <= 12:
            ajuste += 3
            razones.append(
                f"{lado} en zona 7-12: presión por top 8 puede cambiar ritmo y exposición del partido."
            )
        elif posicion >= 13:
            ajuste += 2
            razones.append(
                f"{lado} fuera de zona alta: motivación/urgencia puede ser menos estable."
            )

    # Regla de menores: no ajusta si no tenemos dato específico, pero queda documentado.
    if partido.get("menores_riesgo_rotacion") is True:
        ajuste += 6
        razones.append(
            "Riesgo por regla de menores: posible uso obligado de jóvenes o rotación."
        )
    else:
        avisos.append(
            "Regla de menores: sin dato específico de cumplimiento; no se aplica ajuste numérico."
        )

    if not razones:
        razones.append(
            "Reglas 2026 registradas, pero sin gatillo fuerte adicional para este partido."
        )

    return {
        "ajuste_score": round(ajuste, 2),
        "razones": razones,
        "avisos": avisos,
        "jornada_detectada": jornada,
        "fecha_detectada": fecha.isoformat() if fecha else None,
    }


def aplicar_a_partido(partido: Dict[str, Any]) -> Dict[str, Any]:
    evaluacion = evaluar_reglas(partido)
    riesgo = partido.get("riesgo_sorpresa", {})

    if not isinstance(riesgo, dict):
        riesgo = {}

    score_original = float(riesgo.get("score", 50))
    ajuste = float(evaluacion["ajuste_score"])
    score_nuevo = max(0.0, min(100.0, score_original + ajuste))
    nivel = nivel_por_score(score_nuevo)

    razones_actuales = riesgo.get("razones", [])
    if not isinstance(razones_actuales, list):
        razones_actuales = []

    nuevas_razones = razones_actuales + [
        f"[Reglas Liga MX 2026] {r}" for r in evaluacion["razones"]
    ]

    riesgo_actualizado = {
        **riesgo,
        "score": round(score_nuevo, 2),
        "score_pre_reglas_ligamx_2026": round(score_original, 2),
        "ajuste_reglas_ligamx_2026": round(ajuste, 2),
        "nivel": nivel["nivel"],
        "etiqueta": nivel["etiqueta"],
        "recomendacion": nivel["recomendacion"],
        "razones": nuevas_razones,
    }

    partido["riesgo_sorpresa"] = riesgo_actualizado
    partido["reglas_ligamx_2026"] = evaluacion

    return {
        "partido": nombre_partido(partido),
        "score_original": round(score_original, 2),
        "ajuste": round(ajuste, 2),
        "score_nuevo": round(score_nuevo, 2),
        "nivel": nivel["nivel"],
        "etiqueta": nivel["etiqueta"],
        "razones": evaluacion["razones"],
        "avisos": evaluacion["avisos"],
    }


def escribir_txt(resultados: List[Dict[str, Any]]) -> None:
    OUTPUT_TXT.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append("LIGA MX 2026 RULES ENGINE")
    lines.append("-" * 60)
    lines.append(f"Generado: {datetime.now().isoformat(timespec='seconds')}")
    lines.append("")

    for r in resultados:
        lines.append(r["partido"])
        lines.append(f"Riesgo previo: {r['score_original']}/100")
        lines.append(f"Ajuste reglas 2026: +{r['ajuste']}")
        lines.append(f"Riesgo nuevo: {r['score_nuevo']}/100")
        lines.append(f"Nivel: {r['etiqueta']}")
        lines.append("Razones:")
        for razon in r["razones"]:
            lines.append(f"- {razon}")
        lines.append("Avisos:")
        for aviso in r["avisos"]:
            lines.append(f"- {aviso}")
        lines.append("")

    OUTPUT_TXT.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    data = cargar_json(JORNADAS_PATH, [])
    partidos = extraer_partidos(data)

    if not partidos:
        raise SystemExit("ERROR: No encontré partidos en data/jornadas.json")

    backup = JORNADAS_PATH.with_suffix(
        f".backup-reglas-ligamx-2026-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    )
    backup.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    resultados = [aplicar_a_partido(p) for p in partidos]

    if isinstance(data, list):
        salida = partidos
    elif isinstance(data, dict):
        data["partidos"] = partidos
        salida = data
    else:
        salida = partidos

    guardar_json(JORNADAS_PATH, salida)

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(
        json.dumps(
            {
                "generado_en": datetime.now().isoformat(timespec="seconds"),
                "resultados": resultados,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    escribir_txt(resultados)

    print("📜 LIGA MX 2026 RULES ENGINE")
    print("=" * 60)
    for r in resultados:
        print(
            f"{r['partido']}: {r['score_original']} → {r['score_nuevo']} "
            f"({r['etiqueta']})"
        )
    print(f"✅ Backup creado: {backup}")
    print(f"✅ Reporte: {OUTPUT_TXT}")
    print(f"✅ JSON: {OUTPUT_JSON}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
