#!/usr/bin/env python3
"""
data_confidence.py — Data Confidence Score / Final Audit Readiness.

v1.37.0 — Survivor Liga MX.

Mide, de forma LOCAL, si el bot tiene suficiente información real para pasar a
auditoría final. Combina entradas locales ya existentes:

- API Health Matrix (src/api_role_router.build_matrix) — estados de APIs, sin
  parsear ni imprimir secretos.
- Market Watchdog (data/watchdog_state.json) — disponibilidad de mercado real y
  si hay baseline/snapshot de movimiento.
- FBref local/manual (CSV/reporte de comparación) — apoyo de calendario.
- Noticias locales (data/noticias_ligamx.txt) — apoyo de contexto.

Reglas duras:
- NO toma picks, NO cierra picks, NO manda Telegram, NO activa APIs nuevas.
- NO hace llamadas externas. NO imprime secretos. NO usa CERRAR.
- Si mercado real < 9/9 -> ESPERAR / NO ENVIAR (obligatorio).
- READY_FOR_FULL_AUDIT solo si score >= 70 Y mercado real = 9/9 (y aun así
  NO ENVIAR AUTOMÁTICO).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
CONF_LOW = "DATA_CONFIDENCE_LOW"
CONF_MEDIUM = "DATA_CONFIDENCE_MEDIUM"
CONF_HIGH = "DATA_CONFIDENCE_HIGH"

DEC_ESPERAR = "ESPERAR / NO ENVIAR"
DEC_READY = "READY_FOR_FULL_AUDIT / NO ENVIAR AUTOMÁTICO"

# Estados de API-Football (espejo de api_role_router).
AF_CONFIGURED_UNKNOWN = "CONFIGURED_UNKNOWN"
AF_PLAN_BLOCKED_2026 = "PLAN_BLOCKED_2026"
AF_MISSING = "MISSING_ENV"

ST_CONFIGURED = "CONFIGURED"
ST_DISABLED_BY_CONFIG = "DISABLED_BY_CONFIG"

RECHECK_NOTE = (
    "RECHECK_BEFORE_MATCH T-48h, T-24h, T-6h, T-2h, T-60m. "
    "No rotar llave por plan/temporada/quota/auth."
)

# Jornada Liga MX = 9 partidos (fallback si no hay total en el estado).
TOTAL_DEFAULT = 9

OPTIONAL_AI_PROVIDERS = ("Cerebras", "OpenRouter", "Fireworks")


# ---------------------------------------------------------------------------
# Lectura de entradas locales (tolerante a archivos faltantes)
# ---------------------------------------------------------------------------
def leer_watchdog_state(path: Path) -> Dict[str, Any]:
    """Lee data/watchdog_state.json. Si no existe o es inválido, devuelve {}."""
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def mercado_real_counts(state: Dict[str, Any]) -> tuple[int, int]:
    """
    (disponibles, total) de mercado real desde el estado del watchdog.
    Si no hay estado, mercado real = 0/9.
    """
    if not isinstance(state, dict) or not state:
        return 0, TOTAL_DEFAULT
    try:
        disp = int(state.get("disponibles", 0) or 0)
    except (TypeError, ValueError):
        disp = 0
    try:
        total = int(state.get("total", 0) or 0)
    except (TypeError, ValueError):
        total = 0
    if total <= 0:
        total = TOTAL_DEFAULT
    if disp < 0:
        disp = 0
    return disp, total


def tiene_movimiento(state: Dict[str, Any]) -> bool:
    """True si hay baseline/snapshot de movimiento de mercado guardado."""
    if not isinstance(state, dict):
        return False
    for key in ("mercados_baseline", "odds_baseline"):
        val = state.get(key)
        if isinstance(val, dict) and val:
            return True
    return False


def detectar_fbref(base_dir: Path) -> bool:
    """True si existe salida local de FBref (CSV jornada 1 o reporte de comparación)."""
    candidatos = [
        base_dir / "data" / "fbref" / "fbref_ligamx_schedule_jornada1.csv",
        base_dir / "reports" / "fbref_vs_jornadas_compare.txt",
    ]
    return any(p.exists() and p.is_file() for p in candidatos)


def detectar_noticias(base_dir: Path) -> bool:
    """True si existe data/noticias_ligamx.txt con contenido."""
    p = base_dir / "data" / "noticias_ligamx.txt"
    try:
        return p.exists() and p.is_file() and bool(p.read_text(encoding="utf-8", errors="ignore").strip())
    except Exception:
        return False


def estado_provider(matrix: List[Dict[str, Any]], name: str) -> str:
    for rec in matrix or []:
        if rec.get("name") == name:
            return str(rec.get("status") or AF_MISSING)
    return AF_MISSING


def opcionales_desactivados(matrix: List[Dict[str, Any]]) -> bool:
    """True si los proveedores opcionales NO están activos (DISABLED_BY_CONFIG / no activos)."""
    for rec in matrix or []:
        if rec.get("name") in OPTIONAL_AI_PROVIDERS and rec.get("activo"):
            return False
    return True


# ---------------------------------------------------------------------------
# Scoring (lógica pura)
# ---------------------------------------------------------------------------
def clasificar_confianza(score: int) -> str:
    if score >= 70:
        return CONF_HIGH
    if score >= 40:
        return CONF_MEDIUM
    return CONF_LOW


def decidir(score: int, disponibles: int, total: int) -> str:
    """
    Decisión operativa. Nunca CERRAR.
    - Mercado real < 9/9 -> ESPERAR / NO ENVIAR (obligatorio).
    - score >= 70 y mercado real = 9/9 -> READY_FOR_FULL_AUDIT / NO ENVIAR AUTOMÁTICO.
    - en cualquier otro caso -> ESPERAR / NO ENVIAR.
    """
    mercado_completo = total > 0 and disponibles >= total
    if not mercado_completo:
        return DEC_ESPERAR
    if score >= 70:
        return DEC_READY
    return DEC_ESPERAR


def calcular_confianza(
    *,
    disponibles: int,
    total: int,
    has_movement: bool,
    apifootball_status: str,
    fbref_available: bool,
    news_available: bool,
    groq_configured: bool,
    gemini_configured: bool,
    optional_disabled: bool = True,
) -> Dict[str, Any]:
    """Calcula el Data Confidence Score y la decisión. Lógica pura, sin IO."""
    if total <= 0:
        total = TOTAL_DEFAULT
    if disponibles < 0:
        disponibles = 0

    mercado_completo = disponibles >= total
    secciones: List[Dict[str, Any]] = []
    warnings: List[str] = []
    score = 0

    # --- Market Real ---
    if mercado_completo:
        impacto = 35
        notas = ["Mercado real completo (9/9)."]
    elif disponibles >= 1:
        impacto = 15
        notas = ["Mercado real parcial; aún no es jornada completa."]
    else:
        impacto = -40
        notas = ["Sin mercado real completo. Forzar ESPERAR / NO ENVIAR."]
        warnings.append("Mercado real 0/9: decisión obligatoria ESPERAR / NO ENVIAR.")
    score += impacto
    secciones.append({
        "seccion": "Market Real",
        "status": f"{disponibles}/{total}",
        "impacto": impacto,
        "notas": notas,
    })

    # --- Market Movement ---
    mov_impacto = 10 if has_movement else 0
    score += mov_impacto
    secciones.append({
        "seccion": "Market Movement",
        "status": "AVAILABLE" if has_movement else "MISSING",
        "impacto": mov_impacto,
        "notas": (
            ["Hay baseline/snapshot de movimiento de mercado."]
            if has_movement
            else ["Sin baseline/snapshot de movimiento todavía."]
        ),
    })

    # --- API-Football ---
    if apifootball_status == AF_PLAN_BLOCKED_2026:
        af_impacto = -20
        af_notas = [
            RECHECK_NOTE,
            "PLAN_BLOCKED_2026: revisar alternativa antes del kickoff.",
        ]
        warnings.append("API-Football PLAN_BLOCKED_2026: revisar alternativa antes del kickoff.")
    elif apifootball_status == AF_CONFIGURED_UNKNOWN:
        af_impacto = 5
        af_notas = [RECHECK_NOTE]
    elif apifootball_status == AF_MISSING:
        af_impacto = -15
        af_notas = ["MISSING_ENV: sin llave configurada para API-Football."]
    else:
        af_impacto = 0
        af_notas = [RECHECK_NOTE]
    af_notas.append("Nunca cerrar por API-Football sola.")
    score += af_impacto
    secciones.append({
        "seccion": "API-Football",
        "status": apifootball_status,
        "impacto": af_impacto,
        "notas": af_notas,
    })

    # --- FBref ---
    fbref_impacto = 10 if fbref_available else 0
    score += fbref_impacto
    secciones.append({
        "seccion": "FBref",
        "status": "AVAILABLE" if fbref_available else "MISSING",
        "impacto": fbref_impacto,
        "notas": ["Apoyo manual de calendario, no verdad automática."],
    })

    # --- News ---
    news_impacto = 10 if news_available else 0
    score += news_impacto
    secciones.append({
        "seccion": "News",
        "status": "AVAILABLE" if news_available else "MISSING",
        "impacto": news_impacto,
        "notas": (
            ["Noticias locales disponibles como apoyo de contexto."]
            if news_available
            else ["Sin noticias locales; no se hace búsqueda web nueva."]
        ),
    })

    # --- AI ---
    ai_impacto = (5 if groq_configured else 0) + (5 if gemini_configured else 0)
    score += ai_impacto
    secciones.append({
        "seccion": "AI",
        "status": "AI_SUPPORT",
        "impacto": ai_impacto,
        "groq": ST_CONFIGURED if groq_configured else AF_MISSING,
        "gemini": ST_CONFIGURED if gemini_configured else AF_MISSING,
        "optional": ST_DISABLED_BY_CONFIG,
        "notas": [
            "Cerebras/OpenRouter/Fireworks DISABLED_BY_CONFIG: no cuentan como activos.",
        ] if optional_disabled else [
            "Aviso: algún proveedor opcional aparece activo; no debería en esta versión.",
        ],
    })

    confidence = clasificar_confianza(score)
    decision = decidir(score, disponibles, total)

    return {
        "secciones": secciones,
        "total_score": score,
        "confidence": confidence,
        "decision": decision,
        "warnings": warnings,
        "mercado_disponibles": disponibles,
        "mercado_total": total,
        "mercado_completo": mercado_completo,
    }


# ---------------------------------------------------------------------------
# Orquestación (lee entradas locales + matriz) y render
# ---------------------------------------------------------------------------
def evaluar(base_dir: Path, matrix: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Lee entradas locales bajo base_dir y la matriz de APIs; calcula el score."""
    state = leer_watchdog_state(base_dir / "data" / "watchdog_state.json")
    disp, total = mercado_real_counts(state)

    return calcular_confianza(
        disponibles=disp,
        total=total,
        has_movement=tiene_movimiento(state),
        apifootball_status=estado_provider(matrix, "API-Football"),
        fbref_available=detectar_fbref(base_dir),
        news_available=detectar_noticias(base_dir),
        groq_configured=estado_provider(matrix, "Groq") == ST_CONFIGURED,
        gemini_configured=estado_provider(matrix, "Gemini") == ST_CONFIGURED,
        optional_disabled=opcionales_desactivados(matrix),
    )


