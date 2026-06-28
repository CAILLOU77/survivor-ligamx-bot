# Changelog — Survivor Liga MX Bot

## v2.0.0 — Pivote a ESPN + Modelo Poisson (datos reales y gratis)

Tras descartar las APIs de momios (sin Liga MX o de pago caro), el proyecto
pivota a **fuentes públicas gratuitas + modelo estadístico**.

### Añadido
- `src/espn_data.py`: ingesta desde la **API pública gratuita de ESPN**
  (`site.api.espn.com`, liga `mex.1`) — fixtures, marcadores finales y tabla.
  Sin key, sin scraping. Alimenta el modelo Poisson con resultados reales.
- `src/fuentes_datos.py`: **redundancia multi-fuente** para no depender de una
  sola. Cadena: ESPN → TheSportsDB (key gratis) → caché local.
- `src/motor_pronosticos.py`: **cerebro** que ata fuentes + Poisson y produce,
  por partido próximo: 1X2, Over/Under, BTTS, marcador probable y el
  "no perder" de Survivor. Incluye `mejor_pick_survivor()`.
- `src/poisson_model.py`: modelo **Poisson/Dixon-Coles** restaurado (calcula
  fuerza ofensiva/defensiva desde resultados) + `calibrate_and_predict()` para
  la web.
- **Web** (`src/api.py`): endpoints nuevos `GET /predicciones` y `GET /survivor`
  con predicciones reales (caché 30 min).

### Corregido
- Reparado el núcleo que se había roto (poisson_model, requirements numpy/
  feedparser). Eliminada basura de scripts en la raíz.

### Datos
- Fuentes: **ESPN** (primaria) + **TheSportsDB** (respaldo), ambas gratuitas.
- Las predicciones NO requieren momios: salen de resultados reales.

## v1.43.1 — Fireworks Client Tests (mock)

### Añadido
- `tests/test_fireworks_client.py`: pruebas unitarias para `fireworks_client`
  con `requests.post` mockeado (sin llamadas reales a la red):
  - `FIREWORKS_ENABLED` por defecto es `false`.
  - Clasificación devuelve datos y agrega `decision_operativa = ESPERAR / NO ENVIAR`.
  - JSON inválido del proveedor se guarda como `raw`.
  - HTTP de error lanza `RuntimeError`.
  - Falta de `FIREWORKS_API_KEY` lanza `RuntimeError`.
- Suite total: **232 tests OK**.

## v1.43.0 — Fireworks AI como clasificador de riesgo opcional

### Añadido
- `src/fireworks_client.py`: clasificador de riesgo opcional vía Fireworks AI
  (rol `BACKUP_AI_CLASSIFIER`). Solo resume noticias, clasifica lesiones,
  detecta cambios de alineación y extrae señales de riesgo.
  - **Desactivado por defecto** (`FIREWORKS_ENABLED=false`).
  - NUNCA genera, cierra ni envía picks. La decisión operativa sigue siendo
    `ESPERAR / NO ENVIAR`.
- `requirements.txt`: se agrega `requests` (dependencia del cliente HTTP).

## v1.42.0 — Team Name Normalizer

### Añadido / Mejorado
- `src/team_normalizer.py`: fuente única de verdad para limpiar, comparar y
  mostrar nombres de equipos Liga MX (alias → forma canónica → display).
  Ej.: `Club América` → `America` → `América`; `Atlético de San Luis` →
  `San Luis`; `Tijuana Xolos de Caliente` → `Tijuana`.
  - Corrige el bug de regex (`bad character range`) reportado previamente.
  - No cambia picks, no envía Telegram, no toca `.env`/`data`/`reports`.
- Integrado en `scripts/import_fbref_schedule.py`, `src/assisted_odds_import.py`
  y `src/sync_odds_api.py` para evitar duplicación de lógica de nombres.
- `tests/test_team_normalizer.py`: cobertura de alias, display y normalización.

