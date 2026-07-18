#!/usr/bin/env python3
"""Prueba del análisis inteligente + plan de temporada."""
import sys
import os

# Usar ruta absoluta del proyecto para que funcione desde cualquier directorio (incluido cron)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from src import motor_pronosticos
from src import fuentes_datos
from src import poisson_model as pm
from src import planificador_survivor as plan_mod
import json

try:
    datos = fuentes_datos.obtener_resultados(meses=18)
    print(f"Datos obtenidos: {len(datos.get('resultados', []))} resultados")
    fuerzas = pm.calcular_fuerzas(datos['resultados'])
    print(f"Fuerzas calculadas: {len(fuerzas.get('equipos', {}))} equipos")

    resultado = motor_pronosticos.generar_pronosticos(resultados=datos['resultados'])
    print(f"Pronosticos: {len(resultado.get('pronosticos', []))} partidos")

    picks = motor_pronosticos.mejores_picks_estrategico(resultado.get('pronosticos', []), n=3)
    print(f"Picks estrategicos: {len(picks.get('picks', []))} picks")
    for p in picks.get('picks', []):
        print(f"  - {p['equipo']} (cond:{p['condicion']} vs {p['rival']}) sobrevive {p['no_perder_pct']}%")

    # Plan de temporada
    calendario = plan_mod.cargar_calendario()
    print(f"\nCalendario: {len(calendario)} jornadas")
    if calendario:
        odds = plan_mod.construir_odds_por_partido(calendario)
        plan = plan_mod.planificar(calendario, fuerzas, odds_por_partido=odds)
        print(f"Plan: {len(plan.get('plan', []))} entradas")
        if plan.get("calendario_incompleto"):
            print("⚠️ CALENDARIO INCOMPLETO")
        for p in plan.get("plan", [])[:5]:
            print(f"  J{p['jornada']}: {p['equipo']} ({p['condicion']} vs {p['rival']}) — surv {p['no_perder_pct']}% [{p['nivel']}]")

    print("\n✅ TODO OK")

except Exception as e:
    import traceback
    traceback.print_exc()
    sys.exit(1)