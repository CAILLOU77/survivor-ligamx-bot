from fastapi import FastAPI, Request
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from fastapi import HTTPException, Header, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import os
from datetime import datetime, timezone
from typing import Optional

# Cargar .env en local (en Render/prod las vars vienen del entorno; esto es no-op).
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv es opcional
    pass

from src.database import init_db, get_metrics, get_history, settle_pick
from src.rate_limit import limiter

from pydantic import BaseModel
from typing import Optional, Dict, List


class HealthResponse(BaseModel):
    """Respuesta del healthcheck del sistema."""
    status: str  # "ok" o "degradado"
    version: str
    timestamp: str
    dependencias: Dict[str, str]


class ErrorResponse(BaseModel):
    """Respuesta de error estándar."""
    detail: str
    error_code: Optional[str] = None
    timestamp: Optional[str] = None


class UsadosResponse(BaseModel):
    """Lista de equipos usados en el Survivor."""
    usados: List[str]
    total: int
    decision: str = "INFORMATIVO / REVISIÓN HUMANA"
    error: Optional[str] = None


class UsadoResponse(BaseModel):
    """Resultado de agregar/quitar un equipo usado."""
    equipo: str
    agregado: Optional[bool] = None
    quitado: Optional[bool] = None
    ya_estaba: Optional[bool] = None
    usados: List[str]


class MetricsResponse(BaseModel):
    """Métricas de rendimiento del modelo."""
    total_picks: int
    accuracy_1x2: Optional[float] = None
    accuracy_marcador: Optional[float] = None
    brier_score: Optional[float] = None
    accuracy_por_jornada: List[dict]
    latencia_espn_promedio_ms: Optional[float] = None
    total_predicciones: int
    ultima_actualizacion: Optional[str] = None


class PrediccionItem(BaseModel):
    """Una predicción individual."""
    equipo_local: str
    equipo_visitante: str
    probabilidad_local: float
    probabilidad_empate: float
    probabilidad_visitante: float
    no_perder_pct: Optional[float] = None
    over_pct: Optional[float] = None
    under_pct: Optional[float] = None
    btts_pct: Optional[float] = None


class PrediccionesResponse(BaseModel):
    """Lista de predicciones."""
    pronosticos: List[PrediccionItem]
    fuente_datos: Optional[str] = None
    generado_utc: Optional[str] = None
    decision: str = "INFORMATIVO / REVISIÓN HUMANA"
    error: Optional[str] = None


class CronResponse(BaseModel):
    """Respuesta de un endpoint CRON."""
    status: str = "ok"
    message: Optional[str] = None
    timestamp: str


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


app = FastAPI(title="Survivor LigaMX API Premium", version="2.1.0", docs_url="/docs")
# CORS configurable: en producción usa CORS_ORIGINS="https://tudominio.com,https://otro.com"
# En desarrollo deja vacío (solo localhost) o define CORS_ORIGINS=* explícitamente.
_cors_raw = os.getenv("CORS_ORIGINS", "").strip()
if _cors_raw:
    allow_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]
