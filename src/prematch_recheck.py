#!/usr/bin/env python3
"""
prematch_recheck.py — Pre-Match Recheck Scheduler (Survivor Liga MX).

v1.38.0.

Programador/checklist LOCAL para revisiones pre-partido. Según la distancia al
kickoff indica qué ventana de revisión toca (T-48h, T-24h, T-6h, T-2h, T-60m) y
qué checklist seguir.

Reglas duras:
- NO hace llamadas externas. NO manda Telegram. NO cambia/cierra picks.
- NO activa APIs nuevas. NO imprime secretos. NO usa CERRAR operativo.
- NO crea launchd/cron. Solo lee entradas locales y genera un reporte.
- NO marca READY_FOR_FULL_AUDIT aquí (eso lo decide la auditoría final con
  mercado real 9/9 + Data Confidence HIGH).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
WIN_UPCOMING = "UPCOMING"
WIN_T48 = "DUE_T48"
WIN_T24 = "DUE_T24"
WIN_T6 = "DUE_T6"
WIN_T2 = "DUE_T2"
WIN_T60 = "DUE_T60"
WIN_LIVE_OR_LOCKED = "LIVE_OR_LOCKED"
WIN_UNKNOWN_TIME = "UNKNOWN_TIME"

DEC_ESPERAR = "ESPERAR / NO ENVIAR"

# Estados de API-Football (espejo de api_role_router / data_confidence).
AF_CONFIGURED_UNKNOWN = "CONFIGURED_UNKNOWN"
AF_PLAN_BLOCKED_2026 = "PLAN_BLOCKED_2026"
AF_MISSING = "MISSING_ENV"

OPTIONAL_AI_PROVIDERS = ("Cerebras", "OpenRouter", "Fireworks")

# Umbrales de ventana en minutos desde el kickoff (futuro = positivo).
MIN_48H = 48 * 60
MIN_24H = 24 * 60
MIN_6H = 6 * 60
MIN_2H = 2 * 60
MIN_60M = 60
# Si faltan <= 0 minutos (kickoff pasó) o está extremadamente cerca: bloqueado.
LOCK_MARGIN_MIN = 0

CHECKLISTS: Dict[str, List[str]] = {
    WIN_T48: [
        "Revisar calendario y horario.",
        "Revisar FBref local/manual si existe.",
        "Revisar si The Odds API ya tiene mercado real.",
        "Revisar si API-Football sigue PLAN_BLOCKED_2026 o ya permite 2026.",
        "Mantener ESPERAR / NO ENVIAR.",
    ],
    WIN_T24: [
        "Revisar noticias locales.",
        "Revisar bajas/lesiones/sanciones.",
        "Revisar cambios de sede/hora.",
        "Revisar movimiento de mercado si existe baseline.",
        "Mantener ESPERAR / NO ENVIAR.",
    ],
    WIN_T6: [
        "Revisar mercado real completo.",
        "Revisar movimientos fuertes del watchdog.",
        "Rechecar API-Football.",
        "Si API-Football sigue PLAN_BLOCKED_2026, buscar alternativa de alineaciones/noticias.",
        "Mantener ESPERAR / NO ENVIAR salvo auditoría final posterior.",
    ],
    WIN_T2: [
        "Revisar XI probables / convocatorias / lesiones de último minuto.",
        "Revisar odds movement.",
        "Ejecutar Data Confidence.",
        "Si Data Confidence no está HIGH o mercado real no es 9/9, mantener ESPERAR / NO ENVIAR.",
    ],
    WIN_T60: [
        "Revisión final antes del kickoff.",
        "Revisar XI confirmados si están disponibles.",
        "Revisar mercado real.",
        "Revisar alertas críticas.",
        "Si todo está alto, solo READY_FOR_FULL_AUDIT / NO ENVIAR AUTOMÁTICO. Nunca cierre automático del pick.",
    ],
    WIN_UPCOMING: [
        "Aún faltan más de 48h. Sin acción urgente.",
        "Mantener ESPERAR / NO ENVIAR.",
    ],
    WIN_LIVE_OR_LOCKED: [
        "Kickoff ya pasó o está muy cerca; ventana de recheck cerrada.",
        "No tomar acciones automáticas. Mantener ESPERAR / NO ENVIAR.",
    ],
    WIN_UNKNOWN_TIME: [
        "Falta fecha/hora usable del partido.",
        "Confirmar calendario (FBref local / TheSportsDB) antes de programar rechecks.",
        "Mantener ESPERAR / NO ENVIAR.",
    ],
}


# ---------------------------------------------------------------------------
# Parseo de fecha/hora del repo (tolerante)
# ---------------------------------------------------------------------------
def parse_now(value: Optional[str]) -> datetime:
    """Parsea --now ISO; si es None o inválido, usa datetime.now() (naive, local)."""
    if value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            pass
    return datetime.now()


def parse_kickoff(fecha: str, hora: str) -> Optional[datetime]:
    """
    Convierte fecha/hora del formato del repo a datetime (naive).
    Devuelve None si falta o es 'PENDIENTE_*'/no usable.
    """
    f = str(fecha or "").strip()
    h = str(hora or "").strip()

    if not f or "pendiente" in f.lower():
        return None

    # Caso 1: la fecha ya trae hora ISO completa (con 'T'); se intenta aunque
    # 'hora' venga vacía o pendiente.
    if "t" in f.lower() and len(f) >= 15:
        try:
            return datetime.fromisoformat(f).replace(tzinfo=None)
        except Exception:
            pass  # seguimos con los demás intentos

    hora_usable = bool(h) and "pendiente" not in h.lower()

    # Caso 2: fecha (solo día) + hora separada.
    candidatos: list[str] = []
    if hora_usable:
        candidatos.append(f"{f}T{h}")
        candidatos.append(f"{f} {h}")

    for c in candidatos:
        c = c.replace(" ", "T", 1) if " " in c and "T" not in c else c
        try:
            return datetime.fromisoformat(c).replace(tzinfo=None)
        except Exception:
            continue

    # Último intento manual: fecha YYYY-MM-DD + hora HH:MM.
    try:
        import re

        mf = re.search(r"(\d{4})-(\d{2})-(\d{2})", f)
        mh = re.search(r"(\d{1,2}):(\d{2})", h) if hora_usable else None
        if mf and mh:
            return datetime(
                int(mf.group(1)), int(mf.group(2)), int(mf.group(3)),
                int(mh.group(1)), int(mh.group(2)),
            )
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# Clasificación de ventana
# ---------------------------------------------------------------------------
def clasificar_ventana(now: datetime, kickoff: Optional[datetime]) -> str:
    """
    Clasifica el estado del partido respecto al kickoff.

    minutos_restantes = (kickoff - now) en minutos.
    - kickoff None -> UNKNOWN_TIME
    - minutos <= 0 -> LIVE_OR_LOCKED
    - 0 < minutos <= 60 -> DUE_T60
    - 60 < minutos <= 120 -> DUE_T2
    - 120 < minutos <= 360 -> DUE_T6
    - 360 < minutos <= 1440 -> DUE_T24
    - 1440 < minutos <= 2880 -> DUE_T48
    - minutos > 2880 -> UPCOMING
    """
    if kickoff is None:
        return WIN_UNKNOWN_TIME

    minutos = (kickoff - now).total_seconds() / 60.0

    if minutos <= LOCK_MARGIN_MIN:
        return WIN_LIVE_OR_LOCKED
    if minutos <= MIN_60M:
        return WIN_T60
    if minutos <= MIN_2H:
        return WIN_T2
    if minutos <= MIN_6H:
        return WIN_T6
    if minutos <= MIN_24H:
        return WIN_T24
    if minutos <= MIN_48H:
        return WIN_T48
    return WIN_UPCOMING


def checklist_para(window: str) -> List[str]:
    return list(CHECKLISTS.get(window, CHECKLISTS[WIN_UNKNOWN_TIME]))


# ---------------------------------------------------------------------------
# Lectura local de jornadas (tolerante)
# ---------------------------------------------------------------------------
def cargar_partidos(path: Path, jornada: int) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Lee data/jornadas.json. Devuelve (partidos, existe).
    Filtra por jornada si los registros traen 'jornada'; si no, devuelve todos.
    """
    if not path.exists():
        return [], False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return [], True

    if isinstance(data, list):
        partidos = [x for x in data if isinstance(x, dict)]
    elif isinstance(data, dict) and isinstance(data.get("partidos"), list):
        partidos = [x for x in data["partidos"] if isinstance(x, dict)]
    else:
        partidos = []

    con_jornada = [p for p in partidos if _jornada_de(p) is not None]
    if con_jornada:
        filtrados = [p for p in partidos if _jornada_de(p) == jornada]
        if filtrados:
            return filtrados, True

    return partidos, True


