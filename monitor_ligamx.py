import asyncio, json, logging, os, random
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, Response

TARGET_URL_KEYWORDS = ("odds", "matches", "feed", "sports", "events", "momios", "api", "es_mx", "apuestas")
CONTENT_KEYWORDS = ("liga mx", "ligamx", "mexico", "primera division", "apert", "claus")
OUTPUT_DIR = Path(os.getcwd()) / "datos_liga_mx"
OUTPUT_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S")

def es_ligamx(text):
    return any(kw in text.lower() for kw in CONTENT_KEYWORDS)

async def guardar_json(payload, url):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    nombre = f"{ts}_{url.split('?')[0].split('/')[-1].replace('.','_')}.json"
    ruta = OUTPUT_DIR / nombre
    await asyncio.to_thread(ruta.write_text, json.dumps(payload, indent=2, ensure_ascii=False))
    logging.info(f"Guardado: {ruta.name}")

async def procesar_respuesta(response):
    url = response.url.lower()
    if not any(kw in url for kw in TARGET_URL_KEYWORDS):
        return
    if response.status != 200:
        return
    try:
        body = await response.body()
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        return
    if not es_ligamx(json.dumps(payload, ensure_ascii=False)):
        return
    logging.info("Paquete Liga MX detectado")
    await guardar_json(payload, response.url)

async def simular_actividad(page):
    while True:
        await page.mouse.move(random.randint(100, 900), random.randint(100, 700))
        await asyncio.sleep(random.uniform(8.0, 18.0))

async def main():
    logging.info("Iniciando monitor con URL oficial sports.caliente.mx...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()
        page.on("response", lambda r: asyncio.create_task(procesar_respuesta(r)))
        asyncio.create_task(simular_actividad(page))

        target_url = "https://sports.caliente.mx/es_MX/Apuestas-Futbol-Mexico"

        try:
            logging.info(f"Navegando a: {target_url}")
            await page.goto(target_url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(5)
            logging.info("Escuchando trafico de red... (Ctrl+C para detener)")
            await asyncio.Event().wait()
        except Exception as e:
            logging.error(f"Error durante la navegacion: {e}")
        finally:
            await browser.close()
            logging.info("Navegador cerrado.")

if __name__ == "__main__":
    asyncio.run(main())
