from __future__ import annotations
from typing import Any, Dict, List, Optional

from src import motor_pronosticos as motor
from .contexto import _formatear_contexto
from .utils import _pct, _fecha_mx

DISCLAIMER = "ℹ️ Informativo / revisión humana. No es consejo de apuesta."

def _pick_club(p: Dict[str, Any]) -> str:
    """Traduce el pick 1X2 al nombre real del club (o 'Empate')."""
    pick = str(p.get("pick_1x2", ""))
    if pick == "Gana Local":
        return str(p.get("local", pick))
    if pick == "Gana Visitante":
        return str(p.get("visitante", pick))
    return pick  # "Empate"

def _iso_week(fecha: str) -> str:
    """Etiqueta de jornada = semana ISO de la fecha (YYYY-Www). '' si no se puede."""
    try:
        from datetime import date

        y, m, d = str(fecha)[:10].split("-")
        yr, wk, _ = date(int(y), int(m), int(d)).isocalendar()
        return f"{yr}-W{wk:02d}"
    except Exception:
        return ""

def construir_mensaje_rentabilidad(data: Dict[str, Any]) -> str:
    """Mensaje (HTML) con el track-record de pronósticos (aciertos 1X2 y marcador)."""
    resueltos = int(data.get("resueltos") or 0)
    pend = int(data.get("pendientes") or 0)
    if resueltos == 0:
        return (
            "📊 <b>RESUMEN DE PRONÓSTICOS</b>\n\n"
            f"Aún no hay pronósticos resueltos (pendientes: {pend}). "
            "Se llenará cuando se jueguen las jornadas.\n\n"
            f"{DISCLAIMER}"
        )
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

def render_survivor(
    pronosticos: List[Dict[str, Any]],
    equipos_usados: Optional[List[str]],
    motivacion: Optional[Dict[str, Dict[str, Any]]],
    tops: Optional[List[Dict[str, Any]]],
    advertencia: Optional[str],
    contexto_pick: Optional[Dict[str, Any]],
) -> List[str]:
    """Genera las líneas HTML para la sección Survivor."""
    lineas = []
    if tops is None:
        tops = motor.mejores_picks_survivor(pronosticos, equipos_usados, motivacion, n=3)
    if tops:
        lineas.append("🎯 <b>SURVIVOR</b>")
        if advertencia:
            lineas.append(f"<i>{advertencia}</i>")
        lineas.append("")
        rec = tops[0]
        gana = rec.get("prob_victoria_pct")
        if rec.get("condicion") == "Local":
            local_eq, visita_eq = rec["equipo"], rec["rival"]
        else:
            local_eq, visita_eq = rec["rival"], rec["equipo"]
        lineas.append(f"🏠 <b>{local_eq}</b> vs <b>{visita_eq}</b> ✈️")
        lineas.append(f"🥇 <b>PICK: {rec['equipo']}</b> (de {rec['condicion'].lower()})")
        noperder = rec.get("no_perder_pct")
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
        if rec.get("crowd_risk") == "ALTO":
            lineas.append(
                f"🚨 <b>RIESGO MANADA ALTO:</b> {rec.get('crowd_pct', 0)}% del publico lo picka. Sorpresa = eliminados masivos."
            )
        if rec.get("ajuste_nota"):
            lineas.append(f"🔧 <i>Ajustado por: {rec['ajuste_nota']}</i>")
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
    return lineas

def construir_mensaje_plan(plan: Dict[str, Any]) -> str:
    """Mensaje (HTML) con el plan de temporada del Survivor."""
    if plan.get("calendario_incompleto") or not plan.get("plan"):
        return (
            "📅 <b>PLAN SURVIVOR</b>\n\n"
            "Aún no hay calendario completo (data/calendario.json). "
            "Córrelo de nuevo cuando se publique el calendario del torneo.\n\n"
            f"{DISCLAIMER}"
        )
    lineas = [
        "📅 <b>PLAN SURVIVOR — temporada</b> (modelo · datos ESPN)",
        f"<i>🛡️ Sobrevivir las 17 jornadas: {_pct(plan.get('prob_supervivencia_total_pct'))}% · "
        f"🏆 victorias esperadas: {plan.get('victorias_esperadas')}</i>",
        "<i>Idea: gastar equipos flojos en su mejor partido y guardar a los fuertes "
        "para las jornadas difíciles. Ganar es lo que vale (desempate).</i>",
        "",
    ]
    for p in plan["plan"]:
        lineas.append(f"<b>J{p['jornada']} · {p['equipo']}</b> ({p['condicion']} vs {p['rival']})")
        lineas.append(f"🏆 gana {_pct(p['prob_ganar_pct'])}% · 🛡️ sobrevive {_pct(p['no_perder_pct'])}% [{p['nivel']}]")
    riesgosas = plan.get("jornadas_riesgosas") or []
    if riesgosas:
        lineas.append("")
        lineas.append(f"⚠️ Jornadas riesgosas: {', '.join('J' + str(j) for j in riesgosas)}")
    no_usados = plan.get("equipos_no_usados") or []
    if no_usados:
        lineas.append("")
        if len(no_usados) == 1:
            lineas.append(f"🚫 Equipo que NO usarás (sacrificado): <b>{no_usados[0]}</b> — no tiene una jornada suficientemente buena.")
        else:
            lineas.append(f"🚫 Equipos que NO usarás (sacrificados): <b>{', '.join(no_usados)}</b> — sin jornada lo bastante buena.")
    lineas += ["", DISCLAIMER]
    return "\n".join(lineas)

