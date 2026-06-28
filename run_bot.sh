#!/usr/bin/env bash
# run_bot.sh — Pipeline REAL del bot Survivor Liga MX (ESPN + Poisson).
# Antes orquestaba el path viejo de momios (scraper/sync_odds_api/IA/...).
# Ahora: baja resultados reales de ESPN y genera pronósticos + pick de Survivor.
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"
mkdir -p reports data

# Cargar variables de entorno si hay .env (Telegram, etc.).
if [ -f ".env" ]; then
  set -a; source .env; set +a
fi

echo "🚀 RUN BOT SURVIVOR LIGA MX (ESPN + Poisson) — $(date)"
echo "=================================================="

# 1) Bajar resultados reales de ESPN (si falla, el motor usa caché/respaldo).
echo "▶️ Bajando resultados de ESPN..."
python3 src/espn_data.py --meses 18 || echo "⚠️ ESPN falló; se usará caché/respaldo."

# 2) Generar pronósticos + pick de Survivor (y Telegram si se pasa --telegram
#    o cualquier argumento extra se reenvía a main.py).
echo "▶️ Generando pronósticos..."
python3 main.py "$@"

echo "🏁 PROCESO COMPLETO"
