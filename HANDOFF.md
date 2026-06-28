# 🤝 HANDOFF — Survivor Liga MX Bot

## 1. Identidad
- **Repo:** `BRUCEWAYNE0180/survivor-ligamx-bot` · rama principal `main`
- **Stack:** Python **3.12**, FastAPI (web en **Render**: `survivor-ligamx-bot.onrender.com`), Postgres (prod) / SQLite (local)
- **Estado:** **481 tests** ✅ · **ruff** limpio · **CI corre lint+tests** en cada PR
- **Objetivo:** asistir decisiones de **Survivor Liga MX** + pronósticos (1X2, O/U, BTTS) para el **Apertura 2026** (arranca ~17 de julio).

## 2. REGLA MÁXIMA (no negociable)
**Informativo.** No apuesta, no envía picks automáticos, **no inventa datos**. Toda salida lleva `INFORMATIVO / REVISIÓN HUMANA`. **Cero scraping** a sitios con login/anti-bot. Cero momios o métricas fabricadas.

## 3. Arquitectura actual (post-pivote: ESPN + Poisson)
```
ESPN API (gratis, sin key) + TheSportsDB (respaldo)
   → src/fuentes_datos.py (redundancia + caché + healthcheck)
   → src/poisson_model.py (Dixon-Coles: recencia + shrinkage)  [default]
   → src/motor_pronosticos.py (1X2/OU/BTTS + pick Survivor + top-3)
   → src/tabla_posiciones.py (tabla ESPN + motivación por equipo)
   → Web (FastAPI) + Telegram (telegram_pronosticos.py)
   (opcional) src/comparador_mercado.py ← momios reales odds-api.io
```
Modelos: `poisson_model` (default) y `dixon_coles_mle` (alternativa opcional, validada).

## 4. Endpoints web
`/predicciones` · `/survivor?excluir=` · **`/jornada`** (todo-en-uno: pred+pick+top3+motivación+momios) · `/tabla` · `/valor` · `/valor/diagnostico` · **`/health/fuentes`** · `/stats` · `/history` · `/dashboard` · `/health` · `/cron/backtest` (validación REAL diaria) · `/docs`

## 5. Lo que se hizo en sesiones previas (todo en `main`)
**Modelo (lo grande):**
- Pasó de **38.3% → 49.3%** de accuracy (supera baseline 45%), Brier 0.70→0.63. El fix clave fue **más datos** (8→18 meses) + recencia + shrinkage + rho calibrado.
- Se probó MLE (empató, no es default) y **forma reciente** (medida y **descartada honestamente** porque bajaba el accuracy).

**Integridad / limpieza:**
- 🚩 Quitado el **backtest falso** (`random.random()` que inventaba win-rate/profit) → ahora valida con resultados reales.
- Quitados **momios inventados** (2.0/3.5/3.5) y el path viejo.
- Web/Telegram repunteados al **path real** (ESPN+Poisson), no al EV falso.
- DB **unificada** (Postgres prod / SQLite local; `/history` y `/backtest/settle` estaban rotos en Render, arreglados).
- **−30,000+ líneas** de legado/basura eliminadas (módulos muertos, datos scrapeados commiteados, CSVs/zip, scripts rotos).

**Calidad / infra:**
- **ruff** (linter, gate en CI) + 71 autofixes.
- **Python 3.9 → 3.12** (3.9 estaba EOL).
- **requirements.txt fijado** (reproducible) y **`.env.example` actualizado** a la realidad.
- **`API_KEY` endurecido** (sin default público; workflow usa `secrets.API_KEY`).
- **README/PROYECTO_MASTER** reescritos al estado real.

**Features nuevas:**
- **Momios reales odds-api.io** integrados (opcional, apagado sin key): favorito, Over/Under (explosivo/cauteloso), hándicap, "valor"; **auto-selecciona** las 2 casas con cobertura (límite del tier gratis); match flexible de nombres ESPN↔casas.
- `/jornada` (todo-en-uno) + **Telegram top-3** picks.
- **`/health/fuentes`** (monitoreo de APIs).
- **`src/simulador_survivor.py`** (backtest del *juego*: ¿cuántas jornadas sobrevives?).
- `/tabla` con **motivación** por equipo, usada como desempate del pick Survivor.

## 6. Módulos clave (vigentes)
`fuentes_datos`, `espn_data`, `poisson_model`, `dixon_coles_mle`, `motor_pronosticos`, `tabla_posiciones`, `reglas_liga_mx`, `comparador_mercado`, `telegram_pronosticos`, `telegram_notifier`, `validacion_modelo`, `simulador_survivor`, `backtest_engine`, `database`, `api.py` + `routers/`.

## 7. ⏳ LO QUE FALTA (para el arranque, ~2 semanas)
**🔑 Setup en Render/GitHub (lo único bloqueante):**
1. Render → Environment: confirmar `ODDS_API_IO_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DATABASE_URL`, y agregar **`API_KEY`** (clave fuerte).
2. GitHub → Settings → Secrets → Actions: agregar secret **`API_KEY`** con el mismo valor (para que el workflow de alertas funcione).

**📅 Cuando arranque el Apertura (mediados de julio):**
3. Verificar `/valor/diagnostico` → que aparezcan casas con momios (`eventos_con_odds_por_casa > 0`); luego validar `/valor`.
4. Recalibrar el modelo con datos frescos: `python3 src/validacion_modelo.py`.
5. Correr el backtest del juego: `python3 src/simulador_survivor.py`.

**🟡 Opcionales / deuda menor:**
6. Subir cobertura de los módulos que se conserven.
7. Mejora de modelo solo con datos reales en mano (forma por torneo, etc.) — medir siempre con `validacion_modelo`.

## 8. Notas operativas (gotchas)
- **Merges a main:** PRs normales los puede mergear el agente; los que tocan **`.github/workflows/`** los **mergea el usuario** (barrera de seguridad).
- **Sandbox pierde paquetes pip entre sesiones** → reinstalar: `pip install -r requirements.txt pytest httpx`.
- **Cache de datos** `data/resultados_historicos.json` está **gitignored**; regenerar: `python3 -c "import sys;sys.path.insert(0,'src');import fuentes_datos;fuentes_datos.obtener_resultados(meses=18)"`.
- **odds-api.io free tier:** máx **2 casas** por consulta (3+ da 403); `/odds/multi` es premium → se usa `/odds` individual. Slug Liga MX: `mexico-liga-mx-apertura`.
- **Correr local:** `bash run_bot.sh` (pipeline real) · `python3 main.py [--telegram] [--excluir A,B]`.
- **Tests:** `python3 -m pytest tests/`. **Lint:** `ruff check .`. Ambos en CI.

## 9. Reglas Liga MX 2025-2026 (codificadas en `reglas_liga_mx`)
18 equipos · Apertura (jul-dic) + Clausura (ene-may) · Liguilla: top 6 directo + Play-In (7-10) · Clausura 2026 fue excepción (top 8 directo, sin Play-In) · Descenso suspendido.

---

**Estado: sólido, limpio, moderno y monitoreable.** El gran trabajo está hecho; lo pendiente es **configurar las keys en Render/GitHub** y **recalibrar con datos reales** cuando arranque la liga.
