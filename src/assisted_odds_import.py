#!/usr/bin/env python3
"""
assisted_odds_import.py — Assisted Sportsbook Odds Import (Survivor Liga MX).

v1.39.1.

Lógica PURA de parseo/validación/reporte para una importación ASISTIDA POR
USUARIO de momios 1X2 desde un sportsbook (ej. Caliente Liga MX).

Modelo asistido (NO automatizado):
- El navegador se abre VISIBLE (lo hace el script CLI, no este módulo).
- El usuario completa manualmente cualquier verificación/login si aparece.
- Después el bot solo lee el TEXTO VISIBLE de la página y lo parsea aquí.

Reglas duras (este módulo no rompe ninguna):
- NO stealth. NO playwright-stealth. NO proxy. NO bypass de
  firewall/captcha/login/verificación. NO automatiza login. NO guarda
  credenciales. NO manda Telegram. NO cambia picks. NO imprime secretos.
- Decisión operativa SIEMPRE: ESPERAR / NO ENVIAR. Nunca marca un pick listo.

Este módulo no hace red, no abre navegador y no toca .env: solo recibe texto
ya capturado y devuelve estructuras + reportes en texto.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
VERSION = "v1.39.1"

# Decisión operativa: este flujo asistido NUNCA cierra ni envía un pick.
DEC_ESPERAR = "ESPERAR / NO ENVIAR"

# Estados de resultado del parseo.
STATUS_OK = "OK"
STATUS_NO_MATCHES = "NO_MATCHES_FOUND"
# Se detectaron momios en el texto pero no se pudieron formar partidos completos.
STATUS_PARSER_NEEDS_REVIEW = "PARSER_NEEDS_REVIEW"

LIGA = "Liga MX"
FUENTE = "assisted_manual_sportsbook"

# Etiquetas posibles para el empate (columna central del 1X2).
_DRAW_LABELS = ("empate", "draw", "x")

# Meses ES/EN (abreviados o completos) -> número de mes.
_MESES: Dict[str, int] = {
    "ene": 1, "enero": 1, "jan": 1, "january": 1,
    "feb": 2, "febrero": 2, "february": 2,
    "mar": 3, "marzo": 3, "march": 3,
    "abr": 4, "abril": 4, "apr": 4, "april": 4,
    "may": 5, "mayo": 5,
    "jun": 6, "junio": 6, "june": 6,
    "jul": 7, "julio": 7, "july": 7,
    "ago": 8, "agosto": 8, "aug": 8, "august": 8,
    "sep": 9, "set": 9, "sept": 9, "septiembre": 9, "september": 9,
    "oct": 10, "octubre": 10, "october": 10,
    "nov": 11, "noviembre": 11, "november": 11,
    "dic": 12, "diciembre": 12, "dec": 12, "december": 12,
}

# Un momio americano: signo obligatorio + 2 a 4 dígitos (ej. +120, -125, +275).
_RE_MOMIO = re.compile(r"^[+-]\d{2,4}$")

# Magnitud mínima válida de un momio americano (even money = ±100).
_MOMIO_MIN_ABS = 100


# ---------------------------------------------------------------------------
# Patrón de evento SINGLE-LINE (formato original v1.39.0)
#
#   HH:MM  DD  Mon  EquipoLocal  MOMIO  Empate  MOMIO  EquipoVisitante  MOMIO
#   19:00  16  Jul  Necaxa       -125   Empate  +260   Atlante          +275
#
# Notas de diseño anti-mezcla: la clase de nombre de equipo excluye dígitos y
# signos +/-; no cruza saltos de línea. finditer extrae cada evento de forma
# independiente, sin combinar partidos de un bloque gigante de DOM.
# ---------------------------------------------------------------------------
_EQUIPO = r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ.''/ ]+?"
_MOMIO_G = r"[+-]\d{2,4}"

_RE_EVENTO = re.compile(
    r"(?P<hora>\d{1,2}:\d{2})[ \t]+"
    r"(?P<dia>\d{1,2})[ \t]+"
    r"(?P<mes>[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{3,12})\.?[ \t]+"
    r"(?P<local>" + _EQUIPO + r")[ \t]+"
    r"(?P<momio_local>" + _MOMIO_G + r")[ \t]+"
    r"(?:Empate|Draw|X)[ \t]+"
    r"(?P<momio_empate>" + _MOMIO_G + r")[ \t]+"
    r"(?P<visitante>" + _EQUIPO + r")[ \t]+"
    r"(?P<momio_visitante>" + _MOMIO_G + r")",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Patrón de momio suelto — para detectar si hay momios en texto multiline.
# ---------------------------------------------------------------------------
_RE_MOMIO_SUELTO = re.compile(r"(?:^|[ \t])([+-]\d{2,4})(?:[ \t]|$)", re.MULTILINE)

# ---------------------------------------------------------------------------
# Palabras clave que identifican mercados de CAMPEÓN / FUTURO (no 1X2).
# Un bloque que contenga estas palabras se salta para evitar mezcla de mercados.
# ---------------------------------------------------------------------------
_FUTURO_KEYWORDS = re.compile(
    r"\b(campe[oó]n|champion|liga campeona|ganador|winner|futuro|futures|"
    r"titulo|t[ií]tulo|ascenso|descenso|relegation)\b",
    re.IGNORECASE,
)



# ---------------------------------------------------------------------------
# Helpers de normalización / validación
# ---------------------------------------------------------------------------
def _quitar_acentos(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _norm_equipo(nombre: str) -> str:
    """Normaliza nombre de equipo SOLO para comparar/deduplicar (no para mostrar)."""
    base = _quitar_acentos(str(nombre or "")).lower()
    base = re.sub(r"[^a-z0-9 ]+", " ", base)
    return re.sub(r"\s+", " ", base).strip()


def es_momio_americano_valido(momio: Any) -> bool:
    """True si `momio` es un momio americano válido (±NN..±NNNN, |valor| >= 100)."""
    s = str(momio or "").strip()
    if not _RE_MOMIO.fullmatch(s):
        return False
    try:
        return abs(int(s)) >= _MOMIO_MIN_ABS
    except (TypeError, ValueError):
        return False


def _mes_a_numero(mes: str) -> int:
    """Devuelve el número de mes (1-12) o 0 si no se reconoce."""
    clave = _quitar_acentos(str(mes or "")).lower().strip(".")
    if clave in _MESES:
        return _MESES[clave]
    # Tolera abreviaturas de 3 letras de meses largos no listados.
    return _MESES.get(clave[:3], 0)


def evento_momios_validos(evento: Dict[str, Any]) -> bool:
    """True si los tres momios del evento son americanos válidos."""
    return all(
        es_momio_americano_valido(evento.get(campo))
        for campo in ("momio_local", "momio_empate", "momio_visitante")
    )



# ---------------------------------------------------------------------------
# Parseo SINGLE-LINE (formato original v1.39.0)
# ---------------------------------------------------------------------------
def _construir_evento(m: "re.Match[str]") -> Dict[str, Any]:
    dia = m.group("dia").strip()
    mes_raw = m.group("mes").strip()
    mes_num = _mes_a_numero(mes_raw)
    return {
        "hora": m.group("hora").strip(),
        "dia": int(dia),
        "mes_texto": mes_raw,
        "mes": mes_num,
        "fecha": f"{int(dia):02d} {mes_raw}",
        "equipo_local": m.group("local").strip(),
        "equipo_visitante": m.group("visitante").strip(),
        "momio_local": m.group("momio_local").strip(),
        "momio_empate": m.group("momio_empate").strip(),
        "momio_visitante": m.group("momio_visitante").strip(),
    }


def extraer_eventos_crudos(texto: str) -> List[Dict[str, Any]]:
    """
    Extrae todos los eventos candidatos del texto visible (formato single-line).

    Filtra coincidencias con mes no reconocido o día fuera de rango (1-31),
    lo que evita falsos positivos cuando el DOM trae un bloque gigante.
    """
    eventos: List[Dict[str, Any]] = []
    for m in _RE_EVENTO.finditer(str(texto or "")):
        ev = _construir_evento(m)
        if ev["mes"] == 0:
            continue
        if not (1 <= ev["dia"] <= 31):
            continue
        if not ev["equipo_local"] or not ev["equipo_visitante"]:
            continue
        eventos.append(ev)
    return eventos



# ---------------------------------------------------------------------------
# Parseo MULTILINE (nuevo en v1.39.1)
#
# Caliente cuando se copia desde Chrome normal produce bloques como:
#
#   Necaxa
#   -125
#   Empate
#   +260
#   Atlante
#   +275
#
# La estrategia:
# 1. Dividir el texto en líneas, eliminar líneas vacías y espacios laterales.
# 2. Detectar si hay palabras clave de mercados futuros/campeón y saltarlas.
# 3. Construir una máquina de estados que avanza token a token buscando la
#    secuencia: EQUIPO → MOMIO → "Empate"/"Draw"/"X" → MOMIO → EQUIPO → MOMIO.
#    - Un EQUIPO es una línea que NO es momio y NO es etiqueta Empate/Draw/X.
#    - Un MOMIO es una línea que cumple es_momio_americano_valido().
#    - "Empate/Draw/X" es una línea que coincide con _DRAW_LABELS.
# 4. Ignorar bloques donde se detecte keyword de campeón/futuro.
# 5. Si se completa la secuencia de 6 tokens, guardar el evento. Resetear
#    máquina de estados ante cualquier token que rompa la secuencia.
# ---------------------------------------------------------------------------

# Tokens de la máquina de estados multiline.
_ML_WAIT_LOCAL = 0       # esperando nombre equipo local
_ML_WAIT_ML = 1          # esperando momio local
_ML_WAIT_DRAW_LBL = 2    # esperando etiqueta Empate/Draw/X
_ML_WAIT_MD = 3          # esperando momio empate
_ML_WAIT_VISIT = 4       # esperando nombre equipo visitante
_ML_WAIT_MV = 5          # esperando momio visitante


def _es_etiqueta_empate(linea: str) -> bool:
    return linea.strip().lower() in _DRAW_LABELS


def _es_linea_equipo(linea: str) -> bool:
    """
    Una línea candidata a nombre de equipo:
    - No es un momio americano.
    - No es etiqueta de empate.
    - No tiene solo dígitos.
    - Tiene al menos 2 caracteres.
    - No contiene palabras clave de campeón/futuro (evitar mezcla de mercados).
    """
    s = linea.strip()
    if len(s) < 2:
        return False
    if es_momio_americano_valido(s):
        return False
    if _es_etiqueta_empate(s):
        return False
    if s.isdigit():
        return False
    if _FUTURO_KEYWORDS.search(s):
        return False
    return True


def extraer_eventos_multiline(texto: str) -> List[Dict[str, Any]]:
    """
    Extrae eventos 1X2 de texto multiline copiado desde Caliente en Chrome.

    Formato esperado (una línea por token):
        Necaxa
        -125
        Empate
        +260
        Atlante
        +275

    La máquina de estados avanza por 6 pasos:
        WAIT_LOCAL → WAIT_ML → WAIT_DRAW_LBL → WAIT_MD → WAIT_VISIT → WAIT_MV

    - Líneas de campeón/futuro resetean el estado para no mezclar mercados.
    - Si un token no encaja en el estado actual, se retrocede y se reclasifica
      el token desde el estado inicial donde corresponda.
    """
    lineas = [ln.strip() for ln in str(texto or "").splitlines()]
    lineas = [ln for ln in lineas if ln]  # eliminar vacías

    eventos: List[Dict[str, Any]] = []

    # Variables de estado
    estado: int = _ML_WAIT_LOCAL
    local: str = ""
    momio_local: str = ""
    momio_empate: str = ""
    visitante: str = ""

    def _reset() -> None:
        nonlocal estado, local, momio_local, momio_empate, visitante
        estado = _ML_WAIT_LOCAL
        local = momio_local = momio_empate = visitante = ""

    for linea in lineas:
        # Mercado de campeón/futuro → reset total para evitar mezcla.
        if _FUTURO_KEYWORDS.search(linea):
            _reset()
            continue

        if estado == _ML_WAIT_LOCAL:
            if _es_linea_equipo(linea):
                local = linea
                estado = _ML_WAIT_ML
            # Cualquier otra línea (momios sueltos, cabeceras) se ignora.

        elif estado == _ML_WAIT_ML:
            if es_momio_americano_valido(linea):
                momio_local = linea
                estado = _ML_WAIT_DRAW_LBL
            elif _es_linea_equipo(linea):
                # La línea anterior era ruido; esta podría ser el verdadero local.
                local = linea
                # estado permanece _ML_WAIT_ML
            else:
                _reset()

        elif estado == _ML_WAIT_DRAW_LBL:
            if _es_etiqueta_empate(linea):
                estado = _ML_WAIT_MD
            elif _es_linea_equipo(linea):
                # Secuencia rota; esta línea puede ser un nuevo local.
                _reset()
                local = linea
                estado = _ML_WAIT_ML
            else:
                _reset()

        elif estado == _ML_WAIT_MD:
            if es_momio_americano_valido(linea):
                momio_empate = linea
                estado = _ML_WAIT_VISIT
            else:
                _reset()

        elif estado == _ML_WAIT_VISIT:
            if _es_linea_equipo(linea):
                visitante = linea
                estado = _ML_WAIT_MV
            else:
                _reset()

        elif estado == _ML_WAIT_MV:
            if es_momio_americano_valido(linea):
                momio_visitante = linea
                # Evento completo — fecha/hora ausentes en multiline puro.
                ev: Dict[str, Any] = {
                    "hora": "",
                    "dia": 0,
                    "mes_texto": "",
                    "mes": 0,
                    "fecha": "",
                    "equipo_local": local,
                    "equipo_visitante": visitante,
                    "momio_local": momio_local,
                    "momio_empate": momio_empate,
                    "momio_visitante": momio_visitante,
                }
                eventos.append(ev)
                _reset()
            elif _es_linea_equipo(linea):
                # Ruido entre partidos; tratamos esta línea como nuevo local.
                _reset()
                local = linea
                estado = _ML_WAIT_ML
            else:
                _reset()

    return eventos



# ---------------------------------------------------------------------------
# Deduplicación
# ---------------------------------------------------------------------------
def deduplicar(eventos: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    """
    Deduplica por (local, visitante, fecha, hora) usando nombres normalizados.
    Conserva la primera aparición. Devuelve (eventos_unicos, num_duplicados).
    """
    vistos = set()
    unicos: List[Dict[str, Any]] = []
    duplicados = 0
    for ev in eventos:
        clave = (
            _norm_equipo(ev.get("equipo_local")),
            _norm_equipo(ev.get("equipo_visitante")),
            str(ev.get("fecha", "")).strip().lower(),
            str(ev.get("hora", "")).strip(),
        )
        if clave in vistos:
            duplicados += 1
            continue
        vistos.add(clave)
        unicos.append(ev)
    return unicos, duplicados


# ---------------------------------------------------------------------------
# Detección de momios sueltos (para PARSER_NEEDS_REVIEW)
# ---------------------------------------------------------------------------
def _hay_momios_sueltos(texto: str) -> bool:
    """True si el texto contiene al menos un momio americano válido suelto."""
    for m in _RE_MOMIO_SUELTO.finditer(str(texto or "")):
        if es_momio_americano_valido(m.group(1)):
            return True
    return False


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------
def analizar_texto(texto: str, esperados: int = 9) -> Dict[str, Any]:
    """
    Pipeline completo de parseo sobre el texto visible.

    Estrategia (v1.39.1):
    1. Intenta el parser single-line (regex original).
    2. Si no produce resultados, intenta el parser multiline.
    3. Si ninguno produce resultados pero hay momios sueltos en el texto,
       reporta PARSER_NEEDS_REVIEW en vez de NO_MATCHES_FOUND.

    Devuelve un dict con eventos válidos/deduplicados, conteos, eventos
    inválidos, estado (OK / NO_MATCHES_FOUND / PARSER_NEEDS_REVIEW) y la
    decisión operativa fija.
    """
    texto = str(texto or "")

    # --- Paso 1: parser single-line ---
    crudos_sl = extraer_eventos_crudos(texto)

    # --- Paso 2: parser multiline (solo si single-line no encontró nada) ---
    crudos_ml: List[Dict[str, Any]] = []
    if not crudos_sl:
        crudos_ml = extraer_eventos_multiline(texto)

    crudos = crudos_sl if crudos_sl else crudos_ml
    formato_detectado = "single-line" if crudos_sl else ("multiline" if crudos_ml else "ninguno")

    validos_pre: List[Dict[str, Any]] = []
    invalidos: List[Dict[str, Any]] = []
    for ev in crudos:
        if evento_momios_validos(ev):
            validos_pre.append(ev)
        else:
            invalidos.append(ev)

    eventos, duplicados = deduplicar(validos_pre)

    # --- Determinar status ---
    if eventos:
        status = STATUS_OK
    elif _hay_momios_sueltos(texto):
        # Hay momios en el texto pero no se pudieron armar partidos completos.
        status = STATUS_PARSER_NEEDS_REVIEW
    else:
        status = STATUS_NO_MATCHES

    return {
        "liga": LIGA,
        "fuente": FUENTE,
        "esperados": esperados,
        "total_detectados": len(crudos),
        "total_validos": len(eventos),
        "duplicados_removidos": duplicados,
        "invalidos": invalidos,
        "eventos": eventos,
        "status": status,
        "formato_detectado": formato_detectado,
        "coincide_esperados": len(eventos) == esperados,
        "decision": DEC_ESPERAR,
    }



# ---------------------------------------------------------------------------
# Exportación a JSON (sin secretos)
# ---------------------------------------------------------------------------
def construir_payload_json(resultado: Dict[str, Any]) -> Dict[str, Any]:
    """Construye el payload JSON exportable (solo datos de momios, sin secretos)."""
    eventos_export = [
        {
            "fecha": ev["fecha"],
            "hora": ev["hora"],
            "equipo_local": ev["equipo_local"],
            "equipo_visitante": ev["equipo_visitante"],
            "momio_local": ev["momio_local"],
            "momio_empate": ev["momio_empate"],
            "momio_visitante": ev["momio_visitante"],
        }
        for ev in resultado.get("eventos", [])
    ]
    return {
        "version": VERSION,
        "liga": resultado.get("liga", LIGA),
        "fuente": resultado.get("fuente", FUENTE),
        "generado_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": resultado.get("status", STATUS_NO_MATCHES),
        "total": len(eventos_export),
        "decision": DEC_ESPERAR,
        "pick_listo": False,
        "eventos": eventos_export,
    }


def exportar_json(resultado: Dict[str, Any]) -> str:
    """Serializa el payload JSON con indentación estable."""
    return json.dumps(construir_payload_json(resultado), ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Render del reporte TXT (sin secretos, sin cierre operativo, mantiene ESPERAR)
# ---------------------------------------------------------------------------
def render_report(resultado: Dict[str, Any], *, url: str = "") -> str:
    """
    Genera el reporte en texto plano. No incluye secretos ni credenciales:
    solo el host de la URL (si se pasa), conteos y la decisión operativa.
    """
    eventos = resultado.get("eventos", [])
    status = resultado.get("status", STATUS_NO_MATCHES)
    fmt = resultado.get("formato_detectado", "")

    lineas: List[str] = [
        f"# ASSISTED SPORTSBOOK ODDS IMPORT — SURVIVOR LIGA MX ({VERSION})",
        "",
        "Modo: importación ASISTIDA POR USUARIO (no stealth, no bypass, no proxy).",
        "Login/verificación: manual, en navegador visible. No se guardan credenciales.",
        f"Liga: {resultado.get('liga', LIGA)}",
        f"Fuente: {resultado.get('fuente', FUENTE)}",
    ]
    if url:
        lineas.append(f"Host: {_host_de_url(url)}")
    if fmt and fmt != "ninguno":
        lineas.append(f"Formato detectado: {fmt}")
    lineas += [
        "",
        f"Status: {status}",
        f"Eventos esperados: {resultado.get('esperados', '?')}",
        f"Eventos detectados (crudos): {resultado.get('total_detectados', 0)}",
        f"Eventos válidos (deduplicados): {resultado.get('total_validos', 0)}",
        f"Duplicados removidos: {resultado.get('duplicados_removidos', 0)}",
        f"Eventos inválidos (momios no americanos): {len(resultado.get('invalidos', []))}",
        f"Coincide con esperados: {'SÍ' if resultado.get('coincide_esperados') else 'NO'}",
        "",
    ]

    if status == STATUS_NO_MATCHES:
        lineas += [
            "AVISO: NO_MATCHES_FOUND — no se detectaron eventos 1X2 válidos en el",
            "texto visible. Revisar manualmente la página y volver a capturar.",
            "",
        ]
    elif status == STATUS_PARSER_NEEDS_REVIEW:
        lineas += [
            "AVISO: PARSER_NEEDS_REVIEW — se detectaron momios en el texto pero no",
            "se pudieron formar partidos 1X2 completos. Revisar el formato del texto",
            "capturado y volver a ejecutar. El formato multiline esperado es:",
            "  Equipo Local",
            "  -125",
            "  Empate",
            "  +260",
            "  Equipo Visitante",
            "  +275",
            "",
        ]

    if eventos:
        lineas.append("Eventos Liga MX (1X2):")
        for ev in eventos:
            fecha_hora = f"{ev['fecha']} {ev['hora']}".strip()
            lineas.append(
                f"- {fecha_hora + ' | ' if fecha_hora else ''}"
                f"{ev['equipo_local']} ({ev['momio_local']}) | "
                f"Empate ({ev['momio_empate']}) | "
                f"{ev['equipo_visitante']} ({ev['momio_visitante']})"
            )
        lineas.append("")

    invalidos = resultado.get("invalidos", [])
    if invalidos:
        lineas.append("Eventos descartados por momios inválidos:")
        for ev in invalidos:
            lineas.append(
                f"- {ev.get('fecha', '?')} {ev.get('hora', '?')} | "
                f"{ev.get('equipo_local', '?')} vs {ev.get('equipo_visitante', '?')} "
                f"(momios: {ev.get('momio_local')}, {ev.get('momio_empate')}, "
                f"{ev.get('momio_visitante')})"
            )
        lineas.append("")

    lineas += [
        "DECISIÓN GENERAL:",
        f"- {DEC_ESPERAR}.",
        "- No cambiar pick.",
        "- No enviar Telegram.",
        "- No marcar pick listo (este flujo nunca cierra un pick).",
        "- Importación solo informativa para auditoría manual de mercado.",
    ]
    return "\n".join(lineas) + "\n"


def _host_de_url(url: str) -> str:
    """Devuelve solo el host de una URL (sin querystring) para el reporte."""
    try:
        from urllib.parse import urlparse

        return urlparse(str(url)).netloc or str(url)
    except Exception:
        return str(url)