def _jornada_de(p: Dict[str, Any]) -> Optional[int]:
    val = p.get("jornada", p.get("matchweek", p.get("wk")))
    try:
        return int(val) if val is not None and str(val).strip() != "" else None
    except (TypeError, ValueError):
        return None


def _home(p: Dict[str, Any]) -> str:
    return str(p.get("home_team") or p.get("local") or p.get("equipo_local") or "LOCAL?")


def _away(p: Dict[str, Any]) -> str:
    return str(p.get("away_team") or p.get("visitante") or p.get("equipo_visitante") or "VISITANTE?")


def _fecha(p: Dict[str, Any]) -> str:
    return str(p.get("fecha") or p.get("date") or "")


def _hora(p: Dict[str, Any]) -> str:
    return str(p.get("hora") or p.get("time") or "")


# ---------------------------------------------------------------------------
# Evaluación por partido y armado del resultado
# ---------------------------------------------------------------------------
def evaluar_partido(now: datetime, partido: Dict[str, Any], apifootball_status: str) -> Dict[str, Any]:
    home = _home(partido)
    away = _away(partido)
    kickoff = parse_kickoff(_fecha(partido), _hora(partido))
    window = clasificar_ventana(now, kickoff)
    checklist = checklist_para(window)

    warnings: List[str] = []
    # En ventanas con recheck de API-Football, si está bloqueado, avisar alternativa.
    if apifootball_status == AF_PLAN_BLOCKED_2026 and window in (WIN_T48, WIN_T6, WIN_T2, WIN_T60):
        warnings.append("API-Football PLAN_BLOCKED_2026: buscar alternativa de alineaciones/noticias.")

    return {
        "partido": f"{home} vs {away}",
        "kickoff": kickoff.strftime("%Y-%m-%d %H:%M") if kickoff else "PENDIENTE",
        "window": window,
        "checklist": checklist,
        "warnings": warnings,
        "decision": DEC_ESPERAR,  # este scheduler nunca cierra ni envía
    }


