#!/usr/bin/env python3
"""
analizador_ia.py

Analizador IA para Survivor Liga MX.

Objetivo:
- Recibir/simular un texto largo con noticias de Liga MX.
- Enviar el texto a Llama 3.3 en GroqCloud usando la librería oficial `groq`.
- Extraer un JSON limpio con jugadores confirmados como BAJA por lesión o suspensión.
- Opcionalmente marcar esas bajas dentro de data/jornadas.json.

Uso:
    python3 src/analizador_ia.py

Aplicar cambios a data/jornadas.json:
    python3 src/analizador_ia.py --aplicar

Leer noticias desde archivo:
    python3 src/analizador_ia.py --archivo-noticias data/noticias_ligamx.txt --aplicar
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    from groq import Groq
except ImportError:
    Groq = None


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
JORNADAS_PATH = DATA_DIR / "jornadas.json"

GROQ_MODEL = os.getenv("GROQ_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")


NOTICIAS_DEMO = """
Reporte Liga MX - simulación de noticias largas:

En conferencia de prensa, el técnico de Tigres confirmó que André-Pierre Gignac
no estará disponible para el próximo partido debido a una molestia muscular.
El club informó que será baja por lesión y continuará con trabajo diferenciado.

Por otro lado, América recupera a varios jugadores, aunque Kevin Álvarez sigue
en evaluación. No hay confirmación de baja para él.

Chivas informó que Roberto Alvarado está suspendido por acumulación de tarjetas
y no podrá disputar la siguiente jornada. El cuerpo técnico ya prepara una
alternativa por derecha.

En Monterrey, Sergio Canales entrenó con normalidad y apunta a ser titular.
No se reportan bajas confirmadas.

Pumas confirmó que Lisandro Magallán no jugará por suspensión después de la
tarjeta roja recibida en la jornada anterior.

Cruz Azul mantiene en duda a Gabriel Fernández, pero el club no ha confirmado
que esté descartado. Por ahora se considera duda, no baja oficial.
"""


def ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalizar_texto(texto: str) -> str:
    """
    Normaliza texto para comparar nombres/equipos sin depender de acentos,
    mayúsculas o espacios raros.
    """
    texto = texto or ""
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = texto.lower()
    texto = re.sub(r"[^a-z0-9ñ\s]", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def nombres_similares(a: str, b: str) -> bool:
    """
    Comparación simple y segura para nombres de jugadores/equipos.
    Evita ser demasiado agresiva para no marcar al jugador equivocado.
    """
    na = normalizar_texto(a)
    nb = normalizar_texto(b)

    if not na or not nb:
        return False

    if na == nb:
        return True

    if len(na) >= 6 and len(nb) >= 6:
        if na in nb or nb in na:
            return True

    partes_a = set(na.split())
    partes_b = set(nb.split())

    if len(partes_a) >= 2 and partes_a.issubset(partes_b):
        return True

    if len(partes_b) >= 2 and partes_b.issubset(partes_a):
        return True

    return False


def construir_prompt_sistema() -> str:
    return """
Eres un extractor de datos deportivos para un bot de Survivor de Liga MX.

Tu tarea:
Analizar noticias, reportes médicos, suspensiones y conferencias de prensa.
Debes extraer SOLO jugadores CONFIRMADOS como NO DISPONIBLES para jugar
por LESIÓN o SUSPENSIÓN.

Reglas estrictas:
1. Devuelve únicamente JSON válido.
2. No inventes jugadores.
3. No incluyas jugadores en duda, cuestionables, probables o en evaluación.
4. No incluyas jugadores que ya entrenaron normal o que podrían jugar.
5. Si no hay bajas confirmadas, devuelve "bajas": [].
6. El campo "confianza" debe ser número entre 0 y 1.
7. El campo "motivo" solo puede ser: "lesion", "suspension" u "otro".
8. El JSON debe tener exactamente esta estructura:

