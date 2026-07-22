"""telegram_formato.py — Helpers PUROS de formato para los mensajes de Telegram.

Funciones puras: toman datos y devuelven texto (HTML) listo para Telegram. No
tocan red, base de datos ni envían nada. Extraídas de ``telegram_pronosticos.py``
para reducir el tamaño de ese módulo (god-module) y hacer el formato testeable de
forma aislada (ver tests/test_telegram_formato.py).
"""

from __future__ import annotations

from typing import Any, Dict, List

# Tope real de Telegram es 4096; dejamos margen.
_TELEGRAM_LIMITE = 4000


def _norm_simple(s: str) -> str:
    return " ".join(str(s or "").lower().split())

def _pct(v: Any) -> str:
    """Porcentaje legible en móvil: sin decimales de ruido (55.0 -> '55')."""
    try:
        return str(int(round(float(v))))
    except (TypeError, ValueError):
        return str(v)

def _fecha_mx(generado_utc: str) -> str:
    """Fecha/hora en horario de Ciudad de México, sin segundos. Fallback a UTC."""
    s = str(generado_utc or "")
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(ZoneInfo("America/Mexico_City")).strftime("%d/%m/%Y %H:%M") + " h (CDMX)"
    except Exception:
        return s.replace("T", " ").replace("Z", " UTC")

def _cerca_de_jornada(pronosticos, dias: int = 2) -> bool:
    """
    True si el partido más próximo de la jornada arranca dentro de `dias` (día de
    jornada). En ese caso vale la pena DESPERTAR la API hermana y esperar por los
    extras; lejos de la jornada, mejor responder rápido y sin enriquecer.
    """
    from datetime import date, datetime, timezone

    hoy = datetime.now(timezone.utc).date()
    fechas = []
    for p in pronosticos or []:
        s = str(p.get("fecha", ""))[:10]
        try:
            y, m, d = s.split("-")
            fechas.append(date(int(y), int(m), int(d)))
        except (ValueError, TypeError):
            continue
    if not fechas:
        return False
    return (min(fechas) - hoy).days <= dias

def _linea_goles(p: Dict[str, Any]) -> str:
    """Línea de goles: pick Over/Under con su %, BTTS y marcador más probable.

    Over/Under (masa total de la matriz) y marcador más probable (moda, un solo
    resultado) son métricas distintas y pueden diferir de forma legítima. Cuando
    chocan a simple vista, lo aclaramos para que no parezca un error.
    """
    pick_ou = p.get("pick_ou", "")
    over = p.get("prob_over_pct")
    # % del lado elegido: si el pick es Over, es prob_over; si Under, el complemento.
    pct_txt = ""
    if over is not None:
        pct = float(over) if pick_ou == "Over" else round(100.0 - float(over), 1)
        pct_txt = f" ({_pct(pct)}%)"
    # BTTS solo si hay dato (evita mostrar 'None').
    btts = p.get("pick_btts")
    btts_txt = f" · BTTS {btts}" if btts else ""
    marcador = str(p.get("marcador_pick") or p.get("marcador_mas_probable", ""))
    # Partido sin datos de goles (p.ej. pick solo-momios): no hay línea que mostrar.
    if not pick_ou and not marcador:
        return ""
    partes = []
    if pick_ou:
        partes.append(f"⚽ Goles: {pick_ou} 2.5{pct_txt}{btts_txt}")
    if marcador:
        partes.append(f"🔢 Marcador probable: {marcador}")
    linea = "\n".join(partes)
    # ¿Choca la moda con el pick Over/Under?
    total = None
    if "-" in marcador:
        try:
            gl, gv = (int(x) for x in marcador.split("-", 1))
            total = gl + gv
        except (TypeError, ValueError):
            total = None
    if total is not None:
        if pick_ou == "Over" and total <= 2:
            linea += (
                "\nℹ️ <i>La moda (2 goles) es baja, pero el grueso de "
                "escenarios apunta a más goles: por eso el pick es Over.</i>"
            )
        elif pick_ou == "Under" and total >= 3:
            linea += (
                "\nℹ️ <i>Ese marcador exacto es el más probable, pero el "
                "grueso de escenarios queda por debajo: por eso el pick es Under.</i>"
            )
    return linea

