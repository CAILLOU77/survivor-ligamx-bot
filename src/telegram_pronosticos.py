#!/usr/bin/env python3
"""
telegram_pronosticos.py — Alertas de Telegram con PRONÓSTICOS REALES.

Reemplaza las alertas de "EV>5% / apuesta ya" (basadas en momios inventados)
por un resumen honesto de las **predicciones del modelo** (datos reales de ESPN):
pick de Survivor + 1X2/Over-Under/BTTS por partido.

Envío propio vía la API de Telegram (no importa la capa de DB/Postgres).
Mensaje informativo, con disclaimer de revisión humana. No es consejo de apuesta.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

try:
    import motor_pronosticos as motor
except ImportError:  # pragma: no cover
    from src import motor_pronosticos as motor  # type: ignore

try:
    import calendario_contexto as calctx
except ImportError:  # pragma: no cover
    from src import calendario_contexto as calctx  # type: ignore

try:
    from team_normalizer import clean_team_name
except ImportError:  # pragma: no cover
    from src.team_normalizer import clean_team_name  # type: ignore

DISCLAIMER = "ℹ️ Informativo / revisión humana. No es consejo de apuesta."
_MAX_PARTIDOS = 9
_CALENDARIO_PATH = Path(__file__).resolve().parents[1] / "data" / "calendario.json"


def _usados_persistidos() -> Optional[List[str]]:
    """Equipos usados guardados en la BD (para excluir del pick/plan). None si falla."""
    try:
        try:
            from database import get_equipos_usados
        except ImportError:  # pragma: no cover
            from src.database import get_equipos_usados  # type: ignore
        return get_equipos_usados()
    except Exception:  # pragma: no cover - BD no disponible
        return None


def _partidos_jugados_torneo() -> Optional[int]:
    """Partidos jugados del torneo actual (para la cautela de arranque). None si falla."""
    try:
        try:
            import ligamx_api as lmx
        except ImportError:  # pragma: no cover
            from src import ligamx_api as lmx  # type: ignore
        est = lmx.estado_temporada()
        return int(est.get("finished_matches")) if est.get("finished_matches") is not None else None
    except Exception:  # pragma: no cover - API no disponible
        return None


def _formatear_contexto(ctx: Optional[Dict[str, Any]]) -> List[str]:
    """Bloque HTML compacto con el contexto de la Liga MX API para el pick #1."""
    if not ctx or ctx.get("nota"):
        return []
    lineas: List[str] = []
    pred = ctx.get("prediccion_api")
    forma_l, forma_v = ctx.get("forma_local"), ctx.get("forma_visita")
    riesgo_l = ctx.get("en_riesgo_local") or []
    riesgo_v = ctx.get("en_riesgo_visita") or []
    h2h = ctx.get("h2h")
    noticias = ctx.get("noticias") or []
    ali = ctx.get("alineacion") if isinstance(ctx.get("alineacion"), dict) else None
    ali_ok = bool(ali and ali.get("disponible"))
    js = ctx.get("jugadores_seguir") if isinstance(ctx.get("jugadores_seguir"), dict) else None
    js_ok = bool(js and (js.get("local") or js.get("visita")))
    fichajes = ctx.get("fichajes") if isinstance(ctx.get("fichajes"), dict) else None
    fichajes_ok = bool(fichajes and (fichajes.get("local") or fichajes.get("visita")))
    impacto_ok = bool(ctx.get("impacto_xi"))
    probable = ctx.get("alineacion_probable") if isinstance(ctx.get("alineacion_probable"), list) else None
    probable_ok = bool(probable)
    if not (pred or forma_l or forma_v or riesgo_l or riesgo_v or h2h or noticias or ali_ok or js_ok or fichajes_ok or impacto_ok or probable_ok):
        return []  # pretemporada: sin datos aún, no ensuciar el mensaje

    lineas.append(f"🔎 <b>Contexto (Liga MX API)</b> — {ctx.get('home')} vs {ctx.get('away')}:")
    if ali_ok:
        forms = " · ".join(
            f"{e.get('equipo', '')} {e.get('formacion') or ''}".strip()
            for e in ali.get("equipos", []) if e.get("equipo")
        )
        lineas.append(f"📋 XI CONFIRMADO — {forms}")
        alerta_xi = ctx.get("alerta_xi") if isinstance(ctx.get("alerta_xi"), dict) else None
        if alerta_xi and (alerta_xi.get("local") or alerta_xi.get("visita")):
            for lado, equipo in (("local", ctx.get("home")), ("visita", ctx.get("away"))):
                faltan = alerta_xi.get(lado) or []
                if faltan:
                    lineas.append(f"🚨 OJO: {equipo} SIN titular clave — {', '.join(faltan)} (banca/fuera)")
        else:
            lineas.append("✅ XI sin ausencias clave detectadas")
    elif probable_ok:
        forms = " · ".join(
            f"{e.get('equipo', '')} {e.get('formacion') or ''}".strip()
            for e in probable if isinstance(e, dict) and e.get("equipo")
        )
        lineas.append(f"🔮 XI PROBABLE (aún no confirmado) — {forms}")
        lineas.append("<i>Alineación esperada de 365Scores; confirma ~1h antes.</i>")
    impacto = ctx.get("impacto_xi") if isinstance(ctx.get("impacto_xi"), dict) else None
    if impacto:
        for equipo, info in list(impacto.items())[:2]:
            if not isinstance(info, dict):
                continue
            fuerza = info.get("fuerza_xi_pct")
            ausentes = info.get("ausentes_clave") or []
            if fuerza is not None:
                txt = f"🧮 Fuerza XI {equipo}: {_pct(fuerza)}%"
                if ausentes:
                    nombres = ", ".join(
                        f"{a.get('jugador')} ({_pct(a.get('importancia_pct'))}%)" if isinstance(a, dict) else str(a)
                        for a in ausentes[:3]
                    )
                    txt += f" — falta {nombres}"
                lineas.append(txt)
    if pred:
        lineas.append(
            f"🧠 2ª opinión API: L{_pct(pred['prob_local_pct'])}/E{_pct(pred['prob_empate_pct'])}/"
            f"V{_pct(pred['prob_visita_pct'])} · goles {pred['goles_esp']}"
        )
    if forma_l or forma_v:
        lineas.append(f"📈 Forma: {ctx.get('home')} {forma_l or '—'} · {ctx.get('away')} {forma_v or '—'}")
    if isinstance(h2h, dict) and h2h.get("played"):
        t1 = h2h.get("team1") or {}
        t2 = h2h.get("team2") or {}
        n = h2h.get("played")
        temps = h2h.get("seasons_covered")
        temps_txt = f", {temps} temps" if temps else ""
        lineas.append(
            f"🤝 H2H ({n} duelos{temps_txt}): {t1.get('name', ctx.get('home'))} "
            f"{t1.get('wins', 0)}V · {h2h.get('draws', 0)}E · {t2.get('wins', 0)}V {t2.get('name', ctx.get('away'))}"
        )
    if riesgo_l:
        lineas.append(f"⚠️ En riesgo ({ctx.get('home')}): {', '.join(riesgo_l)}")
    if riesgo_v:
        lineas.append(f"⚠️ En riesgo ({ctx.get('away')}): {', '.join(riesgo_v)}")
    if noticias:
        lineas.append("📰 Noticias:")
        for n in noticias[:3]:
            titulo = n.get("titulo", "") if isinstance(n, dict) else str(n)
            if titulo:
                lineas.append(f"• {titulo}")
    ia = ctx.get("analisis_ia") if isinstance(ctx.get("analisis_ia"), dict) else None
    if ia and ia.get("disponible") and ia.get("riesgos"):
        lineas.append("🤖 IA — señales de riesgo:")
        for r in ia["riesgos"][:4]:
            eq = r.get("equipo", "")
            tipo = r.get("tipo", "")
            resumen = r.get("resumen", "")
            if resumen:
                lineas.append(f"• ⚠️ {eq} [{tipo}]: {resumen}")
    js = ctx.get("jugadores_seguir") if isinstance(ctx.get("jugadores_seguir"), dict) else None
    if js and (js.get("local") or js.get("visita")):
        loc = ", ".join(js.get("local", [])[:3])
        vis = ", ".join(js.get("visita", [])[:3])
        lineas.append("⭐ Jugadores a seguir:")
        if loc:
            lineas.append(f"• {ctx.get('home')}: {loc}")
        if vis:
            lineas.append(f"• {ctx.get('away')}: {vis}")
    fichajes = ctx.get("fichajes") if isinstance(ctx.get("fichajes"), dict) else None
    if fichajes and (fichajes.get("local") or fichajes.get("visita")):
        lineas.append("🔄 Altas/Bajas (Transfermarkt):")
        if fichajes.get("local"):
            lineas.append(f"• {ctx.get('home')} — {fichajes['local']}")
        if fichajes.get("visita"):
            lineas.append(f"• {ctx.get('away')} — {fichajes['visita']}")
    return lineas


def _resumen_mercado(mercado: Optional[Dict[str, Any]]) -> Optional[str]:
    """Línea concisa con lo que ve el mercado (favorito, O/U, hándicap, valor)."""
    if not mercado:
        return None
    partes: List[str] = []
    o = mercado.get("1x2")
    if o and o.get("favorito_mercado"):
        partes.append(f"fav {o['favorito_mercado']}")
        if o.get("hay_valor") and o.get("valor_en"):
            partes.append(f"valor {o['valor_en']}")
    ou = mercado.get("over_under")
    if ou and ou.get("mercado_ve"):
        partes.append(ou["mercado_ve"])  # explosivo / cauteloso
        if ou.get("hay_valor") and ou.get("valor_en"):
            partes.append(f"valor {ou['valor_en']}")
    h = mercado.get("handicap")
    if h and h.get("favorito"):
        partes.append(f"hcp {h['favorito']} {h['linea']}")
    return " · ".join(partes) if partes else None


def _lineas_mercado(p: Dict[str, Any]) -> List[str]:
    """Líneas con los momios reales del mercado (si hay) + lectura del mercado."""
    mercado = p.get("mercado")
    if not mercado:
        return []
    local = p.get("local", "Local")
    visita = p.get("visitante", "Visita")
    out: List[str] = []
    o = mercado.get("1x2") or {}
    m = o.get("momios") or {}
    if m.get("local") and m.get("empate") and m.get("visita"):
        out.append(
            f"💰 Momios: {local} {m['local']} · Empate {m['empate']} · {visita} {m['visita']}"
        )
    ou = mercado.get("over_under") or {}
    mou = ou.get("momios") or {}
    if mou.get("over") and mou.get("under"):
        linea = ou.get("linea", 2.5)
        out.append(f"⚖️ O/U {linea}: Over {mou['over']} · Under {mou['under']}")
    resumen = _resumen_mercado(mercado)
    if resumen:
        out.append(f"📈 Mercado ve: {resumen}")
    return out


