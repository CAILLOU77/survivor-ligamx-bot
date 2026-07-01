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
    fuente = resultado.get("fuente_datos", "?")
    fecha = resultado.get("generado_utc", "")

    lineas = [
        "🔮 <b>PRONÓSTICOS LIGA MX</b> (modelo · datos ESPN)",
        f"<i>Fuente: {fuente} · {fecha}</i>",
        "",
    ]

    if tops is None:
        tops = motor.mejores_picks_survivor(pronosticos, equipos_usados, motivacion, n=3)
    if tops:
        lineas.append("🎯 <b>SURVIVOR — top 3:</b>")
        if advertencia:
            lineas.append(f"<i>{advertencia}</i>")
        medallas = ["🥇", "🥈", "🥉"]
        for i, pk in enumerate(tops):
            extra = f" · rival mot.: {pk['rival_motivacion']}" if pk.get("rival_motivacion") else ""
            gana = pk.get("prob_victoria_pct")
            g = f"gana {gana}% · " if gana is not None else ""
            nivel = pk.get("nivel")
            nv = f" [{nivel}]" if nivel else ""
            estrella = " ⭐ RECOMENDADO" if i == 0 else ""
            lineas.append(
                f"{medallas[i] if i < 3 else '•'} {pk['equipo']} "
                f"({pk['condicion']} vs {pk['rival']}) — {g}no-perder {pk['no_perder_pct']}%{nv}{extra}{estrella}"
            )
        # Recomendación explícita = el #1 (mayor confianza de no-perder + ganar).
        rec = tops[0]
        lineas.append(
            f"➡️ <b>Pick sugerido: {rec['equipo']}</b> "
            f"(confianza {rec.get('nivel', '—')})"
        )
        if rec.get("razon"):
            lineas.append(f"    <i>{rec['razon']}</i>")
        contexto_lineas = _formatear_contexto(contexto_pick)
        if contexto_lineas:
            lineas.append("")
            lineas.extend(contexto_lineas)
        lineas.append("")

    if pronosticos:
        lineas.append("<b>Partidos:</b>")
        for p in pronosticos[:_MAX_PARTIDOS]:
            lineas.append(
                f"⚽ {p['local']} vs {p['visitante']} → <b>{p['pick_1x2']}</b> "
                f"(L{p['prob_local_pct']}/E{p['prob_empate_pct']}/V{p['prob_visitante_pct']})"
            )
            lineas.append(
                f"    {p['pick_ou']} 2.5 · BTTS {p['pick_btts']} · marcador {p['marcador_mas_probable']}"
            )
            resumen = _resumen_mercado(p.get("mercado"))
            if resumen:
                lineas.append(f"    💰 Mercado: {resumen}")
    else:
        lineas.append("Sin pronósticos disponibles (faltan datos de ESPN o fixtures).")

    lineas += ["", DISCLAIMER]
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
        return lmx.resumen_partido(home, away)
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