else:
    # Fallback seguro: no abrir CORS a "*" por defecto en prod.
    allow_origins = (
        ["*"]
        if os.getenv("CORS_ALLOW_ALL", "false").lower() == "true"
        else ["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8000", "null"]
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
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
        return {
            "pronosticos": [],
            "fuente_datos": None,
            "generado_utc": None,
            "decision": "INFORMATIVO / REVISIÓN HUMANA",
            "error": str(exc),
        }


@app.get("/health", response_model=HealthResponse, summary="Estado del sistema", tags=["Status"])
def health():
    """
    Healthcheck del sistema con estado de cada dependencia.
    - base_de_datos: ok si responde, error si no
    - espn: ok si responde, error si no
    - ligamx_api: ok si responde, error si no
    """
    import requests
    deps = {"base_de_datos": "error", "espn": "error", "ligamx_api": "error"}
    status_global = "ok"

    # 1) Base de datos
    try:
        from src.database import get_equipos_usados
        get_equipos_usados()
        deps["base_de_datos"] = "ok"
    except Exception as e:
        status_global = "degradado"
        deps["base_de_datos"] = f"error: {e}"

    # 2) ESPN
    try:
        r = requests.get("https://site.api.espn.com/apis/site/v2/sports/soccer/mex.1/scoreboard", timeout=10)
        if r.status_code == 200:
            deps["espn"] = "ok"
        else:
            deps["espn"] = f"error: HTTP {r.status_code}"
            status_global = "degradado"
    except Exception as e:
        deps["espn"] = f"error: {e}"
        status_global = "degradado"

    # 3) ligamx-api (hermana)
    try:
        r = requests.get("https://ligamx-api.onrender.com/health", timeout=10)
        if r.status_code == 200:
            deps["ligamx_api"] = "ok"
        else:
            deps["ligamx_api"] = f"error: HTTP {r.status_code}"
            status_global = "degradado"
    except Exception as e:
        deps["ligamx_api"] = f"error: {e}"
        status_global = "degradado"

    return {
        "status": status_global,
        "version": "2.1.0-premium",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dependencias": deps,
    }


@app.get("/picks/latest", summary="(Deprecado) Predicciones reales ESPN+Poisson", tags=["Picks"])
@limiter.limit("10/minute")
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


@app.post("/alerts/resumen", summary="Enviar resumen de rentabilidad (track-record) por Telegram", tags=["Alerts"])
@limiter.limit("6/minute")
def alerts_resumen(request: Request, api_key: str = Depends(verify_api_key)):
    """Envía por Telegram el track-record del modelo (aciertos 1X2 y marcador)."""
    from src import telegram_pronosticos

    return telegram_pronosticos.enviar_resumen_rentabilidad()


@app.post("/alerts/momios", summary="Bajar momios (odds-api.io) y reportar cobertura por Telegram", tags=["Alerts"])
@limiter.limit("6/minute")
def alerts_momios(request: Request, solo_si_hay: bool = False, api_key: str = Depends(verify_api_key)):
    """
    Baja los momios de Liga MX (1X2/OU/hándicap), los guarda como caché y envía
    por Telegram un resumen de cobertura. El pick y el plan los usan al instante.

    `solo_si_hay=true` (para el cron): refresca en silencio y solo avisa por
    Telegram si YA hay líneas (evita spam en pretemporada).
    """
    from src import telegram_pronosticos

    return telegram_pronosticos.enviar_momios_estado(solo_si_hay=solo_si_hay)


@app.post("/alerts/recordatorio", summary="Recordar por Telegram que se acerca la jornada", tags=["Alerts"])
@limiter.limit("6/minute")
def alerts_recordatorio(request: Request, dias_antes: int = 1, api_key: str = Depends(verify_api_key)):
    """
    Envía un recordatorio SOLO si la próxima jornada arranca dentro de `dias_antes`
    días. Pensado para un cron diario (no spamea: solo dispara al acercarse).
    """
    from src import telegram_pronosticos

    return telegram_pronosticos.enviar_recordatorio_si_aplica(dias_antes=dias_antes)


@app.post("/fichajes", summary="Importar altas/bajas de un equipo (asistido, sin scraping)", tags=["Datos"])
@limiter.limit("30/minute")
def set_fichajes(
    request: Request, equipo: str, altas: str = "", bajas: str = "", api_key: str = Depends(verify_api_key)
):
    """
    Guarda altas/bajas de un equipo (datos de Transfermarkt que TÚ validas; no se
    scrapea). `altas`/`bajas` separadas por coma. Ej:
    POST /fichajes?equipo=America&altas=Jugador A,Jugador B&bajas=Jugador C
    """
    from src import fichajes

    a = [x for x in altas.split(",") if x.strip()]
    b = [x for x in bajas.split(",") if x.strip()]
    guardado = fichajes.guardar_equipo(equipo, a, b)
    return {"equipo": equipo, "guardado": guardado}


@app.get("/fichajes", summary="Ver altas/bajas de un equipo", tags=["Datos"])
@limiter.limit("30/minute")
def get_fichajes(request: Request, equipo: str):
    """Devuelve las altas/bajas guardadas de un equipo (informativo, público)."""
    from src import fichajes

    return {"equipo": equipo, **fichajes.resumen_equipo(equipo)}


# ---------------------------------------------------------------------------
# Equipos usados en el Survivor (persisten en la BD; el pick los excluye).
# ---------------------------------------------------------------------------
@app.get("/survivor/usados", response_model=UsadosResponse, summary="Lista de equipos ya usados en el Survivor", tags=["Survivor"])
@limiter.limit("30/minute")
def survivor_usados_listar(request: Request):
    """Equipos que ya gastaste (se excluyen automáticamente del pick y del plan)."""
    try:
        from src.database import get_equipos_usados

        usados = get_equipos_usados()
    except Exception as exc:
        return {"usados": [], "total": 0, "error": str(exc)}
    return {"usados": usados, "total": len(usados), "decision": "INFORMATIVO / REVISIÓN HUMANA"}


@app.post("/survivor/usados", response_model=UsadoResponse, summary="Marcar un equipo como usado", tags=["Survivor"])
@limiter.limit("30/minute")
def survivor_usados_agregar(request: Request, equipo: str, api_key: str = Depends(verify_api_key)):
    """Registra el equipo que escogiste esta jornada para que ya no se sugiera."""
    from src.database import add_equipo_usado, get_equipos_usados

    if not equipo or not equipo.strip():
        raise HTTPException(status_code=400, detail="Falta el parámetro 'equipo'.")
    agregado = add_equipo_usado(equipo)
    return {"equipo": equipo.strip(), "agregado": agregado, "ya_estaba": not agregado, "usados": get_equipos_usados()}


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
    elif cmd in tw.CMDS_PLAN:
        background_tasks.add_task(tp.enviar_plan)
        tp.enviar_mensaje("🔄 Armando tu plan de temporada (las 17 jornadas)...")
    elif cmd in tw.CMDS_MOMIOS:
        background_tasks.add_task(tp.enviar_momios_estado)
        tp.enviar_mensaje("🔄 Bajando momios y revisando cobertura...")
    elif cmd in tw.CMDS_SEGUIMIENTO:
        background_tasks.add_task(tp.enviar_seguimiento)
        tp.enviar_mensaje("🔄 Armando tu lista de seguimiento de la jornada...")
    elif cmd in tw.CMDS_PRUEBA:
        background_tasks.add_task(tp.enviar_prueba)
        tp.enviar_mensaje("🔄 Probando la estrategia con torneos pasados (tarda un poco)...")
    elif cmd in tw.CMDS_CONFIANZA:
        background_tasks.add_task(tp.enviar_confianza)
        tp.enviar_mensaje("🔄 Revisando qué tan honesta es la confianza del bot...")
    elif cmd in tw.CMDS_DERROTAS:
        background_tasks.add_task(tp.enviar_derrotas)
        tp.enviar_mensaje("🔄 Revisando en qué partidos cayó el bot y por qué...")
    elif cmd in tw.CMDS_GANADORES:
        background_tasks.add_task(tp.enviar_ganadores)
        tp.enviar_mensaje("🔄 Calculando el 'Survivor perfecto' y comparándolo con el bot...")
    elif cmd in tw.CMDS_ANALISIS:
        background_tasks.add_task(tp.enviar_analisis_jornada)
        tp.enviar_mensaje("🔄 Analizando la jornada: goles, tarjetas, alineaciones y conclusiones...")
    else:
        tp.enviar_mensaje(tw.responder(cmd, arg))
    return {"ok": True}


@app.get("/stats", summary="Métricas de rendimiento", tags=["Analytics"])
@limiter.limit("20/minute")
def premium_stats(request: Request, api_key: str = Depends(verify_api_key)):
    return get_metrics()


@app.get("/history", summary="Historial paginado", tags=["Analytics"])
@limiter.limit("20/minute")
def get_history_endpoint(request: Request, limit: int = 20, offset: int = 0, api_key: str = Depends(verify_api_key)):
    try:
        rows = get_history(limit, offset)
        return {"total": len(rows), "records": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@app.get("/metrics", response_model=MetricsResponse, summary="Métricas de rendimiento del modelo", tags=["Analytics"])
@limiter.limit("10/minute")
def get_metrics_endpoint(request: Request):
    """
    Métricas de negocio del modelo:
    - Accuracy global (1X2 y marcador exacto)
    - Accuracy por jornada (últimas 5)
    - Total de predicciones
    - Brier score (calibración)
    - Latencia promedio de ESPN
    """
    try:
        from src.database import get_metrics as _get_metrics
        base = _get_metrics()
    except Exception:
        base = {"total_picks": 0, "wins": 0, "win_rate": 0.0, "total_profit": 0.0}

    try:
        from src.validacion_modelo import metricas_rendimiento
        extra = metricas_rendimiento()
    except Exception:
        extra = {}

    return {
        "total_picks": base.get("total_picks", 0),
        "accuracy_1x2": extra.get("accuracy_1x2", None),
        "accuracy_marcador": extra.get("accuracy_marcador", None),
        "brier_score": extra.get("brier_score", None),
        "accuracy_por_jornada": extra.get("accuracy_por_jornada", []),
        "latencia_espn_promedio_ms": extra.get("latencia_espn_promedio_ms", None),
        "total_predicciones": extra.get("total_predicciones", base.get("total_picks", 0)),
        "ultima_actualizacion": extra.get("ultima_actualizacion", None),
    }

@app.post("/backtest/settle/{pick_id}", summary="Validar resultado de pick", tags=["Analytics"])
def settle_pick_endpoint(
    pick_id: int, result: float = 0.0, profit_loss: float = 0.0, api_key: str = Depends(verify_api_key)
):
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

    losses = stats["total_picks"] - stats["wins"]
    html = html.format(
        total_picks=stats["total_picks"],
        wins=stats["wins"],
        win_rate=f"{stats['win_rate']:.1f}",
        total_profit=f"{stats['total_profit']:.2f}",
        losses=losses,
    )

    return HTMLResponse(content=html)


@app.get("/debug/jornadas", summary="Debug: ver contenido de jornadas.json", tags=["Debug"])
@limiter.limit("5/minute")
def debug_jornadas(request: Request):
    """Muestra el contenido de jornadas.json para debugging"""
    import json

    try:
        jornadas_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "jornadas.json"
        )
        with open(jornadas_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Contar partidos
        if isinstance(data, list):
            count = len(data)
            sample = data[:2] if data else []
        else:
            partidos = data.get("partidos", [])
            count = len(partidos)
            sample = partidos[:2] if partidos else []

        return {
            "status": "success",
            "total_partidos": count,
            "sample": sample,
            "structure": "list" if isinstance(data, list) else "dict",
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


@app.get("/analisis/jornada", summary="Análisis post-partido de la jornada", tags=["Analisis"])
@limiter.limit("5/minute")
def analisis_jornada(request: Request, fecha: Optional[str] = None, api_key: str = Depends(verify_api_key)):
    """
    Analiza TODOS los partidos YA JUGADOS de la jornada actual (o de `fecha`).
    Incluye: goles, tarjetas, alineaciones, eventos y conclusión IA por partido.
    Compara con picks anteriores del bot.
    """
    try:
        from src import analista_resultados as ar
    except ImportError:  # pragma: no cover
        from src.analista_resultados import analizar_jornada  # type: ignore

    resultado = ar.analizar_jornada(fecha=fecha)
    return {
        "status": "success",
        "total_partidos": len(resultado.get("partidos", [])),
        "partidos": resultado.get("partidos", []),
        "resumen_html": resultado.get("resumen", ""),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.api:app", host="0.0.0.0", port=8000, reload=True)
