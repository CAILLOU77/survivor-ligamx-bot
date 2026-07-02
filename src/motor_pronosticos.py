#!/usr/bin/env python3
"""
motor_pronosticos.py — Cerebro de pronósticos Liga MX (datos reales, gratis).

Ata todas las piezas legítimas:
    fuentes_datos (ESPN/TheSportsDB/caché)  ->  fuerza de equipos
    poisson_model (Dixon-Coles)             ->  probabilidades por partido
    espn_data (fixtures próximos)           ->  qué partidos predecir

Produce, por partido próximo: 1X2, Over/Under, BTTS, marcador probable y el
"no perder" para Survivor. Además calcula el mejor pick de Survivor de la
jornada (equipo con mayor probabilidad de no perder, excluyendo los ya usados).

Sin momios, sin scraping, sin APIs de pago. Solo resultados reales de ESPN.
Decisión operativa informativa: este motor NO cierra ni envía picks por sí solo.
"""
from __future__ import annotations

import json
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

try:
    import fuentes_datos
    import espn_data
    import poisson_model as pm
except ImportError:  # pragma: no cover
    from src import fuentes_datos, espn_data  # type: ignore
    from src import poisson_model as pm  # type: ignore

BASE_DIR = Path(__file__).resolve().parents[1]
PRONOSTICOS_PATH = BASE_DIR / "data" / "pronosticos.json"

DEC_INFORMATIVA = "INFORMATIVO / REVISIÓN HUMANA"


def _norm(t: str) -> str:
    base = unicodedata.normalize("NFKD", str(t or "")).lower()
    base = "".join(c for c in base if not unicodedata.combining(c))
    return " ".join(base.split())


def _equipo_conocido(nombre: str, fuerzas: Dict[str, Any]) -> bool:
    # Usa la MISMA normalización que poisson_model (que conserva acentos),
    # para que las claves de fuerzas coincidan exactamente.
    return pm._norm(nombre) in fuerzas.get("equipos", {})


def _explicar_partido(p: Dict[str, Any]) -> Dict[str, str]:
    """Explica, con los NÚMEROS del modelo (no opinión), el 1X2 y el Over/Under."""
    local, visitante = p["local"], p["visitante"]
    pl, pe, pv = p["prob_local_pct"], p["prob_empate_pct"], p["prob_visitante_pct"]
    gl, gv = p["lambda_local"], p["lambda_visitante"]
    total = gl + gv
    linea = p.get("linea_goles", 2.5)

    if p["pick_1x2"] == "Gana Local":
        e1 = (f"{local} es favorito: el modelo le da {pl}% de ganar (vs {pv}% de {visitante}); "
              f"pesan su mayor fuerza y la ventaja de local. Marcador esperado ~{gl:.1f}-{gv:.1f}.")
    elif p["pick_1x2"] == "Gana Visitante":
        e1 = (f"{visitante} es favorito aun de visita: {pv}% de ganar (vs {pl}% de {local}); "
              f"su fuerza supera la ventaja local del rival. Marcador esperado ~{gl:.1f}-{gv:.1f}.")
    else:
        e1 = (f"Partido parejo (L {pl}% / E {pe}% / V {pv}%): sin favorito claro y con ~{total:.1f} "
              f"goles esperados, el EMPATE es el escenario más probable del modelo.")

    if p["pick_ou"] == "Over":
        e2 = (f"Over {linea}: se esperan ~{total:.1f} goles ({p['prob_over_pct']}%); los ataques "
              f"pesan más que las defensas.")
    else:
        e2 = (f"Under {linea}: solo ~{total:.1f} goles esperados ({p['prob_under_pct']}%); "
              f"defensas sólidas o ataques flojos, por eso el modelo ve pocos goles.")
    return {"explicacion_1x2": e1, "explicacion_ou": e2}


def _nivel_confianza_1x2(prob_pick_pct: float) -> str:
    """Confianza del pronóstico 1X2 según la probabilidad del resultado elegido."""
    if prob_pick_pct >= 55.0:
        return "ALTA"
    if prob_pick_pct >= 42.0:
        return "MEDIA"
    return "BAJA"


# Umbrales de alerta (partido "trampa" para Survivor), derivados del modelo.
_EMPATE_ALTO_PCT = 30.0       # riesgo de push (empate)
_GOLES_CERRADO = 2.3          # goles esperados totales bajos => juego cerrado
_PICK_ABIERTO_PCT = 45.0      # sin favorito claro


