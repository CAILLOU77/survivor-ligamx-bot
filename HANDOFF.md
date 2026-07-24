# 🤝 HANDOFF FINAL — Survivor Liga MX Bot

**Actualizado:** 23 de julio de 2026  
**Repositorio:** `survivor-ligamx/survivor-ligamx-bot`  
**Producción:** https://survivor-ligamx-bot.onrender.com  
**Health:** https://survivor-ligamx-bot.onrender.com/health

## Estado ejecutivo

El proyecto está **listo para lanzamiento** dentro de su alcance actual. El flujo crítico está implementado, probado, desplegado y monitoreado:

- API y dashboard Mi Survivor en Render.
- Persistencia PostgreSQL en Neon y SQLite local.
- Datos reales de ESPN con Liga MX API como integración hermana.
- Modelo Poisson/Dixon-Coles para 1X2, Over/Under, BTTS y Survivor.
- Telegram seguro, durable e idempotente.
- CI, pruebas E2E, cobertura mínima y smoke tests de producción.
- Auto-Deploy de Render confirmado desde pushes a `main`.

## Infraestructura

- **Runtime:** Python 3.12
- **API:** FastAPI 0.139.2 + Uvicorn
- **Producción:** Render free tier
- **Base de datos:** Neon PostgreSQL en producción; SQLite en local/pruebas
- **API hermana:** https://ligamx-api.onrender.com
- **Repositorio API hermana:** `survivor-ligamx/ligamx-api` o su ubicación vigente
- **Fuente principal:** ESPN API
- **Fuente de respaldo/contexto:** Liga MX API y TheSportsDB donde aplique

### Auto-Deploy

Render está configurado con:

- Source: `survivor-ligamx/survivor-ligamx-bot`
- Branch: `main`
- Auto-Deploy: `On Commit`
- GitHub App de Render instalada y autorizada en la organización `survivor-ligamx`

La integración se verificó con el commit de prueba `17318a8`, que apareció automáticamente en Events de Render.

## Seguridad y regla de producto

**INFORMATIVO / REVISIÓN HUMANA.** El proyecto no apuesta, no inventa momios ni resultados y no debe enviar una decisión como definitiva sin revisión humana.

- Endpoints sensibles protegidos con `X-API-Key`.
- Webhook de Telegram protegido por secreto.
- Falla cerrada si faltan credenciales críticas.
- Deduplicación de updates y entregas Telegram.
- Sin scraping de sitios con login o medidas anti-bot.
- Secretos solo en Render/GitHub; nunca en commits ni chats.

## Trabajo completado

### Contrato y ciclo Survivor

- **PR #14:** identidad estable de partidos (`espn_event_id`, `match_key`, UTC).
- **PR #15:** ciclo Survivor v2, estados, snapshots, historial y anti-duplicados.

### Telegram y entrega

- **PR #16:** deduplicación durable, leases y reintentos seguros.
- **PR #17:** transporte Telegram unificado y eliminación de falsos éxitos.
- **PR #18:** E2E predicciones → formato → Telegram → SQLite durable.

### Monitoreo y calidad

- **PR #19:** smoke de producción diario/manual con reintentos para cold starts.
- **PR #20:** 15 pruebas de rutas críticas API/Telegram.
- **PR #6:** FastAPI actualizado a 0.139.2 con CI verde.
- **PR #21:** PyArrow eliminado al confirmar que no se utilizaba.
- **PR #2:** `actions/checkout` actualizado a v7.
- **PR #3:** `actions/setup-python` actualizado a v7.

## Calidad verificada

- **661 pruebas** aprobadas en la validación completa registrada.
- Cobertura global: **67.49%**, superior al mínimo de **64%**.
- Ruff check y format check activos.
- Mypy y validación estructural en CI.
- Dos ejecuciones de CI por PR para cambios recientes.
- Dashboard, `/health`, BD, ESPN, Liga MX API y Telegram verificados en producción.

## Dependencias

- FastAPI quedó en `0.139.2` tras pasar CI y producción.
- PyArrow se eliminó porque no existían imports en el código.
- `requests` permanece fijado en `2.32.5`: la actualización a `2.34.2` falló ambos checks después de rebase y el PR #4 se cerró.
- El antiguo PR #5 de PyArrow se cerró por quedar reemplazado por #21.

No subir una dependencia mayor sin CI verde y comprobación posterior en Render.

## Endpoints operativos principales

- `/` → redirección a Mi Survivor
- `/dashboard`
- `/health`
- `/health/fuentes`
- `/predicciones`
- `/survivor`
- `/survivor/mio`
- `/survivor/usados`
- `/survivor/picks/confirmar`
- `/jornada`
- `/plan-survivor`
- `/alerts/pronosticos`
- `/alerts/momios`
- `/alerts/recordatorio`
- `/alerts/resumen`
- `/telegram/webhook`
- `/docs`

## Runbook

### Después de cada cambio

1. Trabajar en rama y PR.
2. Esperar todos los checks verdes.
3. Fusionar con squash.
4. Confirmar que Render inicia Auto-Deploy.
5. Revisar `/health` hasta que todas las dependencias estén en `ok`.
6. Considerar transitoria una desconexión SSL de Neon durante el reinicio; debe recuperarse en menos de un minuto. Si persiste, revisar logs y `DATABASE_URL`.

### Cold start de Render

El free tier puede dormir el servicio. El primer request puede tardar alrededor de 50 segundos o devolver temporalmente 503. Los smoke tests tienen reintentos para esta condición.

### Si Neon falla

- Revisar `/health` y logs de Render.
- Confirmar `DATABASE_URL` y SSL.
- No repetir operaciones de escritura ambiguas sin comprobar su estado.

### Si Telegram falla

- Revisar `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` y el secreto del webhook.
- Consultar `/health` y logs.
- La entrega idempotente permite reintentos sin duplicar mensajes.

## Pendientes manuales finales

1. **Proteger `main`** con una ruleset que exija PR y CI verde.
2. Confirmar que `API_KEY` esté configurada tanto en Render como en GitHub Actions cuando los workflows la necesiten.
3. Ejecutar recalibración y backtest con datos recientes antes de cada tramo importante del torneo:
   - `python3 src/validacion_modelo.py`
   - `python3 src/simulador_survivor.py`
4. Realizar una prueba funcional del dashboard y comandos Telegram con la cuenta propietaria.
5. Limpiar ramas fusionadas desde GitHub cuando sea conveniente.

## Criterio de lanzamiento

El sistema puede considerarse **10/10 para lanzamiento dentro del alcance definido** cuando `main` quede protegido y se complete la prueba funcional propietaria. Esto no significa software sin mantenimiento: las fuentes externas, dependencias y el modelo requieren seguimiento continuo.
