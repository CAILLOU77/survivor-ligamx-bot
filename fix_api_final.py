import pathlib

code = '''from fastapi import FastAPI, HTTPException, Header, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
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
        raise HTTPException(status_code=403, detail="Clave API invalida o faltante")
    return x_api_key

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Survivor LigaMX API Premium", version="2.1.0", docs_url="/docs")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])
app.include_router(analizar_router)
init_db()

PICKS_CACHE = {"status": "inactive", "picks": [], "last_update": None}

def refresh_cache():
    global PICKS_CACHE
    try:
        if not os.path.exists("data_kiro/ligamx_odds_clean.parquet"):
            PICKS_CACHE = {"status": "error", "message": "Data missing"}
            return
        df = pd.read_parquet("data_kiro/ligamx_odds_clean.parquet")
        valid = df[df["vig_pct"] < 15].copy()
        picks_out = []
        for _, row in valid.iterrows():
            pred = calibrate_and_predict(row["momio_1"], row["momio_2"], row["momio_3"])
            if pred["expected_value"] > 0.04 and pred["kelly_stake"] > 0:
                match_id = f"L{row['id_liga']}_M{row['id_mercado']}"
                picks_out.append({
                    "match_id": match_id,
                    "match": match_id,
                    "market": "1 (Local)",
                    "true_prob": round(pred["true_prob"], 4),
                    "expected_value": round(pred["expected_value"], 4),
                    "kelly_stake": round(pred["kelly_stake"], 2),
                    "momio": round(row["momio_1"], 2),
                    "timestamp": str(row["timestamp"])
                })
                try:
                    save_pick(match_id, "1 (Local)", pred["true_prob"], row["momio_1"], pred["expected_value"], pred["kelly_stake"])
                except:
                    pass
        picks_out = sorted(picks_out, key=lambda x: x["expected_value"], reverse=True)[:10]
        PICKS_CACHE = {"status": "active", "last_update": datetime.utcnow().isoformat() + "Z", "picks": picks_out}
    except Exception as e:
        PICKS_CACHE = {"status": "error", "message": str(e), "last_update": None}

@app.get("/health", summary="Estado del sistema", tags=["Status"])
def health():
    return {"status": "ok", "version": "2.1.0-premium", "timestamp": datetime.utcnow().isoformat()}

@app.get("/picks/latest", summary="Picks activos (EV>4%)", tags=["Picks"])
@limiter.limit("10/minute")
def get_picks(request: Request, api_key: str = Depends(verify_api_key)):
    if not PICKS_CACHE["last_update"] or datetime.fromisoformat(PICKS_CACHE["last_update"].replace("Z","")) < datetime.utcnow() - timedelta(minutes=15):
        refresh_cache()
    return PICKS_CACHE

@app.get("/stats", summary="Metricas de rendimiento", tags=["Analytics"])
@limiter.limit("20/minute")
def premium_stats(request: Request, api_key: str = Depends(verify_api_key)):
    return get_metrics()

@app.get("/history", summary="Historial paginado", tags=["Analytics"])
@limiter.limit("20/minute")
def get_history(request: Request, limit: int = 20, offset: int = 0, api_key: str = Depends(verify_api_key)):
    try:
        from src.database import get_db
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM picks ORDER BY id DESC LIMIT %s OFFSET %s", (limit, offset))
            rows = [dict(zip([col[0] for col in cur.description], row)) for row in cur.fetchall()]
        return {"total": len(rows), "records": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/backtest/settle/{pick_id}", summary="Validar resultado de pick", tags=["Analytics"])
@limiter.limit("10/minute")
def settle_pick(request: Request, pick_id: int, result: float = 0.0, profit_loss: float = 0.0, api_key: str = Depends(verify_api_key)):
    try:
        from src.database import get_db
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE picks SET status='settled', result=%s, profit_loss=%s WHERE id=%s", (result, profit_loss, pick_id))
            conn.commit()
        return {"status": "updated", "pick_id": pick_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/dashboard", response_class=HTMLResponse, summary="Dashboard visual", tags=["Dashboard"])
def dashboard():
    stats = get_metrics()
    html_content = f"""
    <html>
    <head><title>Survivor LigaMX Dashboard</title></head>
    <body style="font-family: Arial; max-width: 800px; margin: 50px auto; padding: 20px;">
        <h1 style="color: #667eea;">📊 Survivor LigaMX Premium</h1>
        <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px; margin: 30px 0;">
            <div style="background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                <h3 style="margin: 0; color: #666;">Total Picks</h3>
                <div style="font-size: 32px; font-weight: bold;">{stats['total_picks']}</div>
            </div>
            <div style="background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                <h3 style="margin: 0; color: #666;">Wins</h3>
                <div style="font-size: 32px; font-weight: bold;">{stats['wins']}</div>
            </div>
            <div style="background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                <h3 style="margin: 0; color: #666;">Win Rate</h3>
                <div style="font-size: 32px; font-weight: bold;">{stats['win_rate']:.1f}%</div>
            </div>
            <div style="background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                <h3 style="margin: 0; color: #666;">Total Profit</h3>
                <div style="font-size: 32px; font-weight: bold;">{stats['total_profit']:.2f}</div>
            </div>
        </div>
        <p><a href="/docs">📚 Ver documentacion API</a></p>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api:app", host="0.0.0.0", port=8000, reload=True)
'''

pathlib.Path('src/api.py').write_text(code)
