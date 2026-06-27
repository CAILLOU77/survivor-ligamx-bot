import csv
from pathlib import Path

INPUT = Path("momios_decodificados.csv")
OUTPUT = Path("ligamx_clean.csv")
# IDs de Liga MX vistos en tu captura
LIGAMX_IDS = {"31908190", "31908201"}

rows = []
with open(INPUT, "r", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        if r.get("id_liga") in LIGAMX_IDS:
            try:
                momio = float(r.get("momio_decimal", 0))
                if momio > 1.01:
                    prob = round(100 / momio, 2)
                    rows.append({
                        "id_liga": r["id_liga"],
                        "id_mercado": r.get("id_mercado",""),
                        "id_seleccion": r.get("id_seleccion",""),
                        "momio": momio,
                        "prob_implied_pct": prob,
                        "tendencia": r.get("tendencia",""),
                        "estado": r.get("estado",""),
                        "timestamp": r.get("timestamp","")
                    })
            except: pass

if rows:
    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f"✅ {len(rows)} momios exportados a {OUTPUT}")
else:
    print("⚠️ Ajusta LIGAMX_IDS si no coinciden con tu captura.")
