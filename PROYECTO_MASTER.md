# 📝 DOCUMENTO MAESTRO — Survivor & Pronósticos Liga MX

> Estado actual (v2): tras el **pivote**, el sistema NO depende de momios ni de
> scraping. Las predicciones salen de **resultados reales de ESPN + un modelo
> Poisson/Dixon-Coles**. Es **informativo**: nunca apuesta ni envía picks
> automáticos.

## ⚙️ Arquitectura (v2 — ESPN + Poisson)

1. **`src/fuentes_datos.py`** — capa de datos con redundancia: ESPN (primaria,
   gratis, sin key) → TheSportsDB (respaldo) → caché local.
2. **`src/espn_data.py`** — ingesta de resultados y fixtures de la API pública de
   ESPN (`mex.1`).
3. **`src/poisson_model.py`** — modelo Dixon-Coles: estima la fuerza de cada
   equipo con **recencia** (los partidos recientes pesan más) y **shrinkage**
   (regularización), y produce 1X2 / Over-Under / BTTS / marcador.
4. **`src/motor_pronosticos.py`** — "cerebro": ata fuentes + modelo y calcula el
   mejor pick de Survivor (mayor prob. de **no perder**).
5. **`src/tabla_posiciones.py`** — tabla de ESPN + **motivación** por equipo
   (zona de clasificación, vivo/eliminado), usada como contexto/desempate.
6. **`src/dixon_coles_mle.py`** — variante por máxima verosimilitud (alternativa
   opcional, validada; no es el default).
7. **`src/comparador_mercado.py`** — capa **opcional** de comparación vs mercado
   (odds-api.io); apagada sin `ODDS_API_IO_KEY`.
8. **`src/api.py` + `src/routers/`** — web FastAPI (`/predicciones`, `/survivor`,
   `/tabla`, `/valor`, …).
9. **`src/telegram_pronosticos.py`** — alertas informativas por Telegram.
10. **`src/validacion_modelo.py`** — backtest honesto del modelo vs resultados
    reales (accuracy / Brier / baseline).

## 🚦 Reglas no negociables

- **Informativo.** Toda salida termina en `INFORMATIVO / REVISIÓN HUMANA`.
- **Cero scraping** a sitios con login/anti-bot. Solo APIs públicas/gratuitas.
- **No inventar.** Sin métricas ni momios fabricados.

## 📦 Cómo correr

```bash
python3 src/espn_data.py            # baja resultados reales
python3 main.py                     # pronósticos + pick Survivor (--telegram opcional)
python3 src/validacion_modelo.py    # mide la precisión del modelo
python3 -m pytest tests/            # suite completa
```

## 🗂️ Historia

Versión 1 (archivada): pipeline basado en momios/scraping
(`scraper`/`contexto`/`predictor`/`optimizer`/`analizador_ia`). Se **descartó**
porque las APIs de momios no cubrían Liga MX de forma fiable. El código viejo se
retiró del repo (recuperable desde el historial de git).