## v1.41.1 — Telegram Report Safety Guard

### Añadido / Mejorado
- `src/telegram_notifier.py`: guard de seguridad antes de enviar. Bloquea el
  envío si el reporte no contiene una etiqueta segura permitida o si detecta
  señales operativas prohibidas (`CERRAR`, `ENVIAR PICK`, `APOSTAR`, etc.).
- `scripts/final_security_gate.py`: refuerzo de detección con manejo de
  negaciones (ej. `NO CERRAR` no dispara falso positivo).
- `tests/test_final_security_gate.py` y `tests/test_telegram_notifier_safety.py`:
  nuevas pruebas de la doble capa de seguridad.

## v1.41.0 — Final Operational Safety Gate

### Añadido
- `scripts/final_security_gate.py`: guardia final que valida el reporte antes
  de cualquier salida. Solo permite continuar si conserva una etiqueta segura
  (`ESPERAR / NO ENVIAR` o `READY_FOR_FULL_AUDIT / NO ENVIAR AUTOMÁTICO`) y no
  contiene señales operativas peligrosas. Exit codes: 0 OK, 1 error, 2 sin
  etiqueta segura, 3 señal prohibida.
- `run_bot.sh`: integra el safety gate como paso final del pipeline antes de
  notificar.
- `tests/test_final_security_gate.py`: pruebas del gate.

## v1.40.0 — Liga MX RSS News / Search Monitor

### Añadido
- `scripts/rss_lesiones_ligamx.py`: monitor de actualidad Liga MX vía Google
  News RSS filtrado por sitio (Mediotiempo, ESPN México). Busca lesiones,
  bajas, suspendidos, dudas y boletines médicos; filtra ruido y notas viejas,
  deduplica por similitud y clasifica impacto operativo.
  - Exporta `reports/lesiones_noticias_ligamx.json` (local, no commiteado).
  - No usa credenciales, no scrapea HTML, no hace bypass.
  - Decisión operativa: `ESPERAR / NO ENVIAR`.

## v1.39.2 — Real Caliente Layout Token Parser Fix

### Corregido / Mejorado
- `src/assisted_odds_import.py`: el parser multiline ahora soporta el formato
  REAL de Caliente copiado desde Chrome, que incluye tokens de layout entre los
  datos de partidos:
  - Tokens ignorados transparentemente (no resetean la máquina de estados):
    `★`, `1 >`, `st`, líneas vacías, cabeceras ("Apuestas Fútbol México",
    "Liga MX", "Próximos eventos", etc.).
  - Líneas de hora (`HH:MM`) se capturan como contexto y se asignan al
    siguiente partido detectado.
  - Líneas de fecha (`DD Mon`, ej. "16 Jul") se capturan como contexto y se
    asignan al siguiente partido detectado.
  - `_es_linea_equipo` ahora rechaza layout junk, horas y fechas para evitar
    que se clasifiquen como nombres de equipo.
  - Los 9 partidos reales de Liga MX se parsean correctamente con hora y fecha:
    Necaxa 18:00 16 Jul, Tijuana 20:00 16 Jul, Atlético San Luis 17:00 17 Jul,
    León 19:00 17 Jul, FC Juárez 21:00 17 Jul, Pumas UNAM 12:00 18 Jul,
    Chivas 17:00 18 Jul, Monterrey 19:00 18 Jul, Querétaro FC 21:00 18 Jul.
- `tests/fixtures/caliente_debug_text_real_layout.txt`: fixture con layout real
  (★, 1 >, st, hora, fecha) para 9 partidos.
- `tests/test_assisted_odds_import.py`: 19 tests nuevos para formato real:
  - 2 partidos con layout tokens (hora, fecha, ★, 1 >, st).
  - 9 partidos desde fixture real (verifica pares, momios, hora, fecha).
  - No mezcla mercados futuros/campeón entre layout tokens.
  - Layout tokens no se confunden con nombres de equipo.