def _alertas_partido(pick_1x2: str, prob_empate: float, prob_pick: float,
                     goles_totales: float) -> Dict[str, Any]:
    """
    Marca un partido como de PRECAUCIÓN / ALERTA ROJA con los motivos concretos
    (basados en los números del modelo). Útil para no quemar el Survivor en un
    partido trampa. Sin invención: cada motivo sale de una condición medible.
    """
    motivos: List[str] = []
    if pick_1x2 == "Gana Visitante":
        motivos.append("El favorito es VISITANTE (de visita hay más sorpresas).")
    if prob_pick < _PICK_ABIERTO_PCT:
        motivos.append(f"Sin favorito claro (pick {prob_pick:.0f}%): resultado muy abierto.")
    if prob_empate >= _EMPATE_ALTO_PCT:
        motivos.append(f"Empate probable ({prob_empate:.0f}%): riesgo de 'push' (empate = sobrevives sin punto).")
    if goles_totales < _GOLES_CERRADO:
        motivos.append(f"Partido cerrado (~{goles_totales:.1f} goles): pocos goles, propenso a empate/sorpresa.")

    if len(motivos) >= 2:
        nivel = "🚨 ALERTA ROJA"
    elif len(motivos) == 1:
        nivel = "⚠️ PRECAUCIÓN"
    else:
        nivel = "OK"
    return {"precaucion": bool(motivos), "nivel_alerta": nivel, "motivos": motivos}


