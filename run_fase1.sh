#!/usr/bin/env bash
echo "📊 FASE 1: Dashboard + Backtesting"
python3 scripts/dashboard_odds.py
python3 src/backtesting.py --data data_kiro/ligamx_odds_clean.csv
echo "✅ Revisa: reports/dashboard_odds.html y reports/backtesting_resultados.csv"