def estado_apifootball(matrix: List[Dict[str, Any]]) -> str:
    for rec in matrix or []:
        if rec.get("name") == "API-Football":
            return str(rec.get("status") or AF_MISSING)
    return AF_MISSING


def notas_apifootball(status: str) -> List[str]:
    notas = ["RECHECK_BEFORE_MATCH", "No rotar llave por plan/temporada/quota/auth"]
    if status == AF_PLAN_BLOCKED_2026:
        notas.append("PLAN_BLOCKED_2026: revisar alternativa de alineaciones/noticias antes del kickoff.")
    return notas


def opcionales_desactivados(matrix: List[Dict[str, Any]]) -> bool:
    for rec in matrix or []:
        if rec.get("name") in OPTIONAL_AI_PROVIDERS and rec.get("activo"):
            return False
    return True


def construir_resultado(
    *,
    now: datetime,
    jornada: int,
    partidos: List[Dict[str, Any]],
    jornadas_existe: bool,
    matrix: List[Dict[str, Any]],
    data_confidence_ctx: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    af_status = estado_apifootball(matrix)
    evaluaciones = [evaluar_partido(now, p, af_status) for p in partidos]

    return {
        "jornada": jornada,
        "now": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "jornadas_existe": jornadas_existe,
        "partidos": evaluaciones,
        "apifootball_status": af_status,
        "apifootball_notas": notas_apifootball(af_status),
        "opcionales_desactivados": opcionales_desactivados(matrix),
        "data_confidence": data_confidence_ctx or {},
        "decision_general": DEC_ESPERAR,
    }


# ---------------------------------------------------------------------------
# Render del reporte (sin secretos, sin CERRAR)
# ---------------------------------------------------------------------------
def render_report(resultado: Dict[str, Any]) -> str:
    lineas: List[str] = [
        "# PRE-MATCH RECHECK SCHEDULER — SURVIVOR LIGA MX",
        "",
        f"Jornada: {resultado['jornada']}",
        f"Now: {resultado['now']}",
        "",
    ]

    if not resultado["jornadas_existe"]:
        lineas += [
            "AVISO: no se encontró data/jornadas.json. No hay partidos que programar.",
            "Confirmar calendario local antes de los rechecks.",
            "",
        ]
    elif not resultado["partidos"]:
        lineas += [
            f"AVISO: no hay partidos para la jornada {resultado['jornada']} en data/jornadas.json.",
            "",
        ]

    for ev in resultado["partidos"]:
        lineas.append("Partido:")
        lineas.append(ev["partido"])
        lineas.append(f"Kickoff: {ev['kickoff']}")
        lineas.append(f"Window: {ev['window']}")
        lineas.append("Checklist:")
        for item in ev["checklist"]:
            lineas.append(f"- {item}")
        if ev["warnings"]:
            lineas.append("Warnings:")
            for w in ev["warnings"]:
                lineas.append(f"- {w}")
        lineas.append("Decision:")
        lineas.append(f"- {ev['decision']}")
        lineas.append("")

    # Contexto opcional de Data Confidence (si se calculó).
    dc = resultado.get("data_confidence") or {}
    if dc:
        lineas.append("Data Confidence (contexto local):")
        if "total_score" in dc:
            lineas.append(f"- Score: {dc.get('total_score')} ({dc.get('confidence')})")
        if "decision" in dc:
            lineas.append(f"- Estado: {dc.get('decision')}")
        lineas.append("")

    lineas += [
        "API-Football:",
        f"Status: {resultado['apifootball_status']}",
        "Notes:",
    ]
    for n in resultado["apifootball_notas"]:
        lineas.append(f"- {n}")
    lineas.append("")

    lineas += [
        "DECISIÓN GENERAL:",
        "- Mantener ESPERAR / NO ENVIAR.",
        "- No cambiar pick.",
        "- No enviar Telegram.",
        "- No activar proveedores nuevos.",
        "- No usar cierre automático del pick.",
    ]

    return "\n".join(lineas) + "\n"