### Compatibilidad conservada
- Single-line v1.39.0: sigue funcionando sin cambios.
- Multiline limpio v1.39.1: sigue funcionando sin cambios.
- Filtro de futuros/campeón: funciona con y sin layout tokens.
- `PARSER_NEEDS_REVIEW`: sigue activo para momios sueltos sin partidos.
- Deduplicación: funciona en todos los formatos.

### Sin cambios (restricciones respetadas)
- **NO** stealth, **NO** proxy, **NO** bypass, **NO** automatiza login, **NO**
  guarda credenciales, **NO** imprime secretos.
- **NO** manda Telegram, **NO** cambia/cierra picks.
- Decisión general siempre `ESPERAR / NO ENVIAR`. Nunca marca un pick listo.

## v1.39.1 — Caliente Multiline Parser Fix + Chrome Capture Prep

### Corregido / Mejorado
- `src/assisted_odds_import.py`: parser multiline para texto copiado desde Chrome
  normal de Caliente. Cuando la página se copia manualmente, los momios llegan en
  formato multiline (una línea por token: equipo local, momio, "Empate", momio,
  equipo visitante, momio). El parser original solo soportaba single-line
  (`HH:MM DD Mon Local MOMIO Empate MOMIO Visitante MOMIO`).
  - Máquina de estados de 6 pasos que detecta la secuencia:
    `EQUIPO → MOMIO → Empate/Draw/X → MOMIO → EQUIPO → MOMIO`.
  - Filtra mercados de campeón/futuros (keywords: "Ganador", "Champion",
    "Título", "Futuro", etc.) para no mezclarlos con partidos 1X2.
  - Si el parser single-line no detecta eventos, intenta el multiline.
  - Nuevo estado `PARSER_NEEDS_REVIEW`: se reporta cuando el texto contiene
    momios americanos pero no se pudieron formar partidos 1X2 completos (antes
    retornaba simplemente `NO_MATCHES_FOUND`).
  - Campo `formato_detectado` en el resultado (`single-line` / `multiline`).
  - Deduplicación funciona igual en ambos formatos.
  - Los 9 partidos reales de Liga MX desde el texto capturado de Caliente se
    parsean correctamente: Necaxa vs Atlante, Tijuana Xolos de Caliente vs
    Tigres UANL, Atlético San Luis vs Cruz Azul, León vs Atlas, FC Juárez vs
    Puebla, Pumas UNAM vs Pachuca, Chivas Guadalajara vs Toluca, Monterrey vs
    Santos Laguna, Querétaro FC vs América.
- `scripts/assisted_caliente_odds.py`: bump de referencia a v1.39.1.
- `tests/fixtures/caliente_debug_text_multiline.txt`: fixture de texto multiline
  con los 9 partidos reales de Liga MX (formato Chrome normal de Caliente).
  Movido desde `reports/` para respetar que `reports/` permanece ignorado.
- `tests/test_assisted_odds_import.py`: tests nuevos para:
  - Parser multiline con 1 partido (Necaxa/-125/Empate/+260/Atlante/+275).
  - Parser multiline con 9 partidos reales (verifica pares y momios).
  - No mezcla mercados de campeón/futuros.
  - `PARSER_NEEDS_REVIEW` cuando hay momios sueltos sin partidos completos.
  - Deduplicación multiline.
  - Single-line sigue funcionando (regresión).
  - Reporte mantiene `ESPERAR / NO ENVIAR`.
  - Reporte no imprime secretos.
  - JSON export funciona con multiline.

### Sin cambios (restricciones respetadas)
- **NO** stealth, **NO** proxy, **NO** bypass, **NO** automatiza login, **NO**
  guarda credenciales, **NO** imprime secretos.
- **NO** manda Telegram, **NO** cambia/cierra picks.
- Decisión general siempre `ESPERAR / NO ENVIAR`. Nunca marca un pick listo.

