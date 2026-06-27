import asyncio, json, logging, re
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, Response

OUTPUT_DIR = Path("datos_ligamx")
OUTPUT_DIR.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s", datefmt="%H:%M:%S")

BET_REGEX = re.compile(r"(odds|market|event|match|home|away|price|bet|selection|outcome|competition|fixture|ligamx|mexico|apuesta)", re.IGNORECASE)

async def intercept(response: Response):
    if response.status != 200: return
    url = response.url.lower()
    if any(ext in url for ext in ['.js','.css','.png','.jpg','.woff','.map','.ico','.svg','analytics','pixel','telemetry']): return
    try:
        body = await response.body()
        text = body.decode('utf-8', errors='ignore')
        if len(text) < 100: return
        if not BET_REGEX.search(text): return
        data = json.loads(text)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        endpoint = url.split('/')[-1].split('?')[0] or "unknown"
        fname = OUTPUT_DIR / f"{ts}_{endpoint}.json"
        fname.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        logging.info(f"Guardado: {fname.name}")
        logging.info(f"CLAVES: {list(data.keys())[:5]}")
    except Exception:
        pass

async def main():
    logging.info("Iniciando captura inteligente...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        context = await browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")
        page = await context.new_page()
        page.on("response", lambda r: asyncio.create_task(intercept(r)))
        target = "https://sports.caliente.mx/es_MX/Apuestas-Futbol-Mexico"
        logging.info(f"Cargando {target}...")
        await page.goto(target, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(4)
        logging.info("Escuchando... (Ctrl+C para salir)")
        try: await asyncio.Event().wait()
        except KeyboardInterrupt: logging.info("\nDetenido.")
        finally: await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
