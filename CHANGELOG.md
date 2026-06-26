# Changelog — Survivor Liga MX Bot

## v1.36.0 — API Role Router & Health Matrix

### Añadido
- `src/api_role_router.py` + `scripts/api_health_matrix.py`: inventario local que
  ordena todas las APIs por **función (rol), estado y uso operativo**.
  - Detecta presencia de variables de entorno (`SET`/`MISSING`) **sin imprimir el
    valor** del secreto. No hace llamadas externas.
  - Genera/imprime `reports/api_health_matrix_ultimo.txt`.
  - Roles: The Odds API=`MARKET_TRUTH`, API-Football=`TEAM_NEWS_LINEUPS`,
    FBref=`MANUAL_STATS_AUDIT`, TheSportsDB/ESPN=`SCHEDULE_FALLBACK`,
    DuckDuckGo/Web=`NEWS_RISK`, Groq=`PRIMARY_AI_ANALYSIS`,
    Gemini=`STABLE_AI_FALLBACK`, Cerebras=`FAST_SECOND_OPINION`,
    OpenRouter=`EMERGENCY_MODEL_ROUTER`, Fireworks=`BACKUP_AI_CLASSIFIER`.
  - The Odds API: `ODDS_MARKETS=h2h,totals,spreads` recomendado; BTTS/Draw No Bet
    => `UNSUPPORTED_MARKET_CONFIG`; HTTP 422 clasificado como mercado no soportado
    (no fallo de llave).
  - API-Football: bloqueo por plan/temporada 2026 => `PLAN_BLOCKED_2026`; **no rota
    llave** por plan/temporada/quota/auth (solo por fallo técnico real); marca
    `RECHECK_BEFORE_MATCH` (T-48h, T-24h, T-6h, T-2h, T-60m).
  - Cerebras/OpenRouter/Fireworks: `DISABLED_BY_CONFIG`; la matriz **nunca** los
    activa, aunque exista llave o `*_ENABLED=true`. OpenRouter anota manejar
    `content=None` de forma segura cuando se implemente.
- `tests/test_api_role_router.py`: detección de env sin filtrar secretos, missing,
  `DISABLED_BY_CONFIG`, ODDS_MARKETS recomendado vs `UNSUPPORTED_MARKET_CONFIG`,
  `PLAN_BLOCKED_2026` sin rotación de llave, `RECHECK_BEFORE_MATCH`, trío no
  activado, y reporte que termina en `ESPERAR / NO ENVIAR`.

### Sin cambios (restricciones respetadas)
- No toma picks, no manda Telegram, no activa proveedores nuevos, no imprime
  secretos, no hace llamadas externas obligatorias.
- No cambia `run_bot.sh`, `market_watchdog` ni la lógica de pick. No pone `CERRAR`.

## v1.35.0 — FBref Schedule Import Audit

### Añadido
- `scripts/import_fbref_schedule.py`: importador/auditor **local** del calendario
  (Scores & Fixtures) de FBref Liga MX.
  - Lee un HTML guardado **manualmente** (Chrome → "Página web, solo HTML") desde
    `data/fbref/raw/fbref_ligamx_schedule.html`. **No hace scraping ni red**, no
    usa `requests`/`curl`, no requiere login ni cookies.
  - Flags: `--html`, `--jornada`, `--jornadas-json`, `--out-dir`, `--reports-dir`.
  - Genera (solo local, ignorado por git):
    - `data/fbref/fbref_ligamx_schedule_full.csv`
    - `data/fbref/fbref_ligamx_schedule_jornada1.csv`
    - `reports/fbref_schedule_import_preview.txt`
    - `reports/fbref_vs_jornadas_compare.txt`
  - Normaliza nombres de equipos (UANL→Tigres UANL, UNAM→Pumas UNAM, Santos
    Laguna→Santos, FC Juárez→FC Juarez, Atlético San Luis→Atlético de San Luis,
    America/Club America→América, etc.). Quita acentos solo para comparar.
  - Compara contra `data/jornadas.json` por local/visitante normalizados:
    reporta `matched`, `missing` y `partidos_con_diferencias`; compara fecha/hora
    y estadio de forma flexible (ignora cambios de artículo/acento como
    "Estadio La Corregidora" vs "Estadio Corregidora"; sí reporta hora y estadios
    realmente distintos).
  - El reporte termina con la `DECISIÓN`: **no sobrescribir automáticamente**,
    revisar primero hora/estadio y mantener `ESPERAR / NO ENVIAR` mientras no haya
    momios reales.
  - Errores claros si falta el HTML (explica cómo guardarlo) o si faltan columnas.
