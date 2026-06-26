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
- `scripts/run_market_watchdog_local.sh`: lanzador local del watchdog (cron/launchd).

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
