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
from datetime import date, datetime, timedelta, timezone
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
    Obtiene los partidos YA JUGADOS de la jornada actual.
    Primero intenta con ESPN scoreboard (rango +/- 2 días).
    Si no hay suficientes, completa con Liga MX API (partidos finalizados).
    """
    partidos_espn = _obtener_partidos_espn(fecha)
    partidos_lmx = _obtener_partidos_ligamx(fecha) if len(partidos_espn) < 3 else []
    # Combinar y deduplicar
    vistos: set = set()
    combinados: List[Dict[str, Any]] = []
    for p in partidos_espn + partidos_lmx:
        clave = (p["home_team"], p["away_team"], p["fecha"])
        if clave in vistos:
            continue
        vistos.add(clave)
        combinados.append(p)
    combinados.sort(key=lambda x: x.get("fecha", ""))
    return combinados


def _obtener_partidos_espn(fecha: Optional[str] = None) -> List[Dict[str, Any]]:
    """Obtiene partidos jugados desde ESPN scoreboard."""
    if requests is None:
        return []
    hoy = datetime.now(timezone.utc)
    fecha_base = fecha or hoy.strftime("%Y%m%d")
    try:
        dt_base = datetime.strptime(fecha_base, "%Y%m%d")
    except ValueError:
        dt_base = hoy

    url = "https://site.api.espn.com/apis/site/v2/sports/soccer/mex.1/scoreboard"
    partidos_vistos: set = set()
    partidos: List[Dict[str, Any]] = []

    for delta in range(-2, 3):
        rango_fecha = (dt_base + timedelta(days=delta)).strftime("%Y%m%d")
        try:
            resp = requests.get(url, params={"dates": rango_fecha}, timeout=20)
            if resp.status_code != 200:
                continue
            data = resp.json()
        except Exception:
            continue

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
            clave = (display_team_name(home), display_team_name(away), fecha_iso[:10])
            if clave in partidos_vistos:
                continue
            partidos_vistos.add(clave)
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


def _obtener_partidos_ligamx(fecha: Optional[str] = None) -> List[Dict[str, Any]]:
    """Obtiene partidos finalizados desde Liga MX API."""
    try:
        partidos_crudos = lmx.obtener_partidos(status="finished", limit=50)
    except Exception:
        return []
    partidos: List[Dict[str, Any]] = []
    vistos: set = set()
    for m in partidos_crudos:
        if not isinstance(m, dict):
            continue
        home = (m.get("home_team") or {}).get("name", "")
        away = (m.get("away_team") or {}).get("name", "")
        hg, ag = m.get("home_score"), m.get("away_score")
        fecha_m = str(m.get("match_date") or "")[:10]
        if not home or not away or hg is None or ag is None:
            continue
        try:
            hg, ag = int(hg), int(ag)
        except (TypeError, ValueError):
            continue
        clave = (display_team_name(home), display_team_name(away), fecha_m)
        if clave in vistos:
            continue
        vistos.add(clave)
        partidos.append(
            {
                "fecha": fecha_m,
                "home_team": display_team_name(home),
                "away_team": display_team_name(away),
                "home_goals": hg,
                "away_goals": ag,
                "estado": "STATUS_FULL_TIME",
                "event_id": m.get("id"),
            }
        )
    return partidos


def _buscar_eventos_partido(home: str, away: str, fecha: str) -> List[Dict[str, Any]]:
    """Busca en web eventos detallados de un partido ya jugado."""
    consultas = [
        f"{home} vs {away} {fecha} goles tarjetas",
        f"{home} {away} Liga MX {fecha} resultado",
        f"{home} vs {away} expulsiones lesion 2026",
    ]
    eventos: List[Dict[str, Any]] = []
    for q in consultas[:2]:
        resultados = ia._buscar_web(q, max_results=3)
        for r in resultados:
            titulo = r.get("title", "")
            snippet = r.get("snippet", "")
            texto = f"{titulo} {snippet}".lower()
            # Extraer goles
            import re
            goles = re.findall(r"(\d+)\s*[-:]\s*(\d+)", texto)
            if goles:
                eventos.append({
                    "type": "goal_search",
                    "team": home if home.lower() in texto else away if away.lower() in texto else "",
                    "player": "",
                    "minute": "",
                    "detail": f"Resultado según búsqueda: {goles[0][0]}-{goles[0][1]}",
                    "source": r.get("url", ""),
                })
            # Extraer tarjetas rojas
            if "expuls" in texto or "roja" in texto or "red card" in texto:
                eventos.append({
                    "type": "card_search",
                    "team": home if home.lower() in texto else away if away.lower() in texto else "",
                    "player": "",
                    "minute": "",
                    "detail": "Expulsión reportada en noticias",
                    "source": r.get("url", ""),
                })
            # Extraer lesiones
            if "lesion" in texto or "baja" in texto or "injury" in texto:
                eventos.append({
                    "type": "injury_search",
                    "team": home if home.lower() in texto else away if away.lower() in texto else "",
                    "player": "",
                    "minute": "",
                    "detail": "Lesión/baja reportada en noticias",
                    "source": r.get("url", ""),
                })
    return eventos[:5]


def obtener_detalle_partido(home: str, away: str, event_id: Optional[str] = None, fecha: str = "") -> Dict[str, Any]:
    """
    Obtiene detalle completo de un partido ya jugado:
    - eventos (goles, tarjetas, cambios)
    - alineación confirmada
    - impacto del XI
    Usa Liga MX API como fuente principal y búsqueda web como fallback.
    """
    out: Dict[str, Any] = {
        "home": home,
        "away": away,
        "eventos": [],
        "alineacion": None,
        "impacto_xi": None,
        "noticias": [],
    }
    # Intentar obtener eventos desde Liga MX API
    try:
        mid = lmx.match_id_de_partido(home, away)
        if mid:
            try:
                out["eventos"] = lmx.eventos_partido(mid) or []
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
    except Exception:
        pass
    # Si no hay eventos, buscar en web
    if not out["eventos"] and fecha:
        out["eventos"] = _buscar_eventos_partido(home, away, fecha)
    # Noticias
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


def _conclusion_ia(home: str, away: str, detalle: Dict[str, Any], hg: Optional[int] = None, ag: Optional[int] = None) -> Dict[str, Any]:
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

    eventos_txt = "\n".join(_formatear_eventos(detalle.get("eventos", []))) or "Sin eventos detallados disponibles."
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

    marcador_txt = f"Marcador final: {home} {hg or '?'} - {ag or '?'} {away}" if hg is not None and ag is not None else "Marcador final no disponible."

    # Búsqueda web agresiva para obtener detalles del partido
    web_txt = ""
    try:
        consultas = [
            f"{home} vs {away} Liga MX goles tarjetas",
            f"{home} vs {away} resumen partido",
            f"{home} {away} Liga MX 2026 resultado",
        ]
        for q in consultas[:2]:
            resultados = ia._buscar_web(q, max_results=3)
            for r in resultados:
                if r.get("snippet"):
                    web_txt += f"\n- {r.get('title', '')}: {r.get('snippet', '')}"
    except Exception:
        pass

    user = (
        f"Partido: {home} vs {away}\n\n"
        f"{marcador_txt}\n\n"
        f"Eventos del partido:\n{eventos_txt}\n\n"
        f"{alineacion_txt}\n\n"
        f"{impacto_txt}\n\n"
    )
    if web_txt:
        user += f"Información de fuentes web:\n{web_txt}\n\n"
    user += (
        "Genera una conclusión DETALLADA (máx 6 líneas) de por qué ganó/perdió/empató "
        "cada equipo. Incluye: goles clave, expulsiones, alineación mermada, cambios "
        "decisivos, contexto del partido. Usa TODA la información disponible, "
        "incluyendo las fuentes web. Si no hay datos suficientes, igual genera "
        "una conclusión basada en el marcador y el contexto."
    )

    payload = {
        "model": ia._modelo(),
        "messages": [
            {"role": "system", "content": "Eres analista de Liga MX. Resumen detallado y objetivo."},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "max_tokens": 400,
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
    # Fallback: conclusión básica sin IA
    if hg is not None and ag is not None:
        if hg > ag:
            return {"disponible": True, "conclusion": f"{home} ganó {hg}-{ag}."}
        elif hg < ag:
            return {"disponible": True, "conclusion": f"{away} ganó {ag}-{hg}."}
        else:
            return {"disponible": True, "conclusion": f"Empate {hg}-{ag}."}
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
      - resumen: texto HTML para Telegram (mensaje 1)
      - resumen_2: texto HTML para Telegram (mensaje 2, si hay más de 5 partidos)
      - tabla_posiciones: resumen de cómo va cada equipo
    """
    partidos = obtener_partidos_jornada(fecha)
    if not partidos:
        return {"partidos": [], "resumen": "No hay partidos jugados aún en la jornada actual.", "resumen_2": "", "tabla_posiciones": ""}

    picks_anteriores = picks_anteriores or []
    analisis: List[Dict[str, Any]] = []
    lineas_html: List[str] = [
        "📊 <b>ANÁLISIS DE LA JORNADA</b>",
        f"🕒 {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} h (UTC)",
        "━━━━━━━━━━",
    ]

    # Estadísticas por equipo
    stats_equipos: Dict[str, Dict[str, Any]] = {}

    for p in partidos:
        home = p.get("home_team", "")
        away = p.get("away_team", "")
        hg = p.get("home_goals")
        ag = p.get("away_goals")
        detalle = obtener_detalle_partido(home, away, event_id=p.get("event_id"), fecha=p.get("fecha", ""))
        conclusion = _conclusion_ia(home, away, detalle, hg=hg, ag=ag)

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

        # Actualizar estadísticas por equipo
        for equipo, goles_favor, goles_contra in [(home, hg or 0, ag or 0), (away, ag or 0, hg or 0)]:
            if equipo not in stats_equipos:
                stats_equipos[equipo] = {"gf": 0, "gc": 0, "pj": 0, "g": 0, "e": 0, "p": 0}
            stats_equipos[equipo]["gf"] += goles_favor
            stats_equipos[equipo]["gc"] += goles_contra
            stats_equipos[equipo]["pj"] += 1
            if goles_favor > goles_contra:
                stats_equipos[equipo]["g"] += 1
            elif goles_favor == goles_contra:
                stats_equipos[equipo]["e"] += 1
            else:
                stats_equipos[equipo]["p"] += 1

        # Armar bloque del partido
        bloque: List[str] = [
            f"⚽ <b>{home}</b> vs <b>{away}</b>",
            f"📊 Resultado: {resultado}",
        ]
        if eventos_lineas:
            bloque.append("📋 Eventos:")
            for ev in eventos_lineas[:8]:
                bloque.append(f"  • {ev}")
        if tarjetas_lineas:
            bloque.append("🟨🟥 Tarjetas:")
            for t in tarjetas_lineas[:6]:
                bloque.append(f"  • {t}")
        if picks_lineas:
            for pl in picks_lineas:
                bloque.append(f"🎯 {pl}")
        if conclusion.get("disponible") and conclusion.get("conclusion"):
            bloque.append(f"💡 <b>Conclusión:</b> {conclusion['conclusion']}")
        elif conclusion.get("motivo"):
            bloque.append(f"<i>Conclusión IA: {conclusion['motivo']}</i>")
        bloque.append("")

        # Agregar bloque al mensaje actual o al segundo
        # Si el mensaje actual supera ~3500 chars, mover a resumen_2
        lineas_html.extend(bloque)

    lineas_html.append("━━━━━━━━━━")
    lineas_html.append(_DECISION)

    # Tabla de posiciones resumida
    tabla_lineas = ["📈 <b>CÓMO VA CADA EQUIPO</b>", "━━━━━━━━━━"]
    for eq, st in sorted(stats_equipos.items(), key=lambda x: x[1]["gf"] - x[1]["gc"], reverse=True):
        tabla_lineas.append(
            f"{eq}: {st['pj']}PJ · {st['g']}G {st['e']}E {st['p']}P · "
            f"GF {st['gf']} · GC {st['gc']} · DG {st['gf'] - st['gc']}"
        )
    tabla_lineas.append("")
    tabla_lineas.append(_DECISION)

    # Dividir en 2 mensajes
    resumen_completo = "\n".join(lineas_html)
    tabla_completa = "\n".join(tabla_lineas)
    
    # Mensaje 1: primeros 5 partidos + inicio de tabla
    mensaje1_partes = []
    mensaje1_partes.append("📊 <b>ANÁLISIS DE LA JORNADA (1/2)</b>")
    mensaje1_partes.append(f"🕒 {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} h (UTC)")
    mensaje1_partes.append("━━━━━━━━━━")
    
    partidos_mensaje1 = partidos[:5]
    partidos_mensaje2 = partidos[5:]
    
    for p_item in partidos[:5]:
        # Reconstruir el bloque para este partido
        home = p_item.get("home_team", "")
        away = p_item.get("away_team", "")
        hg = p_item.get("home_goals")
        ag = p_item.get("away_goals")
        
        if hg is not None and ag is not None:
            if hg > ag:
                resultado = f"🏆 {home} {hg}-{ag} {away}"
            elif hg < ag:
                resultado = f"🏆 {away} {ag}-{hg} {home}"
            else:
                resultado = f"🤝 {home} {hg}-{ag} {away}"
        else:
            resultado = f"⏳ {home} vs {away}"
        
        mensaje1_partes.append(f"⚽ <b>{home}</b> vs <b>{away}</b>")
        mensaje1_partes.append(f"📊 Resultado: {resultado}")
        
        # Buscar el análisis correspondiente
        analisis_p = next((a for a in analisis if a["home"] == home and a["away"] == away), None)
        if analisis_p:
            eventos_lineas = _formatear_eventos(analisis_p.get("eventos", []))
            tarjetas_lineas = analisis_p.get("tarjetas", [])
            conclusion = analisis_p.get("conclusion_ia", {})
            
            if eventos_lineas:
                mensaje1_partes.append("📋 Eventos:")
                for ev in eventos_lineas[:8]:
                    mensaje1_partes.append(f"  • {ev}")
            if tarjetas_lineas:
                mensaje1_partes.append("🟨🟥 Tarjetas:")
                for t in tarjetas_lineas[:6]:
                    mensaje1_partes.append(f"  • {t}")
            if conclusion.get("disponible") and conclusion.get("conclusion"):
                mensaje1_partes.append(f"💡 <b>Conclusión:</b> {conclusion['conclusion'][:200]}")
            elif conclusion.get("motivo"):
                mensaje1_partes.append(f"<i>Conclusión IA: {conclusion['motivo']}</i>")
        mensaje1_partes.append("")
    
    mensaje1_partes.append("━━━━━━━━━━")
    mensaje1_partes.append(_DECISION)
    
    # Mensaje 2: resto de partidos + tabla de posiciones
    mensaje2_partes = []
    if partidos_mensaje2:
        mensaje2_partes.append("📊 <b>ANÁLISIS DE LA JORNADA (2/2)</b>")
        mensaje2_partes.append("━━━━━━━━━━")
        
        for p_item in partidos_mensaje2:
            home = p_item.get("home_team", "")
            away = p_item.get("away_team", "")
            hg = p_item.get("home_goals")
            ag = p_item.get("away_goals")
            
            if hg is not None and ag is not None:
                if hg > ag:
                    resultado = f"🏆 {home} {hg}-{ag} {away}"
                elif hg < ag:
                    resultado = f"🏆 {away} {ag}-{hg} {home}"
                else:
                    resultado = f"🤝 {home} {hg}-{ag} {away}"
            else:
                resultado = f"⏳ {home} vs {away}"
            
            mensaje2_partes.append(f"⚽ <b>{home}</b> vs <b>{away}</b>")
            mensaje2_partes.append(f"📊 Resultado: {resultado}")
            
            analisis_p = next((a for a in analisis if a["home"] == home and a["away"] == away), None)
            if analisis_p:
                eventos_lineas = _formatear_eventos(analisis_p.get("eventos", []))
                tarjetas_lineas = analisis_p.get("tarjetas", [])
                conclusion = analisis_p.get("conclusion_ia", {})
                
                if eventos_lineas:
                    mensaje2_partes.append("📋 Eventos:")
                    for ev in eventos_lineas[:8]:
                        mensaje2_partes.append(f"  • {ev}")
                if tarjetas_lineas:
                    mensaje2_partes.append("🟨🟥 Tarjetas:")
                    for t in tarjetas_lineas[:6]:
                        mensaje2_partes.append(f"  • {t}")
                if conclusion.get("disponible") and conclusion.get("conclusion"):
                    mensaje2_partes.append(f"💡 <b>Conclusión:</b> {conclusion['conclusion'][:200]}")
                elif conclusion.get("motivo"):
                    mensaje2_partes.append(f"<i>Conclusión IA: {conclusion['motivo']}</i>")
            mensaje2_partes.append("")
        
        mensaje2_partes.append("━━━━━━━━━━")
    
    # Agregar tabla de posiciones al último mensaje
    mensaje2_partes.extend(tabla_lineas)

    # Guardar resultados por equipo
    _guardar_resultados_jornada(stats_equipos, fecha or datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    return {
        "partidos": analisis,
        "resumen": "\n".join(mensaje1_partes),
        "resumen_2": "\n".join(mensaje2_partes) if mensaje2_partes else "",
        "tabla_posiciones": tabla_completa,
    }


def _guardar_resultados_jornada(stats_equipos: Dict[str, Dict[str, Any]], fecha: str) -> None:
    """Guarda los resultados de la jornada en un archivo JSON para tracking."""
    import json
    from pathlib import Path
    BASE_DIR = Path(__file__).resolve().parents[1]
    historial_path = BASE_DIR / "data" / "historial_resultados.json"
    try:
        if historial_path.exists():
            with open(historial_path, "r", encoding="utf-8") as f:
                historial = json.load(f)
        else:
            historial = {"jornadas": []}
    except Exception:
        historial = {"jornadas": []}
    
    jornada_data = {
        "fecha": fecha,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "equipos": stats_equipos,
    }
    historial["jornadas"].append(jornada_data)
    historial["jornadas"] = historial["jornadas"][-10:]  # Guardar últimas 10 jornadas
    
    try:
        historial_path.parent.mkdir(parents=True, exist_ok=True)
        with open(historial_path, "w", encoding="utf-8") as f:
            json.dump(historial, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def cargar_historial_resultados() -> Dict[str, Any]:
    """Carga el historial de resultados de las últimas jornadas."""
    import json
    from pathlib import Path
    BASE_DIR = Path(__file__).resolve().parents[1]
    historial_path = BASE_DIR / "data" / "historial_resultados.json"
    try:
        if historial_path.exists():
            with open(historial_path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"jornadas": []}
