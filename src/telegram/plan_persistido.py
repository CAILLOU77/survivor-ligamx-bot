from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .envio import _jornada_actual_num, _usados_persistidos, enviar_mensaje
from .utils import _pct

logger = logging.getLogger(__name__)

DISCLAIMER = "ℹ️ Informativo / revisión humana. No es consejo de apuesta."
_ESTADOS_CERRADOS = {"confirmado", "bloqueado", "resuelto"}


def _cargar_historial_cerrado() -> List[Dict[str, Any]]:
    """Lee las selecciones reales sin impedir el plan si la BD no está disponible."""
    try:
        from src import database as db

        temporada = db.temporada_survivor_actual()
        picks = db.get_survivor_picks(temporada)
    except Exception:
        logger.warning("No se pudo leer el historial cerrado de Survivor", exc_info=True)
        return []

    historial: List[Dict[str, Any]] = []
    for pick in picks:
        estado = str(pick.get("estado") or "").lower()
        if estado not in _ESTADOS_CERRADOS:
            continue
        try:
            jornada = int(pick.get("jornada"))
        except (TypeError, ValueError):
            continue
        historial.append(
            {
                "jornada": jornada,
                "equipo": str(pick.get("equipo") or ""),
                "estado": estado,
                "resultado": str(pick.get("resultado") or "").lower() or None,
            }
        )
    historial.sort(key=lambda item: item["jornada"])
    return historial


def _plan_temporada(
    equipos_usados: Optional[List[str]],
    peso_victoria: float = 0.5,
    usar_momios: bool = True,
    jornada_desde: Optional[int] = None,
    permitir_descarga: bool = True,
) -> Dict[str, Any]:
    """Planifica solo las jornadas que aún no tienen una selección real cerrada."""
    from src import fuentes_datos
    from src import planificador_survivor as plan_mod
    from src import poisson_model as pm

    historial = _cargar_historial_cerrado()
    jornadas_cerradas = {int(item["jornada"]) for item in historial}
    calendario = plan_mod.cargar_calendario()
    jornada_desde = jornada_desde if jornada_desde is not None else _jornada_actual_num()
    if jornada_desde is None:
        return {
            "calendario_incompleto": False,
            "temporada_finalizada": True,
            "plan": [],
            "historial_cerrado": historial,
        }

    calendario_filtrado: List[Dict[str, Any]] = []
    for bloque in calendario:
        try:
            jornada = int(str(bloque.get("jornada")))
        except (TypeError, ValueError):
            logger.warning(
                "Se ignoró una jornada inválida del calendario: %r",
                bloque.get("jornada"),
            )
            continue
        if jornada >= jornada_desde and jornada not in jornadas_cerradas:
            calendario_filtrado.append(bloque)

    if not calendario_filtrado:
        return {
            "calendario_incompleto": False,
            "temporada_finalizada": True,
            "plan": [],
            "historial_cerrado": historial,
        }

    try:
        resultados = fuentes_datos.leer_cache()
        if not resultados and permitir_descarga:
            datos = fuentes_datos.obtener_resultados(meses=18)
            datos_resultados = datos.get("resultados")
            resultados = datos_resultados if isinstance(datos_resultados, list) else []
        if not resultados:
            raise ValueError("No hay resultados históricos en caché para calcular fuerzas")
        fuerzas = pm.calcular_fuerzas(resultados)
        odds = plan_mod.construir_odds_por_partido(calendario_filtrado) if usar_momios else None
        resultado = plan_mod.planificar(
            calendario_filtrado,
            fuerzas,
            equipos_usados=equipos_usados,
            peso_victoria=peso_victoria,
            odds_por_partido=odds,
        )
        if not isinstance(resultado, dict):
            resultado = {"calendario_incompleto": True, "plan": []}
    except Exception as exc:
        logger.warning("No se pudo construir el plan restante de temporada", exc_info=True)
        resultado = {
            "calendario_incompleto": True,
            "plan": [],
            "error": str(exc),
        }

    resultado["historial_cerrado"] = historial
    resultado["jornada_plan_desde"] = min(int(bloque["jornada"]) for bloque in calendario_filtrado)
    return resultado