- `scripts/run_market_watchdog_local.sh`: lanzador local (cron/launchd) que usa
  `$HOME/Projects/survivor-ligamx-bot` (no Desktop), carga `.env` si existe (sin
  imprimir secretos) y escribe a `reports/market_watchdog_launchd.log`.
- `tests/test_import_fbref_schedule.py`: tests con fixture HTML mínimo embebido
  (extracción de tabla, normalización, filtro de jornada, comparación, diferencia
  de hora, estadio menor ignorado, error por HTML faltante y por columnas faltantes).
- `README.md`.

### Sin cambios (restricciones respetadas)
- FBref es fuente de auditoría manual, **no** verdad automática.
- No sobrescribe `jornadas.json`, no cambia picks, no manda Telegram, no cambia el
  estado operativo a `CERRAR`.
- `.gitignore` ampliado para nunca commitear `data/fbref/`, CSV, HTML, `reports/`,
  `results/`, `data/cache/`, `.env` ni logs.

## v1.34.0 — Multi-Market Watchdog

### Añadido
- Monitoreo **multi-mercado** en `src/market_watchdog.py` (además de 1X2/Moneyline),
  cuando The Odds API los publica:
  - **Totals / Over-Under** (línea preferida 2.5, configurable con `--totals-line`
    o `ODDS_WATCHDOG_TOTALS_LINE`).
  - **BTTS / Ambos Anotan** (Sí/No).
  - **Hándicap / Spread** principal (línea + precio).
  - **Draw No Bet / Empate No Acción**.
- Si un mercado opcional no está disponible, se reporta `mercado no disponible` y
  se continúa de forma segura (no se fuerza ningún mercado).
- Conversión a **probabilidad implícita** (sin vig) por mercado y clasificación:
  - `< 5` pts → `NORMAL` (solo se guarda).
  - `5 a 8` pts → `IMPORTANTE` (Telegram opcional con `--telegram-importante`).
  - `>= 8` pts → `DRASTICO` (Telegram).
  - `CRITICO`: flip de favorito (1X2/DNB/spread), flip de lado (Over/Under, BTTS),
    o movimiento mayor de línea de hándicap (`>= 0.5`). Envía Telegram.
- **Anti-duplicado por mercado**: no reenvía el mismo movimiento salvo escalada de
  severidad, nuevo flip, empeoramiento material (`>= 3` pts) o nuevo movimiento de
  línea de hándicap. Registro en `mercados_alertas`.
- Snapshots multi-mercado en `data/watchdog_state.json` (`mercados_baseline`).
- Las alertas usan la etiqueta `AUDITAR / NO ENVIAR AUTOMÁTICO`, **nunca `CERRAR`**.
- Nueva bandera CLI `--totals-line`.
- Tests nuevos: extracción de mercados opcionales presentes/ausentes, clasificación
  de movimiento Over/Under, BTTS, hándicap (línea) y Draw No Bet, detección de
  flip de lado/favorito, prevención de duplicados y `0/9` sin cambios.

### Interpretación Survivor
- 1X2 / ML: mercado **primario**.
- Over/Under y BTTS: contexto de **volatilidad/riesgo**.
- Hándicap y Draw No Bet: señales de **fuerza/contexto**.

### Sin cambios
- Sigue siendo independiente de `run_bot.sh`.
- No produce picks automáticos; la decisión final (`CERRAR`) la controla
  `auditor_pre_cierre.py` / Real Data Gate.
