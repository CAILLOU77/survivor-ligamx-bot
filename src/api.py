from fastapi import FastAPI, Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import HTTPException, Header, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import os
from datetime import datetime
from typing import Optional

# Cargar .env en local (en Render/prod las vars vienen del entorno; esto es no-op).
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # pragma: no cover - dotenv es opcional
    pass

from src.database import init_db, get_metrics, get_history, settle_pick

# Sin default público: la clave DEBE venir del entorno (Render / GitHub secret).
# Si no está configurada, los endpoints protegidos fallan en cerrado (503).
API_KEY = os.getenv("API_KEY", "").strip()

def verify_api_key(x_api_key: Optional[str] = Header(None)):
    if not API_KEY:
        raise HTTPException(
            status_code=503,
            detail="API_KEY no configurada en el servidor",
        )
    if not x_api_key or x_api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Clave API inválida o faltante")
    return x_api_key

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Survivor LigaMX API Premium", version="2.1.0", docs_url="/docs")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
from src.routers.cron_router import router as cron_router
app.include_router(cron_router)
from src.routers.predicciones import router as predicciones_router
app.include_router(predicciones_router)
from src.routers.api_ligamx import router as api_ligamx_router
app.include_router(api_ligamx_router)
init_db()

# NOTA: el viejo path de "picks de alto EV" leia un parquet de momios scrapeados
# (data_kiro/ligamx_odds_clean.parquet) que NO existe en produccion (Render) y
# dependia de momios. El proyecto pivoto a predicciones reales (ESPN + Poisson).
# Los endpoints /predicciones y /survivor (src/routers/predicciones.py) son la
# fuente real; /picks/latest queda como alias DEPRECADO que reexpone esa data.


def _predicciones_reales() -> dict:
    """Obtiene las predicciones reales (ESPN + Poisson) usando la cache del router."""
    try:
        from src.routers.predicciones import _obtener as _obtener_predicciones
        return _obtener_predicciones()
    except Exception as exc:  # pragma: no cover - fallback defensivo
        return {"pronosticos": [], "fuente_datos": None, "generado_utc": None,
                "decision": "INFORMATIVO / REVISIÓN HUMANA", "error": str(exc)}

@app.get("/health", summary="Estado del sistema", tags=["Status"])
def health():
    return {"status": "ok", "version": "2.1.0-premium", "timestamp": datetime.utcnow().isoformat()}

@limiter.limit("10/minute")
@app.get("/picks/latest", summary="(Deprecado) Predicciones reales ESPN+Poisson", tags=["Picks"])
def get_picks(request: Request, api_key: str = Depends(verify_api_key)):
    """
    DEPRECADO: el viejo path de 'picks de alto EV' dependia de momios scrapeados
    inexistentes en produccion. Ahora reexpone las predicciones REALES del modelo
    (ESPN + Poisson). Usa directamente /predicciones y /survivor.
    """
    data = _predicciones_reales()
    return {
        "status": "deprecated",
        "message": "Usa /predicciones (1X2/OU/BTTS por partido) y /survivor (mejor no-perder). Datos reales de ESPN + modelo Poisson.",
        "last_update": data.get("generado_utc"),
        "fuente_datos": data.get("fuente_datos"),
        "predicciones": data.get("pronosticos", []),
        "decision": data.get("decision"),
    }


@app.post("/alerts/pronosticos", summary="Enviar pronósticos reales por Telegram", tags=["Alerts"])
@limiter.limit("6/minute")
def alerts_pronosticos(request: Request, api_key: str = Depends(verify_api_key)):
    """Genera predicciones reales (ESPN + Poisson) y las envía por Telegram."""
    from src import telegram_pronosticos
    return telegram_pronosticos.enviar_pronosticos()


@app.post("/alerts/high-ev", summary="(Deprecado) Alias → pronósticos reales", tags=["Alerts"])
@limiter.limit("6/minute")
def alerts_high_ev(request: Request, api_key: str = Depends(verify_api_key)):
    """
    Compatibilidad con el workflow auto-alerts. El viejo 'EV>5%' se basaba en
    momios inventados; ahora envía PRONÓSTICOS REALES (ESPN + Poisson).
    """
    from src import telegram_pronosticos
    res = telegram_pronosticos.enviar_pronosticos()
    res["nota"] = "Endpoint deprecado: usa /alerts/pronosticos. Envía predicciones reales."
    return res


@app.post("/alerts/plan", summary="Enviar el plan de temporada Survivor por Telegram", tags=["Alerts"])
@limiter.limit("6/minute")
def alerts_plan(request: Request, api_key: str = Depends(verify_api_key)):
    """
    Construye el plan ÓPTIMO de Survivor para la temporada (qué equipo usar en
    cada jornada) y lo envía por Telegram. Requiere data/calendario.json.
    """
    from src import telegram_pronosticos
    return telegram_pronosticos.enviar_plan()


# ---------------------------------------------------------------------------
# Equipos usados en el Survivor (persisten en la BD; el pick los excluye).
# ---------------------------------------------------------------------------
@app.get("/survivor/usados", summary="Lista de equipos ya usados en el Survivor", tags=["Survivor"])
@limiter.limit("30/minute")
def survivor_usados_listar(request: Request):
    """Equipos que ya gastaste (se excluyen automáticamente del pick y del plan)."""
    try:
        from src.database import get_equipos_usados
        usados = get_equipos_usados()
    except Exception as exc:
        return {"usados": [], "total": 0, "error": str(exc)}
    return {"usados": usados, "total": len(usados),
            "decision": "INFORMATIVO / REVISIÓN HUMANA"}


