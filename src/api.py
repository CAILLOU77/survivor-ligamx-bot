from fastapi import FastAPI, HTTPException, Header, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import os
from datetime import datetime, timedelta
from typing import Optional
from src.poisson_model import calibrate_and_predict
from src.routers.analizar_1x2 import router as analizar_router
from src.database import init_db, save_pick, get_metrics

API_KEY = os.getenv("API_KEY", "survivor-ligamx-premium-2026")

def verify_api_key(x_api_key: Optional[str] = Header(None)):
    if not x_api_key or x_api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Clave API inválida o faltante")
    return x_api_key

app = FastAPI(title="Survivor LigaMX API Premium", version="2.1.0", docs_url="/docs")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])
app.include_router(analizar_router)
init_db()

PICKS_CACHE = {"status": "inactive", "picks": [], "last_update": None}

def refresh_cache():
    global PICKS_CACHE
    try:
        if not os.path.exists("data_kiro/ligamx_odds_clean.parquet"):
            PICKS_CACHE = {"status": "error", "message": "Data missing"}; return
        df = pd.read_parquet("data_kiro/ligamx_odds_clean.parquet")
        valid = df[df["vig_pct"] < 15].copy()
        picks_out = []
        for _, row in valid.iterrows():
            pred = calibrate_and_predict(row["momio_1"], row["momio_2"], row["momio_3"])
            if pred["expected_value"] > 0.04 and pred["kelly_stake"] > 0:
                match_id = f"L{row['id_liga']}_M{row['id_mercado']}"
                picks_out.append({
                    "match_id": match_id, "match": match_id, "market": "1 (Local)",
                    "true_prob": round(pred["true_prob"], 4),
                    "expected_value": round(pred["expected_value"], 4),
                    "kelly_stake": round(pred["kelly_stake"], 2),
                    "momio": round(row["momio_1"], 2),
                    "timestamp": str(row["timestamp"])
                })
                try: save_pick(match_id, "1 (Local)", pred["true_prob"], row["momio_1"], pred["expected_value"], pred["kelly_stake"])
                except: pass
        picks_out = sorted(picks_out, key=lambda x: x["expected_value"], reverse=True)[:10]
        PICKS_CACHE = {"status": "active", "last_update": datetime.utcnow().isoformat() + "Z", "picks": picks_out}
    except Exception as e:
        PICKS_CACHE = {"status": "error", "message": str(e), "last_update": None}

@app.get("/health", summary="Estado del sistema", tags=["Status"])
def health():
    return {"status": "ok", "version": "2.1.0-premium", "timestamp": datetime.utcnow().isoformat()}

@app.get("/picks/latest", summary="Picks activos (EV>4%)", tags=["Picks"])
def get_picks(api_key: str = Depends(verify_api_key)):
    if not PICKS_CACHE["last_update"] or datetime.fromisoformat(PICKS_CACHE["last_update"].replace("Z","")) < datetime.utcnow() - timedelta(minutes=15):
        refresh_cache()
    return PICKS_CACHE

@app.get("/stats", summary="Métricas de rendimiento", tags=["Analytics"])
def premium_stats(api_key: str = Depends(verify_api_key)):
    return get_metrics()

@app.get("/history", summary="Historial paginado", tags=["Analytics"])
def get_history(limit: int = 20, offset: int = 0, api_key: str = Depends(verify_api_key)):
    try:
        import sqlite3
        db_path = os.getenv("DATABASE_URL", "data/premium_history.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM picks ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))
        rows = [dict(row) for row in cur.fetchall()]
        conn.close()
        return {"total": len(rows), "records": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/backtest/settle/{pick_id}", summary="Validar resultado de pick", tags=["Analytics"])
def settle_pick(pick_id: int, result: float = 0.0, profit_loss: float = 0.0, api_key: str = Depends(verify_api_key)):
    try:
        import sqlite3
        db_path = os.getenv("DATABASE_URL", "data/premium_history.db")
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE picks SET status='settled', result=?, profit_loss=? WHERE id=?", (result, profit_loss, pick_id))
        conn.commit()
        conn.close()
        return {"status": "updated", "pick_id": pick_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api:app", host="0.0.0.0", port=8000, reload=True)