- `0/9` permanece `ESPERAR / NO ENVIAR`, sin evaluar movimiento ni spam.
- Mercado 1X2 completo marca `READY_FOR_FULL_AUDIT`, no `CERRAR`.

## v1.33.0 — Odds Movement Watchdog

### Añadido
- Seguimiento de **movimiento de momios 1X2** en `src/market_watchdog.py`, una vez
  que existe mercado real (no cambia el comportamiento si el mercado sigue en `0/9`).
  - Guarda snapshots locales de momios 1X2 (local / empate / visitante) dentro de
    `data/watchdog_state.json` (`odds_baseline`) y compara contra el snapshot previo.
  - Convierte momios decimales a **probabilidad implícita** normalizada (sin vig).
  - Clasifica el movimiento por puntos de probabilidad implícita:
    - `< 5` pts → `NORMAL`: solo se guarda, sin Telegram.
    - `5 a 8` pts → `IMPORTANTE`: se reporta; Telegram opcional
      (`--telegram-importante` / `ODDS_WATCHDOG_TELEGRAM_IMPORTANTE=1`).
    - `>= 8` pts → `DRASTICO`: Telegram.
    - **Cambio de favorito** (home/draw/away) → Telegram más fuerte.
  - **Anti-duplicado:** no reenvía el mismo movimiento salvo que escale de severidad,
    cambie de favorito o empeore materialmente (`>= 3` pts adicionales);
    registro en `odds_alertas`.
  - Las alertas de movimiento usan la etiqueta `AUDITAR / NO ENVIAR AUTOMÁTICO`,
    **nunca `CERRAR`**.
- Nuevas banderas CLI: `--no-movimiento` y `--telegram-importante`.
- Tests adicionales en `tests/test_market_watchdog.py`: conversión a probabilidad
  implícita, clasificación de movimiento, extracción 1X2, detección de cambio de
  favorito, decisión de alerta y prevención de duplicados.

### Sin cambios
- Sigue siendo independiente de `run_bot.sh`.
- No produce picks automáticos; la decisión final (`CERRAR`) la controla
  `auditor_pre_cierre.py` / Real Data Gate.
- Mercado completo marca `READY_FOR_FULL_AUDIT`, no `CERRAR`.

## v1.32.0 — Market Watchdog Telegram

### Añadido
- `src/market_watchdog.py`: vigía ligero del mercado real (momios) de la jornada
  actual. Revisa la disponibilidad de mercado **sin correr el bot completo**.
  - Respeta el presupuesto y cooldown de The Odds API vía `api_budget.py`
    (consulta en vivo opcional, una sola llamada, gateada por budget/cooldown).
  - Por defecto puede hacer una consulta en vivo; con `--no-api` usa solo el
    estado local de `data/jornadas.json` (sin gastar API).
  - Persiste el último estado en `data/watchdog_state.json` para enviar Telegram
    **solo en cambios significativos** (sin spam):
    - `0/9 -> >0/9`: alerta "mercado real detectado".
    - parcial creciente: alerta "más mercado disponible".
    - `-> 9/9`: alerta más fuerte y marca `READY_FOR_FULL_AUDIT`.
    - mercado que disminuye: alerta de revisión (`CAMBIAR / REVISAR`).
  - **No cierra ni envía un pick de Survivor automáticamente.** Cuando hay
    mercado completo marca `READY_FOR_FULL_AUDIT`, **nunca `CERRAR`**.
  - La decisión final sigue controlada por `auditor_pre_cierre.py` / Real Data Gate.
  - Usa etiquetas operativas en español: `CERRAR / ESPERAR / CAMBIAR / NO ENVIAR`.
  - No imprime llaves ni secretos.
- `tests/test_market_watchdog.py`: pruebas (stdlib `unittest`) de la lógica pura
  de clasificación, conteo y transiciones de alerta.
- `COMMANDS.md`: referencia de comandos del bot, incluido el watchdog.

### Notas operativas
- Estado actual de Jornada 1: `0/9` mercados reales API → decisión `ESPERAR / NO ENVIAR`.
- El watchdog no usa momios fallback técnicos para cerrar Survivor.
