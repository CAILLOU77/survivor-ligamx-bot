import json
import os

def seleccionar_pick_survivor():
    ruta_archivo = 'data/jornadas.json'
    ruta_historial = 'data/historial_picks.json'
    
    if not os.path.exists(ruta_archivo):
        print("❌ Error: No se encuentra data/jornadas.json. Ejecuta los módulos previos.")
        return None

    with open(ruta_archivo, 'r', encoding='utf-8') as f:
        partidos = json.load(f)
        
    # Inicializar o leer el historial de equipos que ya usaste en jornadas anteriores
    equipos_usados = []
    if os.path.exists(ruta_historial):
        with open(ruta_historial, 'r', encoding='utf-8') as f:
            equipos_usados = json.load(f)

    candidatos_survivor = []

    for partido in partidos:
        local = partido['home_team']
        visita = partido['away_team']
        
        # Calcular probabilidades del mercado
        outcomes = partido['bookmakers'][0]['markets'][0]['outcomes']
        cuota_l = next(o['price'] for o in outcomes if o['name'] == local)
        cuota_v = next(o['price'] for o in outcomes if o['name'] == visita)
        cuota_e = next(o['price'] for o in outcomes if o['name'] == 'Draw')
        
        suma_prob = (1/cuota_l) + (1/cuota_v) + (1/cuota_e)
        prob_l = (1/cuota_l) / suma_prob
        prob_v = (1/cuota_v) / suma_prob
        prob_e = (1/cuota_e) / suma_prob
        
        # Regla Playdoit Liga MX: Avanzas si ganas o empatas
        surv_local = prob_l + prob_e
        surv_visita = prob_v + prob_e
        
        # Agregar a la lista si el equipo NO ha sido usado antes
        if local not in equipos_usados:
            candidatos_survivor.append({"equipo": local, "prob_avance": surv_local, "rival": visita, "condicion": "Local"})
        if visita not in equipos_usados:
            candidatos_survivor.append({"equipo": visita, "prob_avance": surv_visita, "rival": local, "condicion": "Visitante"})

    # Ordenar los equipos de mayor a menor probabilidad de supervivencia
    candidatos_survivor = sorted(candidatos_survivor, key=lambda x: x['prob_avance'], reverse=True)

    print("\n🛡️ --- BOT: OPTIMIZADOR RESTRINGIDO DE SURVIVOR (LIGA MX) ---")
    if equipos_usados:
        print(f"🚫 Equipos bloqueados (Ya usados previamente): {', '.join(equipos_usados)}")
    else:
        print("🆕 Historial limpio: Todos los equipos de la Liga MX están disponibles.")
        
    print("="*65)
    print(f"🔥 PICK RECOMENDADO OFICIAL PARA TU SURVIVOR:")
    top_pick = candidatos_survivor[0]
    print(f"   👉 SELECCIONAR A: {top_pick['equipo']} ({top_pick['condicion']})")
    print(f"   ↳ Enfrentando a: {top_pick['rival']}")
    print(f"   ↳ Probabilidad matemática de avanzar de jornada: {top_pick['prob_avance']*100:.1f}%")
    print("="*65)
    
    print("\n📋 Opciones de respaldo ordenadas por nivel de seguridad:")
    for idx, cand in enumerate(candidatos_survivor[1:4], start=2):
        print(f"   {idx}. {cand['equipo']} vs {cand['rival']} | Probabilidad: {cand['prob_avance']*100:.1f}%")

if __name__ == "__main__":
    seleccionar_pick_survivor()
