#!/usr/bin/env bash
set -euo pipefail
cd /Users/mac/projects/survivor-ligamx-bot
source .venv/bin/activate

LOG="logs/cron.log"
mkdir -p logs

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 🔄 Inicio ciclo" >> "$LOG"
./run_bot.sh >> "$LOG" 2>&1 || echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠️ Error en run_bot" >> "$LOG"

# Notificar según lógica del PASO 1
python3 src/telegram_notifier.py >> "$LOG" 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ Fin ciclo" >> "$LOG"
echo "---" >> "$LOG"
