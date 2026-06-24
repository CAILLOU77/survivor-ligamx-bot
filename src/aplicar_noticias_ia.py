#!/usr/bin/env python3
from __future__ import annotations

import json
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from analizador_ia import llamar_groq


BASE_DIR = Path(__file__).resolve().parents[1]
JORNADAS_PATH = BASE_DIR / "data" / "jornadas.json"
NOTICIAS_PATH = BASE_DIR / "data" / "noticias_ligamx.txt"
SALIDA_BAJAS_PATH = BASE_DIR / "data" / "bajas_ia_ultimo.json"


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


def equipo_coincide(equipo_baja: str, equipo_partido: str) -> bool:
    a = normalizar(equipo_baja)
    b = normalizar(equipo_partido)

    if not a or not b:
        return False

    return a == b or a in b or b in a


def ya_existe_baja(lista: List[Dict[str, Any]], jugador: str) -> bool:
    j = normalizar(jugador)
    for item in lista:
        if normalizar(str(item.get("jugador", ""))) == j:
            return True
    return False


def aplicar_baja_a_partido(partido: Dict[str, Any], baja: Dict[str, Any]) -> bool:
    local = str(buscar_valor(partido, LOCAL_KEYS) or "")
    visitante = str(buscar_valor(partido, VISITANTE_KEYS) or "")
    equipo_baja = str(baja.get("equipo", ""))

    if not equipo_coincide(equipo_baja, local) and not equipo_coincide(equipo_baja, visitante):
        return False

    motivo = str(baja.get("motivo", "otro")).lower().strip()

    registro = {
        "jugador": baja.get("jugador", ""),
        "equipo": baja.get("equipo", ""),
        "motivo": motivo,
        "detalle": baja.get("detalle", ""),
        "confianza_ia": baja.get("confianza", 0.75),
        "fuente_fragmento": baja.get("fuente_fragmento", ""),
        "actualizado_por": "src/aplicar_noticias_ia.py",
        "actualizado_en": datetime.now().isoformat(timespec="seconds"),
    }

    if motivo == "suspension":
        partido.setdefault("suspendidos", [])
        if not ya_existe_baja(partido["suspendidos"], registro["jugador"]):
            partido["suspendidos"].append(registro)
            return True
        return False

    partido.setdefault("lesiones", [])
    if not ya_existe_baja(partido["lesiones"], registro["jugador"]):
        partido["lesiones"].append(registro)
        return True

    return False


def main() -> int:
    if not JORNADAS_PATH.exists():
        raise SystemExit(f"ERROR: No existe {JORNADAS_PATH}")

    if not NOTICIAS_PATH.exists():
        raise SystemExit(f"ERROR: No existe {NOTICIAS_PATH}")

    texto_noticias = NOTICIAS_PATH.read_text(encoding="utf-8")
    resultado_ia = llamar_groq(texto_noticias)

    SALIDA_BAJAS_PATH.write_text(
        json.dumps(resultado_ia, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    data = json.loads(JORNADAS_PATH.read_text(encoding="utf-8"))

    backup = JORNADAS_PATH.with_suffix(
        f".backup-bajas-ia-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    )
    backup.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    partidos = extraer_partidos(data)
    bajas = resultado_ia.get("bajas", [])

    aplicadas = 0

    for partido in partidos:
        partido["bajas_revisadas"] = True

        for baja in bajas:
            if aplicar_baja_a_partido(partido, baja):
                aplicadas += 1

    JORNADAS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"✅ Bajas detectadas por IA: {len(bajas)}")
    print(f"✅ Bajas aplicadas a partidos: {aplicadas}")
    print(f"✅ Backup creado: {backup}")
    print(f"✅ Resultado IA guardado: {SALIDA_BAJAS_PATH}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
