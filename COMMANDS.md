# Comandos — Survivor Liga MX Bot

Todos los comandos se ejecutan desde la raíz del proyecto. Requieren un archivo
`.env` con las llaves necesarias (nunca se versiona).

## Bot completo

```bash
./run_bot.sh
```

Ejecuta toda la cadena: normalizar jornada, sincronizar momios reales, noticias
IA, riesgo, reglas, auditoría, pick ajustado, **auditor pre-cierre (Real Data
Gate)**, lectura de mercado, presupuesto de APIs y reporte/Telegram final.

## Estado de mercado (sin gastar API)

```bash
python3 src/market_status.py
```

## Presupuesto de APIs

```bash
python3 src/api_budget.py report
```

## Market Watchdog (v1.32.0 + v1.33.0 + v1.34.0)

Vigía ligero e independiente del mercado de la jornada actual. **No corre el bot
completo, no cierra ni envía picks.**

- **Disponibilidad (v1.32.0):** avisa por Telegram solo cuando la disponibilidad
  de mercado cambia de forma significativa (evita spam). Mercado completo marca
  `READY_FOR_FULL_AUDIT`, nunca `CERRAR`. Etiquetas: `CERRAR / ESPERAR / CAMBIAR / NO ENVIAR`.
- **Movimiento 1X2 (v1.33.0):** snapshots 1X2, probabilidad implícita (sin vig),
  clasificación NORMAL/IMPORTANTE/DRASTICO y cambio de favorito.
- **Multi-mercado (v1.34.0):** además de 1X2/Moneyline, monitorea cuando The Odds
  API los publica:
  - **Over/Under** (preferente 2.5): movimiento de probabilidad implícita.
  - **BTTS / Ambos Anotan** (Sí/No): movimiento de probabilidad implícita.
  - **Hándicap / Spread**: cambio de línea y/o de precio.
  - **Draw No Bet / Empate No Acción**: movimiento de probabilidad implícita.
  - Mercado opcional ausente → se reporta `mercado no disponible` y se continúa.
  - Clasificación: `NORMAL` (<5 pts), `IMPORTANTE` (5-8), `DRASTICO` (>=8),
    `CRITICO` (flip de favorito/lado, flip Over/Under o BTTS, o movimiento mayor
    de línea de hándicap).
  - Telegram para `DRASTICO`/`CRITICO`; `IMPORTANTE` solo con `--telegram-importante`.
  - Anti-duplicado: no reenvía el mismo movimiento salvo que empeore materialmente.
  - Etiqueta de estas alertas: `AUDITAR / NO ENVIAR AUTOMÁTICO`, nunca `CERRAR`.

**Interpretación Survivor:** 1X2/ML es el mercado primario; Over/Under y BTTS son
contexto de volatilidad/riesgo; Hándicap y Draw No Bet son señales de
fuerza/contexto. Ninguno cierra un pick automáticamente.

```bash
# Revisión normal (puede hacer 1 consulta en vivo si budget/cooldown lo permiten)
python3 src/market_watchdog.py

# Solo estado local, sin tocar The Odds API (no gasta presupuesto)
python3 src/market_watchdog.py --no-api

# Saltar cooldown del watchdog (respeta el límite mensual del budget)
python3 src/market_watchdog.py --force

# Calcular y guardar estado, pero sin enviar Telegram
python3 src/market_watchdog.py --no-telegram

# Diagnóstico sin guardar estado ni enviar Telegram
python3 src/market_watchdog.py --dry-run

# Solo disponibilidad, sin seguimiento de movimiento de mercados
python3 src/market_watchdog.py --no-movimiento

# También enviar Telegram para movimientos IMPORTANTES (5-8 pts)
python3 src/market_watchdog.py --telegram-importante

# Cambiar la línea de Over/Under monitoreada (default 2.5)
python3 src/market_watchdog.py --totals-line 3.0
```

Variables de entorno relevantes:

- `ODDS_WATCHDOG_MIN_INTERVAL_MINUTES`: cooldown del watchdog (default `180`).
- `ODDS_WATCHDOG_TELEGRAM_IMPORTANTE`: `1` para incluir IMPORTANTE en Telegram.
- `ODDS_WATCHDOG_TOTALS_LINE`: línea de Over/Under preferida (default `2.5`).
- `ODDS_MARKETS` (de `sync_odds_api`): default operativo recomendado
  `h2h,totals,spreads`. **BTTS** y **Draw No Bet** son opcionales y solo deben
  añadirse si el proveedor/endpoint los soporta para Liga MX (pedir mercados no
  soportados puede provocar **HTTP 422**). Si un mercado no llega, el watchdog
  reporta `mercado no disponible` sin romper.
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`: destino de las alertas Telegram.

Archivos que produce (en carpetas locales ignoradas por git):

- `data/watchdog_state.json`: último estado (disponibilidad + snapshots
  multi-mercado `mercados_baseline` y registro anti-duplicado `mercados_alertas`).
- `reports/market_watchdog_ultimo.txt`: reporte legible de la última corrida.

## Market Watchdog launcher local (cron/launchd)

```bash
# Lanzador para automatización local. Usa $HOME/Projects/survivor-ligamx-bot,
# carga .env si existe y escribe a reports/market_watchdog_launchd.log.
./scripts/run_market_watchdog_local.sh --no-api
```

## FBref Schedule Import Audit (v1.35.0)

Importador/auditor **local** del calendario (Scores & Fixtures) de FBref Liga MX.
**No hace scraping ni red**, no requiere login/cookies, **no sobrescribe**
`data/jornadas.json`, **no cambia picks** y **no manda Telegram**. Solo genera
CSV y reportes locales para auditoría manual.

Primero guarda la página manualmente desde Chrome: *Guardar como → "Página web,
solo HTML" (HTML Only)* en `data/fbref/raw/fbref_ligamx_schedule.html`.

```bash
python3 scripts/import_fbref_schedule.py \
  --html data/fbref/raw/fbref_ligamx_schedule.html \
  --jornada 1 \
  --jornadas-json data/jornadas.json \
  --out-dir data/fbref \
  --reports-dir reports
```

Salidas locales (ignoradas por git, **no se commitean**):

- `data/fbref/fbref_ligamx_schedule_full.csv`
- `data/fbref/fbref_ligamx_schedule_jornada1.csv`
- `reports/fbref_schedule_import_preview.txt`
- `reports/fbref_vs_jornadas_compare.txt`

El reporte de comparación detecta diferencias de hora/estadio (ignorando cambios
menores de artículo/acento en el estadio) y termina con la `DECISIÓN`: no
sobrescribir automáticamente y mantener `ESPERAR / NO ENVIAR` mientras no existan
momios reales. Si falta el HTML o faltan columnas, el script falla con un mensaje
claro (no rompe nada más).

## Tests

```bash
python3 -m unittest discover -s tests
# o por módulo:
python3 -m unittest tests.test_market_watchdog
python3 -m unittest tests.test_import_fbref_schedule
```
