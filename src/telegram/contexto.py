from __future__ import annotations
from typing import Any, Dict, List, Optional
from src.team_normalizer import clean_team_name
from .utils import _pct

def _norm_simple(s: str) -> str:
    return " ".join(str(s or "").lower().split())

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
    if not (
        pred
        or forma_l
        or forma_v
        or riesgo_l
        or riesgo_v
        or h2h
        or noticias
        or ali_ok
        or js_ok
        or fichajes_ok
        or impacto_ok
        or probable_ok
    ):
        return []  # pretemporada: sin datos aún, no ensuciar el mensaje

    lineas.append(f"🔎 <b>Contexto (Liga MX API)</b> — {ctx.get('home')} vs {ctx.get('away')}:")
    if ali_ok:
        forms = " · ".join(
            f"{e.get('equipo', '')} {e.get('formacion') or ''}".strip()
            for e in (ali or {}).get("equipos", [])
            if e.get("equipo")
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
            for e in (probable or [])
            if isinstance(e, dict) and e.get("equipo")
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

def _jugadores_seguir_partido(p: Dict[str, Any], goleadores_map: Dict[str, List[Dict[str, Any]]]) -> str:
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

def _porteros_partido(p: Dict[str, Any], porteros_map: Dict[str, Dict[str, Any]]) -> str:
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
        nom = str(gk["nombre"])
        try:
            v_val = int(gk.get("vallas_invictas") or 0)
            return f"{nom} ({v_val} {'valla invicta' if v_val == 1 else 'vallas invictas'})"
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

def _contexto_top_pick(
    pronosticos: List[Dict[str, Any]],
    equipos_usados: Optional[List[str]],
    motivacion: Optional[Dict[str, Dict[str, Any]]],
    pick_override: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Dossier compacto (Liga MX API) del pick #1. Tolerante: None si algo falla.
    Si se pasa `pick_override` (dict con equipo/rival/condicion), el dossier se arma
    para ESE pick, de modo que el contexto coincida con el pick del plan que se muestra.
    """
    try:
        from src import ligamx_api as lmx
        from src import motor_pronosticos as motor

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
            from src import analista_ia as ia

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
                    from src import fichajes as fich

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
        return dossier if isinstance(dossier, dict) else None
    except Exception:  # pragma: no cover - nunca debe tumbar el envío
        return None

def _ajustar_pick_top(
    picks: List[Dict[str, Any]], pronosticos: List[Dict[str, Any]], contexto_pick: Optional[Dict[str, Any]]
) -> None:
    """
    Aplica el ajuste MODERADO (XI + H2H) al pick #1 y refleja el resultado en sus
    números (no-perder, gana, nivel) y en `razon`. Muta `picks[0]` in situ.
    """
    if not picks or not contexto_pick:
        return
    try:
        from src import ajuste_pronostico as aj
        from src.team_normalizer import canonical_team_key as _k

        rec = picks[0]
        es_local = rec.get("condicion") == "Local"
        local = rec["equipo"] if es_local else rec["rival"]
        visita = rec["rival"] if es_local else rec["equipo"]
        pron = next(
            (p for p in pronosticos if _k(p.get("local", "")) == _k(local) and _k(p.get("visitante", "")) == _k(visita)),
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
    except Exception:
        pass