@app.post("/survivor/usados", summary="Marcar un equipo como usado", tags=["Survivor"])
@limiter.limit("30/minute")
def survivor_usados_agregar(request: Request, equipo: str, api_key: str = Depends(verify_api_key)):
    """Registra el equipo que escogiste esta jornada para que ya no se sugiera."""
    from src.database import add_equipo_usado, get_equipos_usados
    if not equipo or not equipo.strip():
        raise HTTPException(status_code=400, detail="Falta el parámetro 'equipo'.")
    agregado = add_equipo_usado(equipo)
    return {"equipo": equipo.strip(), "agregado": agregado,
            "ya_estaba": not agregado, "usados": get_equipos_usados()}


@app.delete("/survivor/usados", summary="Quitar un equipo usado", tags=["Survivor"])
@limiter.limit("30/minute")
def survivor_usados_quitar(request: Request, equipo: str, api_key: str = Depends(verify_api_key)):
    """Quita un equipo de la lista de usados (por si te equivocaste al registrarlo)."""
    from src.database import remove_equipo_usado, get_equipos_usados
    filas = remove_equipo_usado(equipo)
    return {"equipo": equipo.strip(), "quitado": bool(filas), "usados": get_equipos_usados()}


@app.post("/survivor/usados/reset", summary="Reiniciar equipos usados (nueva temporada)", tags=["Survivor"])
@limiter.limit("10/minute")
def survivor_usados_reset(request: Request, api_key: str = Depends(verify_api_key)):
    """Vacía la lista de usados (úsalo al empezar una temporada nueva)."""
    from src.database import clear_equipos_usados
    borrados = clear_equipos_usados()
    return {"borrados": borrados, "usados": []}


# ---------------------------------------------------------------------------
# Webhook de Telegram: operar el bot por chat (/usado, /usados, /pick, ...).
# ---------------------------------------------------------------------------
@app.post("/telegram/webhook", summary="Webhook de comandos de Telegram", tags=["Telegram"])
@limiter.limit("30/minute")
async def telegram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_telegram_bot_api_secret_token: Optional[str] = Header(None),
):
    """
    Recibe updates de Telegram y responde a comandos del DUEÑO (/usado, /usados,
    /quitar, /reset, /pick, /ayuda). Solo atiende el TELEGRAM_CHAT_ID configurado
    y, si hay TELEGRAM_WEBHOOK_SECRET, valida el header secreto de Telegram.
    """
    # 1) Validación del secreto del webhook (si está configurado).
    secreto = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if secreto and x_telegram_bot_api_secret_token != secreto:
        raise HTTPException(status_code=403, detail="Secreto de webhook inválido")

    try:
        update = await request.json()
    except Exception:
        return {"ok": True}  # ignora payloads no-JSON sin fallar

    from src import telegram_webhook as tw
    from src import telegram_pronosticos as tp

    chat_id, texto = tw.extraer_mensaje(update)

    # 2) Solo el dueño (chat configurado) puede operar.
    chat_cfg = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if chat_cfg and str(chat_id) != chat_cfg:
        return {"ok": True}  # ignora mensajes de otros chats

    if not texto:
        return {"ok": True}

    cmd, arg = tw.parsear_comando(texto)
    if cmd is None:
        return {"ok": True}  # texto normal, no comando

    if cmd in tw.CMDS_PICK:
        # Generación pesada (ESPN+modelo) en segundo plano; responde rápido.
        background_tasks.add_task(tp.enviar_pronosticos)
        tp.enviar_mensaje("🔄 Generando tu pronóstico y pick de la jornada...")
    else:
        tp.enviar_mensaje(tw.responder(cmd, arg))
    return {"ok": True}

@limiter.limit("20/minute")
@app.get("/stats", summary="Métricas de rendimiento", tags=["Analytics"])
def premium_stats(request: Request, api_key: str = Depends(verify_api_key)):
    return get_metrics()

@limiter.limit("20/minute")
@app.get("/history", summary="Historial paginado", tags=["Analytics"])
def get_history_endpoint(request: Request, limit: int = 20, offset: int = 0, api_key: str = Depends(verify_api_key)):
    try:
        rows = get_history(limit, offset)
        return {"total": len(rows), "records": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/backtest/settle/{pick_id}", summary="Validar resultado de pick", tags=["Analytics"])
def settle_pick_endpoint(pick_id: int, result: float = 0.0, profit_loss: float = 0.0, api_key: str = Depends(verify_api_key)):
    try:
        settle_pick(pick_id, result, profit_loss)
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


@app.get("/debug/scraper", summary="Debug: fixtures reales de ESPN", tags=["Debug"])
@limiter.limit("5/minute")
def debug_scraper(request: Request):
    """Diagnóstico de la fuente real: próximos fixtures de Liga MX desde ESPN."""
    try:
        from src import espn_data
        fixtures = espn_data.obtener_fixtures()
        return {
            "status": "success",
            "fuente": "ESPN (site.api.espn.com, mex.1)",
            "total_fixtures": len(fixtures),
            "sample": fixtures[:5],
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/debug/api-response", summary="Debug: estado de fuentes de datos", tags=["Debug"])
@limiter.limit("5/minute")
def debug_api_response(request: Request):
    """
    The Odds API fue descartada (no cubre Liga MX de forma fiable). La fuente
    real es ESPN. Este endpoint reporta cuántos resultados históricos se
    obtienen de la cadena de fuentes (ESPN → TheSportsDB → caché).
    """
    try:
        from src import fuentes_datos
        datos = fuentes_datos.obtener_resultados(meses=2)
        return {
            "status": "success",
            "nota": "The Odds API descartada; fuente real = ESPN. Ver /debug/scraper y /predicciones.",
            "fuente_usada": datos.get("fuente"),
            "total_resultados": datos.get("total"),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api:app", host="0.0.0.0", port=8000, reload=True)
