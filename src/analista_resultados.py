#!/usr/bin/env python3
"""
analista_resultados.py — Análisis POST-PARTIDO de la jornada actual.

Qué hace:
- Obtiene los partidos YA JUGADOS de la jornada actual.
- Para cada partido: goles, tarjetas, alineaciones, eventos, impacto del XI.
- Usa IA para generar una conclusión narrativa de CADA partido.
- Compara picks anteriores del bot con el resultado real.
- Devuelve un mensaje HTML listo para Telegram.

Fuentes:
- ESPN (scoreboard) para marcadores y estado.
- Liga MX API para detalles (eventos, tarjetas, alineaciones).

Activación: automática desde Telegram (/analisis) o endpoint API.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

try:
    from team_normalizer import canonical_team_key, display_team_name
except ImportError:  # pragma: no cover
    from src.team_normalizer import canonical_team_key, display_team_name  # type: ignore

try:
    import ligamx_api as lmx
except ImportError:  # pragma: no cover
    from src import ligamx_api as lmx  # type: ignore

try:
    import analista_ia as ia
except ImportError:  # pragma: no cover
    from src import analista_ia as ia  # type: ignore

_DECISION = "INFORMATIVO / REVISIÓN HUMANA"

# Umbral para considerar que un partido ya jugó (horas desde el inicio esperado).
_HORAS_POST_PARTIDO = 2.5


def _parse_dt(iso: Any) -> Optional[datetime]:
    if not iso:
        return None
    s = str(iso).replace("Z", "").strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _ya_jugado(fecha_iso: str, estado: str, horas_post: float = _HORAS_POST_PARTIDO) -> bool:
    """True si el partido ya finalizó o ya pasó su horario por `horas_post`."""
    if estado == "STATUS_FULL_TIME":
        return True
    dt = _parse_dt(fecha_iso)
    if dt is None:
        return False
    ahora = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (ahora - dt).total_seconds() / 3600.0 >= horas_post


def obtener_partidos_jornada(fecha: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Obtiene los partidos de la jornada actual desde ESPN scoreboard.
    Si `fecha` es None, usa hoy. Devuelve solo partidos YA JUGADOS.
    """
    if requests is None:
        return []
    fecha = fecha or datetime.now(timezone.utc).strftime("%Y%m%d")
    url = "https://site.api.espn.com/apis/site/v2/sports/soccer/mex.1/scoreboard"
    try:
        resp = requests.get(url, params={"dates": fecha}, timeout=20)
        if resp.status_code != 200:
            return []
        data = resp.json()
    except Exception:
        return []

    partidos: List[Dict[str, Any]] = []
    for ev in data.get("events", []):
        if not isinstance(ev, dict):
            continue
        comps = ev.get("competitions") or [{}]
        comp = comps[0] if comps else {}
        competidores = comp.get("competitors", [])
        home = away = None
        hg = ag = None
        for c in competidores:
            if not isinstance(c, dict):
                continue
            nombre = (c.get("team") or {}).get("displayName", "")
            score = c.get("score")
            if c.get("homeAway") == "home":
                home, hg = nombre, score
            elif c.get("homeAway") == "away":
                away, ag = nombre, score
        if not home or not away:
            continue
        estado = ((ev.get("status") or {}).get("type") or {}).get("name", "")
        fecha_iso = str(ev.get("date", ""))
        if not _ya_jugado(fecha_iso, estado):
            continue
        try:
            home_goals = int(hg) if hg is not None else None
            away_goals = int(ag) if ag is not None else None
        except (TypeError, ValueError):
            continue
        partidos.append(
            {
                "fecha": fecha_iso[:10],
                "home_team": display_team_name(home),
                "away_team": display_team_name(away),
                "home_goals": home_goals,
                "away_goals": away_goals,
                "estado": estado,
                "event_id": ev.get("id"),
            }
        )
    return partidos


def obtener_detalle_partido(home: str, away: str) -> Dict[str, Any]:
    """
    Obtiene detalle completo de un partido ya jugado:
    - eventos (goles, tarjetas, cambios)
    - alineación confirmada
    - impacto del XI
    """
    out: Dict[str, Any] = {
        "home": home,
        "away": away,
        "eventos": [],
        "alineacion": None,
        "impacto_xi": None,
        "noticias": [],
    }
    try:
        out["eventos"] = lmx.eventos_partido(lmx.match_id_de_partido(home, away)) if lmx.match_id_de_partido(home, away) else []
    except Exception:
        pass
    try:
        out["alineacion"] = lmx.alineacion_de_partido(home, away)
    except Exception:
        pass
    try:
        out["impacto_xi"] = lmx.lineup_impact_partido(home, away)
    except Exception:
        pass
    try:
        out["noticias"] = lmx.noticias_de_equipos([home, away], limit=5, dias=7)
    except Exception:
        pass
    return out


