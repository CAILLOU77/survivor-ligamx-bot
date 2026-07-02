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

import os
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

DISCLAIMER = "ℹ️ Informativo / revisión humana. No es consejo de apuesta."
_MAX_PARTIDOS = 9


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
    if not (pred or forma_l or forma_v or riesgo_l or riesgo_v or h2h or noticias or ali_ok):
        return []  # pretemporada: sin datos aún, no ensuciar el mensaje

    lineas.append(f"🔎 <b>Contexto (Liga MX API)</b> — {ctx.get('home')} vs {ctx.get('away')}:")
    if ali_ok:
        forms = " · ".join(
            f"{e.get('equipo', '')} {e.get('formacion') or ''}".strip()
            for e in ali.get("equipos", []) if e.get("equipo")
        )
        lineas.append(f"    📋 XI CONFIRMADO — {forms} ⚠️ revisa si tu favorito rotó (suplentes)")
    if pred:
        lineas.append(
            f"    2ª opinión API: L{pred['prob_local_pct']}/E{pred['prob_empate_pct']}/"
            f"V{pred['prob_visita_pct']} · goles {pred['goles_esp']}"
        )
    if forma_l or forma_v:
        lineas.append(f"    Forma: {ctx.get('home')} {forma_l or '—'} · {ctx.get('away')} {forma_v or '—'}")
    if riesgo_l:
        lineas.append(f"    ⚠️ En riesgo ({ctx.get('home')}): {', '.join(riesgo_l)}")
    if riesgo_v:
        lineas.append(f"    ⚠️ En riesgo ({ctx.get('away')}): {', '.join(riesgo_v)}")
    if noticias:
        lineas.append("    📰 Noticias:")
        for n in noticias[:3]:
            titulo = n.get("titulo", "") if isinstance(n, dict) else str(n)
            if titulo:
                lineas.append(f"      • {titulo}")
    ia = ctx.get("analisis_ia") if isinstance(ctx.get("analisis_ia"), dict) else None
    if ia and ia.get("disponible") and ia.get("riesgos"):
        lineas.append("    🤖 IA — señales de riesgo (de las noticias):")
        for r in ia["riesgos"][:4]:
            eq = r.get("equipo", "")
            tipo = r.get("tipo", "")
            resumen = r.get("resumen", "")
            if resumen:
                lineas.append(f"      ⚠️ {eq} [{tipo}]: {resumen}")
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
            f"     💰 Momios: {local} {m['local']} · Empate {m['empate']} · {visita} {m['visita']}"
        )
    ou = mercado.get("over_under") or {}
    mou = ou.get("momios") or {}
    if mou.get("over") and mou.get("under"):
        linea = ou.get("linea", 2.5)
        out.append(f"        O/U {linea}: Over {mou['over']} · Under {mou['under']}")
    resumen = _resumen_mercado(mercado)
    if resumen:
        out.append(f"     📈 Mercado ve: {resumen}")
    return out


def _pick_club(p: Dict[str, Any]) -> str:
    """Traduce el pick 1X2 al nombre real del club (o 'Empate')."""
    pick = p.get("pick_1x2", "")
    if pick == "Gana Local":
        return p.get("local", pick)
    if pick == "Gana Visitante":
        return p.get("visitante", pick)
    return pick  # "Empate"


