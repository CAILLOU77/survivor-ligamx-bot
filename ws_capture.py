import asyncio, json, logging, re
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright

OUTPUT_DIR = Path("datos_ligamx")
OUTPUT_DIR.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s", datefmt="%H:%M:%S")

BET_REGEX = re.compile(r"(odds|market|event|match|home|away|price|bet|selection|outcome|competition|fixture|ligamx|mexico|apuesta|participants|scores|outcomes)", re.IGNORECASE)

async def procesar_ws_frame(frame, ws_url: str):
    try:
        text = frame.text if hasattr(frame, 'text') else str(frame)
    except Exception:
        return
    if not text or len(text) < 60:
        return
    if not BET_REGEX.search(text):
        return

    try:
        data = json.loads(text)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        safe_host = ws_url.split("//")[-1].split("/")[0].replace(".", "_")[:25]
        fname = OUTPUT_DIR / f"{ts}_ws_{safe_host}.json"
        fname.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        logging.info(f"🎯 MOMIOS REALES (WS): {fname.name}")
        logging.info(f"   CLAVES: {list(data.keys())[:6]}")
    except json.JSONDecodeError:
        pass

async def main():
    logging.info("🚀 Iniciando captura vía WebSockets...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        context = await browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")
        page = await context.new_page()

        def on_ws(ws):
            ws.on("framereceived", lambda f: asyncio.create_task(procesar_ws_frame(f, ws.url)))

        page.on("websocket", on_ws)

        target = "https://sports.caliente.mx/es_MX/Apuestas-Futbol-Mexico"
        logging.info(f"🌐 Cargando {target}...")
        await page.goto(target, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(5)

        logging.info("📡 Escuchando WebSockets... (Ctrl+C para salir)")
        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logging.info("\n🛑 Detenido por usuario.")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