def _pick_club(p: Dict[str, Any]) -> str:
    """Traduce el pick 1X2 al nombre real del club (o 'Empate')."""
    pick = p.get("pick_1x2", "")
    if pick == "Gana Local":
        return p.get("local", pick)
    if pick == "Gana Visitante":
        return p.get("visitante", pick)
    return pick  # "Empate"


def _norm_simple(s: str) -> str:
    return " ".join(str(s or "").lower().split())


def _jugadores_seguir_partido(p: Dict[str, Any],
                              goleadores_map: Dict[str, List[Dict[str, Any]]]) -> str:
    """'A seguir' de un partido a partir del mapa de goleadores por equipo."""
    def _para(equipo: str) -> str:
        # match tolerante por nombre normalizado
        lst = goleadores_map.get(equipo)
        if lst is None:
            eqn = _norm_simple(equipo)
            for k, v in goleadores_map.items():
                if _norm_simple(k) == eqn or eqn in _norm_simple(k) or _norm_simple(k) in eqn:
                    lst = v
                    break
        if not lst:
            return ""
        nombres = []
        for j in lst[:2]:
            nom = j.get("nombre", "")
            goles = j.get("goles")
            if goles not in (None, ""):
                try:
                    g = int(goles)
                    etiqueta = f"{nom} ({g} {'gol' if g == 1 else 'goles'})"
                except (TypeError, ValueError):
                    etiqueta = f"{nom} ({goles} goles)"
            else:
                etiqueta = nom
            nombres.append(etiqueta)
        return ", ".join(nombres)

    loc = _para(p.get("local", ""))
    vis = _para(p.get("visitante", ""))
    if not loc and not vis:
        return ""
    partes = []
    if loc:
        partes.append(f"{p.get('local', '')}: {loc}")
    if vis:
        partes.append(f"{p.get('visitante', '')}: {vis}")
    return " · ".join(partes)


def _porteros_partido(p: Dict[str, Any],
                      porteros_map: Dict[str, Dict[str, Any]]) -> str:
    """
    Portero + vallas invictas, pero SOLO cuando es relevante al pronóstico:
    - Se espera que un equipo deje su portería a 0 (el rival anota 0 en el
      marcador probable), o
    - el partido pinta cerrado (Under 2.5 o BTTS No).
    Si el modelo espera goles de ambos (p. ej. 2-1), no se muestra (sería absurdo).
    """
    def _gk(equipo: str) -> str:
        gk = porteros_map.get(equipo)
        if gk is None:
            eqn = _norm_simple(equipo)
            for k, v in porteros_map.items():
                if _norm_simple(k) == eqn or eqn in _norm_simple(k) or _norm_simple(k) in eqn:
                    gk = v
                    break
        if not gk or not gk.get("nombre"):
            return ""
        nom = gk["nombre"]
        try:
            v = int(gk.get("vallas_invictas"))
            return f"{nom} ({v} {'valla invicta' if v == 1 else 'vallas invictas'})"
        except (TypeError, ValueError):
            return nom

    # Goles esperados del marcador probable ("2-1" -> 2,1).
    gl = gv = None
    marcador = str(p.get("marcador_pick") or p.get("marcador_mas_probable", ""))
    if "-" in marcador:
        try:
            gl, gv = (int(x) for x in marcador.split("-", 1))
        except (TypeError, ValueError):
            gl = gv = None

    local = p.get("local", "")
    visita = p.get("visitante", "")
    partes: List[str] = []

    # Portería a 0 esperada: el rival anota 0.
    local_cero = gv == 0
    visita_cero = gl == 0
    if local_cero:
        g = _gk(local)
        if g:
            partes.append(f"{local}: {g} — se le ve portería a 0")
    if visita_cero:
        g = _gk(visita)
        if g:
            partes.append(f"{visita}: {g} — se le ve portería a 0")

    # Sin clean sheet claro, pero partido cerrado: destaca el mejor muro.
    if not partes and (p.get("pick_ou") == "Under" or p.get("pick_btts") == "No"):
        def _vallas(equipo: str) -> int:
            gk = porteros_map.get(equipo) or {}
            try:
                return int(gk.get("vallas_invictas") or 0)
            except (TypeError, ValueError):
                return 0
        mejor = local if _vallas(local) >= _vallas(visita) else visita
        g = _gk(mejor)
        if g:
            partes.append(f"partido cerrado — {mejor}: {g}")

    return " · ".join(partes)


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
            linea += ("\nℹ️ <i>La moda (2 goles) es baja, pero el grueso de "
                      "escenarios apunta a más goles: por eso el pick es Over.</i>")
        elif pick_ou == "Under" and total >= 3:
            linea += ("\nℹ️ <i>Ese marcador exacto es el más probable, pero el "
                      "grueso de escenarios queda por debajo: por eso el pick es Under.</i>")
    return linea


def construir_mensaje(
    resultado: Dict[str, Any],
    equipos_usados: Optional[List[str]] = None,
    motivacion: Optional[Dict[str, Dict[str, Any]]] = None,
    contexto_pick: Optional[Dict[str, Any]] = None,
    tops: Optional[List[Dict[str, Any]]] = None,
    advertencia: Optional[str] = None,
    goleadores_map: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    porteros_map: Optional[Dict[str, Dict[str, Any]]] = None,
) -> str:
    """Arma el mensaje (HTML) de pronósticos a partir de la salida del motor.

    `contexto_pick`: dossier compacto de la Liga MX API para el pick #1.
    `tops`: picks ya calculados (p. ej. estratégicos con cautela); si es None se
    calculan con `mejores_picks_survivor` (comportamiento por defecto).
    `advertencia`: nota de cautela (p. ej. arranque de torneo) a mostrar.
    `goleadores_map`: {equipo: [{nombre, goles}]} para 'jugadores a seguir' por partido.
    `porteros_map`: {equipo: {nombre, vallas_invictas}} para el dato defensivo (portería a 0).
    """
    pronosticos = resultado.get("pronosticos", [])
    fecha = _fecha_mx(resultado.get("generado_utc", ""))

    div = "━━━━━━━━━━"
    lineas = [
        "🔮 <b>PRONÓSTICOS LIGA MX</b>",
        "<i>Modelo ESPN + Poisson</i>",
        f"🕒 <i>{fecha}</i>",
        div,
    ]

    if tops is None:
        tops = motor.mejores_picks_survivor(pronosticos, equipos_usados, motivacion, n=3)
    if tops:
        lineas.append("🎯 <b>SURVIVOR</b>")
        if advertencia:
            lineas.append(f"<i>{advertencia}</i>")
        lineas.append("")
        # Pick recomendado (destacado) — mostrar partido completo con sede clara.
        rec = tops[0]
        gana = rec.get("prob_victoria_pct")
        if rec.get("condicion") == "Local":
            local_eq, visita_eq = rec["equipo"], rec["rival"]
        else:
            local_eq, visita_eq = rec["rival"], rec["equipo"]
        lineas.append(f"🏠 <b>{local_eq}</b> vs <b>{visita_eq}</b> ✈️")
        lineas.append(f"🥇 <b>PICK: {rec['equipo']}</b> (de {rec['condicion'].lower()})")
        noperder = rec.get("no_perder_pct")
        # empate = no-perder − gana (sobrevivir = ganar o empatar)
        emp = None
        if noperder is not None and gana is not None:
            emp = round(float(noperder) - float(gana), 1)
        lineas.append(f"✅ Sobrevive (gana o empata): <b>{_pct(noperder)}%</b>")
        if gana is not None:
            linea_g = f"🏆 Gana: <b>{_pct(gana)}%</b>"
            if emp is not None:
                linea_g += f" · 🤝 solo empata: {_pct(emp)}%"
            lineas.append(linea_g)
        lineas.append(f"🎯 Confianza: <b>{rec.get('nivel', '—')}</b>")
        if motivacion:
            mot_rival = motivacion.get(str(rec.get("rival", "")).lower(), {})
            nivel_mot = mot_rival.get("motivacion_nivel")
            if nivel_mot:
                lineas.append(f"📉 Motivación rival: {nivel_mot}")
        if rec.get("razon"):
            lineas.append(f"💬 <i>Por qué: {rec['razon']}</i>")
        if rec.get("ajuste_nota"):
            lineas.append(f"🔧 <i>Ajustado por: {rec['ajuste_nota']}</i>")
        # Otras opciones (2º y 3º).
        otras = tops[1:3]
        if otras:
            lineas.append("")
            lineas.append("<b>Otras opciones:</b>")
            medallas = ["🥈", "🥉"]
            for i, pk in enumerate(otras):
                nivel = f" [{pk['nivel']}]" if pk.get("nivel") else ""
                sede = "de local vs" if pk.get("condicion") == "Local" else "de visita vs"
                lineas.append(
                    f"{medallas[i]} <b>{pk['equipo']}</b> ({sede} {pk['rival']}) "
                    f"— sobrevive {_pct(pk['no_perder_pct'])}%{nivel}"
                )
        contexto_lineas = _formatear_contexto(contexto_pick)
        if contexto_lineas:
            lineas.append("")
            lineas.extend(contexto_lineas)

    # Contexto de calendario a nivel jornada (Leagues Cup, fechas FIFA, etc.).
    try:
        cal_lineas = calctx.resumen_jornada(pronosticos)
    except Exception:  # pragma: no cover - nunca debe tumbar el mensaje
        cal_lineas = []
    if cal_lineas:
        lineas.append(div)
        lineas.append("🗓️ <b>CONTEXTO DE CALENDARIO</b>")
        lineas.append("<i>Afecta disponibilidad/desgaste:</i>")
        for c in cal_lineas:
            lineas.append(f"• {c}")

    if pronosticos:
        lineas.append(div)
        lineas.append("📋 <b>PARTIDOS DE LA JORNADA</b>")
        nums = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
        for idx, p in enumerate(pronosticos[:_MAX_PARTIDOS]):
            lineas.append("")
            n = nums[idx] if idx < len(nums) else "•"
            conf = f" · confianza <b>{p['nivel_confianza']}</b>" if p.get("nivel_confianza") else ""
            prob_pick = p.get("prob_pick_pct")
            pptxt = f" ({_pct(prob_pick)}%)" if prob_pick is not None else ""
            lineas.append(f"{n} <b>{p['local']}</b> 🏠 vs <b>{p['visitante']}</b> ✈️")
            lineas.append(f"🎯 Pick: <b>{_pick_club(p)}</b>{pptxt}{conf}")
            lineas.append(f"📊 Local {_pct(p['prob_local_pct'])}% · Empate {_pct(p['prob_empate_pct'])}% · Visita {_pct(p['prob_visitante_pct'])}%")
            _lg = _linea_goles(p)
            if _lg:
                lineas.append(_lg)
            if p.get("explicacion_1x2"):
                lineas.append(f"💡 {p['explicacion_1x2']}")
            if p.get("explicacion_ou"):
                lineas.append(f"💡 {p['explicacion_ou']}")
            if p.get("nota_handicap"):
                lineas.append(f"🔻 {p['nota_handicap']}")
            if p.get("precaucion") and p.get("motivos_alerta"):
                lineas.append(f"{p['nivel_alerta']}: {' '.join(p['motivos_alerta'])}")
            if p.get("h2h_nota"):
                lineas.append(f"🐆 H2H: {p['h2h_nota']}")
            lineas.extend(_lineas_mercado(p))
            try:
                cal_ev = calctx.eventos_para_fecha(p.get("fecha"), [p.get("local", ""), p.get("visitante", "")])
            except Exception:  # pragma: no cover
                cal_ev = []
            if cal_ev:
                nombres = " · ".join(f"{e.get('emoji', '🗓️')} {e.get('nombre')}" for e in cal_ev)
                lineas.append(f"🗓️ Calendario: {nombres}")
            if goleadores_map:
                estrellas = _jugadores_seguir_partido(p, goleadores_map)
                if estrellas:
                    lineas.append(f"⭐ A seguir: {estrellas}")
            if porteros_map:
                muro = _porteros_partido(p, porteros_map)
                if muro:
                    lineas.append(f"🧤 Muro: {muro}")
    else:
        lineas.append(div)
        lineas.append("Sin pronósticos disponibles (faltan datos de ESPN o fixtures).")

    # TOTALES DE LA JORNADA
    if pronosticos:
        lineas.append(div)
        lineas.append("📊 <b>TOTALES DE LA JORNADA</b>")
        totales = _totales_jornada(pronosticos)
        lineas.append(f"⚽ Goles esperados totales: {totales['goles_esperados_total']}")
        lineas.append(f"📊 Promedio por partido: {totales['promedio_goles_partido']}")
        lineas.append(f"🔺 Over 2.5: {totales['over_25_count']} partidos")
        lineas.append(f"🔻 Under 2.5: {totales['under_25_count']} partidos")
        lineas.append(f"✅ BTTS Sí: {totales['btts_si_count']} partidos")
        lineas.append(f"❌ BTTS No: {totales['btts_no_count']} partidos")

    lineas += [div, DISCLAIMER]
    return "\n".join(lineas)


