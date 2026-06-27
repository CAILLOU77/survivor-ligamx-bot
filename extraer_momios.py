import json, csv, os
from pathlib import Path
from datetime import datetime

DATA_DIR = Path("datos_liga_mx")
OUTPUT_CSV = "momios_ligamx.csv"

def extraer_datos(ruta_json):
    with open(ruta_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    resultados = []
    # Adaptador flexible para estructuras comunes
    eventos = data.get("Events") or data.get("Matches") or data.get("Games") or []
    if not eventos and isinstance(data, list):
        eventos = data
        
    for evt in eventos:
        comp = evt.get("Competition", {}).get("Name", evt.get("League", "Desconocida"))
        if "mexico" not in comp.lower() and "liga mx" not in comp.lower():
            continue
            
        local = evt.get("HomeTeam", evt.get("Competitors", [{}])[0].get("Name", ""))
        visita = evt.get("AwayTeam", evt.get("Competitors", [{}])[1].get("Name", ""))
        
        mercados = evt.get("Markets", evt.get("Odds", []))
        momio_1 = momio_x = momio_2 = ""
        for m in mercados:
            m_name = m.get("Name", "").lower()
            if any(k in m_name for k in ["1x2", "moneyline", "resultado final", "full time"]):
                selecciones = m.get("Outcomes", m.get("Odds", m.get("Selections", [])))
                if len(selecciones) >= 3:
                    momio_1 = str(selecciones[0].get("Price", selecciones[0].get("Odds", "")))
                    momio_x = str(selecciones[1].get("Price", selecciones[1].get("Odds", "")))
                    momio_2 = str(selecciones[2].get("Price", selecciones[2].get("Odds", "")))
                    break
                    
        resultados.append({
            "liga": comp,
            "local": local,
            "empate": momio_x,
            "visita": visita,
            "momio_local": momio_1,
            "momio_visita": momio_2,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
    return resultados

# Procesar todos los JSON
todos = []
for f in sorted(DATA_DIR.glob("*.json")):
    todos.extend(extraer_datos(f))
    
if todos:
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=todos[0].keys())
        writer.writeheader()
        writer.writerows(todos)
    print(f"✅ {len(todos)} registros extraídos → {OUTPUT_CSV}")
else:
    print("⚠️ No se encontraron momios 1X2. Pega las primeras 30 líneas del JSON y ajusto el parser en 10 seg.")
