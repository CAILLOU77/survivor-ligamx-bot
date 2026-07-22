# Imagen de producción del bot Survivor Liga MX (Python 3.12).
#
# Modo por defecto: API web (uvicorn), coherente con el Procfile de Render.
# Para el ciclo batch/cron (generar pronósticos + envío a Telegram):
#   docker run --env-file .env <imagen> bash run_bot_prod.sh
#
# Seguridad: corre como usuario sin privilegios (appuser, uid 1000) y el
# .dockerignore deja fuera .env/.git, así que los secretos NUNCA se hornean.
FROM python:3.12-slim

WORKDIR /app

# 1) Dependencias primero → aprovecha la caché de capas cuando solo cambia código.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2) Código fuente (respetando .dockerignore: fuera .env, .git, data/, reports/,
#    logs/, tmp/, __pycache__, docs, etc.).
COPY . .

# 3) Usuario sin privilegios: el contenedor no necesita root para correr uvicorn.
#    Nota: si montas volúmenes bind (./data, ./reports, ./logs) asegúrate de que
#    el directorio del host sea escribible por uid 1000 (p.ej. `chown -R 1000:1000 data`).
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]
