#!/usr/bin/env bash
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

mkdir -p reports

TS="$(date +"%Y%m%d-%H%M%S")"
LOG="reports/run-${TS}.log"
REPORTE="reports/reporte_survivor_ultimo.txt"

echo "🚀 RUN BOT SURVIVOR LIGA MX — SATCHEL" | tee "$LOG"
echo "Fecha: $(date)" | tee -a "$LOG"
echo "Proyecto: $PROJECT_DIR" | tee -a "$LOG"
echo "==================================================" | tee -a "$LOG"

if [ ! -f ".env" ]; then
  echo "❌ ERROR: No existe .env" | tee -a "$LOG"
  exit 1
fi

set -a
source .env
set +a

run_step() {
  local name="$1"
  shift

  echo "" | tee -a "$LOG"
  echo "▶️ $name" | tee -a "$LOG"
  echo "--------------------------------------------------" | tee -a "$LOG"

  "$@" 2>&1 | tee -a "$LOG"
  local status=${PIPESTATUS[0]}

  if [ "$status" -ne 0 ]; then
    echo "❌ Falló paso: $name" | tee -a "$LOG"
    return "$status"
  fi

  echo "✅ Paso completado: $name" | tee -a "$LOG"
  return 0
}

run_step "Normalizar jornada" python3 src/normalizar_jornadas.py || exit 1
run_step "Sincronizar momios reales API" python3 src/sync_odds_api.py
run_step "Buscar noticias web Liga MX" python3 src/actualizador_noticias_web.py

run_step "Aplicar noticias con IA" python3 -u src/aplicar_noticias_ia.py
IA_STATUS=$?

if [ "$IA_STATUS" -ne 0 ]; then
  echo "⚠️ IA falló. Intentando con limitador de noticias..." | tee -a "$LOG"

  if [ -f "src/limitar_noticias.py" ]; then
    run_step "Limitar noticias para Groq" python3 src/limitar_noticias.py
    run_step "Reintentar IA con noticias limitadas" python3 -u src/aplicar_noticias_ia.py || exit 1
  else
    echo "❌ No existe src/limitar_noticias.py" | tee -a "$LOG"
    exit 1
  fi
fi

run_step "Calcular riesgo tumba quinielas" python3 src/riesgo_sorpresa.py
run_step "Aplicar reglas Liga MX 2026" python3 src/reglas_ligamx_2026.py
run_step "Auditar data" python3 src/auditor_datos.py
run_step "Correr bot principal" python3 -u main.py || exit 1
run_step "Ajustar pick anti-tumba" python3 src/ajustar_pick_survivor.py --main-log "$LOG" --output-json "data/pick_ajustado_survivor.json" --output-text "reports/pick_ajustado_ultimo.txt"
run_step "Auditor pre-cierre real" python3 src/auditor_pre_cierre.py
run_step "Lectura de mercado" python3 src/lectura_mercado.py
run_step "Generar reporte final" python3 src/generar_reporte.py --main-log "$LOG" --output "$REPORTE"

echo "" | tee -a "$LOG"
echo "▶️ Enviar reporte por Telegram" | tee -a "$LOG"
echo "--------------------------------------------------" | tee -a "$LOG"
python3 src/telegram_notifier.py --report "$REPORTE" 2>&1 | tee -a "$LOG" || true

echo "" | tee -a "$LOG"
echo "🏁 PROCESO COMPLETO" | tee -a "$LOG"
echo "📄 Log completo: $LOG" | tee -a "$LOG"
echo "📋 Reporte final: $REPORTE" | tee -a "$LOG"
