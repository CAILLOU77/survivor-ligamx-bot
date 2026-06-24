#!/usr/bin/env python3
from __future__ import annotations

import json
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from analizador_ia import llamar_groq


BASE_DIR = Path(__file__).resolve().parents[1]
JORNADAS_PATH = BASE_DIR / "data" / "jornadas.json"
NOTICIAS_PATH = BASE_DIR / "data" / "noticias_ligamx.txt"
SALIDA_BAJAS_PATH = BASE_DIR / "data" / "bajas_ia_ultimo.json"
SALIDA_REVISION_PATH = BASE_DIR / "data" / "bajas_ia_pendientes_revision.json"


LOCAL_KEYS = ["local", "equipo_local", "home", "home_team", "casa"]
VISITANTE_KEYS = ["visitante", "equipo_visitante", "away", "away_team", "visita"]


TERMINOS_CONFIRMACION = [
    "no jugará",
    "no jugara",
    "no estará",
    "no estara",
    "será baja",
    "sera baja",
    "es baja",
    "baja confirmada",
    "descartado",
    "descartada",
    "suspendido",
    "suspendida",
    "suspensión",
    "suspension",
    "sancionado",
    "tarjeta roja",
    "acumulación de tarjetas",
    "acumulacion de tarjetas",
    "fractura",
    "rotura",
    "operado",
    "quirófano",
    "quirofano",
]

TERMINOS_DEBILES = [
    "duda",
    "en duda",
    "podría",
    "podria",
    "evaluación",
    "evaluacion",
    "probable",
    "posible",
    "molestia",
    "entrenó separado",
    "entreno separado",
    "trabajo diferenciado",
    "se espera",
    "apunta",
    "podria jugar",
    "podría jugar",
]


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


def limpiar_bajas_ia_previas(partido: Dict[str, Any]) -> None:
    """
    Borra bajas anteriores generadas por IA para evitar que una noticia vieja
    siga afectando el partido cuando el nuevo reporte ya no confirma esa baja.
    Conserva bajas manuales.
    """
    for campo in ["lesiones", "suspendidos"]:
        valor = partido.get(campo, [])
        if not isinstance(valor, list):
            partido[campo] = []
            continue

        partido[campo] = [
            item for item in valor
            if not (
                isinstance(item, dict)
                and str(item.get("actualizado_por", "")).startswith("src/aplicar_noticias_ia.py")
            )
        ]


def texto_baja(baja: Dict[str, Any]) -> str:
    partes = [
        str(baja.get("jugador", "")),
        str(baja.get("equipo", "")),
        str(baja.get("motivo", "")),
        str(baja.get("detalle", "")),
        str(baja.get("fuente_fragmento", "")),
    ]
    return normalizar(" ".join(partes))


def es_baja_confiable(baja: Dict[str, Any], partido: Dict[str, Any]) -> Tuple[bool, str]:
    jugador = str(baja.get("jugador", "")).strip()
    equipo = str(baja.get("equipo", "")).strip()
    motivo = str(baja.get("motivo", "")).strip().lower()
    detalle = str(baja.get("detalle", "")).strip()
    fragmento = str(baja.get("fuente_fragmento", "")).strip()

    local = str(buscar_valor(partido, LOCAL_KEYS) or "")
    visitante = str(buscar_valor(partido, VISITANTE_KEYS) or "")

    try:
        confianza = float(baja.get("confianza", 0))
    except Exception:
        confianza = 0

    texto = texto_baja(baja)

    if not jugador:
        return False, "sin_jugador"

    if not equipo:
        return False, "sin_equipo"

    if motivo not in {"lesion", "suspension"}:
        return False, "motivo_no_aplicable"

    if not equipo_coincide(equipo, local) and not equipo_coincide(equipo, visitante):
        return False, "equipo_no_pertenece_al_partido"

    if confianza < 0.88:
        return False, "confianza_baja"

    tiene_confirmacion = any(t in texto for t in TERMINOS_CONFIRMACION)
    tiene_debil = any(t in texto for t in TERMINOS_DEBILES)

    # Evita aceptar salidas genéricas tipo "Lesionado" sin prueba real.
    if len(detalle) < 12 and len(fragmento) < 30:
        return False, "detalle_o_fuente_demasiado_generico"

    if not tiene_confirmacion:
        return False, "sin_frase_de_confirmacion_fuerte"

    if tiene_debil and not ("no jugara" in texto or "no jugara" in texto or "no estara" in texto or "descartado" in texto):
        return False, "texto_parece_duda_no_confirmacion"

    return True, "confirmada"


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
    pendientes_revision: List[Dict[str, Any]] = []

    for partido in partidos:
        limpiar_bajas_ia_previas(partido)
        partido["bajas_revisadas"] = True

        for baja in bajas:
            local = str(buscar_valor(partido, LOCAL_KEYS) or "")
            visitante = str(buscar_valor(partido, VISITANTE_KEYS) or "")
            equipo_baja = str(baja.get("equipo", ""))

            if not equipo_coincide(equipo_baja, local) and not equipo_coincide(equipo_baja, visitante):
                continue

            confiable, razon = es_baja_confiable(baja, partido)

            if confiable:
                if aplicar_baja_a_partido(partido, baja):
                    aplicadas += 1
            else:
                pendientes_revision.append(
                    {
                        "partido": f"{local} vs {visitante}",
                        "baja": baja,
                        "razon_no_aplicada": razon,
                        "actualizado_en": datetime.now().isoformat(timespec="seconds"),
                    }
                )

    SALIDA_REVISION_PATH.write_text(
        json.dumps(
            {
                "generado_en": datetime.now().isoformat(timespec="seconds"),
                "pendientes_revision": pendientes_revision,
                "nota": "Estas bajas fueron detectadas por IA pero NO aplicadas por filtro conservador anti-falsos positivos.",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    JORNADAS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"✅ Bajas detectadas por IA: {len(bajas)}")
    print(f"✅ Bajas aplicadas a partidos: {aplicadas}")
    print(f"🟡 Bajas mandadas a revisión: {len(pendientes_revision)}")
    print(f"✅ Backup creado: {backup}")
    print(f"✅ Resultado IA guardado: {SALIDA_BAJAS_PATH}")
    print(f"✅ Pendientes revisión guardadas: {SALIDA_REVISION_PATH}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
