#!/usr/bin/env bash
# run_bot_prod.sh — Ejecución programada (cron) del bot, con log y Telegram.
# Portable: usa la carpeta del script (sin rutas absolutas).
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"
mkdir -p logs

# Activar venv si existe (opcional).
if [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

LOG="logs/cron.log"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 🔄 Inicio ciclo" >> "$LOG"
./run_bot.sh --telegram >> "$LOG" 2>&1 || echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠️ Error en run_bot" >> "$LOG"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ Fin ciclo" >> "$LOG"
echo "---" >> "$LOG"