def construir_mensaje_prueba(comp: Dict[str, Any]) -> str:
    """Mensaje (HTML, simple) del backtest de estrategias, para el comando /prueba."""
    div = "━━━━━━━━━━"
    por = (comp or {}).get("por_estrategia", {})
    real = por.get("real", {})
    ingenua = por.get("ingenua", {})

    if not real or real.get("torneos_evaluados", 0) == 0:
        return f"🧪 <b>PRUEBA DE LA ESTRATEGIA</b>\n\nTodavía no hay suficiente historial.\n\n{DISCLAIMER}"

    n = real.get("torneos_evaluados")
    lineas = [
        "🧪 <b>PRUEBA DE LA ESTRATEGIA</b>",
        f"<i>Jugué el Survivor en {n} torneos completos con datos reales</i>",
        div,
        "🤖 <b>La estrategia del bot</b>:",
        f"✅ Sobrevivió completo: <b>{real.get('torneos_sobrevividos_completos')}/{n}</b> ({real.get('tasa_supervivencia_torneo_pct')}%)",
        f"📊 Aguantó en promedio: <b>{real.get('jornadas_sobrevividas_prom')}</b> jornadas",
        f"🏆 Victorias por torneo: <b>{real.get('victorias_prom_por_torneo')}</b>",
    ]
    if ingenua and ingenua.get("torneos_evaluados"):
        lineas += ["", f"🎲 <b>Elegir a lo simple</b>: Sobrevivió <b>{ingenua.get('torneos_sobrevividos_completos')}/{ingenua.get('torneos_evaluados')}</b>"]
    lineas += [div, DISCLAIMER]
    return "\n".join(lineas)

def construir_mensaje_confianza(rep: Dict[str, Any]) -> str:
    """Mensaje del reporte de calibración, para el comando /confianza."""
    div = "━━━━━━━━━━"
    if not rep or rep.get("n_muestras", 0) < 20:
        return f"📐 <b>¿LA CONFIANZA DEL BOT ES HONESTA?</b>\n\nAún no hay suficientes datos.\n\n{DISCLAIMER}"
    alpha = rep.get("alpha_sugerido", 0.0)
    diag = "🟢 Bien calibrado" if alpha <= 0.0 else "🟡 Un poco OPTIMISTA"
    lineas = [
        "📐 <b>¿LA CONFIANZA DEL BOT ES HONESTA?</b>",
        f"<i>Revisé {rep.get('n_muestras')} pronósticos pasados</i>",
        div, diag,
        f"🔧 Ajuste sugerido: <b>{int(round(alpha * 100))}%</b> menos de confianza",
        "", DISCLAIMER
    ]
    return "\n".join(lineas)

def construir_mensaje_derrotas(rep: Dict[str, Any]) -> str:
    """Mensaje del análisis de derrotas, para el comando /derrotas."""
    div = "━━━━━━━━━━"
    n = (rep or {}).get("total_derrotas", 0)
    if not rep or n == 0:
        return f"🔍 <b>APRENDER DE LAS DERROTAS</b>\n\nAún no hay eliminaciones.\n\n{DISCLAIMER}"
    lineas = [
        "🔍 <b>APRENDER DE LAS DERROTAS</b>",
        div, f"💀 Cayó <b>{n}</b> veces. Patrones:",
        f"🟡 Evitables: <b>{rep.get('patrones', {}).get('evitables')}/{n}</b>",
        f"🎲 Mala suerte: <b>{rep.get('patrones', {}).get('mala_suerte')}/{n}</b>",
        "", DISCLAIMER
    ]
    return "\n".join(lineas)

def _marcador_a_favor(marcador: str, es_local: bool) -> str:
    try:
        hg, ag = str(marcador or "").split("-")
        return f"{hg.strip()}-{ag.strip()}" if es_local else f"{ag.strip()}-{hg.strip()}"
    except Exception: return str(marcador or "")

def construir_mensaje_survivor_historial(resumen: Dict[str, Any]) -> str:
    """Mensaje de la racha del pick de Survivor, para /racha."""
    div = "━━━━━━━━━━"
    resumen = resumen or {}
    jugadas = int(resumen.get("jugadas", 0) or 0)
    if not jugadas and not resumen.get("pendientes"):
        return f"🏆 <b>RACHA SURVIVOR</b>\n\nAún no hay picks.\n\n{DISCLAIMER}"
    lineas = ["🏆 <b>RACHA SURVIVOR</b>", div, f"Estado: <b>{resumen.get('sigue_vivo', True)}</b>"]
    if jugadas:
        lineas.append(f"🛡️ Sobrevividas: <b>{resumen.get('sobrevividas')}/{jugadas}</b>")
    lineas += [div, DISCLAIMER]
    return "\n".join(lineas)

def construir_mensaje_ganadores(rep: Dict[str, Any]) -> str:
    """Mensaje del Survivor perfecto vs el bot, para /ganadores."""
    div = "━━━━━━━━━━"
    n = (rep or {}).get("torneos", 0)
    if not rep or n == 0:
        return f"🏆 <b>EL SURVIVOR PERFECTO</b>\n\nAún no hay historial.\n\n{DISCLAIMER}"
    lineas = [
        "🏆 <b>EL SURVIVOR PERFECTO vs EL BOT</b>",
        div,
        f"🔮 Camino perfecto en <b>{rep.get('con_camino_perfecto')}/{n}</b> torneos",
        f"🤖 El bot completó <b>{rep.get('bot_completos')}/{n}</b>",
        "", DISCLAIMER
    ]
    return "\n".join(lineas)