## v1.39.0 — Assisted Sportsbook Odds Import

### Añadido
- `src/assisted_odds_import.py` + `scripts/assisted_caliente_odds.py`: importación
  **ASISTIDA POR USUARIO** de momios 1X2 Liga MX desde un sportsbook (probado con
  Caliente Liga MX). El navegador se abre **visible** (Playwright persistent
  context); el usuario completa **manualmente** cualquier verificación/login y el
  script solo lee el **texto visible** tras presionar ENTER.
  - Parser de eventos con patrón
    `HH:MM DD Mon Local MOMIO Empate MOMIO Visitante MOMIO`
    (ej. `19:00 16 Jul Necaxa -125 Empate +260 Atlante +275`). Extrae fecha, hora,
    equipo_local, equipo_visitante, momio_local, momio_empate y momio_visitante.
  - Diseño **anti-mezcla**: la clase de nombre de equipo excluye dígitos y signos
    `+/-` y no cruza saltos de línea; con `re.finditer` cada evento se extrae de
    forma independiente, así un bloque gigante de DOM no combina partidos
    (p. ej. no mezcla América/Atlas con Necaxa/Atlante).
  - Validación de **momios americanos** (`+120`, `-125`, …; magnitud ≥ 100),
    deduplicación por (local, visitante, fecha, hora) ignorando acentos/mayúsculas,
    y estado `NO_MATCHES_FOUND` cuando no hay eventos válidos.
  - Exporta JSON a `reports/momios_liga_mx.json`, guarda el texto de debug en
    `reports/caliente_debug_text.txt` y genera el reporte
    `reports/assisted_odds_import_ultimo.txt`. El reporte solo muestra el **host**
    de la URL (nunca query/llaves) y mantiene la decisión `ESPERAR / NO ENVIAR`.
  - CLI con `--url` (default Caliente), `--debug-file` (reparsear texto ya
    capturado sin abrir navegador), `--user-data-dir`, `--esperados` y `--timeout`.
    Playwright se importa de forma **perezosa** (compila/corre `--help` y tests sin
    tenerlo instalado).
- `tests/test_assisted_odds_import.py`: parser con 9 partidos reales del texto de
  Caliente, no mezcla de pares en bloque gigante, momio inválido descartado,
  duplicados deduplicados, reporte sin secretos, reporte mantiene
  `ESPERAR / NO ENVIAR`, y garantías sobre el código fuente (no stealth, no proxy,
  no automatiza login, no Telegram, no cambia picks, navegador visible).
- `.gitignore` ampliado: nunca se commitean el perfil persistente de Playwright,
  `reports/caliente_debug_text.txt`, `reports/momios_liga_mx.json` ni
  `reports/assisted_odds_import_ultimo.txt`.

### Sin cambios (restricciones respetadas)
- **NO** stealth, **NO** playwright-stealth, **NO** proxy, **NO** bypass de
  firewall/captcha/login/verificación, **NO** automatiza login, **NO** guarda
  credenciales, **NO** imprime secretos.
- **NO** manda Telegram, **NO** cambia/cierra picks, **NO** usa cierre operativo.
- Decisión general siempre `ESPERAR / NO ENVIAR`. Nunca marca un pick listo.

## v1.38.0 — Pre-Match Recheck Scheduler