def _formatear_eventos(eventos: List[Dict[str, Any]]) -> List[str]:
    """Convierte eventos a líneas legibles."""
    lineas: List[str] = []
    for e in (eventos or [])[:15]:
        if not isinstance(e, dict):
            continue
        tipo = e.get("type", "").lower()
        minuto = e.get("minute") or e.get("time", "")
        equipo = e.get("team", "") or ""
        jugador = e.get("player", "") or e.get("playerName", "") or ""
        detalle = e.get("detail", "") or ""
        if "goal" in tipo:
            lineas.append(f"⚽ {minuto}' {equipo} — {jugador} {detalle}")
        elif "card" in tipo:
            color = "🟨" if "yellow" in tipo else "🟥"
            lineas.append(f"{color} {minuto}' {equipo} — {jugador}")
        elif "substitution" in tipo or "sub" in tipo:
            entra = e.get("playerIn", "") or e.get("substitute", "") or ""
            sale = e.get("playerOut", "") or jugador
            if entra:
                lineas.append(f"🔄 {minuto}' {equipo} — entra {entra}, sale {sale}")
            else:
                lineas.append(f"🔄 {minuto}' {equipo} — {sale}")
        elif "penalty" in tipo:
            lineas.append(f"🎯 {minuto}' {equipo} — {jugador} {detalle}")
    return lineas


def _formatear_tarjetas(eventos: List[Dict[str, Any]]) -> List[str]:
    """Solo tarjetas amarillas y rojas."""
    out: List[str] = []
    for e in (eventos or []):
        if not isinstance(e, dict):
            continue
        tipo = str(e.get("type", "")).lower()
        if "card" not in tipo:
            continue
        color = "🟨" if "yellow" in tipo else "🟥"
        minuto = e.get("minute") or e.get("time", "")
        equipo = e.get("team", "") or ""
        jugador = e.get("player", "") or e.get("playerName", "") or ""
        out.append(f"{color} {minuto}' {equipo} — {jugador}")
    return out[:10]