{
  "bajas": [
    {
      "jugador": "Nombre del jugador",
      "equipo": "Nombre del equipo",
      "motivo": "lesion",
      "detalle": "Explicación corta",
      "partidos_afectados": ["próxima jornada"],
      "fuente_fragmento": "Fragmento corto del texto que justifica la baja",
      "confianza": 0.95
    }
  ],
  "resumen": "Resumen breve de las bajas detectadas"
}
""".strip()



FAILOVER_STATUS_CODES = {500, 502, 503, 504}
NO_ROTATE_STATUS_CODES = {401, 403, 429}


def key_valida(value: str) -> bool:
    if not value:
        return False

    value = value.strip()
    return bool(value) and "tu_api_key" not in value.lower()


def groq_key_candidates() -> list[tuple[str, str]]:
    primary = os.getenv("GROQ_API_KEY_PRIMARY", "").strip() or os.getenv("GROQ_API_KEY", "").strip()
    backup = os.getenv("GROQ_API_KEY_BACKUP", "").strip()

    keys: list[tuple[str, str]] = []
    seen = set()

    for label, value in [("primary", primary), ("backup", backup)]:
        if not key_valida(value):
            continue

        if value in seen:
            continue

        keys.append((label, value))
        seen.add(value)

    return keys


def status_code_from_exception(exc: Exception) -> int | None:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status

    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)

    if isinstance(response_status, int):
        return response_status

    return None


def es_falla_tecnica_groq(exc: Exception) -> bool:
    nombre = type(exc).__name__.lower()
    texto = str(exc).lower()

    patrones = [
        "timeout",
        "connection",
        "connect",
        "temporarily unavailable",
        "server error",
        "service unavailable",
        "bad gateway",
        "gateway timeout",
    ]

    return any(p in nombre or p in texto for p in patrones)


def llamar_groq_con_key(label: str, api_key: str, texto_noticias: str) -> Dict[str, Any]:
    client = Groq(api_key=api_key)

    respuesta = client.chat.completions.create(
        model=GROQ_MODEL,
        temperature=0,
        max_tokens=2500,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": construir_prompt_sistema(),
            },
            {
                "role": "user",
                "content": (
                    "Analiza este texto de noticias de Liga MX y devuelve JSON limpio "
                    "con los jugadores confirmados como baja:\n\n"
                    f"{texto_noticias}"
                ),
            },
        ],
    )

    contenido = respuesta.choices[0].message.content or "{}"
    return cargar_json_seguro(contenido)


def llamar_groq(texto_noticias: str) -> Dict[str, Any]:
    """
    Envía el texto a GroqCloud y devuelve el JSON parseado.
    Usa failover técnico solo en errores 5xx o fallas de red/timeout.
    No rota por 401/403/429.
    """
    if Groq is None:
        raise RuntimeError(
            "No está instalada la librería 'groq'. Instálala con: pip3 install groq"
        )

    keys = groq_key_candidates()

    if not keys:
        raise RuntimeError(
            "Falta GROQ_API_KEY_PRIMARY o GROQ_API_KEY. Configúrala antes de ejecutar."
        )

    last_error: Exception | None = None

    for idx, (label, api_key) in enumerate(keys):
        try:
            print(f"🤖 Groq: intentando llave {label}...")
            resultado = llamar_groq_con_key(label, api_key, texto_noticias)
            print(f"✅ Groq: análisis exitoso con llave {label}.")
            return resultado

        except Exception as exc:
            last_error = exc
            status = status_code_from_exception(exc)

            if status in FAILOVER_STATUS_CODES or (status is None and es_falla_tecnica_groq(exc)):
                print(f"⚠️ Groq falla técnica con llave {label}: {type(exc).__name__}")

                if idx < len(keys) - 1:
                    print("➡️ Probando llave backup por falla técnica de Groq.")
                    continue

                raise RuntimeError("Groq falló técnicamente y no hay más backup.") from exc

            if status in NO_ROTATE_STATUS_CODES:
                raise RuntimeError(
                    f"Groq respondió {status}. No se rota llave por auth/cuota/rate limit."
                ) from exc

            raise

    raise RuntimeError("No se pudo consultar Groq con ninguna llave.") from last_error

def cargar_json_seguro(contenido: str) -> Dict[str, Any]:
    """
    Intenta parsear JSON directo. Si el modelo agrega texto accidental,
    busca el primer bloque tipo objeto JSON.
    """
    contenido = contenido.strip()

    try:
        data = json.loads(contenido)
        return validar_salida_ia(data)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", contenido, flags=re.DOTALL)
    if not match:
        raise ValueError(f"La IA no devolvió JSON válido:\n{contenido}")

    data = json.loads(match.group(0))
    return validar_salida_ia(data)


def validar_salida_ia(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Limpia y valida la salida para que el resto del bot siempre reciba
    la misma estructura.
    """
    if not isinstance(data, dict):
        data = {}

    bajas_limpias: List[Dict[str, Any]] = []

    for item in data.get("bajas", []):
        if not isinstance(item, dict):
            continue

        jugador = str(item.get("jugador", "")).strip()
        equipo = str(item.get("equipo", "")).strip()
        motivo = str(item.get("motivo", "otro")).strip().lower()

        if not jugador or not equipo:
            continue

        if motivo not in {"lesion", "suspension", "otro"}:
            motivo = "otro"

        try:
            confianza = float(item.get("confianza", 0.75))
        except (TypeError, ValueError):
            confianza = 0.75

        confianza = max(0.0, min(1.0, confianza))

        partidos_afectados = item.get("partidos_afectados", [])
        if not isinstance(partidos_afectados, list):
            partidos_afectados = [str(partidos_afectados)]

        bajas_limpias.append(
            {
                "jugador": jugador,
                "equipo": equipo,
                "motivo": motivo,
                "detalle": str(item.get("detalle", "")).strip(),
                "partidos_afectados": [str(p).strip() for p in partidos_afectados if str(p).strip()],
                "fuente_fragmento": str(item.get("fuente_fragmento", "")).strip(),
                "confianza": confianza,
            }
        )

    resumen = str(data.get("resumen", "")).strip()
    if not resumen:
        resumen = f"Se detectaron {len(bajas_limpias)} bajas confirmadas."

    return {
        "bajas": bajas_limpias,
        "resumen": resumen,
        "modelo": GROQ_MODEL,
        "generado_en": ahora_iso(),
    }