def _fmt_impacto(n: int) -> str:
    return f"+{n}" if n > 0 else str(n)


def render_report(resultado: Dict[str, Any]) -> str:
    lineas: List[str] = ["# DATA CONFIDENCE SCORE — SURVIVOR LIGA MX", ""]

    for sec in resultado["secciones"]:
        if sec["seccion"] == "AI":
            lineas.append("AI:")
            lineas.append(f"Groq: {sec.get('groq')}")
            lineas.append(f"Gemini: {sec.get('gemini')}")
            lineas.append(f"Optional Providers: {sec.get('optional')}")
            lineas.append(f"Score Impact: {_fmt_impacto(sec['impacto'])}")
            if sec.get("notas"):
                lineas.append("Notes: " + " | ".join(sec["notas"]))
            lineas.append("")
            continue

        lineas.append(f"{sec['seccion']}:")
        lineas.append(f"Status: {sec['status']}")
        lineas.append(f"Score Impact: {_fmt_impacto(sec['impacto'])}")
        if sec.get("notas"):
            lineas.append("Notes: " + " | ".join(sec["notas"]))
        lineas.append("")

    lineas.append(f"TOTAL SCORE: {resultado['total_score']}")
    lineas.append(f"CONFIDENCE: {resultado['confidence']}")
    lineas.append("")

    if resultado.get("warnings"):
        lineas.append("WARNINGS:")
        for w in resultado["warnings"]:
            lineas.append(f"- {w}")
        lineas.append("")

    lineas.append("DECISIÓN:")
    lineas.append(f"- Estado: {resultado['decision']}")
    lineas.append("- No cambiar pick.")
    lineas.append("- No enviar Telegram.")
    lineas.append("- No activar proveedores nuevos.")
    if not resultado.get("mercado_completo"):
        lineas.append("- Mantener ESPERAR / NO ENVIAR (sin mercado real 9/9).")

    return "\n".join(lineas) + "\n"
