from fastapi import APIRouter

router = APIRouter(prefix="/analizar-1x2", tags=["Análisis 1X2"])

@router.get("/datos")
def get_datos():
    return {"msg": "Endpoint de tu otra API listo"}
