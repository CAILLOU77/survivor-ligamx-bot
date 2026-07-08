# Memoria del proyecto — Survivor Liga MX (y API hermana)

Memoria persistente para no re-descubrir ni re-litigar lo ya hecho/medido.
Complementa a `survivor-playdoit-reglas.md` (las reglas del juego).

## Los dos repos (cuenta GitHub: CAILLOU77)
- **survivor-ligamx-bot** — el bot. Desplegado en Render: `https://survivor-ligamx-bot.onrender.com`.
- **ligamx-api** — API hermana (datos Liga MX). Render: `https://ligamx-api.onrender.com`. Repo aparte, deploy aparte.
- Ambos en `/Users/mac/Desktop/repos-CAILLOU77/`. También está `blackjack-coach-pro-demo` (recuperado de una cuenta baneada → subido PRIVADO a CAILLOU77) y `FANTASY5678`.

## Arquitectura del bot
- **Modelo**: Poisson/Dixon-Coles (`poisson_model.py`) con recencia (half-life 365d), shrinkage (4.0), rho (-0.10). Entrena con resultados reales.
- **Fuente de datos**: `fuentes_datos.py`. ESPN por defecto; `obtener_historico_largo()` prefiere la Liga MX API (~1200 partidos desde 2022) para backtest/calibración.
- **Pick de jornada**: `motor_pronosticos.mejores_picks_estrategico` — maximiza no-perder, castiga favorito VISITANTE (PEN_VISITANTE), cautela de arranque, victoria como desempate (PESO_VICTORIA_PICK=0.5). **Mezcla momios** (`comparador_mercado.mezclar_pronosticos_con_mercado`, 50/50) en las probabilidades del pick.
- **Plan de temporada**: `planificador_survivor.py` (asignación húngara). NO está predeterminado: se recalcula cada vez según resultados, momios y equipos usados.
- **Protecciones (partido trampa)**: sensor under/partido cerrado (`_GOLES_CERRADO=2.3`), favorito visitante penalizado, empate alto, sin favorito claro. Medido: favorito visitante falla ~59% vs ~46% local.
- **Comandos Telegram** (bot @Brucewayneuwu_bot, chat dueño): jugar → `/pick`, `/seguir` (XI ~1h antes), `/plan`, `/momios`. Revisar → `/prueba`, `/confianza`, `/derrotas`, `/ganadores`.

## Arquitectura de la API (ligamx-api)
- FastAPI + SQLAlchemy + Alembic. **Neon Postgres** en prod (SQLite en tests). Scrapers: ESPN, 365Scores, Sofascore, noticias.
- **Histórico de momios**: tabla `match_odds` + `POST /odds` (protegido con `X-API-Key` = `SYNC_API_KEY`) y `GET /odds` (público). El bot lo llena vía `ligamx_api.archivar_momios` cuando genera pronósticos.
- **CLAVE / TRAMPA de deploy**: el Start Command del servicio NO corre `alembic upgrade head` de forma fiable → por eso `main.py` tiene una **red de seguridad `create_all`** (crea tablas nuevas al arrancar; no altera existentes). Las migraciones nuevas deben ser idempotentes. NO agregar columnas al modelo sin que la columna exista en la BD (rompió `/matches` con `altitude_m` una vez).

## Deploy (siempre manual en Render; el usuario lo hace)
- Cambios de bot → deploy del bot. Cambios de API → deploy de la API.
- Si hay tabla nueva en la API → la red de seguridad la crea al arrancar (deploy normal basta).
- `LIGAMX_API_SYNC_KEY` (env del BOT en Render) debe = `SYNC_API_KEY` (env de la API).

## Hallazgos MEDIDOS (no volver a probar a ciegas — ya se hizo con datos reales)
- El modelo **ya está bien calibrado** (tuning de half_life/shrink/rho mejoró Brier solo 0.0009 = ruido). NO cambiar parámetros por ruido.
- **Altitud**: NO mejora (0.0006 Brier). No activada. `altitud.py` queda como herramienta.
- **Puro sobrevivir (peso victoria 0)**: NO mejora supervivencia (igual ~5.1 jornadas). Se conserva peso 0.5 (respeta la regla: ganar desempata).
- **Derrotas del bot**: ~50% favorito que perdió, 25% under/cerrado, 25% visitante → cae por VARIANZA, no por elegir mal ni por unders.
- **Patrón ganador NO copiable**: las corridas ganadoras (oráculo) usaban picks rank ~8 / 67% no-perder / 41% visitante → suerte retrospectiva, no método.
- **Variedad**: ~8.9 sobrevivientes/jornada, cientos+ de corridas ganadoras distintas por torneo. El pick más seguro (top-1) **sobrevivió 85%** de jornadas; algún top-3 sobrevivió 100%.
- **Realidad**: sobrevivir las 17 ≈ 0.85^17 ≈ 6% para cualquiera. El bot ya juega lo óptimo predecible; ganar = durar más que los demás + suerte.

## Preferencias del usuario (respetar siempre)
- **Honestidad sin adornos.** Medir antes de afirmar; no vender mejoras que no ayudan; corregir cuando algo estaba mal.
- **Mensajes de Telegram limpios y legibles en MÓVIL** (sin sangrías con espacios, emojis al inicio, divisores cortos).
- **Jugadores a seguir**: usar SOLO goleo del torneo ACTUAL. En pretemporada queda vacío a propósito (se llena al arrancar). **CUIDADO CON DATOS VIEJOS**: entre torneos los jugadores cambian de equipo o se venden, así que NO usar goleadores/jugadores de temporadas pasadas mapeados al equipo actual (sería engañoso). Aplica igual a cualquier dato de jugadores.
- **Unders de valor + hándicap**: el usuario apuesta hándicap +1.5/+2 a unders de valor. El bot detecta "under de valor" y muestra el **riesgo de goleada** (P(margen 2+) y P(margen 3+ = goleada)) para avisar si el +1.5/+2 cubre. Ver `motor._nota_under_handicap` y `poisson.probabilidad_margen_ge`.
- Le gusta intentar GANAR el Survivor completo, no solo sobrevivir; recordarle que el bot maximiza la chance real.
- Idioma: español, tono cercano.

## Estado actual (al día)
- Ambos repos limpios, todo pusheado, tests verdes, servicios arriba.
- Momios archivándose (pretemporada → cobertura limitada; Liga MX arranca ~16 jul).
- Calidad: bot ruff-limpio, ~539 tests; API ~124 tests.
