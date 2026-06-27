from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
from datetime import datetime, timedelta
from src.poisson_model import calibrate_and_predict

app = FastAPI(title="Survivor LigaMX API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])

PICKS_CACHE = {"status": "inactive", "picks": [], "last_update": None}

def refresh_cache():
    global PICKS_CACHE
    try:
        df = pd.read_parquet("data_kiro/ligamx_odds_clean.parquet")
        valid = df[df["vig_pct"] < 15].copy()
        picks_out = []

        for _, row in valid.iterrows():
            pred = calibrate_and_predict(row["momio_1"], row["momio_2"], row["momio_3"])
            if pred["expected_value"] > 0.04 and pred["kelly_stake"] > 0:
                picks_out.append({
                    "match": f"Liga {row['id_liga']} | ID {row['id_mercado']}",
                    "true_prob": pred["true_prob"],
                    "expected_value": pred["expected_value"],
                    "kelly_stake": pred["kelly_stake"],
                    "market": "1 (Local)",
                    "timestamp": str(row["timestamp"])
                })

        picks_out = sorted(picks_out, key=lambda x: x["expected_value"], reverse=True)[:10]
        PICKS_CACHE = {"status": "active", "last_update": datetime.utcnow().isoformat() + "Z", "picks": picks_out}
    except Exception as e:
        PICKS_CACHE = {"status": "error", "message": str(e), "last_update": None}

@app.get("/health")
def health(): 
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

@app.get("/picks/latest")
def get_picks():
    if not PICKS_CACHE["last_update"] or datetime.fromisoformat(PICKS_CACHE["last_update"].replace("Z","")) < datetime.utcnow() - timedelta(minutes=15):
        refresh_cache()
    return PICKS_CACHE


from src.routers.analizar_1x2 import router as analizar_router
app.include_router(analizar_router)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api:app", host="0.0.0.0", port=8000, reload=True)