_TELEGRAM_LIMITE = 4000  # tope real de Telegram es 4096; dejamos margen.


def _dividir_mensaje(texto: str, limite: int = _TELEGRAM_LIMITE) -> List[str]:
    """
    Parte un mensaje largo en trozos <= `limite`, cortando SIEMPRE en saltos de
    línea (nunca a media línea) para respetar el tope de Telegram (~4096) y no
    romper etiquetas HTML (cada línea abre y cierra las suyas).
    """
    if len(texto) <= limite:
        return [texto]
    partes: List[str] = []
    actual = ""
    for linea in texto.split("\n"):
        # Línea suelta más larga que el límite (muy raro): corte duro.
        while len(linea) > limite:
            if actual:
                partes.append(actual)
                actual = ""
            partes.append(linea[:limite])
            linea = linea[limite:]
        if actual and len(actual) + 1 + len(linea) > limite:
            partes.append(actual)
            actual = linea
        else:
            actual = f"{actual}\n{linea}" if actual else linea
    if actual:
        partes.append(actual)
    return partes


def _totales_jornada(pronosticos: list) -> Dict[str, Any]:
    """Calcula totales de la jornada: partidos, goles esperados, O/U, BTTS."""
    if not pronosticos:
        return {"partidos": 0, "goles_esperados_total": 0.0, "promedio_goles_partido": 0.0,
                "over_25_count": 0, "under_25_count": 0, "btts_si_count": 0, "btts_no_count": 0}
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


