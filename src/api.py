from fastapi import FastAPI, Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import HTTPException, Header, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import pandas as pd
import os
from datetime import datetime, timedelta
from typing import Optional
from src.poisson_model import calibrate_and_predict
from src.routers.analizar_1x2 import router as analizar_router
from src.market_analyzer import analyze_additional_markets
from src.telegram_alerts import send_high_ev_alerts
from src.database import init_db, save_pick, get_metrics

API_KEY = os.getenv("API_KEY", "survivor-ligamx-premium-2026")

def verify_api_key(x_api_key: Optional[str] = Header(None)):
    if not x_api_key or x_api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Clave API inválida o faltante")
    return x_api_key

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Survivor LigaMX API Premium", version="2.1.0", docs_url="/docs")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.include_router(analizar_router)
from src.routers.cron_router import router as cron_router
app.include_router(cron_router)
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

@limiter.limit("10/minute")
@app.get("/picks/latest", summary="Picks activos (EV>4%)", tags=["Picks"])
def get_picks(request: Request, api_key: str = Depends(verify_api_key)):
    if not PICKS_CACHE["last_update"] or datetime.fromisoformat(PICKS_CACHE["last_update"].replace("Z","")) < datetime.utcnow() - timedelta(minutes=15):
        refresh_cache()
    return PICKS_CACHE

@limiter.limit("20/minute")
@app.get("/stats", summary="Métricas de rendimiento", tags=["Analytics"])
def premium_stats(request: Request, api_key: str = Depends(verify_api_key)):
    return get_metrics()

@limiter.limit("20/minute")
@app.get("/history", summary="Historial paginado", tags=["Analytics"])
def get_history(request: Request, limit: int = 20, offset: int = 0, api_key: str = Depends(verify_api_key)):
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



@app.get("/dashboard", response_class=HTMLResponse, summary="Dashboard visual", tags=["Dashboard"])
def dashboard():
    stats = get_metrics()
    
    html = """<!DOCTYPE html>
<html>
<head>
    <title>Survivor LigaMX Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{ font-family: Arial, sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; background: #f5f5f5; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 10px; margin-bottom: 30px; }}
        .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }}
        .metric {{ background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .metric h3 {{ margin: 0; color: #666; font-size: 14px; }}
        .metric .value {{ font-size: 32px; font-weight: bold; color: #333; margin-top: 10px; }}
        .chart-container {{ background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 20px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>📊 Survivor LigaMX Premium</h1>
        <p>Dashboard de Rendimiento en Vivo</p>
    </div>
    <div class="metrics">
        <div class="metric">
            <h3>Total Picks</h3>
            <div class="value">{total_picks}</div>
        </div>
        <div class="metric">
            <h3>Wins</h3>
            <div class="value">{wins}</div>
        </div>
        <div class="metric">
            <h3>Win Rate</h3>
            <div class="value">{win_rate}%</div>
        </div>
        <div class="metric">
            <h3>Total Profit</h3>
            <div class="value">{total_profit}</div>
        </div>
    </div>
    <div class="chart-container">
        <h3>📈 Rendimiento</h3>
        <canvas id="performanceChart"></canvas>
    </div>
    <script>
        const ctx = document.getElementById('performanceChart').getContext('2d');
        new Chart(ctx, {{
            type: 'bar',
            data: {{
                labels: ['Total Picks', 'Wins', 'Losses'],
                datasets: [{{
                    label: 'Estadísticas',
                    data: [{total_picks}, {wins}, {losses}],
                    backgroundColor: ['#667eea', '#10b981', '#ef4444']
                }}]
            }},
            options: {{
                responsive: true,
                plugins: {{
                    legend: {{ display: false }}
                }}
            }}
        }});
    </script>
    <p><a href="/docs">📚 Ver documentación API</a></p>
</body>
</html>"""
    
    losses = stats['total_picks'] - stats['wins']
    html = html.format(
        total_picks=stats['total_picks'],
        wins=stats['wins'],
        win_rate=f"{stats['win_rate']:.1f}",
        total_profit=f"{stats['total_profit']:.2f}",
        losses=losses
    )
    
    return HTMLResponse(content=html)


@app.post("/update/data", summary="Forzar actualización de datos", tags=["Admin"])
@limiter.limit("2/minute")
def update_data(request: Request, api_key: str = Depends(verify_api_key)):
    """Fuerza la actualización manual de datos"""
    import subprocess
    import sys
    try:
        result = subprocess.run(
            [sys.executable, "src/auto_update.py"],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        return {
            "status": "success" if result.returncode == 0 else "error",
            "message": "Datos actualizados" if result.returncode == 0 else "Error en actualización",
            "output": result.stdout[-500:] if result.stdout else "",
            "errors": result.stderr[-500:] if result.stderr else ""
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




@app.get("/analyze/advanced", summary="Análisis avanzado de mercados", tags=["Analysis"])
@limiter.limit("10/minute")
def analyze_advanced(request: Request, api_key: str = Depends(verify_api_key)):
    """Analiza Handicap Asiático, Goles por Equipo, Marcador Exacto"""
    import subprocess
    import sys
    import json
    try:
        result = subprocess.run(
            [sys.executable, "src/advanced_markets.py"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        
        # Capturar tanto stdout como stderr
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        
        if result.returncode != 0:
            return {
                "status": "error", 
                "message": "Error en análisis", 
                "returncode": result.returncode,
                "stdout": stdout[:500] if stdout else "",
                "stderr": stderr[:500] if stderr else ""
            }
        
        # Buscar JSON en el output
        lines = stdout.split("\n")
        json_start = None
        for i, line in enumerate(lines):
            if line.strip().startswith("["):
                json_start = i
                break
        
        if json_start is not None:
            json_output = "\n".join(lines[json_start:])
            data = json.loads(json_output)
            return {"status": "success", "matches": data}
        else:
            return {
                "status": "warning",
                "message": "No se encontró JSON en el output",
                "stdout": stdout[:500] if stdout else "",
                "stderr": stderr[:500] if stderr else ""
            }
    except Exception as e:
        return {
            "status": "error",
            "message": "Excepción en el endpoint",
            "error": str(e)
        }


@app.get("/debug/jornadas", summary="Debug: ver contenido de jornadas.json", tags=["Debug"])
@limiter.limit("5/minute")
def debug_jornadas(request: Request):
    """Muestra el contenido de jornadas.json para debugging"""
    import json
    try:
        jornadas_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "jornadas.json")
        with open(jornadas_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Contar partidos
        if isinstance(data, list):
            count = len(data)
            sample = data[:2] if data else []
        else:
            partidos = data.get('partidos', [])
            count = len(partidos)
            sample = partidos[:2] if partidos else []
        
        return {
            "status": "success",
            "total_partidos": count,
            "sample": sample,
            "structure": "list" if isinstance(data, list) else "dict"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api:app", host="0.0.0.0", port=8000, reload=True)