### Añadido
- `src/prematch_recheck.py` + `scripts/prematch_recheck_scheduler.py`: programador/
  checklist **local** de revisiones pre-partido según la distancia al kickoff.
  - Ventanas por partido: `UPCOMING`, `DUE_T48`, `DUE_T24`, `DUE_T6`, `DUE_T2`,
    `DUE_T60`, `LIVE_OR_LOCKED`, `UNKNOWN_TIME`.
  - Checklist específico por ventana (T-48h, T-24h, T-6h, T-2h, T-60m).
  - Entradas locales: `data/jornadas.json` (si falta, no rompe), API Health Matrix
    (`api_role_router.build_matrix`) y, opcionalmente, Data Confidence como contexto.
  - API-Football `PLAN_BLOCKED_2026` agrega warning de buscar alternativa de
    alineaciones/noticias; `CONFIGURED_UNKNOWN` mantiene `RECHECK_BEFORE_MATCH`;
    no rota llave por plan/temporada/quota/auth.
  - CLI determinístico con `--now` para pruebas. Genera/imprime
    `reports/prematch_recheck_ultimo.txt`.
  - Decisión general: `ESPERAR / NO ENVIAR`. No marca `READY_FOR_FULL_AUDIT` aquí
    (eso requiere mercado real 9/9 + Data Confidence HIGH en la auditoría final).
- `tests/test_prematch_recheck.py`: clasificación de las 8 ventanas (incluyendo
  bordes), parseo de kickoff, warning de PLAN_BLOCKED_2026, RECHECK en
  CONFIGURED_UNKNOWN, tolerancia a `jornadas.json` faltante, trío no activo,
  reporte sin secretos ni cierre automático, y generación del reporte vía CLI.

### Sin cambios (restricciones respetadas)
- No hace llamadas externas, no manda Telegram, no cambia/cierra picks, no activa
  Cerebras/OpenRouter/Fireworks, no crea launchd/cron, no imprime secretos.
- No cambia `run_bot.sh`, `market_watchdog` ni la lógica de pick. No usa cierre
  operativo automático.

## v1.37.0 — Data Confidence Score / Final Audit Readiness

### Añadido
- `src/data_confidence.py` + `scripts/final_audit_readiness.py`: sistema **local**
  que mide si el bot tiene suficiente información real para pasar a auditoría final.
  - Combina entradas locales: API Health Matrix (`api_role_router.build_matrix`),
    Market Watchdog (`data/watchdog_state.json`), FBref local (CSV/comparación) y
    noticias locales (`data/noticias_ligamx.txt`). No hace llamadas externas.
  - Genera/imprime `reports/data_confidence_ultimo.txt`.
  - Scoring: mercado real 9/9 `+35` / 1–8 `+15` / 0/9 `-40`; movimiento `+10`;
    API-Football `CONFIGURED_UNKNOWN +5` (RECHECK_BEFORE_MATCH) / `PLAN_BLOCKED_2026 -20`
    (warning) / `MISSING_ENV -15`; FBref `+10`; noticias `+10`; Groq `+5`; Gemini `+5`;
    Cerebras/OpenRouter/Fireworks `0` (DISABLED_BY_CONFIG).
  - Clasificación: `<40` LOW, `40–69` MEDIUM, `>=70` HIGH.
  - Decisión: `ESPERAR / NO ENVIAR` salvo score `>=70` **y** mercado real 9/9, que
    marca `READY_FOR_FULL_AUDIT / NO ENVIAR AUTOMÁTICO`. **Nunca `CERRAR`** y nunca
    `READY` si el mercado no es 9/9. Mercado 0/9 fuerza `ESPERAR / NO ENVIAR`.
- `tests/test_data_confidence.py`: 0/9 fuerza ESPERAR; 9/9+score alto permite READY;
  clasificación LOW/MEDIUM/HIGH; PLAN_BLOCKED_2026 resta y avisa; CONFIGURED_UNKNOWN
  suma poco + RECHECK; FBref/Groq/Gemini suman; trío no activo; reporte sin secretos
  ni `CERRAR`; tolerancia a archivos faltantes.

### Sin cambios (restricciones respetadas)
- No toma/cierra picks, no manda Telegram, no activa proveedores nuevos, no imprime
  secretos, no hace llamadas externas obligatorias en tests.
- No cambia `run_bot.sh`, `market_watchdog` ni la lógica de pick. No usa `CERRAR`.

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
