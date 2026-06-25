#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

from analizador_ia import llamar_groq

try:
    from api_budget import can_call as budget_can_call
    from api_budget import record_call as budget_record_call
    from api_budget import write_report as budget_write_report
except Exception:
    budget_can_call = None
    budget_record_call = None
    budget_write_report = None


BASE_DIR = Path(__file__).resolve().parents[1]
JORNADAS_PATH = BASE_DIR / "data" / "jornadas.json"
NOTICIAS_PATH = BASE_DIR / "data" / "noticias_ligamx.txt"
SALIDA_BAJAS_PATH = BASE_DIR / "data" / "bajas_ia_ultimo.json"
SALIDA_REVISION_PATH = BASE_DIR / "data" / "bajas_ia_pendientes_revision.json"
GROQ_CACHE_MINUTES = int(os.getenv("GROQ_CACHE_MINUTES", "60"))
GROQ_MAX_NOTICIAS = int(os.getenv("GROQ_MAX_NOTICIAS", "15"))
GROQ_MAX_INPUT_CHARS = int(os.getenv("GROQ_MAX_INPUT_CHARS", "18000"))
GROQ_MAX_RESUMEN_CHARS = int(os.getenv("GROQ_MAX_RESUMEN_CHARS", "300"))


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


PALABRAS_CLAVE_IA = [
    "lesión", "lesion", "lesionado", "lesionados",
    "suspendido", "suspensión", "suspension", "sancionado",
    "baja", "bajas", "descartado", "no jugará", "no jugara",
    "no estará", "no estara", "duda", "molestia",
    "entrenó separado", "entreno separado", "convocatoria",
    "rueda de prensa", "alineación", "alineacion", "titular",
    "regresa", "alta médica", "alta medica",
]


def score_noticia_para_ia(bloque: str) -> int:
    texto = bloque.lower()
    return sum(1 for palabra in PALABRAS_CLAVE_IA if palabra in texto)


def recortar_bloque_noticia_para_ia(bloque: str) -> str:
    lineas = []

    for linea in bloque.splitlines():
        if linea.startswith("Link:"):
            continue

        if linea.startswith("Resumen:"):
            resumen = linea.replace("Resumen:", "", 1).strip()
            if len(resumen) > GROQ_MAX_RESUMEN_CHARS:
                resumen = resumen[:GROQ_MAX_RESUMEN_CHARS].rstrip() + "..."
            lineas.append(f"Resumen: {resumen}")
            continue

        if linea.startswith("Título:") and len(linea) > 240:
            lineas.append(linea[:240].rstrip() + "...")
            continue

        lineas.append(linea)

    return "\n".join(lineas).strip()


def preparar_texto_noticias_para_groq(texto: str) -> str:
    partes = re.split(r"\n(?=NOTICIA #\d+)", texto)
    encabezado = partes[0].strip() if partes else ""

    bloques = [
        parte.strip()
        for parte in partes[1:]
        if parte.strip().startswith("NOTICIA #")
    ]

    if not bloques:
        return texto[:GROQ_MAX_INPUT_CHARS].rstrip()

    puntuados = sorted(
        bloques,
        key=lambda bloque: score_noticia_para_ia(bloque),
        reverse=True,
    )

    seleccionados = puntuados[:GROQ_MAX_NOTICIAS]
    seleccionados = [recortar_bloque_noticia_para_ia(b) for b in seleccionados]

    salida = [
        encabezado,
        "",
        f"NOTA: Entrada recortada dentro de aplicar_noticias_ia.py para Groq.",
        f"Máximo noticias enviadas: {GROQ_MAX_NOTICIAS}.",
        f"Máximo caracteres enviados: {GROQ_MAX_INPUT_CHARS}.",
        "Prioridad: bajas confirmadas, lesiones, suspensiones, dudas, convocatorias y ruedas de prensa.",
        "",
    ]

    salida.extend(seleccionados)
    texto_final = "\n\n".join(salida).strip()

    if len(texto_final) > GROQ_MAX_INPUT_CHARS:
        texto_final = texto_final[:GROQ_MAX_INPUT_CHARS].rstrip() + "\n\n[RECORTADO POR LIMITE INTERNO]"

    return texto_final