import re as _re_div

_TAG_RE_DIV = _re_div.compile(r"<\s*(/?)\s*([a-zA-Z0-9]+)([^>]*)>")
_VOID_DIV = {"br", "hr", "img", "meta", "link", "input"}


def _balancear_html(texto: str):
    """Cierra las etiquetas HTML abiertas para que el trozo sea válido.
    Devuelve (texto_corregido, lista_de_etiquetas_abiertas)."""
    pila: List[str] = []
    for m in _TAG_RE_DIV.finditer(texto):
        cierre, tag = m.group(1), m.group(2).lower()
        if tag in _VOID_DIV:
            continue
        if cierre:
            if pila and pila[-1] == tag:
                pila.pop()
        else:
            if not (m.group(3) or "").rstrip().endswith("/"):
                pila.append(tag)
    return texto + "".join(f"</{t}>" for t in reversed(pila)), pila


def _dividir_mensaje(texto: str, limite: int = _TELEGRAM_LIMITE) -> List[str]:
    """
    Parte un mensaje largo en trozos <= `limite` que son HTML válido cada uno.
    1) Prefiere cortar en saltos de línea. 2) Si una línea sola excede el límite,
    la corta y BALANCEA las etiquetas (cierra al final del trozo y reabre al
    inicio del siguiente) para que Telegram nunca rechace un trozo (HTTP 400).
    """
    if len(texto) <= limite:
        return [texto]
    partes: List[str] = []
    actual = ""
    reapertura: List[str] = []

    def _flush(bloque: str):
        nonlocal reapertura
        if reapertura:
            bloque = "".join(f"<{t}>" for t in reapertura) + bloque
        corregido, abiertas = _balancear_html(bloque)
        partes.append(corregido)
        reapertura = list(abiertas)

    for linea in texto.split("\n"):
        while len(linea) > limite:
            if actual:
                _flush(actual)
                actual = ""
            _flush(linea[:limite])
            linea = linea[limite:]
        candidato = f"{actual}\n{linea}" if actual else linea
        if len(candidato) > limite and actual:
            _flush(actual)
            actual = linea
        else:
            actual = candidato
    if actual:
        _flush(actual)
    return partes

def _totales_jornada(pronosticos: list) -> Dict[str, Any]:
    """Calcula totales de la jornada: partidos, goles esperados, O/U, BTTS."""
    if not pronosticos:
        return {
            "partidos": 0,
            "goles_esperados_total": 0.0,
            "promedio_goles_partido": 0.0,
            "over_25_count": 0,
            "under_25_count": 0,
            "btts_si_count": 0,
            "btts_no_count": 0,
        }
    total_goles = sum(p.get("goles_esperados_local", 0) + p.get("goles_esperados_visitante", 0) for p in pronosticos)
    over_25 = sum(1 for p in pronosticos if p.get("pick_ou") == "Over")
    under_25 = sum(1 for p in pronosticos if p.get("pick_ou") == "Under")
    btts_si = sum(1 for p in pronosticos if p.get("pick_btts") == "Sí")
    btts_no = sum(1 for p in pronosticos if p.get("pick_btts") == "No")
    return {
        "partidos": len(pronosticos),
        "goles_esperados_total": round(total_goles, 1),
        "promedio_goles_partido": round(total_goles / len(pronosticos), 2),
        "over_25_count": over_25,
        "under_25_count": under_25,
        "btts_si_count": btts_si,
        "btts_no_count": btts_no,
    }

def _marcador_a_favor(marcador: str, es_local: bool) -> str:
    """Orienta 'local-visitante' al lado del equipo elegido (equipo-rival)."""
    try:
        hg, ag = str(marcador or "").split("-")
        return f"{hg.strip()}-{ag.strip()}" if es_local else f"{ag.strip()}-{hg.strip()}"
    except Exception:
        return str(marcador or "")