def _conclusion_ia(home: str, away: str, detalle: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pide a la IA una conclusión narrativa del partido.
    Tolerante: si no hay IA, devuelve fallback.
    """
    if not ia.habilitado():
        return {
            "disponible": False,
            "motivo": "IA desactivada.",
            "conclusion": "",
        }

    eventos_txt = "\n".join(_formatear_eventos(detalle.get("eventos", []))) or "Sin eventos detallados."
    alineacion_txt = ""
    if detalle.get("alineacion") and detalle["alineacion"].get("disponible"):
        equipos = detalle["alineacion"].get("equipos", [])
        partes = []
        for eq in equipos:
            if not isinstance(eq, dict):
                continue
            nombre = eq.get("equipo", "")
            titulares = ", ".join(eq.get("titulares", [])[:4])
            if titulares:
                partes.append(f"{nombre}: {titulares}...")
        if partes:
            alineacion_txt = "Alineaciones:\n" + "\n".join(partes)
    else:
        alineacion_txt = "Alineación no disponible."

    impacto_txt = ""
    if detalle.get("impacto_xi") and detalle["impacto_xi"].get("disponible"):
        equipos_imp = detalle["impacto_xi"].get("equipos", {})
        partes = []
        for eq, info in (equipos_imp or {}).items():
            if not isinstance(info, dict):
                continue
            fuerza = info.get("fuerza_xi_pct")
            ausentes = info.get("ausentes_clave") or []
            if fuerza is not None:
                partes.append(f"{eq}: fuerza XI {fuerza}%")
            if ausentes:
                nombres = ", ".join(str(a.get("jugador", "")) for a in ausentes[:3] if isinstance(a, dict))
                if nombres:
                    partes.append(f"  Ausentes clave: {nombres}")
        if partes:
            impacto_txt = "Impacto XI:\n" + "\n".join(partes)
    else:
        impacto_txt = "Impacto XI no disponible."

    user = (
        f"Partido: {home} vs {away}\n\n"
        f"Eventos del partido:\n{eventos_txt}\n\n"
        f"{alineacion_txt}\n\n"
        f"{impacto_txt}\n\n"
        "Genera una conclusión BREVE (máx 4 líneas) de por qué ganó/perdió/empató "
        "cada equipo, enfocándote en: goles clave, expulsiones, alineación mermada, "
        "cambios decisivos. Si no hay datos suficientes, di 'Datos insuficientes'."
    )

    payload = {
        "model": ia._modelo(),
        "messages": [
            {"role": "system", "content": "Eres analista de Liga MX. Resumen breve y objetivo."},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "max_tokens": 300,
    }

    backend = ia._backend()
    url = ia._PROXY_URL if backend == "proxy" else ia.GROQ_URL
    headers = {"Authorization": f"Bearer {ia._PROXY_KEY if backend == 'proxy' else ia._groq_api_key()}"}

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=60 if backend == "proxy" else 30)
        if resp.status_code == 200:
            contenido = resp.json()["choices"][0]["message"]["content"]
            return {"disponible": True, "conclusion": str(contenido).strip()}
    except Exception:
        pass
    return {
        "disponible": False,
        "motivo": "Error en llamada IA.",
        "conclusion": "",
    }


def _comparar_picks_anteriores(home: str, away: str, picks_anteriores: List[Dict[str, Any]]) -> List[str]:
    """
    Compara este partido con picks anteriores del bot.
    Devuelve líneas como: "El bot había recomendado América (local) — acertó."
    """
    lineas: List[str] = []
    if not picks_anteriores:
        return lineas
    key_home = canonical_team_key(home)
    key_away = canonical_team_key(away)
    for pk in picks_anteriores:
        pk_eq = pk.get("equipo", "")
        pk_rival = pk.get("rival", "")
        pk_cond = pk.get("condicion", "")
        if canonical_team_key(pk_eq) == key_home and canonical_team_key(pk_rival) == key_away:
            lineas.append(f"🤖 El bot había recomendado {pk_eq} ({pk_cond}) en este partido.")
        elif canonical_team_key(pk_eq) == key_away and canonical_team_key(pk_rival) == key_home:
            lineas.append(f"🤖 El bot había recomendado {pk_eq} ({pk_cond}) en este partido.")
    return lineas


def analizar_jornada(fecha: Optional[str] = None, picks_anteriores: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """
    Analiza TODOS los partidos YA JUGADOS de la jornada actual.
    Devuelve un dict con:
      - partidos: lista de análisis por partido
      - resumen: texto HTML para Telegram
    """
    partidos = obtener_partidos_jornada(fecha)
    if not partidos:
        return {"partidos": [], "resumen": "No hay partidos jugados aún en la jornada actual."}

    picks_anteriores = picks_anteriores or []
    analisis: List[Dict[str, Any]] = []
    lineas_html: List[str] = [
        "📊 <b>ANÁLISIS DE LA JORNADA</b>",
        f"🕒 {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} h (UTC)",
        "━━━━━━━━━━",
    ]

    for p in partidos:
        home = p.get("home_team", "")
        away = p.get("away_team", "")
        hg = p.get("home_goals")
        ag = p.get("away_goals")
        detalle = obtener_detalle_partido(home, away)
        conclusion = _conclusion_ia(home, away, detalle)

        eventos_lineas = _formatear_eventos(detalle.get("eventos", []))
        tarjetas_lineas = _formatear_tarjetas(detalle.get("eventos", []))
        picks_lineas = _comparar_picks_anteriores(home, away, picks_anteriores)

        # Determinar resultado
        if hg is not None and ag is not None:
            if hg > ag:
                resultado = f"🏆 {home} {hg}-{ag} {away}"
            elif hg < ag:
                resultado = f"🏆 {away} {ag}-{hg} {home}"
            else:
                resultado = f"🤝 {home} {hg}-{ag} {away}"
        else:
            resultado = f"⏳ {home} vs {away}"

        analisis.append(
            {
                "home": home,
                "away": away,
                "home_goals": hg,
                "away_goals": ag,
                "eventos": detalle.get("eventos", []),
                "tarjetas": tarjetas_lineas,
                "alineacion": detalle.get("alineacion"),
                "impacto_xi": detalle.get("impacto_xi"),
                "conclusion_ia": conclusion,
            }
        )

        # Armar mensaje HTML
        lineas_html.append(f"⚽ <b>{home}</b> vs <b>{away}</b>")
        lineas_html.append(f"📊 Resultado: {resultado}")
        if eventos_lineas:
            lineas_html.append("📋 Eventos:")
            for ev in eventos_lineas[:8]:
                lineas_html.append(f"  • {ev}")
        if tarjetas_lineas:
            lineas_html.append("🟨🟥 Tarjetas:")
            for t in tarjetas_lineas[:6]:
                lineas_html.append(f"  • {t}")
        if picks_lineas:
            for pl in picks_lineas:
                lineas_html.append(f"🎯 {pl}")
        if conclusion.get("disponible") and conclusion.get("conclusion"):
            lineas_html.append(f"💡 <b>Conclusión:</b> {conclusion['conclusion']}")
        elif conclusion.get("motivo"):
            lineas_html.append(f"<i>Conclusión IA: {conclusion['motivo']}</i>")
        lineas_html.append("")

    lineas_html.append("━━━━━━━━━━")
    lineas_html.append(_DECISION)
    return {
        "partidos": analisis,
        "resumen": "\n".join(lineas_html),
    }
