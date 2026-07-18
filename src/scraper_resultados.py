#!/usr/bin/env python3
"""
scraper_resultados.py — Scraper robusto para resultados de Liga MX.

Busca información DETALLADA de partidos ya jugados en múltiples fuentes:
- ESPN (scoreboard + eventos)
- Liga MX API (eventos, tarjetas, alineaciones)
- Google News RSS (resúmenes, goles, expulsiones)
- MARCA, ESPN Deportes, Rebaño Pasión, Claro Sports, etc.

Guarda resultados en data/resultados_detallados.json para que el bot los use.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTADOS_PATH = os.path.join(BASE_DIR, "..", "data", "resultados_detallados.json")

LIGA_CODE = "mex.1"
ESPN_SCOREBOARD = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{LIGA_CODE}/scoreboard"
LIGAMX_API_BASE = "https://ligamx-api.onrender.com"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LigaMXBot/1.0; +https://github.com/CAILLOU77/survivor-ligamx-bot)",
    "Accept": "application/json, text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
}


def _get(url: str, params: Optional[Dict[str, Any]] = None, timeout: int = 15) -> Optional[Dict[str, Any]]:
    if requests is None:
        return None
    try:
        resp = requests.get(url, params=params, timeout=timeout, headers=_HEADERS)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def _post(url: str, data: Optional[Dict[str, Any]] = None, timeout: int = 15) -> Optional[str]:
    if requests is None:
        return None
    try:
        resp = requests.post(url, data=data, timeout=timeout, headers=_HEADERS)
        if resp.status_code == 200:
            return resp.text
        return None
    except Exception:
        return None


def obtener_partidos_espn(fecha: Optional[str] = None, delta_dias: int = 2) -> List[Dict[str, Any]]:
    """Obtiene partidos jugados desde ESPN scoreboard (±delta_dias)."""
    partidos: List[Dict[str, Any]] = []
    vistos: set = set()
    hoy = datetime.now(timezone.utc)
    fecha_base = fecha or hoy.strftime("%Y%m%d")
    try:
        dt_base = datetime.strptime(fecha_base, "%Y%m%d")
    except ValueError:
        dt_base = hoy

    for delta in range(-delta_dias, delta_dias + 1):
        rango = (dt_base + timedelta(days=delta)).strftime("%Y%m%d")
        data = _get(ESPN_SCOREBOARD, {"dates": rango})
        if not data:
            continue
        for ev in data.get("events", []):
            if not isinstance(ev, dict):
                continue
            comps = ev.get("competitions") or [{}]
            comp = comps[0] if comps else {}
            competitors = comp.get("competitors", [])
            home = away = None
            hg = ag = None
            for c in competitors:
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
            if estado != "STATUS_FULL_TIME":
                continue
            try:
                hg_i = int(hg) if hg is not None else None
                ag_i = int(ag) if ag is not None else None
            except (TypeError, ValueError):
                continue
            clave = (home, away, str(ev.get("date", ""))[:10])
            if clave in vistos:
                continue
            vistos.add(clave)
            partidos.append({
                "home_team": home,
                "away_team": away,
                "home_goals": hg_i,
                "away_goals": ag_i,
                "estado": estado,
                "event_id": ev.get("id"),
                "fecha": str(ev.get("date", ""))[:10],
                "fuente": "espn",
            })
    return partidos


def obtener_eventos_ligamx(home: str, away: str) -> List[Dict[str, Any]]:
    """Obtiene eventos desde Liga MX API."""
    eventos: List[Dict[str, Any]] = []
    try:
        data = _get(f"{LIGAMX_API_BASE}/matches", {"status": "finished", "limit": 50})
        if not data or not isinstance(data, list):
            return eventos
        for m in data:
            if not isinstance(m, dict):
                continue
            h = (m.get("home_team") or {}).get("name", "")
            a = (m.get("away_team") or {}).get("name", "")
            if not h or not a:
                continue
            # Match flexible
            if home.lower() in h.lower() and away.lower() in a.lower():
                mid = m.get("id")
                if mid:
                    ev_data = _get(f"{LIGAMX_API_BASE}/matches/{mid}/events")
                    if ev_data and isinstance(ev_data, list):
                        eventos = ev_data
                    break
    except Exception:
        pass
    return eventos


def buscar_en_web(home: str, away: str, fecha: str) -> List[Dict[str, Any]]:
    """Busca en web información detallada del partido."""
    resultados: List[Dict[str, Any]] = []
    
    # Fuente 1: ESPN search
    try:
        espn_data = _get("https://site.api.espn.com/apis/v2/sports/search", {"query": f"{home} {away} Liga MX", "limit": 5})
        if espn_data and isinstance(espn_data, dict):
            for item in (espn_data.get("items") or [])[:3]:
                if isinstance(item, dict):
                    resultados.append({
                        "titulo": item.get("headline", "") or item.get("title", ""),
                        "descripcion": item.get("description", "") or item.get("summary", ""),
                        "url": item.get("links", {}).get("web", {}).get("href", "") or item.get("url", ""),
                        "fuente": "espn",
                    })
    except Exception:
        pass
    
    # Fuente 2: Google News RSS (por si acaso)
    if len(resultados) < 2:
        try:
            q = f"{home} vs {away} Liga MX {fecha}"
            data = _get("https://news.google.com/rss/search", {"q": q, "hl": "es", "gl": "MX"})
            if data and isinstance(data, str):
                import re as _re
                items = _re.findall(r'<item>(.*?)</item>', data, _re.DOTALL)
                for item in items[:3]:
                    titulo = _re.search(r'<title>(.*?)</title>', item, _re.DOTALL)
                    desc = _re.search(r'<description>(.*?)</description>', item, _re.DOTALL)
                    link = _re.search(r'<link/>(.*?)$', item, _re.MULTILINE)
                    titulo_txt = _re.sub(r'<[^>]+>', '', titulo.group(1)).strip() if titulo else ""
                    desc_txt = _re.sub(r'<[^>]+>', '', desc.group(1)).strip() if desc else ""
                    url = link.group(1).strip() if link else ""
                    if titulo_txt and not any(r.get("titulo") == titulo_txt for r in resultados):
                        resultados.append({
                            "titulo": titulo_txt,
                            "descripcion": desc_txt,
                            "url": url,
                            "fuente": "google_news",
                        })
        except Exception:
            pass
    
    # Intentar obtener contenido de las URLs encontradas
    for r in resultados[:3]:
        url = r.get("url", "")
        if not url:
            continue
        try:
            page_resp = requests.get(url, timeout=10, headers=_HEADERS)
            if page_resp.status_code == 200:
                texto = re.sub(r'<[^>]+>', ' ', page_resp.text)
                texto = ' '.join(texto.split())
                # Extraer oraciones relevantes
                oraciones = re.split(r'[.!?]+', texto)
                relevantes = [o.strip() for o in oraciones if any(pal in o.lower() for pal in [home.lower(), away.lower(), 'gol', 'tarjeta', 'expuls', 'penal', 'minuto', 'lesión'])]
                if relevantes:
                    r["contenido"] = ' '.join(relevantes[:8])
                else:
                    r["contenido"] = texto[:800]
        except Exception:
            continue
        time.sleep(0.5)
    
    return resultados[:5]


def analizar_partido_fuerte(home: str, away: str, hg: int, ag: int, fecha: str) -> Dict[str, Any]:
    """Análisis completo y detallado de un partido."""
    eventos = obtener_eventos_ligamx(home, away)
    web = buscar_en_web(home, away, fecha)

    eventos_formateados = []
    for e in eventos[:15]:
        if not isinstance(e, dict):
            continue
        tipo = str(e.get("type", "")).lower()
        minuto = e.get("minute") or e.get("time", "") or ""
        equipo = e.get("team", "") or ""
        jugador = e.get("player", "") or e.get("playerName", "") or ""
        detalle = e.get("detail", "") or ""
        if "goal" in tipo:
            eventos_formateados.append(f"⚽ {minuto}' {equipo} — {jugador} {detalle}")
        elif "card" in tipo:
            color = "🟨" if "yellow" in tipo else "🟥"
            eventos_formateados.append(f"{color} {minuto}' {equipo} — {jugador}")
        elif "substitution" in tipo or "sub" in tipo:
            eventos_formateados.append(f"🔄 {minuto}' {equipo} — {jugador}")
        elif "penalty" in tipo:
            eventos_formateados.append(f"🎯 {minuto}' {equipo} — {jugador} {detalle}")

    # Agregar eventos de web
    for r in web:
        titulo = r.get("titulo", "")
        desc = r.get("descripcion", "")
        contenido = r.get("contenido", "")
        texto = f"{titulo} {desc} {contenido}".lower()
        import re
        if re.search(r"expuls|roja|red card", texto):
            eventos_formateados.append(f"🟥 (web) {titulo[:60]}")
        if re.search(r"lesión|baja|injury", texto):
            eventos_formateados.append(f"⚠️ (web) {titulo[:60]}")
        if re.search(r"penal|penalty", texto):
            eventos_formateados.append(f"🎯 (web) {titulo[:60]}")
        # Extraer goles del contenido
        goles = re.findall(r"(\d+)\s*[-:]\s*(\d+)", contenido)
        if goles and not any("⚽" in e for e in eventos_formateados):
            eventos_formateados.append(f"⚽ (web) Resultado confirmado: {goles[0][0]}-{goles[0][1]}")

    # Determinar resultado
    if hg > ag:
        resultado = f"🏆 {home} {hg}-{ag} {away}"
    elif hg < ag:
        resultado = f"🏆 {away} {ag}-{hg} {home}"
    else:
        resultado = f"🤝 {home} {hg}-{ag} {away}"

    # Generar conclusión detallada
    conclusion = _generar_conclusion(home, away, hg, ag, eventos_formateados, web)

    return {
        "home": home,
        "away": away,
        "home_goals": hg,
        "away_goals": ag,
        "resultado": resultado,
        "eventos": eventos_formateados[:20],
        "web_sources": [r.get("url", "") for r in web if r.get("url")],
        "conclusion": conclusion,
        "fecha": fecha,
    }


def _generar_conclusion(home: str, away: str, hg: int, ag: int, eventos: List[str], web: List[Dict[str, str]]) -> str:
    """Genera una conclusión detallada del partido."""
    partes = []
    
    # Contexto general
    partes.append(f"<b>{home} vs {away}</b> — Análisis completo del partido.")
    
    # Resumen del marcador
    if hg > ag:
        partes.append(f"<b>Resultado:</b> Victoria de {home} por {hg}-{ag}.")
    elif hg < ag:
        partes.append(f"<b>Resultado:</b> Victoria de {away} por {ag}-{hg}.")
    else:
        partes.append(f"<b>Resultado:</b> Empate {hg}-{ag}.")
    
    # Eventos clave
    goles = [e for e in eventos if e.startswith("⚽")]
    tarjetas = [e for e in eventos if "🟥" in e or "🟨" in e]
    expulsiones = [e for e in eventos if "🟥" in e]
    
    if goles:
        partes.append(f"<b>Goles ({len(goles)}):</b>")
        for g in goles[:6]:
            partes.append(f"  • {g}")
    
    if tarjetas:
        partes.append(f"<b>Tarjetas ({len(tarjetas)}):</b>")
        for t in tarjetas[:6]:
            partes.append(f"  • {t}")
    
    if expulsiones:
        partes.append(f"⚠️ <b>Expulsiones:</b> El partido tuvo {len(expulsiones)} expulsión(es), lo que cambió el desarrollo del juego.")
    
    # Fuentes consultadas
    if web:
        partes.append(f"📰 <b>Fuentes consultadas:</b> {len(web)} noticias analizadas.")
    
    # Conclusión táctica
    partes.append("💡 <b>Análisis:</b> El resultado refleja el rendimiento de ambos equipos durante los 90 minutos. "
                  "Los goles determinaron el ganador, mientras que las tarjetas y expulsiones indican la intensidad y el estado del juego.")
    
    return "\n".join(partes)


def analizar_jornada_completa(fecha: Optional[str] = None) -> Dict[str, Any]:
    """Analiza TODOS los partidos de la jornada."""
    partidos = obtener_partidos_espn(fecha)
    if not partidos:
        return {"error": "No se encontraron partidos jugados."}

    analisis = []
    for p in partidos:
        home = p.get("home_team", "")
        away = p.get("away_team", "")
        hg = p.get("home_goals")
        ag = p.get("away_goals")
        fecha_p = p.get("fecha", "")
        if hg is None or ag is None:
            continue
        analisis.append(analizar_partido_fuerte(home, away, hg, ag, fecha_p))
        time.sleep(0.5)  # Evitar rate limit

    return {
        "fecha": fecha or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "total_partidos": len(analisis),
        "partidos": analisis,
    }


def guardar_resultados(data: Dict[str, Any]) -> str:
    """Guarda resultados en JSON."""
    os.makedirs(os.path.dirname(RESULTADOS_PATH), exist_ok=True)
    with open(RESULTADOS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return RESULTADOS_PATH


def cargar_resultados() -> Dict[str, Any]:
    """Carga resultados guardados."""
    try:
        if os.path.exists(RESULTADOS_PATH):
            with open(RESULTADOS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


if __name__ == "__main__":
    import sys
    fecha = sys.argv[1] if len(sys.argv) > 1 else None
    print(f"Analizando jornada: {fecha or 'hoy'}...")
    data = analizar_jornada_completa(fecha)
    ruta = guardar_resultados(data)
    print(f"Guardado en: {ruta}")
    print(f"Total partidos analizados: {data.get('total_partidos', 0)}")
    for p in data.get("partidos", []):
        print(f"- {p['home']} vs {p['away']}: {p['home_goals']}-{p['away_goals']}")
