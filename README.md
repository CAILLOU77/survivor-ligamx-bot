# Survivor Liga MX Bot

Herramientas para asistir decisiones de **Survivor Liga MX**. El sistema recolecta
datos (momios, calendario, contexto), audita la disponibilidad de mercado real y
genera reportes. **La decisión final (CERRAR) la controla el auditor pre-cierre /
Real Data Gate; las herramientas auxiliares no cierran ni envían picks por su
cuenta.**

> Proyecto local: `~/Projects/survivor-ligamx-bot`.

## Estado operativo actual

- Sin momios reales Liga MX todavía: **0/9**.
- Decisión operativa: **ESPERAR / NO ENVIAR**.
- Equipo bloqueado Survivor: **Toluca**.

## Componentes principales

- `run_bot.sh`: cadena completa del bot (normalización, momios, IA, riesgo,
  auditoría pre-cierre, reporte/Telegram).
- `src/market_watchdog.py`: **Market Watchdog** independiente. Vigila la
  disponibilidad de mercado real y el movimiento de momios multi-mercado
  (1X2/ML, Over/Under, BTTS, Hándicap, Draw No Bet). Nunca emite `CERRAR`; como
  máximo marca `READY_FOR_FULL_AUDIT`. Alertas etiquetadas
  `AUDITAR / NO ENVIAR AUTOMÁTICO`.
- `scripts/import_fbref_schedule.py`: **FBref Schedule Import Audit** (v1.35.0).
  Importador/auditor **local** del calendario de FBref para revisión manual.
- `scripts/api_health_matrix.py` + `src/api_role_router.py`: **API Role Router &
  Health Matrix** (v1.36.0). Inventario local que ordena todas las APIs por
  función, estado y uso operativo. No toma picks, no manda Telegram, no activa
  proveedores nuevos y no imprime secretos.
- `scripts/final_audit_readiness.py` + `src/data_confidence.py`: **Data Confidence
  Score / Final Audit Readiness** (v1.37.0). Mide localmente si hay suficiente
  información real para auditoría final. Nunca `CERRAR`; `READY_FOR_FULL_AUDIT`
  solo con score `>=70` y mercado real `9/9` (y aun así `NO ENVIAR AUTOMÁTICO`).
- `scripts/prematch_recheck_scheduler.py` + `src/prematch_recheck.py`: **Pre-Match
  Recheck Scheduler** (v1.38.0). Checklist local por ventana al kickoff (T-48h…T-60m).
  No red, no Telegram, no picks, no cierre automático, no cron.
- `scripts/run_market_watchdog_local.sh`: lanzador local del watchdog (cron/launchd).

## Data Confidence Score / Final Audit Readiness (v1.37.0)

```bash
python3 scripts/final_audit_readiness.py
```

Combina la API Health Matrix, el Market Watchdog (`data/watchdog_state.json`),
salidas locales de FBref y noticias locales para calcular un score de confianza y
escribe `reports/data_confidence_ultimo.txt`. Con mercado real `0/9` la decisión es
`ESPERAR / NO ENVIAR`. No toma/cierra picks, no manda Telegram, no activa APIs, no
hace llamadas externas, no imprime secretos y nunca usa `CERRAR`.

## API Role Router & Health Matrix (v1.36.0)

Genera un inventario local de roles/estado/uso de cada API (sin secretos, sin red,
sin picks ni Telegram):

```bash
python3 scripts/api_health_matrix.py
```

Escribe `reports/api_health_matrix_ultimo.txt`. Resumen de roles:

| API | Rol | Notas |
|---|---|---|
| The Odds API | `MARKET_TRUTH` | mercado real / momios / movimiento. `ODDS_MARKETS=h2h,totals,spreads`. HTTP 422 = `UNSUPPORTED_MARKET_CONFIG` (no fallo de llave). |
| API-Football | `TEAM_NEWS_LINEUPS` | alineaciones/lesiones/suspendidos. Temporada 2026 por plan = `PLAN_BLOCKED_2026`. No rota llave por plan/temporada/quota/auth. `RECHECK_BEFORE_MATCH` (T-48h…T-60m). |
| FBref / Stathead | `MANUAL_STATS_AUDIT` | manual, sin scraping, sin overwrite. |
| TheSportsDB / ESPN | `SCHEDULE_FALLBACK` | fuente secundaria de calendario. |
| DuckDuckGo / Web News | `NEWS_RISK` | bajas/lesiones/DT/crisis. |
| Groq | `PRIMARY_AI_ANALYSIS` | análisis principal. |
| Gemini | `STABLE_AI_FALLBACK` | respaldo técnico de Groq. |
| Cerebras | `FAST_SECOND_OPINION` | `DISABLED_BY_CONFIG`. |
| OpenRouter | `EMERGENCY_MODEL_ROUTER` | `DISABLED_BY_CONFIG`. |
| Fireworks | `BACKUP_AI_CLASSIFIER` | `DISABLED_BY_CONFIG`. |

Cerebras/OpenRouter/Fireworks permanecen desactivados
(`CEREBRAS_ENABLED=false`, `OPENROUTER_ENABLED=false`, `FIREWORKS_ENABLED=false`)
hasta que el código los soporte; la matriz nunca los activa.

## FBref Schedule Import Audit (v1.35.0)

FBref se usa como **fuente de auditoría manual**, no como verdad automática.

1. Guarda manualmente la página *Scores & Fixtures* de Liga MX desde Chrome:
   *Guardar como → "Página web, solo HTML" (HTML Only)* en
   `data/fbref/raw/fbref_ligamx_schedule.html`.
2. Ejecuta:

   ```bash
   python3 scripts/import_fbref_schedule.py \
     --html data/fbref/raw/fbref_ligamx_schedule.html \
     --jornada 1
   ```

3. Revisa los reportes locales generados en `reports/`:
   - `fbref_schedule_import_preview.txt`
   - `fbref_vs_jornadas_compare.txt`

El importador **no** hace scraping/red, **no** sobrescribe `data/jornadas.json`,
**no** cambia picks y **no** manda Telegram. Compara contra `jornadas.json`
(local/visitante normalizados) y reporta `matched`, `missing` y
`partidos_con_diferencias`, marcando diferencias de hora/estadio (ignorando
cambios menores de artículo/acento). El reporte termina con la `DECISIÓN`: no
sobrescribir automáticamente y mantener `ESPERAR / NO ENVIAR` mientras no existan
momios reales.

## Tests

```bash
python3 -m unittest discover -s tests
```

## Configuración de The Odds API (mercados)

El default operativo **recomendado** para The Odds API es:

```bash
ODDS_MARKETS=h2h,totals,spreads
```

Los mercados **BTTS** y **Draw No Bet** son **opcionales** y solo deben añadirse a
`ODDS_MARKETS` si el proveedor/endpoint realmente los soporta para Liga MX. Si se
piden mercados no soportados, The Odds API puede responder **HTTP 422**; por eso
no van en el default. El watchdog igualmente reporta `mercado no disponible` para
cualquier mercado que no llegue, sin romper.

## Notas de seguridad / repo

- Nunca se commitea `.env`, `data/` (incluye `data/fbref/`, CSV, HTML, caché),
  `reports/`, `results/` ni logs.
- No se imprimen llaves ni secretos.

Más comandos en [`COMMANDS.md`](COMMANDS.md) y el historial en
[`CHANGELOG.md`](CHANGELOG.md).