def sha256_texto(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def cache_ia_fresco(
    texto_noticias: str,
    max_minutes: int = GROQ_CACHE_MINUTES,
) -> Tuple[bool, str, Dict[str, Any]]:
    if max_minutes <= 0:
        return False, "Cache IA desactivado por GROQ_CACHE_MINUTES<=0.", {}

    if not SALIDA_BAJAS_PATH.exists():
        return False, "No existe cache IA previo.", {}

    try:
        resultado = json.loads(SALIDA_BAJAS_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"No se pudo leer cache IA: {exc}", {}

    if not isinstance(resultado, dict):
        return False, "Cache IA inválido: no es objeto JSON.", {}

    if resultado.get("fuente") == "budget_blocked":
        return False, "Cache IA anterior fue bloqueo de presupuesto; no se reutiliza.", {}

    hash_actual = sha256_texto(texto_noticias)
    hash_cache = str(resultado.get("noticias_sha256", "")).strip()

    if hash_cache != hash_actual:
        return False, "Noticias cambiaron o cache IA no tiene hash compatible.", {}

    generado_raw = str(resultado.get("generado_en", "")).strip()
    if not generado_raw:
        return False, "Cache IA sin timestamp generado_en.", {}

    try:
        generado = datetime.fromisoformat(generado_raw)
    except Exception:
        return False, f"Cache IA con timestamp inválido: {generado_raw}", {}

    edad = datetime.now() - generado
    minutos = int(edad.total_seconds() // 60)

    if edad <= timedelta(minutes=max_minutes):
        return (
            True,
            f"Cache IA vigente: generado en {generado_raw}, hace {minutos} min, límite {max_minutes} min.",
            resultado,
        )

    return False, f"Cache IA vencido: generado hace {minutos} min, límite {max_minutes} min.", {}


def preparar_resultado_ia(
    resultado_ia: Any,
    texto_noticias: str,
    fuente_default: str,
) -> Dict[str, Any]:
    if not isinstance(resultado_ia, dict):
        resultado_ia = {
            "bajas": [],
            "pendientes_revision": [],
            "resumen": "Respuesta IA inválida. No se aplican bajas.",
            "actualizado_por": "src/aplicar_noticias_ia.py",
            "fuente": "respuesta_invalida",
        }

    resultado_ia.setdefault("bajas", [])
    resultado_ia.setdefault("pendientes_revision", [])
    resultado_ia.setdefault("actualizado_por", "src/aplicar_noticias_ia.py")
    resultado_ia.setdefault("fuente", fuente_default)
    resultado_ia["generado_en"] = datetime.now().isoformat(timespec="seconds")
    resultado_ia["noticias_sha256"] = sha256_texto(texto_noticias)
    resultado_ia["groq_cache_minutes"] = GROQ_CACHE_MINUTES

    return resultado_ia


def llamar_groq_seguro(texto_noticias: str) -> Dict[str, Any]:
    try:
        return llamar_groq(texto_noticias)
    except Exception as exc:
        mensaje = str(exc)
        print(f"⚠️ Groq falló: {type(exc).__name__}")
        print(f"   Detalle: {mensaje[:500]}")
        print("➡️ No se aplican bajas nuevas para evitar inventar información.")

        return {
            "bajas": [],
            "pendientes_revision": [],
            "resumen": "Groq falló durante el análisis. No se detectan bajas nuevas sin IA.",
            "actualizado_por": "src/aplicar_noticias_ia.py",
            "fuente": "groq_error",
            "error_tipo": type(exc).__name__,
            "error_mensaje": mensaje[:1200],
        }


def main() -> int:
    if not JORNADAS_PATH.exists():
        raise SystemExit(f"ERROR: No existe {JORNADAS_PATH}")

    if not NOTICIAS_PATH.exists():
        raise SystemExit(f"ERROR: No existe {NOTICIAS_PATH}")

    texto_noticias_original = NOTICIAS_PATH.read_text(encoding="utf-8")
    texto_noticias = preparar_texto_noticias_para_groq(texto_noticias_original)

    if len(texto_noticias) != len(texto_noticias_original):
        print(
            f"✂️ Noticias para Groq recortadas: "
            f"{len(texto_noticias_original)} -> {len(texto_noticias)} caracteres"
        )
    else:
        print(f"📄 Noticias para Groq: {len(texto_noticias)} caracteres")

    cache_ok, cache_msg, resultado_cache = cache_ia_fresco(texto_noticias)

    if cache_ok:
        print("🤖 Usando cache fresco de análisis IA Groq.")
        print(f"♻️ {cache_msg}")
        print("➡️ No se llama Groq en esta corrida.")
        resultado_ia = resultado_cache

        if budget_write_report is not None:
            budget_write_report()

    else:
        print(f"🟡 Cache IA no usable: {cache_msg}")

        if budget_can_call is not None:
            permitido, mensaje_budget = budget_can_call(
                "groq",
                units=1,
                min_interval_minutes=0,
            )

            if not permitido:
                print(f"⏸️ Groq bloqueado por presupuesto: {mensaje_budget}")
                print("➡️ No se llama IA. Se deja bajas=0 para evitar inventar información.")

                resultado_ia = {
                    "bajas": [],
                    "pendientes_revision": [],
                    "resumen": "Groq bloqueado por presupuesto. No se detectan bajas nuevas sin IA.",
                    "actualizado_por": "src/aplicar_noticias_ia.py",
                    "fuente": "budget_blocked",
                }

                if budget_write_report is not None:
                    budget_write_report()
            else:
                resultado_ia = llamar_groq_seguro(texto_noticias)
                resultado_ia = preparar_resultado_ia(
                    resultado_ia,
                    texto_noticias,
                    fuente_default="groq",
                )

                if budget_record_call is not None:
                    budget_record_call(
                        "groq",
                        units=1,
                        note=f"aplicar_noticias_ia chars={len(texto_noticias)}",
                    )

                if budget_write_report is not None:
                    budget_write_report()
        else:
            resultado_ia = llamar_groq_seguro(texto_noticias)
            resultado_ia = preparar_resultado_ia(
                resultado_ia,
                texto_noticias,
                fuente_default="groq",
            )

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