def _estado_historial(item: Dict[str, Any]) -> str:
    estado = str(item.get("estado") or "").lower()
    resultado = str(item.get("resultado") or "").lower()
    if estado == "resuelto":
        if resultado == "gano":
            return "🔒 ✅ Ganó"
        if resultado == "empate":
            return "🔒 🤝 Empató"
        if resultado == "perdio":
            return "🔒 ❌ Perdió"
        return "🔒 Resuelto"
    if estado == "bloqueado":
        return "🔒 ⏳ Bloqueado"
    return "✅ Confirmado"


def construir_mensaje_plan_persistido(plan: Dict[str, Any]) -> str:
    """Muestra primero los picks reales y después únicamente el plan pendiente."""
    historial = plan.get("historial_cerrado") or []
    futuro = plan.get("plan") or []
    if not historial and (plan.get("calendario_incompleto") or not futuro):
        return (
            "📅 <b>PLAN SURVIVOR</b>\n\n"
            "Aún no hay calendario completo (data/calendario.json). "
            "Córrelo de nuevo cuando se publique el calendario del torneo.\n\n"
            f"{DISCLAIMER}"
        )

    lineas = ["📅 <b>PLAN SURVIVOR — temporada</b> (modelo · datos ESPN)"]
    if historial:
        lineas.extend(["", "<b>Historial cerrado</b>"])
        for item in historial:
            jornada = int(item.get("jornada") or 0)
            equipo = str(item.get("equipo") or "—")
            lineas.append(f"<b>J{jornada} · {equipo}</b> {_estado_historial(item)}")

    if futuro:
        desde = plan.get("jornada_plan_desde") or min(int(pick["jornada"]) for pick in futuro)
        lineas.extend(
            [
                "",
                f"<b>Plan restante desde J{desde}</b>",
                (
                    f"<i>🛡️ Sobrevivir el tramo restante: "
                    f"{_pct(plan.get('prob_supervivencia_total_pct'))}% · "
                    f"🏆 victorias esperadas: {plan.get('victorias_esperadas')}</i>"
                ),
                "<i>Los picks cerrados no se recalculan ni consumen otro equipo.</i>",
                "",
            ]
        )
        for pick in futuro:
            lineas.append(
                f"<b>J{pick['jornada']} · {pick['equipo']}</b> "
                f"({pick['condicion']} vs {pick['rival']})"
            )
            lineas.append(
                f"🏆 gana {_pct(pick['prob_ganar_pct'])}% · "
                f"🛡️ sobrevive {_pct(pick['no_perder_pct'])}% [{pick['nivel']}]"
            )
        riesgosas = plan.get("jornadas_riesgosas") or []
        if riesgosas:
            jornadas_texto = ", ".join("J" + str(jornada) for jornada in riesgosas)
            lineas.extend(["", f"⚠️ Jornadas riesgosas: {jornadas_texto}"])
    elif plan.get("temporada_finalizada"):
        lineas.extend(["", "No quedan jornadas pendientes por planificar."])

    lineas.extend(["", DISCLAIMER])
    return "\n".join(lineas)


def enviar_plan(
    equipos_usados: Optional[List[str]] = None,
    peso_victoria: float = 0.5,
    usar_momios: bool = True,
) -> Dict[str, Any]:
    """Envía historial cerrado y plan futuro sin reasignar jornadas reales."""
    if equipos_usados is None:
        equipos_usados = _usados_persistidos()
    plan = _plan_temporada(
        equipos_usados,
        peso_victoria=peso_victoria,
        usar_momios=usar_momios,
    )
    mensaje = (
        "🧠 <b>ANÁLISIS INTELIGENTE</b>\n"
        "<i>Plan optimizado para sobrevivir sin repetir equipo y priorizar victorias.</i>\n\n"
        + construir_mensaje_plan_persistido(plan)
    )
    enviado = enviar_mensaje(mensaje)
    pasos = plan.get("plan")
    return {
        "enviado": enviado,
        "jornadas": len(pasos) if isinstance(pasos, list) else 0,
        "calendario_incompleto": bool(plan.get("calendario_incompleto")),
    }
