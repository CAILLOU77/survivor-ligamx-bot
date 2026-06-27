import json, csv, base64, os
from pathlib import Path
from datetime import datetime

DATA_DIR = Path("datos_ligamx")
OUTPUT_CSV = "momios_decodificados.csv"

# Mapeo basado en tu payload observado
FIELD_MAP = {
    0: "meta_b64",
    1: "momio_decimal",
    3: "id_liga",
    4: "momio_fraccionario",
    5: "id_mercado",
    6: "tendencia",      # INCR / DECR
    7: "estado_linea",   # LP = Line Posted / Live
    8: "id_seleccion",
    9: "variacion_pts"
}

def decode_meta(b64_str):
    try:
        return base64.b64decode(b64_str).decode('utf-8', errors='ignore')
    except Exception:
        return b64_str

records = []
for f in sorted(DATA_DIR.glob("*_ws_U.json")):
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        continue
        
    for update in data.get("updates", []):
        if update.get("obj_type") != "P":
            continue
            
        row = {
            "timestamp": datetime.now().isoformat(),
            "archivo_origen": f.name,
            "msg_ref": data.get("msg_ref", "")
        }
        for idx, val in update.get("data", []):
            key = FIELD_MAP.get(int(idx), f"campo_{idx}")
            row[key] = val
            
        if "meta_b64" in row:
            row["meta_decodificada"] = decode_meta(row["meta_b64"])
        records.append(row)

if records:
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)
    print(f"✅ {len(records)} registros decodificados → {OUTPUT_CSV}")
    print(f"📊 Primeras 5 filas:")
    with open(OUTPUT_CSV, "r") as f:
        for _ in range(6): print(f.readline().strip())
else:
    print("⚠️ No se encontraron mensajes 'U' válidos. Ejecuta ws_fixed.py por 30s más y repite.")
