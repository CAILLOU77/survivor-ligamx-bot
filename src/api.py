from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import os
from datetime import datetime, timedelta

app = FastAPI(title="Survivor LigaMX API")

# Permitir peticiones desde cualquier origen
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

PICKS_CACHE = {"status": "inactive", "picks": [], "last_update": None}

def refresh_cache():
    global PICKS_CACHE
    try:
        df = pd.read_parquet("data_kiro/ligamx_odds_clean.parquet")
        valid = df[(df["VIG"] < 15) & (df["expected_value"] > 0.04)].copy()
        valid = valid.sort_values("timestamp", ascending=False).head(10)
        PICKS_CACHE = {
            "status": "active",
            "last_update": datetime.utcnow().isoformat() + "Z",
            "picks": valid.reset_index(drop=True).to_dict(orient="records")
        }
    except Exception as e:
        PICKS_CACHE = {"status": "error", "message": str(e), "last_update": None}

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

@app.get("/picks/latest")
def get_latest_picks():
    if not PICKS_CACHE["last_update"] or \
       datetime.fromisoformat(PICKS_CACHE["last_update"].replace("Z","")) < datetime.utcnow() - timedelta(minutes=15):
        refresh_cache()
    return PICKS_CACHE

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api:app", host="0.0.0.0", port=8000, reload=True)