def construir_mensaje(
    resultado: Dict[str, Any],
    equipos_usados: Optional[List[str]] = None,
    motivacion: Optional[Dict[str, Dict[str, Any]]] = None,
    contexto_pick: Optional[Dict[str, Any]] = None,
    tops: Optional[List[Dict[str, Any]]] = None,
    advertencia: Optional[str] = None,
) -> str:
    """Arma el mensaje (HTML) de pronósticos a partir de la salida del motor.

    `contexto_pick`: dossier compacto de la Liga MX API para el pick #1.
    `tops`: picks ya calculados (p. ej. estratégicos con cautela); si es None se
    calculan con `mejores_picks_survivor` (comportamiento por defecto).
    `advertencia`: nota de cautela (p. ej. arranque de torneo) a mostrar.
    """
    pronosticos = resultado.get("pronosticos", [])
    fecha = str(resultado.get("generado_utc", "")).replace("T", " ").replace("Z", " UTC")

    div = "━━━━━━━━━━━━━━━━━━"
    lineas = [
        "🔮 <b>PRONÓSTICOS LIGA MX</b>",
        f"<i>Modelo ESPN + Poisson · {fecha}</i>",
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
        gtxt = f" · gana {gana}%" if gana is not None else ""
        if rec.get("condicion") == "Local":
            local_eq, visita_eq = rec["equipo"], rec["rival"]
        else:
            local_eq, visita_eq = rec["rival"], rec["equipo"]
        lineas.append(f"⚽ <b>{local_eq}</b> (🏠 local) vs <b>{visita_eq}</b> (✈️ visita)")
        lineas.append(f"🥇 <b>PICK: {rec['equipo']}</b> — juega de {rec['condicion'].lower()}")
        lineas.append(f"     ✅ no-perder <b>{rec['no_perder_pct']}%</b>{gtxt} · confianza <b>{rec.get('nivel', '—')}</b>")
        if motivacion:
            mot_rival = motivacion.get(str(rec.get("rival", "")).lower(), {})
            nivel_mot = mot_rival.get("motivacion_nivel")
            if nivel_mot:
                lineas.append(f"     📉 rival mot.: {nivel_mot}")
        if rec.get("razon"):
            lineas.append(f"     💬 <i>Por qué: {rec['razon']}</i>")
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
                    f"— no-perder {pk['no_perder_pct']}%{nivel}"
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
        lineas.append("<i>Afecta disponibilidad/desgaste de jugadores:</i>")
        for c in cal_lineas:
            lineas.append(f"  {c}")

    if pronosticos:
        lineas.append(div)
        lineas.append("📋 <b>PARTIDOS DE LA JORNADA</b>")
        nums = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
        for idx, p in enumerate(pronosticos[:_MAX_PARTIDOS]):
            lineas.append("")
            n = nums[idx] if idx < len(nums) else "•"
            conf = f" · confianza <b>{p['nivel_confianza']}</b>" if p.get("nivel_confianza") else ""
            prob_pick = p.get("prob_pick_pct")
            pptxt = f" ({prob_pick}%)" if prob_pick is not None else ""
            lineas.append(f"{n} 🏠 <b>{p['local']} vs {p['visitante']}</b> ✈️")
            lineas.append(f"     🎯 Pick: <b>{_pick_club(p)}</b>{pptxt}{conf}")
            lineas.append(f"     📊 Local {p['prob_local_pct']}% · Empate {p['prob_empate_pct']}% · Visita {p['prob_visitante_pct']}%")
            lineas.append(f"     ⚽ Goles: {p['pick_ou']} 2.5 · BTTS {p['pick_btts']} · marcador {p['marcador_mas_probable']}")
            if p.get("explicacion_1x2"):
                lineas.append(f"     💡 {p['explicacion_1x2']}")
            if p.get("explicacion_ou"):
                lineas.append(f"     💡 {p['explicacion_ou']}")
            if p.get("precaucion") and p.get("motivos_alerta"):
                lineas.append(f"     {p['nivel_alerta']}: {' '.join(p['motivos_alerta'])}")
            lineas.extend(_lineas_mercado(p))
            try:
                cal_ev = calctx.eventos_para_fecha(p.get("fecha"), [p.get("local", ""), p.get("visitante", "")])
            except Exception:  # pragma: no cover
                cal_ev = []
            if cal_ev:
                nombres = " · ".join(f"{e.get('emoji', '🗓️')} {e.get('nombre')}" for e in cal_ev)
                lineas.append(f"     🗓️ Calendario: {nombres}")
    else:
        lineas.append(div)
        lineas.append("Sin pronósticos disponibles (faltan datos de ESPN o fixtures).")

    lineas += [div, DISCLAIMER]
    return "\n".join(lineas)


def enviar_mensaje(mensaje: str) -> bool:
    """Envía un mensaje a Telegram. Devuelve True si se envió (200)."""
    if requests is None:
        print("⚠️ 'requests' no instalado; no se envía.")
        return False
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("⚠️ Telegram no configurado (faltan TELEGRAM_BOT_TOKEN/CHAT_ID).")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(
            url, data={"chat_id": chat_id, "text": mensaje, "parse_mode": "HTML"}, timeout=20
        )
        return resp.status_code == 200
    except Exception as exc:  # pragma: no cover
        print(f"Error enviando Telegram: {exc}")
        return False


def _contexto_top_pick(pronosticos: List[Dict[str, Any]],
                       equipos_usados: Optional[List[str]],
                       motivacion: Optional[Dict[str, Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """Dossier compacto (Liga MX API) del pick #1. Tolerante: None si algo falla."""
    try:
        try:
            import ligamx_api as lmx
        except ImportError:  # pragma: no cover
            from src import ligamx_api as lmx  # type: ignore
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
                p.get("prob_visitante_pct", 0), p.get("marcador_mas_probable", ""),
                fecha=p.get("fecha", ""),
            )
        except Exception:  # pragma: no cover - nunca tumbar el envío por el log
            continue


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

    # Momios/valor (gated por key; sin key no toca nada).
    con_momios = 0
    try:
        try:
            import comparador_mercado as cm
        except ImportError:  # pragma: no cover
            from src import comparador_mercado as cm  # type: ignore
        comp = cm.comparar_pronosticos(pronosticos)
        resultado["pronosticos"] = comp.get("pronosticos", pronosticos)
        con_momios = comp.get("partidos_con_momios", 0)
    except Exception:  # pragma: no cover - nunca debe tumbar el envío
        pass

    # Motivación de la tabla (contexto/desempate Survivor).
    try:
        motivacion = motor.motivacion_por_equipo()
    except Exception:  # pragma: no cover
        motivacion = {}

    contexto_pick = None
    if incluir_contexto:
        contexto_pick = _contexto_top_pick(resultado.get("pronosticos", []),
                                           equipos_usados, motivacion)

    # Pick ESTRATÉGICO (cautela de arranque + anti-sorpresa visitante).
    est = motor.mejores_picks_estrategico(
        resultado.get("pronosticos", []), equipos_usados, motivacion,
        partidos_jugados_torneo=_partidos_jugados_torneo(), n=3,
    )
    mensaje = construir_mensaje(resultado, equipos_usados, motivacion, contexto_pick,
                                tops=est.get("picks"), advertencia=est.get("advertencia"))
    enviado = enviar_mensaje(mensaje)
    return {
        "enviado": enviado,
        "total_pronosticos": resultado.get("total_pronosticos", 0),
        "partidos_con_momios": con_momios,
        "fuente": resultado.get("fuente_datos"),
        "cautela": est.get("cautela"),
    }


def construir_mensaje_plan(plan: Dict[str, Any]) -> str:
    """Mensaje (HTML) con el plan de temporada del Survivor."""
    if plan.get("calendario_incompleto") or not plan.get("plan"):
        return ("📅 <b>PLAN SURVIVOR</b>\n\n"
                "Aún no hay calendario completo (data/calendario.json). "
                "Córrelo de nuevo cuando se publique el calendario del torneo.\n\n"
                f"{DISCLAIMER}")
    lineas = [
        "📅 <b>PLAN SURVIVOR — temporada</b> (modelo · datos ESPN)",
        f"<i>Sobrevivir toda la temporada: {plan.get('prob_supervivencia_total_pct')}% · "
        f"victorias esperadas: {plan.get('victorias_esperadas')}</i>",
        "",
    ]
    for p in plan["plan"]:
        lineas.append(
            f"J{p['jornada']}: <b>{p['equipo']}</b> ({p['condicion']} vs {p['rival']}) "
            f"— gana {p['prob_ganar_pct']}% / no-perder {p['no_perder_pct']}% [{p['nivel']}]"
        )
    riesgosas = plan.get("jornadas_riesgosas") or []
    if riesgosas:
        lineas.append("")
        lineas.append(f"⚠️ Jornadas riesgosas: {', '.join('J'+str(j) for j in riesgosas)}")
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


if __name__ == "__main__":
    res = enviar_pronosticos()
    print(f"Enviado: {res['enviado']} | pronósticos: {res['total_pronosticos']} | fuente: {res['fuente']}")
