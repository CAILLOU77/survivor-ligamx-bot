import pandas as pd
from src.poisson_model import calibrate_poisson
from pathlib import Path

df = pd.read_parquet("data_kiro/ligamx_odds_clean.parquet")
calibrated = calibrate_poisson(df, target_cols=["momio_1", "momio_2", "momio_3"])

calibrated.to_csv("data/poisson_calibrated.csv", index=False)
print(f"✅ Modelo calibrado. {len(calibrated)} partidos procesados.")
print("📈 Diferencia media prob modelo vs mercado:", round((calibrated["prob_modelo"] - calibrated["prob_mercado"]).abs().mean()*100, 2), "%")