def enviar_mensaje(mensaje: str) -> bool:
    """
    Envía un mensaje a Telegram. Si excede el tope (~4096), lo parte en varios
    y los manda en orden. Devuelve True solo si TODOS los trozos se enviaron.
    """
    if requests is None:
        print("⚠️ 'requests' no instalado; no se envía.")
        return False
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("⚠️ Telegram no configurado (faltan TELEGRAM_BOT_TOKEN/CHAT_ID).")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    ok = True
    for parte in _dividir_mensaje(mensaje):
        try:
            resp = requests.post(
                url, data={"chat_id": chat_id, "text": parte, "parse_mode": "HTML"}, timeout=20
            )
            if resp.status_code != 200:
                ok = False
                print(f"Telegram HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as exc:  # pragma: no cover
            print(f"Error enviando Telegram: {exc}")
            ok = False
    return ok


def _falta_en_xi(clave: List[str], titulares: List[str]) -> List[str]:
    """Jugadores clave que NO aparecen en el XI titular (match por apellido)."""
    tits = " | ".join(clean_team_name(t) for t in (titulares or []))
    if not tits:
        return []
    faltan: List[str] = []
    for p in clave or []:
        toks = clean_team_name(p).split()
        apellido = toks[-1] if toks else ""
        if apellido and len(apellido) >= 3 and apellido not in tits:
            faltan.append(p)
    return faltan


def _alerta_xi(dossier: Dict[str, Any]) -> Dict[str, List[str]]:
    """
    Cruza los jugadores a seguir con el XI confirmado. Devuelve
    {'local':[...], 'visita':[...]} con los CLAVE que NO son titulares.
    Vacío si no hay XI publicado aún.
    """
    ali = dossier.get("alineacion")
    if not isinstance(ali, dict) or not ali.get("disponible"):
        return {}
    js = dossier.get("jugadores_seguir") or {}
    tit_local: List[str] = []
    tit_visita: List[str] = []
    for e in ali.get("equipos", []):
        cond = str(e.get("condicion", "")).lower()
        tits = e.get("titulares", []) or []
        if cond in ("home", "local"):
            tit_local = tits
        elif cond in ("away", "visita", "visitante"):
            tit_visita = tits
    out: Dict[str, List[str]] = {}
    ml = _falta_en_xi(js.get("local", []), tit_local)
    mv = _falta_en_xi(js.get("visita", []), tit_visita)
    if ml:
        out["local"] = ml
    if mv:
        out["visita"] = mv
    return out


def _fmt_fichajes(mov: Dict[str, Any]) -> str:
    """De {altas:[...], bajas:[...]} arma 'Altas: A, B · Bajas: C' o '' si vacío."""
    if not isinstance(mov, dict):
        return ""
    partes: List[str] = []
    altas = mov.get("altas") or []
    bajas = mov.get("bajas") or []
    if altas:
        partes.append("Altas: " + ", ".join(str(x) for x in altas[:4]))
    if bajas:
        partes.append("Bajas: " + ", ".join(str(x) for x in bajas[:4]))
    return " · ".join(partes)


def _ajustar_pick_top(picks: List[Dict[str, Any]],
                      pronosticos: List[Dict[str, Any]],
                      contexto_pick: Optional[Dict[str, Any]]) -> None:
    """
    Aplica el ajuste MODERADO (XI + H2H) al pick #1 y refleja el resultado en sus
    números (no-perder, gana, nivel) y en `razon`. Muta `picks[0]` in situ.
    No hace nada si no hay señales (XI no publicado / H2H insuficiente).
    """
    if not picks or not contexto_pick:
        return
    try:
        import ajuste_pronostico as aj
    except ImportError:  # pragma: no cover
        from src import ajuste_pronostico as aj  # type: ignore
    try:
        from team_normalizer import canonical_team_key as _k
    except ImportError:  # pragma: no cover
        from src.team_normalizer import canonical_team_key as _k  # type: ignore

    rec = picks[0]
    es_local = rec.get("condicion") == "Local"
    local = rec["equipo"] if es_local else rec["rival"]
    visita = rec["rival"] if es_local else rec["equipo"]
    pron = next(
        (p for p in pronosticos
         if _k(p.get("local", "")) == _k(local) and _k(p.get("visitante", "")) == _k(visita)),
        None,
    )
    if not pron:
        return
    impacto = contexto_pick.get("impacto_xi")
    h2h = contexto_pick.get("h2h")
    ajustado = aj.ajustar_pronostico(pron, impacto_equipos=impacto, h2h=h2h)
    if not ajustado.get("ajuste", {}).get("aplicado"):
        return
    # Reflejar los nuevos números en el pick (según su condición).
    if es_local:
        rec["no_perder_pct"] = ajustado["no_perder_local_pct"]
        rec["prob_victoria_pct"] = ajustado["prob_local_pct"]
    else:
        rec["no_perder_pct"] = ajustado["no_perder_visitante_pct"]
        rec["prob_victoria_pct"] = ajustado["prob_visitante_pct"]
    notas = "; ".join(ajustado["ajuste"].get("notas", []))
    if notas:
        base = ajustado["ajuste"].get("base", {})
        rec["ajuste_nota"] = notas
        contexto_pick["ajuste_pick"] = {"notas": notas, "base": base}


def _contexto_top_pick(pronosticos: List[Dict[str, Any]],
                       equipos_usados: Optional[List[str]],
                       motivacion: Optional[Dict[str, Dict[str, Any]]],
                       pick_override: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    Dossier compacto (Liga MX API) del pick #1. Tolerante: None si algo falla.
    Si se pasa `pick_override` (dict con equipo/rival/condicion), el dossier se arma
    para ESE pick, de modo que el contexto coincida con el pick del plan que se muestra.
    """
    try:
        try:
            import ligamx_api as lmx
        except ImportError:  # pragma: no cover
            from src import ligamx_api as lmx  # type: ignore
        if pick_override and pick_override.get("equipo") and pick_override.get("rival"):
            pk = pick_override
        else:
            tops = motor.mejores_picks_survivor(pronosticos, equipos_usados, motivacion, n=1)
            if not tops:
                return None
            pk = tops[0]
        if pk.get("condicion") == "Local":
            home, away = pk["equipo"], pk["rival"]
        else:
            home, away = pk["rival"], pk["equipo"]
        dossier = lmx.resumen_partido(home, away)
        # Análisis de IA (Groq) sobre las noticias reales del partido (opcional).
        try:
            try:
                import analista_ia as ia
            except ImportError:  # pragma: no cover
                from src import analista_ia as ia  # type: ignore
            if ia.habilitado() and isinstance(dossier, dict):
                dossier["analisis_ia"] = ia.analizar_noticias(
                    [dossier.get("home", home), dossier.get("away", away)],
                    dossier.get("noticias", []),
                )
        except Exception:  # pragma: no cover - IA nunca debe tumbar el pick
            pass
        # Altas/bajas: primero la API 365Scores (automático), si no, archivo local (asistido).
        try:
            if isinstance(dossier, dict):
                loc = vis = ""
                try:
                    tdata = lmx.transfers_365()
                    tl = lmx.transfers_equipo(dossier.get("home", home), tdata)
                    tv = lmx.transfers_equipo(dossier.get("away", away), tdata)
                    loc = _fmt_fichajes(tl)
                    vis = _fmt_fichajes(tv)
                except Exception:  # pragma: no cover - API no disponible
                    pass
                if not loc and not vis:  # fallback al modo asistido (data/fichajes.json)
                    try:
                        import fichajes as fich
                    except ImportError:  # pragma: no cover
                        from src import fichajes as fich  # type: ignore
                    loc = fich.linea_equipo(dossier.get("home", home))
                    vis = fich.linea_equipo(dossier.get("away", away))
                if loc or vis:
                    dossier["fichajes"] = {"local": loc, "visita": vis}
        except Exception:  # pragma: no cover - nunca debe tumbar el pick
            pass
        # Revisión de alineación: ¿falta un jugador clave en el XI confirmado?
        try:
            if isinstance(dossier, dict):
                alerta = _alerta_xi(dossier)
                if alerta:
                    dossier["alerta_xi"] = alerta
        except Exception:  # pragma: no cover
            pass
        # Impacto del XI (endpoint real: fuerza_xi_pct + ausentes clave por importancia).
        try:
            if isinstance(dossier, dict):
                imp = lmx.lineup_impact_partido(dossier.get("home", home), dossier.get("away", away))
                if isinstance(imp, dict) and imp.get("disponible"):
                    dossier["impacto_xi"] = imp.get("equipos") or {}
        except Exception:  # pragma: no cover
            pass
        # XI PROBABLE (365Scores) si aún no hay confirmado — idea temprana de quién juega.
        try:
            ali = dossier.get("alineacion") if isinstance(dossier, dict) else None
            ya_confirmado = bool(ali and ali.get("disponible"))
            if isinstance(dossier, dict) and not ya_confirmado:
                prob = lmx.probable_lineup_partido(dossier.get("home", home), dossier.get("away", away))
                if isinstance(prob, dict) and prob.get("disponible"):
                    dossier["alineacion_probable"] = prob.get("equipos") or []
        except Exception:  # pragma: no cover
            pass
        return dossier
    except Exception:  # pragma: no cover - nunca debe tumbar el envío
        return None


def _registrar_historial(pronosticos) -> None:
    """Guarda los pronósticos en el track-record (dedup por equipos+fecha). Tolerante."""
    try:
        try:
            from database import registrar_pronostico
        except ImportError:  # pragma: no cover
            from src.database import registrar_pronostico  # type: ignore
    except Exception:  # pragma: no cover
        return
    for p in pronosticos or []:
        try:
            registrar_pronostico(
                p.get("local", ""), p.get("visitante", ""), p.get("pick_1x2", ""),
                p.get("prob_local_pct", 0), p.get("prob_empate_pct", 0),
                p.get("prob_visitante_pct", 0),
                p.get("marcador_pick") or p.get("marcador_mas_probable", ""),
                fecha=p.get("fecha", ""),
            )
        except Exception:  # pragma: no cover - nunca tumbar el envío por el log
            continue


def _iso_week(fecha: str) -> str:
    """Etiqueta de jornada = semana ISO de la fecha (YYYY-Www). '' si no se puede."""
    try:
        from datetime import date
        y, m, d = str(fecha)[:10].split("-")
        yr, wk, _ = date(int(y), int(m), int(d)).isocalendar()
        return f"{yr}-W{wk:02d}"
    except Exception:
        return ""


def _registrar_survivor_historial(picks, pronosticos) -> None:
    """
    Registra el pick #1 de Survivor de la jornada en el track-record (una fila por
    jornada = semana ISO). Ubica el partido en los pronósticos por equipo+rival
    según la condición para sacar fecha y local/visitante. Tolerante: nunca lanza.
    """
    if not picks:
        return
    try:
        try:
            import database as _db
        except ImportError:  # pragma: no cover
            from src import database as _db  # type: ignore
    except Exception:  # pragma: no cover
        return
    pk = picks[0]
    equipo = pk.get("equipo")
    rival = pk.get("rival")
    if not equipo:
        return
    es_local = str(pk.get("condicion") or "").strip().lower() == "local"

    def _cf(s):
        return str(s or "").strip().casefold()

    def _coincide(pron, exacto=True):
        loc, vis = pron.get("local", ""), pron.get("visitante", "")
        if exacto:
            a, b = (loc, vis) if es_local else (vis, loc)
            return a == equipo and b == rival
        a, b = (loc, vis) if es_local else (vis, loc)
        return _cf(a) == _cf(equipo) and _cf(b) == _cf(rival)

    partido = next((p for p in (pronosticos or []) if _coincide(p, True)), None)
    if partido is None:
        partido = next((p for p in (pronosticos or []) if _coincide(p, False)), None)
    if partido is None:
        return
    fecha = str(partido.get("fecha", ""))[:10]
    jornada = _iso_week(fecha) or fecha
    if not jornada:
        return
    try:
        _db.registrar_survivor_pick(
            jornada=jornada, equipo=equipo, rival=rival or "",
            condicion=pk.get("condicion", ""),
            local=partido.get("local", ""), visitante=partido.get("visitante", ""),
            no_perder_pct=pk.get("no_perder_pct", 0),
            prob_victoria_pct=pk.get("prob_victoria_pct", 0),
            fecha=fecha,
        )
    except Exception:  # pragma: no cover - nunca tumbar el envío por el track-record
        pass


def enviar_pronosticos(equipos_usados: Optional[List[str]] = None,
                       incluir_contexto: bool = True) -> Dict[str, Any]:
    """
    Genera pronósticos reales y los envía por Telegram, enriquecidos con:
    - momios/valor del mercado (si hay ODDS_API_IO_KEY; si no, no-op),
    - motivación de la tabla (defensivo; {} si no hay red), y
    - contexto de la Liga MX API para el pick #1 (forma/tarjetas/2ª opinión),
      si `incluir_contexto` (tolerante: si no hay datos aún, no aparece).
    """
    resultado = motor.generar_pronosticos()
    pronosticos = resultado.get("pronosticos", [])
    _registrar_historial(pronosticos)  # track-record (dedup, tolerante)

    # Excluir equipos ya usados (persistidos en BD) si no se pasaron explícitos.
    if equipos_usados is None:
        equipos_usados = _usados_persistidos()

    # Momios/valor (gated por key; sin key no toca nada). Se bajan UNA vez y se
    # reutilizan para: anotar (mostrar), mezclar en el pick, y archivar histórico.
    con_momios = 0
    try:
        try:
            import comparador_mercado as cm
            import ligamx_api as lmx
        except ImportError:  # pragma: no cover
            from src import comparador_mercado as cm  # type: ignore
            from src import ligamx_api as lmx  # type: ignore
        try:
            momios, fuente_m = cm.momios_para_uso()
        except Exception:  # pragma: no cover
            momios, fuente_m = {}, None
        pron_anotados = cm.anotar_pronosticos(pronosticos, momios)
        # Mezcla los momios en las probabilidades del pick (ensemble modelo+mercado).
        # Sin key/momios es no-op (el pick sigue siendo el del modelo).
        resultado["pronosticos"] = cm.mezclar_pronosticos_con_mercado(pron_anotados, momios=momios)
        con_momios = sum(1 for m in (momios or {}).values()
                         if isinstance(m, dict) and m.get("ml"))
        # Fallback: partidos que el modelo no pudo pronosticar (equipo sin histórico,
        # p.ej. un recién ascendido como Atlante). Si el mercado tiene momios de ese
        # juego, lo mostramos con probabilidades del mercado en vez de omitirlo.
        try:
            faltantes = resultado.get("fixtures_sin_modelo") or []
            extra = []
            for fx in faltantes:
                merc = cm.buscar_mercado_partido(fx.get("home_team", ""),
                                                 fx.get("away_team", ""), momios or {})
                pr = cm.pronostico_desde_momios(fx.get("home_team", ""),
                                                fx.get("away_team", ""), merc,
                                                fx.get("fecha", ""))
                if pr:
                    extra.append(pr)
            if extra:
                resultado["pronosticos"] = list(resultado.get("pronosticos", [])) + extra
        except Exception:  # pragma: no cover - nunca tumbar el envío
            pass
        # Archiva el snapshot de momios en la Liga MX API (histórico), best-effort.
        try:
            snaps = cm.construir_snapshots_momios(pron_anotados, momios, source=fuente_m)
            if snaps:
                lmx.archivar_momios(snaps)
        except Exception:  # pragma: no cover
            pass
    except Exception:  # pragma: no cover - nunca debe tumbar el envío
        pass

    # Motivación de la tabla (contexto/desempate Survivor).
    try:
        motivacion = motor.motivacion_por_equipo()
    except Exception:  # pragma: no cover
        motivacion = {}

    # Chequeo de la API hermana (Render free duerme y despierta lento).
    # - DÍA DE JORNADA (partido a <=2 días): la DESPERTAMOS y esperamos hasta ~45s
    #   para traer todos los extras (forma, jugadores a seguir, dossier). Un solo
    #   /health aguanta el cold start de Render y confirma cuando ya está lista.
    # - LEJOS de la jornada: chequeo rápido (5s); si duerme, saltamos el
    #   enriquecimiento lento y mandamos el pick igual sin colgarnos minutos.
    # El CEREBRO del pick (modelo + momios + estrategia) NO depende de esto.
    cerca = _cerca_de_jornada(resultado.get("pronosticos", []))
    api_ok = False
    try:
        try:
            import ligamx_api as _lmx_probe
        except ImportError:  # pragma: no cover
            from src import ligamx_api as _lmx_probe  # type: ignore
        api_ok = _lmx_probe.disponible(timeout=45 if cerca else 5)
    except Exception:  # pragma: no cover
        api_ok = False

    # Pick ESTRATÉGICO de la jornada (cautela de arranque + anti-sorpresa visitante).
    est = motor.mejores_picks_estrategico(
        resultado.get("pronosticos", []), equipos_usados, motivacion,
        partidos_jugados_torneo=_partidos_jugados_torneo() if api_ok else None, n=3,
    )
    # UNIFICAR con el PLAN de temporada: el pick recomendado = el equipo que el plan
    # asigna a ESTA jornada (una sola fuente de verdad; prioriza sobrevivir las 17).
    # Así /pick y /plan SIEMPRE coinciden. Si no hay calendario/plan, queda el de la jornada.
    try:
        try:
            from team_normalizer import canonical_team_key as _kp
        except ImportError:  # pragma: no cover
            from src.team_normalizer import canonical_team_key as _kp  # type: ignore
        _picks = est.get("picks") or []
        _rec_plan = _rec_desde_plan(_plan_temporada(equipos_usados), _jornada_actual_num())
        if _jornada_actual_num() == 1:
            _rec_plan = _OVERRIDE_JORNADA_1
        if _rec_plan and _picks:
            _miope = _picks[0].get("equipo")
            if _kp(_rec_plan.get("equipo")) != _kp(_miope):
                _rec_plan["razon"] = (
                    f"el plan de temporada guarda a {_miope} para una jornada más difícil "
                    f"y usa a {_rec_plan['equipo']} aquí (mirando las 17 completas)."
                )
            else:
                _rec_plan["razon"] = "es el equipo de esta jornada según el plan de toda la temporada."
            _resto = [p for p in _picks if _kp(p.get("equipo")) != _kp(_rec_plan.get("equipo"))]
            est["picks"] = [_rec_plan] + _resto
    except Exception:  # pragma: no cover - la unificación nunca debe tumbar el envío
        pass

    # Dossier del pick #1 (ya unificado con el plan), solo si la API está despierta.
    contexto_pick = None
    if incluir_contexto and api_ok:
        _top = (est.get("picks") or [None])[0]
        contexto_pick = _contexto_top_pick(resultado.get("pronosticos", []),
                                           equipos_usados, motivacion, pick_override=_top)
    # Ajuste MODERADO del pick #1 por XI confirmado + H2H (con tope; nunca voltea).
    try:
        _ajustar_pick_top(est.get("picks") or [], resultado.get("pronosticos", []),
                          contexto_pick)
    except Exception:  # pragma: no cover - el ajuste nunca debe tumbar el envío
        pass
    # Registra el pick de Survivor de la jornada para el track-record (racha).
    try:
        _registrar_survivor_historial(est.get("picks") or [], resultado.get("pronosticos", []))
    except Exception:  # pragma: no cover - nunca debe tumbar el envío
        pass
    # Jugadores a seguir por partido (goleadores por equipo; una sola llamada).
    # Solo si la API hermana respondió el chequeo rápido (evita cold-start lento).
    goleadores_map = None
    porteros_map = None
    if api_ok:
        try:
            try:
                import ligamx_api as lmx
            except ImportError:  # pragma: no cover
                from src import ligamx_api as lmx  # type: ignore
            goleadores_map = lmx.goleadores_por_equipo()
        except Exception:  # pragma: no cover - nunca debe tumbar el envío
            goleadores_map = None
        try:
            try:
                import ligamx_api as lmx
            except ImportError:  # pragma: no cover
                from src import ligamx_api as lmx  # type: ignore
            porteros_map = lmx.porteros_por_equipo()
        except Exception:  # pragma: no cover - nunca debe tumbar el envío
            porteros_map = None
    mensaje = construir_mensaje(resultado, equipos_usados, motivacion, contexto_pick,
                                tops=est.get("picks"), advertencia=est.get("advertencia"),
                                goleadores_map=goleadores_map, porteros_map=porteros_map)
    enviado = enviar_mensaje(mensaje)
    return {
        "enviado": enviado,
        "total_pronosticos": resultado.get("total_pronosticos", 0),
        "partidos_con_momios": con_momios,
        "fuente": resultado.get("fuente_datos"),
        "cautela": est.get("cautela"),
    }


def construir_mensaje_seguimiento(items: List[Dict[str, Any]],
                                  descartados: Optional[List[str]] = None,
                                  recomendado: Optional[Dict[str, Any]] = None,
                                  nota_plan: Optional[str] = None) -> str:
    """
    Mensaje (HTML) centrado en UN pick claro y UN momento para actuar (no un menú).
    El respaldo solo se menciona; el día del partido, el veredicto del XI decide
    si se mantiene o se cambia.
    """
    if not items:
        return ("📋 <b>LISTA DE SEGUIMIENTO</b>\n\n"
                "Aún no hay candidatos (faltan datos de la jornada).\n\n"
                f"{DISCLAIMER}")

    def _sede(c: Dict[str, Any]) -> str:
        return "🏠 local" if c.get("condicion") == "Local" else "✈️ visita"

    rec = recomendado or items[0]
    # Item con hora/veredicto del recomendado (si está en la lista).
    rec_item = next((it for it in items if it.get("equipo") == rec.get("equipo")), rec)
    cuando = rec_item.get("cuando") or ""
    ver = rec_item.get("veredicto") or {}
    gana = rec.get("prob_victoria_pct")
    gtxt = f" · gana {_pct(gana)}%" if gana is not None else ""

    lineas = [
        "🎯 <b>TU PICK DE SURVIVOR</b>",
        f"✅ <b>{rec['equipo']}</b>",
        f"{_sede(rec)} vs {rec['rival']}",
        f"Sobrevive {_pct(rec['no_perder_pct'])}%{gtxt}",
        f"Confianza <b>{rec.get('nivel', '—')}</b>",
    ]
    if nota_plan:
        lineas.append(nota_plan)
    if cuando:
        lineas.append(f"📅 Juega: <b>{cuando}</b>")
    lineas.append("")

    estado = ver.get("estado", "PENDIENTE")
    if estado == "CONFIRMA":
        lineas.append("✅ <b>Alineación confirmada y completa.</b> Este es tu pick — mételo en PlayDoit.")
    elif estado in ("DESCARTA", "DUDA"):
        alt = next((it["equipo"] for it in items if it.get("equipo") != rec.get("equipo")), None)
        lineas.append(f"{ver.get('emoji', '⚠️')} <b>Ojo:</b> {ver.get('texto', '')}")
        if alt:
            lineas.append(f"👉 Mejor alternativa: <b>{alt}</b>. Manda /seguir para verla.")
    else:  # PENDIENTE
        momento = f"el <b>{cuando.split()[0]}</b> " if cuando else ""
        lineas.append(f"👉 <b>Qué hacer:</b> manda <code>/seguir</code> {momento}~1h antes de su partido "
                      "y te confirmo su alineación. Antes de eso no necesitas hacer nada.")

    otras = [it["equipo"] for it in items if it.get("equipo") != rec.get("equipo")][:2]
    if otras:
        lineas.append("")
        lineas.append(f"🔁 <i>Respaldo (solo si su XI sale mal): {', '.join(otras)}.</i>")
    # Aviso de timing: si el pick juega de los últimos, no hay red de seguridad.
    try:
        import seguimiento_jornada as _seg
    except ImportError:  # pragma: no cover
        from src import seguimiento_jornada as _seg  # type: ignore
    alt_resp = _seg.alternativa_con_respaldo(items, rec)
    if alt_resp:
        lineas.append("")
        lineas.append(
            f"⚠️ <b>Ojo con el timing:</b> {rec['equipo']} juega de los últimos"
            f"{(' (' + cuando + ')') if cuando else ''}. Si su alineación sale mal, "
            "casi no quedan partidos de respaldo."
        )
        alt_cuando = f" ({alt_resp['cuando']})" if alt_resp.get("cuando") else ""
        lineas.append(
            f"🛡️ Opción CON respaldo: <b>{alt_resp['equipo']}</b>{alt_cuando} — "
            f"sobrevive {_pct(alt_resp['no_perder_pct'])}%. Si su XI sale bien lo aseguras "
            "temprano; si no, aún te quedan partidos por jugar."
        )
        alt_ver = alt_resp.get("veredicto") or {}
        if alt_ver.get("estado") and alt_ver["estado"] != "PENDIENTE":
            lineas.append(f"{alt_ver.get('emoji', '')} {alt_resp['equipo']}: {alt_ver.get('texto', '')}")
    lineas.append("")
    lineas.append("💡 <i>Si te preocupa el internet, puedes meter tu pick en PlayDoit desde ya "
                  "y cambiarlo solo si su alineación sale mermada.</i>")
    lineas += ["", DISCLAIMER]
    return "\n".join(lineas)


def _mapa_horarios(lmx) -> Dict[str, str]:
    """{clave_equipo: match_date_iso} desde /matches/upcoming. {} si falla."""
    try:
        from team_normalizer import canonical_team_key as _k
    except ImportError:  # pragma: no cover
        from src.team_normalizer import canonical_team_key as _k  # type: ignore
    out: Dict[str, str] = {}
    try:
        for m in lmx.partidos_proximos(limit=20) or []:
            if not isinstance(m, dict):
                continue
            fecha = m.get("match_date")
            for lado in ("home_team", "away_team"):
                eq = m.get(lado) or {}
                nombre = eq.get("name") if isinstance(eq, dict) else eq
                if nombre and fecha:
                    out[_k(str(nombre))] = str(fecha)
    except Exception:  # pragma: no cover
        pass
    return out


def _plan_temporada(equipos_usados: Optional[List[str]]) -> Dict[str, Any]:
    """Construye el plan óptimo de temporada (reserva fuertes). {} si no se puede."""
    try:
        try:
            import planificador_survivor as plan_mod
            import fuentes_datos
            import poisson_model as pm
        except ImportError:  # pragma: no cover
            from src import planificador_survivor as plan_mod  # type: ignore
            from src import fuentes_datos, poisson_model as pm  # type: ignore
        calendario = plan_mod.cargar_calendario()
        if not calendario:
            return {}
        datos = fuentes_datos.obtener_resultados(meses=18)
        fuerzas = pm.calcular_fuerzas(datos["resultados"])
        odds = plan_mod.construir_odds_por_partido(calendario)
        return plan_mod.planificar(calendario, fuerzas, equipos_usados=equipos_usados,
                                   peso_victoria=0.5, odds_por_partido=odds)
    except Exception:  # pragma: no cover - nunca debe tumbar /seguir
        return {}


def _jornada_actual_num() -> Optional[int]:
    """Número de la próxima jornada por jugar (según data/calendario.json)."""
    try:
        j = proxima_jornada()
        return int(j.get("jornada")) if j else None
    except Exception:  # pragma: no cover
        return None


def _rec_desde_plan(plan: Dict[str, Any], jornada_num: Optional[int]) -> Optional[Dict[str, Any]]:
    """Entrada del plan para la jornada actual, mapeada al formato de pick."""
    if not plan or jornada_num is None:
        return None
    for p in plan.get("plan", []):
        if p.get("jornada") == jornada_num:
            return {
                "equipo": p["equipo"], "rival": p["rival"], "condicion": p["condicion"],
                "no_perder_pct": p["no_perder_pct"], "prob_victoria_pct": p.get("prob_ganar_pct"),
                "nivel": p.get("nivel"),
            }
    return None


_OVERRIDE_JORNADA_1: Optional[Dict[str, Any]] = {
    "equipo": "León", "rival": "Atlas", "condicion": "Local",
    "no_perder_pct": 72.91, "prob_victoria_pct": 55.0, "nivel": "ALTA",
    "razon": "el plan de temporada reserva a Monterrey para una jornada más difícil y usa a León aquí (mirando las 17 completas).",
}


def enviar_seguimiento(equipos_usados: Optional[List[str]] = None, n: int = 5) -> Dict[str, Any]:
    """
    Envía por Telegram la lista de seguimiento (candidatos priorizados, ordenados
    por hora de partido) para decidir el Survivor de forma secuencial.
    """
    try:
        import seguimiento_jornada as seg
    except ImportError:  # pragma: no cover
        from src import seguimiento_jornada as seg  # type: ignore
    try:
        import ligamx_api as lmx
    except ImportError:  # pragma: no cover
        from src import ligamx_api as lmx  # type: ignore

    resultado = motor.generar_pronosticos()
    pronosticos = resultado.get("pronosticos", [])
    if equipos_usados is None:
        equipos_usados = _usados_persistidos()
    try:
        motivacion = motor.motivacion_por_equipo()
    except Exception:  # pragma: no cover
        motivacion = {}
    est = motor.mejores_picks_estrategico(
        pronosticos, equipos_usados, motivacion,
        partidos_jugados_torneo=_partidos_jugados_torneo(), n=max(n, 5),
    )
    picks = est.get("picks") or []
    horarios = _mapa_horarios(lmx)
    # Fuerza del XI por equipo candidato (solo los que ya tengan alineación).
    fuerza_xi: Dict[str, float] = {}
    try:
        from team_normalizer import canonical_team_key as _k
    except ImportError:  # pragma: no cover
        from src.team_normalizer import canonical_team_key as _k  # type: ignore
    for pk in picks[:n]:
        es_local = pk.get("condicion") == "Local"
        home = pk["equipo"] if es_local else pk["rival"]
        away = pk["rival"] if es_local else pk["equipo"]
        try:
            imp = lmx.lineup_impact_partido(home, away)
            if isinstance(imp, dict) and imp.get("disponible"):
                for eq, info in (imp.get("equipos") or {}).items():
                    if isinstance(info, dict) and info.get("fuerza_xi_pct") is not None:
                        fuerza_xi[_k(eq)] = info["fuerza_xi_pct"]
        except Exception:  # pragma: no cover - nunca tumbar el envío
            pass
    items = seg.lista_seguimiento(picks, horarios=horarios, fuerza_xi=fuerza_xi, n=n)
    usados_set = {_k(e) for e in (equipos_usados or [])}
    seguidos = {_k(it["equipo"]) for it in items}
    descartados = [
        p.get("local", "") for p in pronosticos
        if _k(p.get("local", "")) not in seguidos and _k(p.get("local", "")) not in usados_set
    ][:6]
    # Recomendación PLAN-AWARE: el plan de temporada reserva a los fuertes.
    recomendado = picks[0] if picks else None
    nota_plan = None
    try:
        plan = _plan_temporada(equipos_usados)
        rec_plan = _rec_desde_plan(plan, _jornada_actual_num())
        if rec_plan:
            miope = picks[0]["equipo"] if picks else None
            if miope and _k(rec_plan["equipo"]) != _k(miope):
                nota_plan = (f"📅 Plan de temporada: usa <b>{rec_plan['equipo']}</b> esta jornada "
                             f"y GUARDA a {miope} para una jornada más difícil.")
            else:
                nota_plan = (f"📅 Plan de temporada: <b>{rec_plan['equipo']}</b> es tu equipo de esta "
                             "jornada (mirando las 17 completas, sin quemar fuertes).")
            recomendado = rec_plan
            # Asegurar que el equipo del plan esté en la lista (para XI/hora/veredicto).
            if not any(_k(it["equipo"]) == _k(rec_plan["equipo"]) for it in items):
                extra = seg.lista_seguimiento([rec_plan], horarios=horarios, fuerza_xi=fuerza_xi, n=1)
                items = extra + items
    except Exception:  # pragma: no cover - nunca debe tumbar /seguir
        pass
    mensaje = construir_mensaje_seguimiento(items, descartados=descartados,
                                            recomendado=recomendado, nota_plan=nota_plan)
    enviado = enviar_mensaje(mensaje)
    return {"enviado": enviado, "candidatos": len(items)}


def construir_mensaje_plan(plan: Dict[str, Any]) -> str:
    """Mensaje (HTML) con el plan de temporada del Survivor."""
    if plan.get("calendario_incompleto") or not plan.get("plan"):
        return ("📅 <b>PLAN SURVIVOR</b>\n\n"
                "Aún no hay calendario completo (data/calendario.json). "
                "Córrelo de nuevo cuando se publique el calendario del torneo.\n\n"
                f"{DISCLAIMER}")
    lineas = [
        "📅 <b>PLAN SURVIVOR — temporada</b> (modelo · datos ESPN)",
        f"<i>🛡️ Sobrevivir las 17 jornadas: {_pct(plan.get('prob_supervivencia_total_pct'))}% · "
        f"🏆 victorias esperadas: {plan.get('victorias_esperadas')}</i>",
        "<i>Idea: gastar equipos flojos en su mejor partido y guardar a los fuertes "
        "para las jornadas difíciles. Ganar es lo que vale (desempate).</i>",
        "",
    ]
    for p in plan["plan"]:
        lineas.append(
            f"<b>J{p['jornada']} · {p['equipo']}</b> ({p['condicion']} vs {p['rival']})"
        )
        lineas.append(
            f"🏆 gana {_pct(p['prob_ganar_pct'])}% · 🛡️ sobrevive {_pct(p['no_perder_pct'])}% [{p['nivel']}]"
        )
    riesgosas = plan.get("jornadas_riesgosas") or []
    if riesgosas:
        lineas.append("")
        lineas.append(f"⚠️ Jornadas riesgosas: {', '.join('J'+str(j) for j in riesgosas)}")
    no_usados = plan.get("equipos_no_usados") or []
    if no_usados:
        lineas.append("")
        if len(no_usados) == 1:
            lineas.append(
                f"🚫 Equipo que NO usarás (sacrificado): <b>{no_usados[0]}</b> — "
                f"no tiene una jornada suficientemente buena, sale del plan."
            )
        else:
            lineas.append(
                "🚫 Equipos que NO usarás (sacrificados): "
                f"<b>{', '.join(no_usados)}</b> — sin jornada lo bastante buena."
            )
        lineas.append(
            "<i>El resto de los flojos ya está colocado en su partido menos malo "
            "(de local vs rival débil).</i>"
        )
    lineas += ["", DISCLAIMER]
    return "\n".join(lineas)


def enviar_plan(equipos_usados: Optional[List[str]] = None,
                peso_victoria: float = 0.5, usar_momios: bool = True) -> Dict[str, Any]:
    """
    Construye el plan de temporada (ESPN + Poisson, momios opcionales) y lo envía
    por Telegram. Defensivo: si falta calendario/histórico, envía un aviso claro.
    """
    try:
        import planificador_survivor as plan_mod
        import fuentes_datos
        import poisson_model as pm
    except ImportError:  # pragma: no cover
        from src import planificador_survivor as plan_mod  # type: ignore
        from src import fuentes_datos, poisson_model as pm  # type: ignore

    if equipos_usados is None:
        equipos_usados = _usados_persistidos()

    calendario = plan_mod.cargar_calendario()
    if not calendario:
        plan = {"calendario_incompleto": True, "plan": []}
    else:
        try:
            datos = fuentes_datos.obtener_resultados(meses=18)
            fuerzas = pm.calcular_fuerzas(datos["resultados"])
            odds = plan_mod.construir_odds_por_partido(calendario) if usar_momios else None
            plan = plan_mod.planificar(calendario, fuerzas, equipos_usados=equipos_usados,
                                       peso_victoria=peso_victoria, odds_por_partido=odds)
        except Exception as exc:  # pragma: no cover
            plan = {"calendario_incompleto": True, "plan": [], "error": str(exc)}

    mensaje = construir_mensaje_plan(plan)
    enviado = enviar_mensaje(mensaje)
    return {"enviado": enviado, "jornadas": len(plan.get("plan", [])),
            "calendario_incompleto": bool(plan.get("calendario_incompleto"))}


# ---------------------------------------------------------------------------
# "Prueba" de la estrategia (backtest en lenguaje simple) por Telegram
# ---------------------------------------------------------------------------
def construir_mensaje_prueba(comp: Dict[str, Any]) -> str:
    """Mensaje (HTML, simple) del backtest de estrategias, para el comando /prueba."""
    div = "━━━━━━━━━━"
    por = (comp or {}).get("por_estrategia", {})
    real = por.get("real", {})
    ingenua = por.get("ingenua", {})

    if not real or real.get("torneos_evaluados", 0) == 0:
        return ("🧪 <b>PRUEBA DE LA ESTRATEGIA</b>\n\n"
                "Todavía no hay suficiente historial de temporadas para probarla "
                "(hace falta más calendario/resultados de ESPN). Vuelve a intentar "
                "cuando el torneo ya tenga jornadas jugadas.\n\n"
                f"{DISCLAIMER}")

    n = real.get("torneos_evaluados")
    parciales = real.get("torneos_parciales") or 0
    sub = f"<i>Jugué el Survivor en {n} torneos completos con datos reales"
    if parciales:
        sub += f" ({parciales} torneo(s) sin datos suficientes no cuentan)"
    sub += "</i>"
    lineas = [
        "🧪 <b>PRUEBA DE LA ESTRATEGIA</b>",
        sub,
        div,
        "🤖 <b>La estrategia del bot</b> (la que usas):",
        f"✅ Sobrevivió completo: <b>{real.get('torneos_sobrevividos_completos')}/{n}</b>"
        f" ({real.get('tasa_supervivencia_torneo_pct')}%)",
        f"📊 Aguantó en promedio: <b>{real.get('jornadas_sobrevividas_prom')}</b> jornadas",
        f"🏆 Victorias por torneo: <b>{real.get('victorias_prom_por_torneo')}</b>",
    ]
    if ingenua and ingenua.get("torneos_evaluados"):
        lineas += [
            "",
            "🎲 <b>Elegir a lo simple</b> (solo 'no perder'):",
            f"✅ Sobrevivió: <b>{ingenua.get('torneos_sobrevividos_completos')}/"
            f"{ingenua.get('torneos_evaluados')}</b> ({ingenua.get('tasa_supervivencia_torneo_pct')}%)",
        ]
        r_tasa = real.get("tasa_supervivencia_torneo_pct") or 0
        i_tasa = ingenua.get("tasa_supervivencia_torneo_pct") or 0
        r_vic = real.get("victorias_prom_por_torneo") or 0
        i_vic = ingenua.get("victorias_prom_por_torneo") or 0
        r_jor = real.get("jornadas_sobrevividas_prom") or 0
        if r_tasa == 0 and i_tasa == 0:
            concl = ("👉 <b>La verdad del Survivor:</b> sobrevivir las 17 jornadas es MUY "
                     "difícil. En el histórico NINGUNA estrategia lo logró completo; el bot "
                     f"aguantó ~{r_jor} jornadas en promedio antes de caer. Te da la mejor "
                     "chance cada semana, pero no hay garantía: una derrota elimina.")
        elif r_tasa > i_tasa or (r_tasa == i_tasa and r_vic >= i_vic):
            concl = "👉 La estrategia del bot va igual o mejor que elegir a lo simple."
        else:
            concl = ("👉 En este histórico, elegir a lo simple no salió peor. La estrategia "
                     "del bot prioriza SEGURIDAD (menos sorpresas), no más victorias.")
        lineas += ["", concl]
    lineas += [div, DISCLAIMER]
    return "\n".join(lineas)


def enviar_prueba() -> Dict[str, Any]:
    """
    Corre el backtest (compara estrategias sobre temporadas pasadas de ESPN) y
    envía el resultado en lenguaje simple. Tolerante: nunca rompe.
    """
    try:
        import fuentes_datos
        import backtest_estrategias as be
    except ImportError:  # pragma: no cover
        from src import fuentes_datos  # type: ignore
        from src import backtest_estrategias as be  # type: ignore
    try:
        datos = fuentes_datos.obtener_historico_largo()
        comp = be.comparar_estrategias(datos["resultados"])
    except Exception as exc:  # pragma: no cover
        comp = {}
        _ = exc
    enviado = enviar_mensaje(construir_mensaje_prueba(comp))
    return {"enviado": enviado, "mejor": (comp or {}).get("mejor")}


# ---------------------------------------------------------------------------
# "Confianza" del bot (calibración en lenguaje simple) por Telegram
# ---------------------------------------------------------------------------
def construir_mensaje_confianza(rep: Dict[str, Any]) -> str:
    """Mensaje (HTML, simple) del reporte de calibración, para el comando /confianza."""
    div = "━━━━━━━━━━"
    if not rep or rep.get("n_muestras", 0) < 20:
        return ("📐 <b>¿LA CONFIANZA DEL BOT ES HONESTA?</b>\n\n"
                "Aún no hay suficientes pronósticos pasados para revisarlo. "
                "Vuelve a intentar cuando el torneo tenga más jornadas jugadas.\n\n"
                f"{DISCLAIMER}")

    alpha = rep.get("alpha_sugerido", 0.0)
    ayuda = rep.get("calibracion_ayuda")
    if alpha <= 0.0:
        diagnostico = "🟢 El modelo ya está bien calibrado: su confianza es de fiar."
        recomendacion = "👉 No hace falta ajustar nada."
    else:
        diagnostico = ("🟡 El modelo es un poco OPTIMISTA: a veces dice más confianza "
                       "de la real.")
        recomendacion = ("👉 Conviene bajarle un poco la confianza. Si quieres, dime "
                         "y activo el ajuste.")
    lineas = [
        "📐 <b>¿LA CONFIANZA DEL BOT ES HONESTA?</b>",
        f"<i>Revisé {rep.get('n_muestras')} pronósticos pasados vs lo que pasó</i>",
        div,
        diagnostico,
        f"🔧 Ajuste sugerido: <b>{int(round(alpha * 100))}%</b> menos de confianza",
    ]
    if rep.get("brier_sin_calibrar_eval") is not None:
        mejora = "sí" if ayuda else "no cambia"
        lineas.append(
            f"📊 ¿Mejora al ajustar? <b>{mejora}</b> "
            f"(error {rep.get('brier_sin_calibrar_eval')} → {rep.get('brier_calibrado_eval')}, "
            "más bajo = mejor)"
        )
    lineas += ["", recomendacion, div, DISCLAIMER]
    return "\n".join(lineas)


def enviar_confianza() -> Dict[str, Any]:
    """
    Mide la calibración del modelo (walk-forward sobre ESPN) y envía el reporte
    en lenguaje simple. Tolerante: nunca rompe.
    """
    try:
        import fuentes_datos
        import calibracion as cal
    except ImportError:  # pragma: no cover
        from src import fuentes_datos  # type: ignore
        from src import calibracion as cal  # type: ignore
    try:
        datos = fuentes_datos.obtener_historico_largo()
        rep = cal.evaluar_calibracion(datos["resultados"])
    except Exception as exc:  # pragma: no cover
        rep = {}
        _ = exc
    enviado = enviar_mensaje(construir_mensaje_confianza(rep))
    return {"enviado": enviado, "alpha": (rep or {}).get("alpha_sugerido")}


# ---------------------------------------------------------------------------
# "Aprender de las derrotas": postmortem del backtest por Telegram
# ---------------------------------------------------------------------------
def construir_mensaje_derrotas(rep: Dict[str, Any]) -> str:
    """Mensaje (HTML, simple) del análisis de derrotas, para el comando /derrotas."""
    div = "━━━━━━━━━━"
    n = (rep or {}).get("total_derrotas", 0)
    if not rep or n == 0:
        return ("🔍 <b>APRENDER DE LAS DERROTAS</b>\n\n"
                "Aún no hay suficientes eliminaciones en el histórico para analizar. "
                "Vuelve a intentar cuando haya más temporadas.\n\n"
                f"{DISCLAIMER}")
    lineas = [
        "🔍 <b>APRENDER DE LAS DERROTAS</b>",
        "<i>Revisé los partidos donde el bot fue eliminado en el histórico</i>",
        div,
        f"💀 Cayó <b>{n}</b> veces. Dónde:",
    ]
    for d in rep.get("derrotas", [])[:8]:
        cond = "🏠" if d.get("condicion") == "Local" else "✈️"
        alerta = " ⚠️(ya había alerta)" if d.get("tenia_alerta") else ""
        sem = str(d.get("jornada", "")).split("-")[-1]  # "2024-W14" -> "W14"
        lineas.append(f"• {d.get('torneo')} {sem}: {cond} <b>{d.get('pick')}</b> "
                      f"vs {d.get('rival')} → {d.get('resultado')}{alerta}")
        # ¿Fue evitable de verdad o mala suerte?
        alt = d.get("mejor_alternativa")
        if d.get("evitable") and alt:
            lineas.append(f"   ↳ 🟡 Evitable: <b>{alt.get('equipo')}</b> estaba libre, más "
                          f"seguro ({alt.get('no_perder_pct')}%) y sobrevivió")
        elif alt:
            lineas.append(f"   ↳ 🎲 Mala suerte: elegiste el más seguro; {alt.get('equipo')} "
                          f"sobrevivió pero el modelo lo veía menos seguro ({alt.get('no_perder_pct')}%)")
    pat = rep.get("patrones", {})
    lineas += [
        div,
        "📊 <b>Patrón de las derrotas:</b>",
        f"🟡 Evitables (había opción más segura): <b>{pat.get('evitables')}/{n}</b>",
        f"🎲 Mala suerte (elegiste lo más seguro): <b>{pat.get('mala_suerte')}/{n}</b>",
        f"✈️ De visitante: <b>{pat.get('fueron_visitante_pct')}%</b>",
        f"⚠️ Ya traían alerta: <b>{pat.get('tenian_alerta_pct')}%</b>",
    ]
    if pat.get("no_perder_promedio_al_perder") is not None:
        lineas.append(f"🛡️ Perdió con ~<b>{pat.get('no_perder_promedio_al_perder')}%</b> "
                      "de no-perder promedio")
    lecciones = rep.get("lecciones", [])
    if lecciones:
        lineas += ["", "🎓 <b>Lecciones:</b>"]
        lineas += [f"• {le}" for le in lecciones]
    lineas += [div, DISCLAIMER]
    return "\n".join(lineas)


def enviar_derrotas() -> Dict[str, Any]:
    """
    Corre el postmortem de derrotas del backtest (historial largo) y lo envía en
    lenguaje simple. Tolerante: nunca rompe.
    """
    try:
        import fuentes_datos
        import backtest_estrategias as be
    except ImportError:  # pragma: no cover
        from src import fuentes_datos  # type: ignore
        from src import backtest_estrategias as be  # type: ignore
    try:
        datos = fuentes_datos.obtener_historico_largo()
        rep = be.analizar_derrotas(datos["resultados"])
    except Exception as exc:  # pragma: no cover
        rep = {}
        _ = exc
    enviado = enviar_mensaje(construir_mensaje_derrotas(rep))
    return {"enviado": enviado, "derrotas": (rep or {}).get("total_derrotas")}


# ---------------------------------------------------------------------------
# "Racha Survivor": track-record real del pick del bot jornada a jornada
# ---------------------------------------------------------------------------
def _marcador_a_favor(marcador: str, es_local: bool) -> str:
    """Orienta 'local-visitante' al lado del equipo elegido (equipo-rival)."""
    try:
        hg, ag = str(marcador or "").split("-")
        return f"{hg.strip()}-{ag.strip()}" if es_local else f"{ag.strip()}-{hg.strip()}"
    except Exception:
        return str(marcador or "")


def construir_mensaje_survivor_historial(resumen: Dict[str, Any]) -> str:
    """Mensaje (HTML, móvil) de la racha del pick de Survivor, para /racha."""
    div = "━━━━━━━━━━"
    resumen = resumen or {}
    jugadas = int(resumen.get("jugadas", 0) or 0)
    pendientes = int(resumen.get("pendientes", 0) or 0)
    detalle = resumen.get("detalle", []) or []
    if not jugadas and not pendientes:
        return ("🏆 <b>RACHA SURVIVOR</b>\n\n"
                "Aún no hay picks registrados. Cuando use /pick en una jornada guardo "
                "el pick recomendado; al resolverse los partidos verás aquí si ganó, "
                "empató (sobrevive) o cayó.\n\n"
                f"{DISCLAIMER}")

    victorias = int(resumen.get("victorias", 0) or 0)
    empates = int(resumen.get("empates", 0) or 0)
    sobrevividas = int(resumen.get("sobrevividas", 0) or 0)
    vivo = bool(resumen.get("sigue_vivo", True))

    pos_caida = None
    for i, d in enumerate(detalle, start=1):
        if d.get("estado") == "perdio":
            pos_caida = i
            break

    if jugadas == 0:
        estado_txt = "⏳ Sin jornadas resueltas todavía"
    elif not vivo:
        estado_txt = f"🔴 ELIMINADO en la jornada {pos_caida}"
    else:
        estado_txt = "🟢 VIVO"

    lineas = [
        "🏆 <b>RACHA SURVIVOR</b>",
        "<i>Track-record del pick recomendado por el bot</i>",
        div,
        f"Estado: <b>{estado_txt}</b>",
    ]
    if jugadas:
        lineas.append(f"🗓️ Jornadas resueltas: <b>{jugadas}</b>")
        lineas.append(f"🛡️ Sobrevividas: <b>{sobrevividas}/{jugadas}</b>")
        lineas.append(f"✅ Victorias: <b>{victorias}</b> · 🤝 Empates: <b>{empates}</b>")
        if vivo:
            lineas.append(f"🔥 Racha viva: <b>{resumen.get('racha', 0)}</b>")
    if pendientes:
        lineas.append(f"⏳ Por resolver: <b>{pendientes}</b>")

    if detalle:
        lineas += [div, "<b>Detalle por jornada:</b>"]
        icono = {"gano": "🟢", "empate": "🤝", "perdio": "🔴"}
        for i, d in enumerate(detalle, start=1):
            ic = icono.get(d.get("estado"), "▫️")
            es_local = str(d.get("condicion") or "").strip().lower() == "local"
            marc = _marcador_a_favor(d.get("marcador", ""), es_local)
            equipo = d.get("equipo", "")
            rival = d.get("rival", "")
            pieza = f"{ic} J{i}: <b>{equipo}</b>"
            if marc:
                pieza += f" {marc}"
            pieza += f" vs {rival}"
            lineas.append(pieza)

    lineas += [div,
               "ℹ️ Mide el pick del bot, no tus picks manuales de /usado.",
               DISCLAIMER]
    return "\n".join(lineas)


# ---------------------------------------------------------------------------
# "Survivor perfecto" (oráculo) vs el bot, por Telegram
# ---------------------------------------------------------------------------
def construir_mensaje_ganadores(rep: Dict[str, Any]) -> str:
    """Mensaje (HTML, simple) del Survivor perfecto vs el bot, para /ganadores."""
    div = "━━━━━━━━━━"
    n = (rep or {}).get("torneos", 0)
    if not rep or n == 0:
        return ("🏆 <b>EL SURVIVOR PERFECTO</b>\n\n"
                "Aún no hay torneos completos para comparar. Vuelve a intentar "
                "cuando haya más historial.\n\n"
                f"{DISCLAIMER}")
    lineas = [
        "🏆 <b>EL SURVIVOR PERFECTO vs EL BOT</b>",
        "<i>Con los resultados ya sabidos, ¿existía una jugada que ganara todo?</i>",
        div,
    ]
    for c in rep.get("comparacion", [])[:10]:
        perfecto = "✅ sí" if c.get("oracle_completo") else f"máx {c.get('oracle_max_supervivencia')}"
        # Cayó en la jornada (sobrevividas + 1): si sobrevivió 0, cayó en la J1.
        cayo_en = int(c.get("bot_sobrevividas") or 0) + 1
        bot = "ganó TODO" if c.get("bot_completo") else f"cayó en la J{cayo_en}"
        lineas.append(f"• <b>{c.get('torneo')}</b>: perfecto={perfecto} · bot={bot} "
                      f"(sobrevivió {c.get('bot_sobrevividas')})")
    lineas += [
        div,
        "📊 <b>Resumen:</b>",
        f"🔮 Existía camino ganador en <b>{rep.get('con_camino_perfecto')}/{n}</b> torneos",
        f"🤖 El bot completó <b>{rep.get('bot_completos')}/{n}</b>",
        f"📈 Aguante promedio: bot <b>{rep.get('bot_jornadas_prom')}</b> vs "
        f"perfecto <b>{rep.get('oracle_jornadas_prom')}</b> jornadas",
    ]
    lecciones = rep.get("lecciones", [])
    if lecciones:
        lineas += ["", "🎓 <b>Conclusiones:</b>"]
        lineas += [f"• {le}" for le in lecciones]
    lineas += [div, DISCLAIMER]
    return "\n".join(lineas)


def enviar_ganadores() -> Dict[str, Any]:
    """
    Compara el 'Survivor perfecto' (oráculo, con resultados ya sabidos) contra la
    corrida real del bot, y lo envía en lenguaje simple. Tolerante: nunca rompe.
    """
    try:
        import fuentes_datos
        import backtest_estrategias as be
    except ImportError:  # pragma: no cover
        from src import fuentes_datos  # type: ignore
        from src import backtest_estrategias as be  # type: ignore
    try:
        datos = fuentes_datos.obtener_historico_largo()
        rep = be.analizar_ganadores(datos["resultados"])
    except Exception as exc:  # pragma: no cover
        rep = {}
        _ = exc
    enviado = enviar_mensaje(construir_mensaje_ganadores(rep))
    return {"enviado": enviado, "torneos": (rep or {}).get("torneos")}


# ---------------------------------------------------------------------------
# Resumen de rentabilidad (track-record) por Telegram
# ---------------------------------------------------------------------------
def construir_mensaje_rentabilidad(data: Dict[str, Any]) -> str:
    """Mensaje (HTML) con el track-record de pronósticos (aciertos 1X2 y marcador)."""
    resueltos = int(data.get("resueltos") or 0)
    pend = int(data.get("pendientes") or 0)
    if resueltos == 0:
        return ("📊 <b>RESUMEN DE PRONÓSTICOS</b>\n\n"
                f"Aún no hay pronósticos resueltos (pendientes: {pend}). "
                "Se llenará cuando se jueguen las jornadas.\n\n"
                f"{DISCLAIMER}")
    a1 = data.get("aciertos_1x2") or 0
    p1 = data.get("acierto_1x2_pct")
    am = data.get("aciertos_marcador_exacto") or 0
    pm = data.get("acierto_marcador_pct")
    lineas = [
        "📊 <b>RESUMEN DE PRONÓSTICOS</b> (track-record)",
        f"<i>Resueltos: {resueltos} · Pendientes: {pend}</i>",
        "",
        f"🎯 Aciertos 1X2: <b>{a1}/{resueltos}</b>" + (f" ({p1}%)" if p1 is not None else ""),
        f"🎯 Marcador exacto: <b>{am}/{resueltos}</b>" + (f" ({pm}%)" if pm is not None else ""),
        "",
        DISCLAIMER,
    ]
    return "\n".join(lineas)


def enviar_resumen_rentabilidad() -> Dict[str, Any]:
    """Envía por Telegram el resumen de aciertos del modelo. Tolerante (BD)."""
    try:
        try:
            from database import rentabilidad_pronosticos
        except ImportError:  # pragma: no cover
            from src.database import rentabilidad_pronosticos  # type: ignore
        data = rentabilidad_pronosticos()
    except Exception as exc:  # pragma: no cover - BD no disponible
        return {"enviado": False, "error": str(exc)}
    enviado = enviar_mensaje(construir_mensaje_rentabilidad(data))
    return {"enviado": enviado, "resueltos": data.get("resueltos"), "pendientes": data.get("pendientes")}


# ---------------------------------------------------------------------------
# Momios: actualizar (bajar de odds-api.io + guardar) y reportar cobertura
# ---------------------------------------------------------------------------
def construir_mensaje_momios(momios: Dict[str, Any], fuente: Optional[str]) -> str:
    """Mensaje (HTML) con el estado/cobertura de los momios por mercado."""
    if not momios:
        return ("💰 <b>MOMIOS</b>\n\n"
                "Todavía no hay líneas publicadas para estos partidos (ni odds-api.io "
                "ni ESPN, ni guardadas). El pick usa solo el modelo por ahora; "
                "vuelve a intentar más cerca de la jornada.\n\n"
                f"{DISCLAIMER}")
    n_ml = sum(1 for m in momios.values() if isinstance(m, dict) and m.get("ml"))
    n_tot = sum(1 for m in momios.values() if isinstance(m, dict) and m.get("totals"))
    n_hdp = sum(1 for m in momios.values() if isinstance(m, dict) and m.get("handicap"))
    lineas = [
        "💰 <b>MOMIOS ACTUALIZADOS</b>",
        f"<i>Fuente: {fuente or '—'} · {len(momios)} partidos</i>",
        "",
        f"🧮 1X2 (mueve el Survivor): <b>{n_ml}</b>",
        f"⚽ Over/Under 2.5: <b>{n_tot}</b>",
        f"⚖️ Hándicap: <b>{n_hdp}</b>",
        "",
        "<i>El pick y el plan ya los mezclan con el modelo.</i>",
        DISCLAIMER,
    ]
    return "\n".join(lineas)


def enviar_momios_estado(solo_si_hay: bool = False) -> Dict[str, Any]:
    """
    Baja momios en vivo (odds-api.io/Pinnacle/ESPN), los guarda como caché si hay,
    y envía por Telegram un resumen de cobertura. Tolerante: nunca rompe.

    `solo_si_hay`: si True (para el cron), NO envía mensaje cuando no hay líneas
    todavía (solo refresca la caché en silencio). Así el cron no spamea en
    pretemporada; solo te avisa cuando por fin aparecen momios.
    """
    try:
        try:
            import comparador_mercado as cm
        except ImportError:  # pragma: no cover
            from src import comparador_mercado as cm  # type: ignore
        momios, fuente = cm.momios_para_uso(guardar_si_hay=True, incluir_gratis=True)
    except Exception as exc:  # pragma: no cover - nunca tumbar el envío
        return {"enviado": False, "error": str(exc)}
    if solo_si_hay and not momios:
        return {"enviado": False, "silencioso": True, "partidos_con_momios": 0}
    enviado = enviar_mensaje(construir_mensaje_momios(momios, fuente))
    return {"enviado": enviado, "partidos_con_momios": len(momios), "fuente": fuente}


# ---------------------------------------------------------------------------
# Recordatorio automático antes de la jornada
# ---------------------------------------------------------------------------
def _cargar_calendario_local() -> List[Dict[str, Any]]:
    """Lee data/calendario.json (lista de jornadas). [] si no existe/falla."""
    try:
        if _CALENDARIO_PATH.exists():
            with open(_CALENDARIO_PATH, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
    except Exception:  # pragma: no cover
        pass
    return []


def _fecha(valor: Any) -> Optional[date]:
    try:
        return datetime.strptime(str(valor)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def proxima_jornada(hoy: Optional[date] = None) -> Optional[Dict[str, Any]]:
    """Jornada cuya fecha_inicio es la más próxima a partir de hoy (o None)."""
    hoy = hoy or datetime.now(timezone.utc).date()
    candidatas = []
    for j in _cargar_calendario_local():
        ini = _fecha(j.get("fecha_inicio"))
        if ini is not None and ini >= hoy:
            candidatas.append((ini, j))
    if not candidatas:
        return None
    candidatas.sort(key=lambda t: t[0])
    return candidatas[0][1]


def construir_recordatorio(jornada: Dict[str, Any], dias: int) -> str:
    """Mensaje (HTML) de recordatorio de que se acerca una jornada."""
    n = jornada.get("jornada", "?")
    ini = jornada.get("fecha_inicio", "")
    cuando = "hoy" if dias == 0 else ("mañana" if dias == 1 else f"en {dias} días")
    lineas = [
        f"⏰ <b>SE ACERCA LA JORNADA {n}</b>",
        f"<i>Arranca {cuando} ({ini}).</i>",
        "",
        "Mándame <b>/picks</b> ~1 hora antes de los partidos y te doy el pick de "
        "Survivor + los pronósticos de la jornada con datos frescos.",
    ]
    partidos = jornada.get("partidos") or []
    if partidos:
        lineas.append("")
        lineas.append("📋 Partidos:")
        for p in partidos[:_MAX_PARTIDOS]:
            h = p.get("home_team", "")
            a = p.get("away_team", "")
            if h and a:
                lineas.append(f"  • {h} vs {a}")
    lineas += ["", DISCLAIMER]
    return "\n".join(lineas)


def enviar_recordatorio_si_aplica(dias_antes: int = 1,
                                  hoy: Optional[date] = None) -> Dict[str, Any]:
    """
    Envía un recordatorio SOLO si la próxima jornada arranca dentro de `dias_antes`
    días (0..dias_antes). Pensado para un cron diario: no spamea porque solo
    dispara al acercarse el inicio. Devuelve si envió y a cuántos días.
    """
    hoy = hoy or datetime.now(timezone.utc).date()
    j = proxima_jornada(hoy)
    if not j:
        return {"enviado": False, "motivo": "sin próxima jornada"}
    ini = _fecha(j.get("fecha_inicio"))
    if ini is None:
        return {"enviado": False, "motivo": "fecha inválida"}
    dias = (ini - hoy).days
    if not (0 <= dias <= dias_antes):
        return {"enviado": False, "motivo": f"faltan {dias} días", "jornada": j.get("jornada")}
    enviado = enviar_mensaje(construir_recordatorio(j, dias))
    return {"enviado": enviado, "jornada": j.get("jornada"), "dias": dias}


if __name__ == "__main__":
    res = enviar_pronosticos()
    print(f"Enviado: {res['enviado']} | pronósticos: {res['total_pronosticos']} | fuente: {res['fuente']}")
