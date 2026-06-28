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


def pronosticar_partido(
    home: str, away: str, fuerzas: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Pronóstico de un partido si ambos equipos tienen histórico; si no, None."""
    if not _equipo_conocido(home, fuerzas) or not _equipo_conocido(away, fuerzas):
        return None
    p = pm.pronostico(home, away, fuerzas)
    return {
        "local": home,
        "visitante": away,
        "pick_1x2": p["pick_1x2"],
        "prob_local_pct": p["prob_local_pct"],
        "prob_empate_pct": p["prob_empate_pct"],
        "prob_visitante_pct": p["prob_visitante_pct"],
        "pick_ou": p["pick_ou"],
        "prob_over_pct": p["prob_over_pct"],
        "pick_btts": p["pick_btts"],
        "prob_btts_si_pct": p["prob_btts_si_pct"],
        "marcador_mas_probable": p["marcador_mas_probable"],
        "no_perder_local_pct": round(p["prob_local_pct"] + p["prob_empate_pct"], 2),
        "no_perder_visitante_pct": round(p["prob_visitante_pct"] + p["prob_empate_pct"], 2),
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
