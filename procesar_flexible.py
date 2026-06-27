import csv
from pathlib import Path

INPUT = Path("momios_1x2_estructurados.csv")
OUTPUT = Path("momios_finales.csv")

resultados = []
with open(INPUT, "r", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        num = int(r["num_opciones"])
        if num < 2: continue

        momios = []
        tendencias = []
        for i in range(1, 4):
            try:
                momios.append(float(r[f"opcion_{i}_momio"]))
                tendencias.append(r.get(f"opcion_{i}_tendencia", ""))
            except (ValueError, KeyError):
                momios.append("")
                tendencias.append("")

        moms_num = [m for m in momios if isinstance(m, float) and m > 1.01]
        vig = round((sum(1/m for m in moms_num) - 1) * 100, 2) if moms_num else 0

        resultados.append({
            "id_mercado": r["id_mercado"],
            "id_liga": r["id_liga"],
            "opciones_totales": num,
            "margen_casa_pct": vig,
            "timestamp": r["timestamp"],
            "momio_1": momios[0], "ten_1": tendencias[0],
            "momio_2": momios[1], "ten_2": tendencias[1],
            "momio_3": momios[2], "ten_3": tendencias[2]
        })

with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=resultados[0].keys())
    w.writeheader()
    w.writerows(resultados)
print(f"✅ {len(resultados)} registros exportados a {OUTPUT.name}")