def cargar_jornadas(path: Path = JORNADAS_PATH) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"No existe el archivo: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def guardar_jornadas(jornadas: Any, path: Path = JORNADAS_PATH) -> Path:
    """
    Guarda jornadas.json creando backup antes.
    """
    backup = path.with_suffix(f".backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json")

    if path.exists():
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    tmp = path.with_suffix(".tmp.json")
    tmp.write_text(
        json.dumps(jornadas, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)

    return backup


def obtener_nombre_jugador(obj: Dict[str, Any]) -> str:
    for key in ("nombre", "name", "jugador", "player"):
        valor = obj.get(key)
        if isinstance(valor, str) and valor.strip():
            return valor.strip()
    return ""


def obtener_equipo(obj: Dict[str, Any]) -> str:
    for key in ("equipo", "club", "team"):
        valor = obj.get(key)
        if isinstance(valor, str) and valor.strip():
            return valor.strip()
    return ""


def marcar_baja_dict_jugador(obj: Dict[str, Any], baja: Dict[str, Any]) -> bool:
    nombre_jugador = obtener_nombre_jugador(obj)
    if not nombre_jugador:
        return False

    if not nombres_similares(nombre_jugador, baja["jugador"]):
        return False

    equipo_obj = obtener_equipo(obj)
    if equipo_obj and not nombres_similares(equipo_obj, baja["equipo"]):
        return False

    obj["disponible"] = False
    obj["estatus"] = "baja"
    obj["baja_confirmada"] = True
    obj["motivo_baja"] = baja["motivo"]
    obj["detalle_baja"] = baja.get("detalle", "")
    obj["equipo_baja_reportado"] = baja["equipo"]
    obj["confianza_ia"] = baja.get("confianza", 0.75)
    obj["fuente_baja"] = baja.get("fuente_fragmento", "")
    obj["actualizado_por"] = "analizador_ia.py"
    obj["actualizado_en"] = ahora_iso()

    return True


def recorrer_y_marcar(
    obj: Any,
    bajas: List[Dict[str, Any]],
    parent_key: str = "",
) -> int:
    """
    Recorre estructuras flexibles de jornadas.json.

    Soporta:
    - jugadores como diccionarios:
      {"nombre": "Jugador", "equipo": "América"}
    - plantillas como listas de strings:
      "plantilla": ["Jugador A", "Jugador B"]

    Regresa cuántas marcas hizo.
    """
    marcas = 0
    parent_key_norm = normalizar_texto(parent_key)

    if isinstance(obj, dict):
        for baja in bajas:
            if marcar_baja_dict_jugador(obj, baja):
                marcas += 1

        for key, value in list(obj.items()):
            if key in {"bajas_ia", "_analizador_ia"}:
                continue
            marcas += recorrer_y_marcar(value, bajas, parent_key=key)

    elif isinstance(obj, list):
        lista_de_jugadores = parent_key_norm in {
            "plantilla",
            "plantillas",
            "jugadores",
            "players",
            "roster",
        }

        for idx, item in enumerate(obj):
            if isinstance(item, str) and lista_de_jugadores:
                for baja in bajas:
                    if nombres_similares(item, baja["jugador"]):
                        obj[idx] = {
                            "nombre": item,
                            "equipo": baja["equipo"],
                            "disponible": False,
                            "estatus": "baja",
                            "baja_confirmada": True,
                            "motivo_baja": baja["motivo"],
                            "detalle_baja": baja.get("detalle", ""),
                            "confianza_ia": baja.get("confianza", 0.75),
                            "fuente_baja": baja.get("fuente_fragmento", ""),
                            "actualizado_por": "analizador_ia.py",
                            "actualizado_en": ahora_iso(),
                        }
                        marcas += 1
                        break
            else:
                marcas += recorrer_y_marcar(item, bajas, parent_key=parent_key)

    return marcas


def aplicar_bajas_a_jornadas(jornadas: Any, resultado_ia: Dict[str, Any]) -> Tuple[Any, int]:
    """
    Devuelve una copia de jornadas con bajas marcadas.
    También agrega un bloque de auditoría si el JSON raíz es diccionario.
    """
    actualizado = copy.deepcopy(jornadas)
    bajas = resultado_ia.get("bajas", [])

    if not isinstance(bajas, list):
        bajas = []

    marcas = recorrer_y_marcar(actualizado, bajas)

    if isinstance(actualizado, dict):
        actualizado.setdefault("bajas_ia", [])
        actualizado["bajas_ia"].append(
            {
                "generado_en": resultado_ia.get("generado_en", ahora_iso()),
                "modelo": resultado_ia.get("modelo", GROQ_MODEL),
                "resumen": resultado_ia.get("resumen", ""),
                "bajas": bajas,
                "marcas_en_plantillas": marcas,
            }
        )

        actualizado["_analizador_ia"] = {
            "ultimo_update": ahora_iso(),
            "modelo": resultado_ia.get("modelo", GROQ_MODEL),
            "marcas_en_plantillas": marcas,
        }

    return actualizado, marcas


def leer_texto_noticias(args: argparse.Namespace) -> str:
    if args.texto:
        return args.texto

    if args.archivo_noticias:
        path = Path(args.archivo_noticias)
        if not path.exists():
            raise FileNotFoundError(f"No existe el archivo de noticias: {path}")
        return path.read_text(encoding="utf-8")

    return NOTICIAS_DEMO


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analiza noticias de Liga MX con Groq/Llama 3.3 y detecta bajas confirmadas."
    )
    parser.add_argument(
        "--texto",
        help="Texto directo con noticias de Liga MX.",
    )
    parser.add_argument(
        "--archivo-noticias",
        help="Ruta a un archivo .txt con noticias largas.",
    )
    parser.add_argument(
        "--jornadas",
        default=str(JORNADAS_PATH),
        help="Ruta a data/jornadas.json.",
    )
    parser.add_argument(
        "--aplicar",
        action="store_true",
        help="Si se activa, marca las bajas dentro de data/jornadas.json.",
    )
    parser.add_argument(
        "--salida",
        help="Ruta opcional para guardar el JSON de bajas detectadas.",
    )

    args = parser.parse_args()

    try:
        texto_noticias = leer_texto_noticias(args)
        resultado_ia = llamar_groq(texto_noticias)

        print(json.dumps(resultado_ia, ensure_ascii=False, indent=2))

        if args.salida:
            salida_path = Path(args.salida)
            salida_path.parent.mkdir(parents=True, exist_ok=True)
            salida_path.write_text(
                json.dumps(resultado_ia, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"\nJSON de bajas guardado en: {salida_path}", file=sys.stderr)

        if args.aplicar:
            jornadas_path = Path(args.jornadas)
            jornadas = cargar_jornadas(jornadas_path)
            jornadas_actualizadas, marcas = aplicar_bajas_a_jornadas(jornadas, resultado_ia)
            backup = guardar_jornadas(jornadas_actualizadas, jornadas_path)

            print(f"\nBajas marcadas en plantillas: {marcas}", file=sys.stderr)
            print(f"Backup creado en: {backup}", file=sys.stderr)
            print(f"Archivo actualizado: {jornadas_path}", file=sys.stderr)

        return 0

    except Exception as exc:
        print(f"ERROR analizador_ia.py: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
