import asyncio, json, logging
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright

OUTPUT_DIR = Path("datos_ligamx")
OUTPUT_DIR.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s", datefmt="%H:%M:%S")

frame_counter = 0

async def process_payload(payload, ws_url):
    global frame_counter
    frame_counter += 1
    try:
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="ignore")
        if not payload or len(payload) < 15:
            return

        if frame_counter <= 5:
            logging.info(f"🔍 PAYLOAD #{frame_counter} ({len(payload)} chars): {payload[:350]}")

        try:
            data = json.loads(payload)
            msg_type = data.get("msg_type", "UNKNOWN")
            if msg_type != "S":
                ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                fname = OUTPUT_DIR / f"{ts}_ws_{msg_type}.json"
                fname.write_text(json.dumps(data, indent=2, ensure_ascii=False))
                logging.info(f"✅ Guardado dato real: {fname.name}")
        except json.JSONDecodeError:
            pass
    except Exception as e:
        logging.error(f"❌ Error: {e}")

async def main():
    logging.info("🚀 Iniciando captura WS (API corregida)...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--no-sandbox"])
        context = await browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")
        page = await context.new_page()

        def on_ws(ws):
            ws.on("framereceived", lambda pl: asyncio.create_task(process_payload(pl, ws.url)))

        page.on("websocket", on_ws)

        logging.info("🌐 Navegando...")
        await page.goto("https://sports.caliente.mx/es_MX/Apuestas-Futbol-Mexico", wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(4)

        logging.info("📡 Escuchando WS por 20 segundos...")
        await asyncio.sleep(20)
        logging.info(f"📊 Total payloads interceptados: {frame_counter}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
