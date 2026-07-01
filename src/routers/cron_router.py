from fastapi import APIRouter

try:
    from src.backtest_engine import run_backtest
except ImportError:  # pragma: no cover
    from backtest_engine import run_backtest  # type: ignore

router = APIRouter()


@router.post("/cron/backtest", summary="Validación diaria del modelo (real, sin inventar)")
def cron_backtest():
    """Corre la validación real del modelo vs ESPN y resuelve el historial de pronósticos."""
    resultado = {"status": "success", "validacion": run_backtest()}
    # Resolver el track-record de pronósticos con resultados reales frescos.
    try:
        try:
            import fuentes_datos as fd
            from database import settle_pronosticos
        except ImportError:  # pragma: no cover
            from src import fuentes_datos as fd  # type: ignore
            from src.database import settle_pronosticos  # type: ignore
        datos = fd.obtener_resultados(meses=6)
        resultado["pronosticos_resueltos"] = settle_pronosticos(datos.get("resultados", []))
    except Exception as exc:  # pragma: no cover - no tumbar el cron por esto
        resultado["settle_error"] = str(exc)
    return resultado
