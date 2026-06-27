import asyncio, json, logging, os
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, Response

OUTPUT_DIR = Path(os.getcwd()) / "datos_ligamx"
OUTPUT_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s | %(levelname)-5s | %(message)s", datefmt="%H:%M:%S")

async def procesar_respuesta(response: Response):
    url = response.url
    status = response.status

    if status != 200:
        return
    if any(ext in url.lower() for ext in ['.js', '.css', '.png', '.jpg', '.svg', '.woff', '.map', '.ico', 'analytics', 'telemetry', 'pixel']):
        return

    try:
        body = await response.body()
        text = body.decode("utf-8", errors="ignore")

        # Ignorar payloads de promos/banners
        if "bhighlight" in text or "jackpot_area" in text or "<html" in text or "<!doctype" in text:
            return

        data = json.loads(text)
        endpoint_name = url.split("?")[0].split("/")[-1]

        # Detectar si es un feed real de momios/partidos
        claves = set(data.keys())
        es_feed = any(k in claves for k in ["Events", "Matches", "Fixtures", "Competitions", "Markets", "Odds", "Outcomes", "participants", "event_groups"])

        if es_feed:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = OUTPUT_DIR / f"{ts}_{endpoint_name}.json"
            filename.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            logging.info(f"✅ MOMIOS REALES capturados: {filename.name}")
            logging.info(f"   URL: {url}")
        else:
            logging.debug(f"⏭️ JSON ignorado (estructura no es feed): {endpoint_name}")

    except (json.JSONDecodeError, Exception):
        pass

async def main():
    logging.info("🚀 Iniciando monitor DEBUG...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        context = await browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")
        page = await context.new_page()
        page.on("response", lambda r: asyncio.create_task(procesar_respuesta(r)))

        target = "https://sports.caliente.mx/es_MX/Apuestas-Futbol-Mexico"
        logging.info(f"🌐 Navegando a {target}...")
        await page.goto(target, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(5)

        logging.info("📡 Escuchando tráfico. Espera a ver líneas con ✅ MOMIOS REALES capturados")
        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logging.info("\n🛑 Detenido por usuario.")
        finally:
            await browser.close()
            logging.info("🔒 Navegador cerrado.")

if __name__ == "__main__":
    asyncio.run(main())
