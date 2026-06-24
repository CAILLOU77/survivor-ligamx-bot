#!/usr/bin/env python3
"""
riesgo_sorpresa.py

Capa anti-tumba quinielas para Survivor Liga MX.

Objetivo:
- No elegir solo por favorito.
- Castigar partidos con alto riesgo de empate/sorpresa.
- Detectar clásicos, rivalidades, favoritos vulnerables, mercado cerrado,
  bajas sensibles y partidos de baja confianza.
- Guardar el análisis dentro de data/jornadas.json.

Uso:
    python3 src/riesgo_sorpresa.py
"""

from __future__ import annotations

import json
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple


BASE_DIR = Path(__file__).resolve().parents[1]
JORNADAS_PATH = BASE_DIR / "data" / "jornadas.json"

LOCAL_KEYS = ["local", "equipo_local", "home", "home_team", "casa"]
VISITANTE_KEYS = ["visitante", "equipo_visitante", "away", "away_team", "visita"]


CLASICOS_Y_RIVALIDADES = [
    ("club america", "chivas guadalajara"),
    ("america", "guadalajara"),
    ("club america", "cruz azul"),
    ("america", "cruz azul"),
    ("club america", "pumas unam"),
    ("america", "pumas"),
    ("chivas guadalajara", "atlas"),
    ("guadalajara", "atlas"),
    ("tigres", "monterrey"),
    ("pumas unam", "cruz azul"),
    ("pumas", "cruz azul"),
    ("toluca", "club america"),
    ("toluca", "america"),
]


EQUIPOS_VOLATILES = {
    "chivas guadalajara",
    "guadalajara",
    "pumas unam",
    "pumas",
    "cruz azul",
    "tijuana",
    "atlas",
    "puebla",
    "queretaro",
    "juarez",
    "mazatlan",
}


EQUIPOS_FUERTES_PERO_PUBLICOS = {
    "club america",
    "america",
    "tigres",
    "monterrey",
    "toluca",
    "cruz azul",
}


def normalizar(texto: str) -> str:
    texto = texto or ""
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return texto.lower().strip()


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


def equipos_son_rivalidad(local: str, visitante: str) -> bool:
    a = normalizar(local)
    b = normalizar(visitante)

    for x, y in CLASICOS_Y_RIVALIDADES:
        if (x in a and y in b) or (y in a and x in b):
            return True

    return False


def contar_bajas(partido: Dict[str, Any]) -> Tuple[int, int]:
    lesiones = partido.get("lesiones", [])
    suspendidos = partido.get("suspendidos", [])

    total_lesiones = len(lesiones) if isinstance(lesiones, list) else 0
    total_suspendidos = len(suspendidos) if isinstance(suspendidos, list) else 0

    return total_lesiones, total_suspendidos


def mercado_disponible(partido: Dict[str, Any]) -> bool:
    momios = partido.get("momios")

    if not momios:
        return False

    if isinstance(momios, dict):
        estado = str(momios.get("estado", "")).lower()
        if "no_publicado" in estado or "cerrado" in estado or "pendiente" in estado:
            return False

    return True


def obtener_probabilidades_si_existen(partido: Dict[str, Any]) -> Dict[str, float]:
    """
    Si en el futuro guardamos probabilidades dentro de jornadas.json,
    este módulo las usará. Si no existen, aplica heurística.
    """
    posibles = [
        partido.get("probabilidades"),
        partido.get("prediccion"),
        partido.get("pronostico"),
    ]

    for obj in posibles:
        if not isinstance(obj, dict):
            continue

        local = obj.get("local") or obj.get("home") or obj.get("gana_local")
        empate = obj.get("empate") or obj.get("draw")
        visita = obj.get("visitante") or obj.get("away") or obj.get("gana_visitante")

        try:
            if local is not None and empate is not None and visita is not None:
                return {
                    "local": float(local),
                    "empate": float(empate),
                    "visitante": float(visita),
                }
        except (TypeError, ValueError):
            continue

    return {}


