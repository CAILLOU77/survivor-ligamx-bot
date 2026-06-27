import csv, time, os
from pathlib import Path
from datetime import datetime

DATA_DIR = Path("datos_ligamx")
INPUT_CSV = Path("momios_finales.csv")
OUTPUT_HIST = Path("historico_ligamx.csv")

def run_pipeline():
    if not INPUT_CSV.exists():
        return 0

    rows = []
    with open(INPUT_CSV, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows: return 0

    valid_count = 0
    header_exists = OUTPUT_HIST.exists()

    with open(OUTPUT_HIST, "a", newline="", encoding="utf-8") as f:
        writer = None
        for r in rows:
            try:
                momios = [float(r.get(f"momio_{i}", 0)) for i in range(1, 4)]
                moms_clean = [m for m in momios if m > 1.01]
                
                # Filtro estricto educativo
                if len(moms_clean) != 3: continue
                vig = (sum(1/m for m in moms_clean) - 1) * 100
                if vig <= 0 or vig > 15: continue

                probs_imp = [1/m for m in moms_clean]
                
                # EJEMPLO EDUCATIVO: prob_real estimada (en producción usarías tu modelo estadístico)
                prob_real = 0.35  # Reemplazar con tu fuente externa o modelo
                ev = round((moms_clean[1] * prob_real) - 1, 3)  # Calculado sobre la opción 2 (ej: empate)

                valid_count += 1
                row_out = {
                    "timestamp": datetime.now().isoformat(),
                    "id_mercado": r["id_mercado"],
                    "vig_pct": round(vig, 2),
                    "momios_1x2": "|".join([f"{m:.2f}" for m in moms_clean]),
                    "probs_imp_pct": "|".join([f"{p*100:.1f}%" for p in probs_imp]),
                    "ev_ejemplo": ev,
                    "senal": "🟢 +EV" if ev > 0 else "🔴 -EV"
                }
                if not writer:
                    writer = csv.DictWriter(f, fieldnames=row_out.keys())
                    if not header_exists:
                        writer.writeheader()
                writer.writerow(row_out)
            except Exception:
                continue
    return valid_count

if __name__ == "__main__":
    print("🚀 Iniciando loop educativo. Revisa historico_ligamx.csv cada 30s.")
    print("📊 Filtra solo mercados 1X2 completos con VIG 0-15%.")
    print("⏹️  Presiona Ctrl+C para detener.")
    try:
        while True:
            n = run_pipeline()
            if n > 0: print(f"✅ {n} mercados válidos agregados al histórico.")
            time.sleep(30)
    except KeyboardInterrupt:
        print("\n🛑 Loop detenido. Datos listos en historico_ligamx.csv")
