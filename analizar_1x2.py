import csv
from pathlib import Path

INPUT = Path("momios_1x2_estructurados.csv")
OUTPUT = Path("1x2_validado.csv")

valid = []
with open(INPUT, "r", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        if int(r["num_opciones"]) != 3:
            continue
        moms = [float(r[f"opcion_{i}_momio"]) for i in range(1,4)]
        probs = [float(r[f"opcion_{i}_prob"]) for i in range(1,4)]
        vig = round((sum(1/m for m in moms if m>1.01) - 1)*100, 2)
        valid.append({
            "id_mercado": r["id_mercado"], "id_liga": r["id_liga"],
            "momio_local": moms[0], "momio_empate": moms[1], "momio_visita": moms[2],
            "prob_local_pct": probs[0], "prob_empate_pct": probs[1], "prob_visita_pct": probs[2],
            "margen_casa_pct": vig, "timestamp": r["timestamp"]
        })

if valid:
    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=valid[0].keys())
        w.writeheader()
        w.writerows(valid)
    print(f"✅ {len(valid)} mercados 1X2 válidos → {OUTPUT.name}")
else:
    print("⚠️ Ningún mercado tiene exactamente 3 opciones en este snapshot.")
