# Survivor Liga MX Bot

Asistente **informativo** para decisiones de **Survivor Liga MX** y pronósticos
de partidos (1X2, Over/Under, BTTS, marcador). **No apuesta ni envía picks
automáticos**: toda salida es informativa y para revisión humana.

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![CI](https://github.com/BRUCEWAYNE0180/survivor-ligamx-bot/workflows/CI%2FCD/badge.svg)

## Arquitectura (ESPN + Poisson)

Tras descartar las APIs de momios como fuente primaria (no cubrían bien Liga MX
o eran de pago caro), el sistema usa **datos públicos gratuitos + un modelo
estadístico**. Las predicciones salen de **resultados reales**, no de momios.

```
ESPN API (gratis, sin key) ─┐
TheSportsDB (gratis, respaldo) ─┤→ fuentes_datos (redundancia + caché)
                                 │
                                 ▼
                         poisson_model (Dixon-Coles)
                         fuerza de equipos: recencia + shrinkage
                                 │
ESPN fixtures ───────────────────┼──────────────┐
                                 ▼              ▼
                          motor_pronosticos   tabla_posiciones (motivación)
                                 │
              ┌──────────────────┼───────────────────────┐
              ▼                  ▼                        ▼
        /predicciones        /survivor                Telegram
        1X2·O/U·BTTS         pick "no perder"          (informativo)
                                 ▲
                  (opcional) comparador_mercado ── momios reales odds-api.io
```

- **Sin scraping, sin bypass.** Solo APIs públicas/gratuitas.
- **Redundancia:** ESPN → TheSportsDB → caché local.
- **Momios opcionales:** solo para *comparar* el modelo vs el mercado (capa
  apagada por defecto; ver más abajo).

## Endpoints de la web (FastAPI)

| Endpoint | Qué hace |
|---|---|
| `GET /predicciones` | 1X2 / Over-Under / BTTS / marcador por partido próximo |
| `GET /survivor?excluir=America,Toluca` | mejor equipo "no perder" (excluye usados) |
| `GET /tabla` | tabla de ESPN + **motivación** por equipo (zona, vivo/eliminado) |
| `GET /valor` | predicciones + comparación vs **mercado** (si hay momios) |
| `GET /valor/diagnostico` | diagnóstico de la conexión de momios (sin exponer la key) |
| `POST /alerts/pronosticos` | envía el resumen por Telegram (real) |
| `POST /cron/backtest` | **validación real** del modelo vs ESPN (cron diario) |
| `GET /stats`, `GET /history`, `GET /dashboard`, `GET /health`, `GET /docs` | métricas, historial, dashboard, salud, OpenAPI |

## Instalación

Requiere **Python 3.9+**.

```bash
git clone https://github.com/BRUCEWAYNE0180/survivor-ligamx-bot.git
cd survivor-ligamx-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # edita y rellena lo que uses (opcional)
python3 -m pytest tests/        # verificar (todos los tests deben pasar)
```

## Cómo correr (local)

```bash
# Pipeline real: baja resultados de ESPN y genera pronósticos + pick Survivor
bash run_bot.sh

# Solo el orquestador (con Telegram opcional y equipos ya usados):
python3 main.py
python3 main.py --telegram --excluir "America,Toluca"

# Pasos individuales:
python3 src/espn_data.py            # resultados reales -> data/resultados_historicos.json
python3 src/motor_pronosticos.py    # pronósticos + pick Survivor
python3 src/validacion_modelo.py    # ¿qué tan bueno es el modelo? (backtest honesto)
```

## Validación honesta del modelo

`src/validacion_modelo.py` mide el modelo contra resultados **reales** de ESPN
(entrena con lo antiguo, predice lo reciente):

- **accuracy** del pick 1X2 vs el baseline "siempre gana local".
- **Brier** (calibración de probabilidades).

El cron diario `POST /cron/backtest` corre exactamente esa validación (ya **no**
hay métricas inventadas). Referencia reciente: accuracy ~49% vs baseline ~45%.

## Telegram (opcional, informativo)

El resumen de pronósticos se envía con `src/telegram_pronosticos.py` (incluye el
pick de Survivor, 1X2/O-U/BTTS por partido y, si están disponibles, momios/valor
y la motivación del rival). Requiere `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`.

```bash
python3 main.py --telegram          # genera y envía
# o vía la web (lo usa el workflow auto-alerts cada 6h):
#   POST /alerts/pronosticos
```

Sin credenciales, no envía nada (no-op). Nunca dice "apuesta ya".

## Capa de momios (opcional) — odds-api.io

Apagada por defecto. Solo sirve para **comparar el modelo contra el mercado**
(favorito, Over/Under explosivo/cauteloso, hándicap y dónde el modelo ve valor).
El modelo sigue siendo la fuente de verdad.

Para activarla, define en el entorno (p. ej. en Render):

| Variable | Default | Descripción |
|---|---|---|
| `ODDS_API_IO_KEY` | — | key gratis de odds-api.io (requerida para activar) |
| `ODDS_API_IO_LIGA` | `mexico-liga-mx-apertura` | slug de la liga |
| `ODDS_API_IO_MAX_CASAS` | `2` | máx. casas por consulta (límite del tier gratis) |
| `ODDS_API_IO_BOOKMAKERS` | (auto) | forzar casas concretas (coma) en vez de auto-selección |

El bot **auto-selecciona** las casas que sí tienen momios de Liga MX. Verifica el
estado en `GET /valor/diagnostico`.

> En pretemporada puede no haber momios publicados aún; aparecen solos conforme
> se acerca la jornada.

## Tests y CI

```bash
python3 -m pytest tests/
```

El workflow `.github/workflows/ci.yml` instala dependencias y **corre toda la
suite** en cada push y pull request.

## Herramientas locales (opcionales)

Utilidades locales de apoyo manual (no deciden picks, no envían nada):
`scripts/import_fbref_schedule.py` (importar/auditar calendario de FBref a mano),
`scripts/assisted_caliente_odds.py` (importar momios pegados manualmente, sin
scraping), `scripts/rss_lesiones_ligamx.py` (lesiones vía RSS) y
`scripts/final_security_gate.py` (gate de seguridad).

## Notas

- El bot **nunca** cierra ni envía picks automáticos. Salidas:
  `INFORMATIVO / REVISIÓN HUMANA`.
- No se commitea `.env`, `data/`, `reports/` ni logs. No se imprimen secretos.
- Más comandos en [`COMMANDS.md`](COMMANDS.md); historial en
  [`CHANGELOG.md`](CHANGELOG.md).
