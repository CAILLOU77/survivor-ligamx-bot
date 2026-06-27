import asyncio, json, logging
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright

OUTPUT_DIR = Path("datos_ligamx")
OUTPUT_DIR.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s", datefmt="%H:%M:%S")

seen_types = set()

async def procesar_ws_frame(frame, ws_url: str):
    try:
        raw = frame.data
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        if not raw or len(raw) < 30:
            return

        data = json.loads(raw)
        msg_type = data.get("msg_type", "RAW")

        if msg_type == "S":  # Ignorar esquema
            return

        if msg_type not in seen_types:
            seen_types.add(msg_type)
            preview = json.dumps(data, ensure_ascii=False)[:180]
            logging.info(f"🆕 TIPO DETECTADO: {msg_type}")
            logging.info(f"📦 MUESTRA: {preview}")

        # Guardar solo datos reales
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        fname = OUTPUT_DIR / f"{ts}_data_{msg_type}.json"
        fname.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    except (json.JSONDecodeError, Exception):
        pass

async def main():
    logging.info("🚀 Capturando mensajes de datos WS (sin schema)...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--no-sandbox"])
        context = await browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")
        page = await context.new_page()

        def on_ws(ws):
            ws.on("framereceived", lambda f: asyncio.create_task(procesar_ws_frame(f, ws.url)))

        page.on("websocket", on_ws)

        target = "https://sports.caliente.mx/es_MX/Apuestas-Futbol-Mexico"
        logging.info(f"🌐 Cargando {target}...")
        await page.goto(target, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(4)

        logging.info("📡 Esperando payloads de datos... (Ctrl+C para salir)")
        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logging.info("\n🛑 Detenido.")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
