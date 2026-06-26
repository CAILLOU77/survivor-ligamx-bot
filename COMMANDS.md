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

## API Health Matrix (v1.36.0)

Inventario local que ordena todas las APIs por función (rol), estado y uso
operativo. **No toma picks, no manda Telegram, no activa proveedores nuevos, no
imprime secretos y no hace llamadas externas.**

```bash
python3 scripts/api_health_matrix.py
```

Imprime y guarda `reports/api_health_matrix_ultimo.txt`. Reglas clave:

- The Odds API (`MARKET_TRUTH`): `ODDS_MARKETS=h2h,totals,spreads`; BTTS/Draw No
  Bet solo si el endpoint los soporta; HTTP 422 = `UNSUPPORTED_MARKET_CONFIG`
  (no es fallo de llave).
- API-Football (`TEAM_NEWS_LINEUPS`): bloqueo de temporada 2026 por plan =
  `PLAN_BLOCKED_2026`; **no** rota llave por plan/temporada/quota/auth (solo por
  fallo técnico real); marca `RECHECK_BEFORE_MATCH` (T-48h, T-24h, T-6h, T-2h, T-60m).
- Cerebras/OpenRouter/Fireworks: `DISABLED_BY_CONFIG` (no se activan).

El reporte termina con `DECISIÓN` y mantiene `ESPERAR / NO ENVIAR`.

## Data Confidence Score / Final Audit Readiness (v1.37.0)

Mide localmente si el bot tiene suficiente información real para pasar a auditoría
final. Combina la API Health Matrix, el estado del Market Watchdog
(`data/watchdog_state.json`), salidas locales de FBref y noticias locales.
**No toma/cierra picks, no manda Telegram, no activa APIs, no hace llamadas
externas, no imprime secretos y nunca usa `CERRAR`.**

```bash
python3 scripts/final_audit_readiness.py
```

Imprime y guarda `reports/data_confidence_ultimo.txt`. Scoring resumido:

- Mercado real 9/9 `+35` · 1–8 `+15` · 0/9 `-40` (fuerza `ESPERAR / NO ENVIAR`).
- Movimiento de mercado presente `+10`.
- API-Football: `CONFIGURED_UNKNOWN` `+5` (con `RECHECK_BEFORE_MATCH`),
  `PLAN_BLOCKED_2026` `-20` (warning), `MISSING_ENV` `-15`. Nunca cierra solo.
- FBref local `+10` · Noticias locales `+10`.
- Groq `+5` · Gemini `+5` · Cerebras/OpenRouter/Fireworks `0` (DISABLED_BY_CONFIG).

Clasificación: `<40` LOW · `40–69` MEDIUM · `>=70` HIGH. Decisión:
`ESPERAR / NO ENVIAR` salvo score `>=70` **y** mercado real `9/9`, donde marca
`READY_FOR_FULL_AUDIT / NO ENVIAR AUTOMÁTICO`. Nunca `READY` si el mercado no es 9/9.

## Pre-Match Recheck Scheduler (v1.38.0)

Programador/checklist **local** para revisiones pre-partido. Según la distancia al
kickoff indica qué ventana de revisión toca y qué checklist seguir.
**No hace llamadas externas, no manda Telegram, no cambia/cierra picks, no activa
APIs nuevas, no imprime secretos, no usa cierre automático y no crea launchd/cron.**

```bash
# Usa la hora actual
python3 scripts/prematch_recheck_scheduler.py --jornada 1

# Determinístico (pruebas)
python3 scripts/prematch_recheck_scheduler.py --jornada 1 --now "2026-07-16T12:00:00"
```

Imprime y guarda `reports/prematch_recheck_ultimo.txt`. Ventanas por partido:
`UPCOMING`, `DUE_T48`, `DUE_T24`, `DUE_T6`, `DUE_T2`, `DUE_T60`, `LIVE_OR_LOCKED`,
`UNKNOWN_TIME` (falta fecha/hora usable). Si `data/jornadas.json` falta, no rompe.
API-Football `PLAN_BLOCKED_2026` agrega warning de buscar alternativa de
alineaciones/noticias; `CONFIGURED_UNKNOWN` mantiene `RECHECK_BEFORE_MATCH`. La
decisión general se mantiene en `ESPERAR / NO ENVIAR`.

## Tests

```bash
python3 -m unittest discover -s tests
# o por módulo:
python3 -m unittest tests.test_market_watchdog
python3 -m unittest tests.test_import_fbref_schedule
python3 -m unittest tests.test_api_role_router
python3 -m unittest tests.test_data_confidence
python3 -m unittest tests.test_prematch_recheck
```