def pronosticar_partido(
    home: str, away: str, fuerzas: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Pronóstico de un partido si ambos equipos tienen histórico; si no, None."""
    if not _equipo_conocido(home, fuerzas) or not _equipo_conocido(away, fuerzas):
        return None
    p = pm.pronostico(home, away, fuerzas)
    exp = _explicar_partido(p)
    prob_pick = max(p["prob_local_pct"], p["prob_empate_pct"], p["prob_visitante_pct"])
    goles_totales = p["lambda_local"] + p["lambda_visitante"]
    alerta = _alertas_partido(p["pick_1x2"], p["prob_empate_pct"], prob_pick, goles_totales)
    return {
        "local": home,
        "visitante": away,
        "pick_1x2": p["pick_1x2"],
        "prob_local_pct": p["prob_local_pct"],
        "prob_empate_pct": p["prob_empate_pct"],
        "prob_visitante_pct": p["prob_visitante_pct"],
        "prob_pick_pct": round(prob_pick, 2),
        "nivel_confianza": _nivel_confianza_1x2(prob_pick),
        "precaucion": alerta["precaucion"],
        "nivel_alerta": alerta["nivel_alerta"],
        "motivos_alerta": alerta["motivos"],
        "goles_esperados_local": p["lambda_local"],
        "goles_esperados_visitante": p["lambda_visitante"],
        "pick_ou": p["pick_ou"],
        "prob_over_pct": p["prob_over_pct"],
        "pick_btts": p["pick_btts"],
        "prob_btts_si_pct": p["prob_btts_si_pct"],
        "marcador_mas_probable": p["marcador_mas_probable"],
        "no_perder_local_pct": round(p["prob_local_pct"] + p["prob_empate_pct"], 2),
        "no_perder_visitante_pct": round(p["prob_visitante_pct"] + p["prob_empate_pct"], 2),
        "explicacion_1x2": exp["explicacion_1x2"],
        "explicacion_ou": exp["explicacion_ou"],
    }


def generar_pronosticos(
    meses: int = 18,
    fixtures: Optional[Sequence[Dict[str, Any]]] = None,
    resultados: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Genera pronósticos para los próximos partidos.

    `fixtures`/`resultados` se pueden inyectar (tests); si no, se bajan de las
    fuentes reales (ESPN con respaldo).
    """
    if resultados is None:
        datos = fuentes_datos.obtener_resultados(meses)
        resultados = datos["resultados"]
        fuente = datos["fuente"]
    else:
        fuente = "inyectada"

    if fixtures is None:
        try:
            fixtures = espn_data.obtener_fixtures()
        except Exception:
            fixtures = []

    pronosticos: List[Dict[str, Any]] = []
    fuerzas: Optional[Dict[str, Any]] = None
    if resultados:
        try:
            fuerzas = pm.calcular_fuerzas(resultados)
        except ValueError:
            fuerzas = None

    if fuerzas:
        for fx in fixtures:
            home = fx.get("home_team", "")
            away = fx.get("away_team", "")
            pron = pronosticar_partido(home, away, fuerzas)
            if pron:
                pron["fecha"] = fx.get("fecha", "")
                pronosticos.append(pron)

    # Señal "bestia negra" (H2H): avisa si el favorito no domina a ese rival.
    try:
        try:
            import matchup_h2h as mh2h
        except ImportError:  # pragma: no cover
            from src import matchup_h2h as mh2h  # type: ignore
        pronosticos = mh2h.anotar_h2h(pronosticos, resultados)
    except Exception:  # pragma: no cover - nunca tumbar el pipeline
        pass

    return {
        "generado_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fuente_datos": fuente,
        "total_resultados_historicos": len(resultados),
        "total_pronosticos": len(pronosticos),
        "pronosticos": pronosticos,
        "decision": DEC_INFORMATIVA,
    }


def mejores_picks_survivor(
    pronosticos: Sequence[Dict[str, Any]],
    equipos_usados: Optional[Sequence[str]] = None,
    motivacion: Optional[Dict[str, Dict[str, Any]]] = None,
    n: int = 3,
) -> List[Dict[str, Any]]:
    """
    Devuelve los `n` mejores candidatos de Survivor, ordenados de mejor a peor,
    excluyendo los ya usados.

    Orden (alineado con las reglas PlayDoit):
      1) mayor prob. de NO perder (sobrevivir es prioridad #1: derrota = eliminado),
      2) mayor prob. de GANAR (desempate: ganar da puntos y es lo que se busca),
      3) rival con MENOR motivación (contexto/desempate fino).

    Cada candidato incluye `prob_victoria_pct`, `prob_empate_pct` (riesgo de
    empate/push) y `nivel` (ALTA / MEDIA / RIESGOSA). `motivacion` es CONTEXTO.
    El criterio principal es la probabilidad del modelo (fuente de verdad).
    """
    usados = {_norm(e) for e in (equipos_usados or [])}
    mot = motivacion or {}
    candidatos: List[Dict[str, Any]] = []
    for p in pronosticos:
        empate = p.get("prob_empate_pct")
        for equipo, rival, cond, prob, win in (
            (p["local"], p["visitante"], "Local",
             p["no_perder_local_pct"], p.get("prob_local_pct")),
            (p["visitante"], p["local"], "Visitante",
             p["no_perder_visitante_pct"], p.get("prob_visitante_pct")),
        ):
            if _norm(equipo) in usados:
                continue
            candidatos.append({
                "equipo": equipo, "rival": rival, "condicion": cond,
                "no_perder_pct": prob,
                "prob_victoria_pct": win,
                "prob_empate_pct": empate,
                "nivel": _nivel_pick(prob, win),
                "motivacion_propia": (mot.get(_norm(equipo)) or {}).get("motivacion_nivel"),
                "rival_motivacion": (mot.get(_norm(rival)) or {}).get("motivacion_nivel"),
            })
    candidatos.sort(
        key=lambda c: (
            c["no_perder_pct"],
            c.get("prob_victoria_pct") or 0.0,
            _rank_motivacion(c["rival_motivacion"]),
        ),
        reverse=True,
    )
    return candidatos[: max(0, n)]


# Umbrales del nivel de confianza del pick (en %), coherentes con el planificador.
_NIVEL_NO_PERDER_ALTA = 75.0
_NIVEL_GANAR_ALTA = 55.0
_NIVEL_NO_PERDER_MEDIA = 65.0


def _nivel_pick(no_perder_pct: float, win_pct: Optional[float]) -> str:
    """Clasifica la confianza del pick. Sin info de victoria, usa solo no-perder."""
    if win_pct is None:
        if no_perder_pct >= _NIVEL_NO_PERDER_ALTA:
            return "ALTA"
        if no_perder_pct >= _NIVEL_NO_PERDER_MEDIA:
            return "MEDIA"
        return "RIESGOSA"
    if no_perder_pct >= _NIVEL_NO_PERDER_ALTA and win_pct >= _NIVEL_GANAR_ALTA:
        return "ALTA"
    if no_perder_pct >= _NIVEL_NO_PERDER_MEDIA:
        return "MEDIA"
    return "RIESGOSA"


def mejor_pick_survivor(
    pronosticos: Sequence[Dict[str, Any]],
    equipos_usados: Optional[Sequence[str]] = None,
    motivacion: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """Mejor candidato de Survivor (el #1 de `mejores_picks_survivor`)."""
    tops = mejores_picks_survivor(pronosticos, equipos_usados, motivacion, n=1)
    return tops[0] if tops else None


# ---------------------------------------------------------------------------
# Capa ESTRATÉGICA: cautela de arranque + anti-sorpresa (favorito visitante).
# ---------------------------------------------------------------------------
# Debajo de este # de partidos jugados del torneo, estamos en "arranque":
# pocos datos frescos y muchas sorpresas => modo cauteloso.
UMBRAL_CAUTELA_PARTIDOS = 27  # ~3 jornadas de 9 partidos
# Penalización (en puntos de no-perder) a los favoritos VISITANTES: se midió que
# el favorito visitante falla ~58% vs ~44% del local (analisis_riesgo).
PEN_VISITANTE = 4.0
PEN_VISITANTE_CAUTELA = 8.0

# Peso de la VICTORIA en el score del pick. El Survivor se gana sobreviviendo
# (prioridad #1), pero el desempate entre finalistas es "más victorias / menos
# empates": por eso ganar debe valer, no solo no-perder. El empate es push (no
# suma), así que un pick que sobrevive GANANDO vale más que uno que sobrevive por
# empate. En arranque (cautela) bajamos el peso: sobrevivir manda aún más.
PESO_VICTORIA_PICK = 0.5
PESO_VICTORIA_PICK_CAUTELA = 0.25


def _razon_pick(c: Dict[str, Any], es_local: bool, cautela: bool) -> str:
    """Explica en una frase por qué (o por qué no) conviene este pick, con números."""
    rival_mot = (c.get("rival_motivacion") or "").lower()
    np_pct = c.get("no_perder_pct")
    win = c.get("prob_victoria_pct")
    emp = c.get("prob_empate_pct")
    nums = f"{np_pct}% de no perder"
    if win is not None:
        nums += f" ({win}% ganar"
        if emp is not None:
            nums += f" + {emp}% empatar"
        nums += ")"
    cond = "de LOCAL" if es_local else "de VISITA"
    base = f"{c.get('equipo')} {cond}: {nums}."
    if es_local:
        base += " Los locales fallan menos que los visitantes."
        if rival_mot == "baja":
            base += f" Además {c.get('rival')} llega sin presión (relajado/eliminado): escenario más seguro."
    else:
        base += " ⚠️ Ojo: es favorito visitante y de visita hay más sorpresas."
    if cautela:
        base += " Arranque de torneo: voy conservador."
    return base


def _nivel_estrategico(no_perder: float, win: Optional[float], es_local: bool, cautela: bool) -> str:
    """Confianza ajustada por sorpresa: castiga visitantes y sube el listón en arranque."""
    nivel = _nivel_pick(no_perder, win)
    if not es_local and nivel == "ALTA":
        nivel = "MEDIA"  # favorito visitante nunca es 'ALTA' (riesgo de sorpresa)
    if cautela and nivel == "ALTA" and no_perder < 80.0:
        nivel = "MEDIA"  # en arranque, ALTA exige margen alto de no-perder
    return nivel


def mejores_picks_estrategico(
    pronosticos: Sequence[Dict[str, Any]],
    equipos_usados: Optional[Sequence[str]] = None,
    motivacion: Optional[Dict[str, Dict[str, Any]]] = None,
    partidos_jugados_torneo: Optional[int] = None,
    n: int = 3,
) -> Dict[str, Any]:
    """
    Pick de Survivor con ESTRATEGIA anti-sorpresa y cautela de arranque.

    Sobre el ranking base (no-perder + victoria + motivación del rival) aplica:
      - Penalización a favoritos VISITANTES (fallan más).
      - Cautela cuando el torneo tiene POCOS partidos jugados (`partidos_jugados_torneo`
        bajo o desconocido => modo cauteloso: penaliza más al visitante y sube el
        listón de confianza). "Sin datos" => por defecto cauteloso.
      - `razon` (explicación) y `nivel` ajustado por sorpresa a cada candidato.

    Devuelve {cautela, partidos_jugados_torneo, advertencia, picks}.
    """
    cautela = (partidos_jugados_torneo is None) or (partidos_jugados_torneo < UMBRAL_CAUTELA_PARTIDOS)
    pen = PEN_VISITANTE_CAUTELA if cautela else PEN_VISITANTE
    peso_victoria = PESO_VICTORIA_PICK_CAUTELA if cautela else PESO_VICTORIA_PICK

    base = list(mejores_picks_survivor(pronosticos, equipos_usados, motivacion, n=10_000))
    for c in base:
        es_local = c.get("condicion") == "Local"
        no_perder = float(c.get("no_perder_pct") or 0.0)
        victoria = float(c.get("prob_victoria_pct") or 0.0)
        # Sobrevivir manda (no_perder), pero premiamos GANAR (desempate del Survivor)
        # y penalizamos al favorito visitante. El empate no aporta al score extra.
        c["_score"] = no_perder + peso_victoria * victoria - (0.0 if es_local else pen)
        c["nivel"] = _nivel_estrategico(no_perder, c.get("prob_victoria_pct"), es_local, cautela)
        c["razon"] = _razon_pick(c, es_local, cautela)
    base.sort(
        key=lambda c: (c["_score"], c.get("prob_victoria_pct") or 0.0, _rank_motivacion(c.get("rival_motivacion"))),
        reverse=True,
    )
    for c in base:
        c.pop("_score", None)

    advertencia = None
    if cautela:
        advertencia = (
            "⚠️ Arranque de torneo (pocos datos aún): priorizo LOCALES, evito favoritos "
            "visitantes y guardo a los equipos fuertes para jornadas difíciles. "
            "Las primeras semanas traen sorpresas."
        )
    return {
        "cautela": cautela,
        "partidos_jugados_torneo": partidos_jugados_torneo,
        "advertencia": advertencia,
        "picks": base[: max(0, n)],
    }


# Rango de "qué tan conveniente es el rival" (rival menos motivado = más seguro).
_RANK_MOTIVACION = {"baja": 3.0, "n/a": 2.0, "media": 1.0, "alta": 0.0}


def _rank_motivacion(nivel: Optional[str]) -> float:
    """Rank de conveniencia del rival; None => neutral (no afecta el orden base)."""
    if nivel is None:
        return 1.5
    return _RANK_MOTIVACION.get(str(nivel).lower(), 1.5)


def motivacion_por_equipo() -> Dict[str, Dict[str, Any]]:
    """
    Mapa {equipo_norm: {motivacion_nivel, zona}} desde la tabla de ESPN.
    Defensivo: devuelve {} si no hay red/datos (no rompe el flujo).
    """
    try:
        import tabla_posiciones as tabla_mod
    except ImportError:  # pragma: no cover
        from src import tabla_posiciones as tabla_mod  # type: ignore
    try:
        data = tabla_mod.obtener_tabla()
    except Exception:
        return {}
    salida: Dict[str, Dict[str, Any]] = {}
    for fila in data.get("tabla", []):
        salida[_norm(fila.get("equipo", ""))] = {
            "motivacion_nivel": fila.get("motivacion_nivel"),
            "zona": fila.get("zona"),
        }
    return salida


def guardar_pronosticos(resultado: Dict[str, Any], path: Path = PRONOSTICOS_PATH) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(resultado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    print("🧠 Generando pronósticos Liga MX (datos reales de ESPN)...")
    resultado = generar_pronosticos()
    guardar_pronosticos(resultado)
    print(f"✅ Fuente: {resultado['fuente_datos']} | "
          f"histórico: {resultado['total_resultados_historicos']} | "
          f"pronósticos: {resultado['total_pronosticos']}")
    for p in resultado["pronosticos"]:
        print(f"  {p['local']} vs {p['visitante']}: {p['pick_1x2']} "
              f"(L{p['prob_local_pct']}/E{p['prob_empate_pct']}/V{p['prob_visitante_pct']}) "
              f"| {p['pick_ou']} 2.5 | marcador {p['marcador_mas_probable']}")
    pick = mejor_pick_survivor(resultado["pronosticos"])
    if pick:
        print(f"🎯 Survivor sugerido: {pick['equipo']} ({pick['condicion']} vs "
              f"{pick['rival']}) — no perder {pick['no_perder_pct']}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