def calcular_riesgo(partido: Dict[str, Any]) -> Dict[str, Any]:
    local = buscar_valor(partido, LOCAL_KEYS)
    visitante = buscar_valor(partido, VISITANTE_KEYS)

    local_norm = normalizar(local)
    visitante_norm = normalizar(visitante)

    score = 20
    razones = []

    # Liga MX base: siempre hay volatilidad.
    score += 10
    razones.append("Liga MX tiene alta frecuencia de sorpresas y empates.")

    # Rivalidad / clásico.
    if equipos_son_rivalidad(local, visitante):
        score += 25
        razones.append("Clásico/rivalidad: sube el riesgo de empate o resultado raro.")

    # Visitante volátil puede tumbar favoritos.
    if visitante_norm in EQUIPOS_VOLATILES:
        score += 8
        razones.append(f"{visitante} es visitante con perfil volátil.")

    # Favoritos públicos: cuidado con sobreconfianza.
    if local_norm in EQUIPOS_FUERTES_PERO_PUBLICOS:
        score += 5
        razones.append(f"{local} puede estar sobrevalorado por nombre/público.")

    # Mercado cerrado = falta confirmación externa.
    if not mercado_disponible(partido):
        score += 10
        razones.append("Mercado/momios no publicados: falta confirmación externa.")

    # Fecha/hora pendiente = información incompleta.
    fecha = str(partido.get("fecha", "")).upper()
    hora = str(partido.get("hora", "")).upper()
    if "PENDIENTE" in fecha or "PENDIENTE" in hora or not fecha or not hora:
        score += 6
        razones.append("Fecha/hora pendiente: datos de jornada aún no cerrados.")

    lesiones, suspendidos = contar_bajas(partido)

    if lesiones or suspendidos:
        score += min(20, lesiones * 6 + suspendidos * 8)
        razones.append(f"Bajas detectadas: lesiones={lesiones}, suspendidos={suspendidos}.")
    elif partido.get("bajas_revisadas"):
        razones.append("Bajas revisadas por IA: sin bajas confirmadas.")
    else:
        score += 8
        razones.append("Bajas no revisadas: riesgo informativo.")

    probs = obtener_probabilidades_si_existen(partido)

    if probs:
        p_local = probs["local"]
        p_empate = probs["empate"]
        p_visita = probs["visitante"]

        # Soporta 0-1 o 0-100.
        if p_local <= 1 and p_empate <= 1 and p_visita <= 1:
            p_local *= 100
            p_empate *= 100
            p_visita *= 100

        no_perder_local = p_local + p_empate

        if p_empate >= 28:
            score += 12
            razones.append("Empate alto: peligro para picks de ganador.")

        if p_visita >= 25:
            score += 10
            razones.append("Probabilidad visitante peligrosa: posible tumba quiniela.")

        if no_perder_local < 75:
            score += 10
            razones.append("Avance Survivor local por debajo de zona cómoda.")

        if p_local < 50:
            score += 10
            razones.append("Favorito local débil o partido demasiado parejo.")

    score = max(0, min(100, score))

    if score >= 65:
        nivel = "ROJO"
        etiqueta = "🔴 TUMBA QUINIELAS"
        recomendacion = "EVITAR como pick principal Survivor salvo que no haya alternativas."
    elif score >= 45:
        nivel = "AMARILLO"
        etiqueta = "🟡 RIESGO MEDIO"
        recomendacion = "Usar solo si la probabilidad de no perder es claramente superior a las alternativas."
    else:
        nivel = "VERDE"
        etiqueta = "🟢 RIESGO BAJO"
        recomendacion = "Candidato aceptable si también lidera en probabilidad de no perder."

    return {
        "score": score,
        "nivel": nivel,
        "etiqueta": etiqueta,
        "recomendacion": recomendacion,
        "razones": razones,
        "actualizado_en": datetime.now().isoformat(timespec="seconds"),
    }


def main() -> int:
    if not JORNADAS_PATH.exists():
        raise SystemExit(f"ERROR: No existe {JORNADAS_PATH}")

    data = json.loads(JORNADAS_PATH.read_text(encoding="utf-8"))
    partidos = extraer_partidos(data)

    if not partidos:
        raise SystemExit("ERROR: No encontré partidos en data/jornadas.json")

    for partido in partidos:
        partido["riesgo_sorpresa"] = calcular_riesgo(partido)

    if isinstance(data, dict):
        data["_riesgo_sorpresa"] = {
            "actualizado_por": "src/riesgo_sorpresa.py",
            "actualizado_en": datetime.now().isoformat(timespec="seconds"),
            "criterio": "Liga MX: prioridad Survivor no perder + castigo por empate/sorpresa/rivalidad/datos incompletos.",
        }

    JORNADAS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("🧨 RIESGO TUMBA QUINIELAS — LIGA MX")
    print("=" * 60)

    for partido in partidos:
        local = buscar_valor(partido, LOCAL_KEYS)
        visitante = buscar_valor(partido, VISITANTE_KEYS)
        riesgo = partido.get("riesgo_sorpresa", {})

        print(f"{local} vs {visitante}")
        print(f"   {riesgo.get('etiqueta')} | Score: {riesgo.get('score')}/100")
        print(f"   Recomendación: {riesgo.get('recomendacion')}")
        for razon in riesgo.get("razones", [])[:4]:
            print(f"   - {razon}")
        print("")

    print("✅ Riesgo de sorpresa actualizado en data/jornadas.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
