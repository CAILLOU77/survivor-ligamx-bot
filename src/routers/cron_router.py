from fastapi import APIRouter

try:
    from src.backtest_engine import run_backtest
except ImportError:  # pragma: no cover
    from backtest_engine import run_backtest  # type: ignore

router = APIRouter()


@router.post("/cron/backtest", summary="Validación diaria del modelo (real, sin inventar)")
def cron_backtest():
    """Corre la validación real del modelo vs resultados de ESPN (cron diario)."""
    return {"status": "success", "validacion": run_backtest()}
