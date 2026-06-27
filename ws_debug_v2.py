import asyncio, json, logging
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright

OUTPUT_DIR = Path("datos_ligamx")
OUTPUT_DIR.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s", datefmt="%H:%M:%S")

frame_counter = 0

async def intercept_ws(frame, ws_url):
    global frame_counter
    frame_counter += 1
    try:
        payload = frame.payload  # ATRIBUTO CORRECTO en Playwright Python
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="ignore")
        if not payload or len(payload) < 15:
            return

        # Primeros 5 frames: log completo para diagnóstico
        if frame_counter <= 5:
            logging.info(f"🔍 FRAME #{frame_counter} ({len(payload)} chars): {payload[:200]}...")

        # Intentar parsear JSON
        try:
            data = json.loads(payload)
            msg_type = data.get("msg_type", "RAW")
            if msg_type != "S":  # Ignorar solo el schema inicial
                ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                fname = OUTPUT_DIR / f"{ts}_{msg_type}.json"
                fname.write_text(json.dumps(data, indent=2, ensure_ascii=False))
                logging.info(f"✅ Guardado dato real: {fname.name}")
        except json.JSONDecodeError:
            logging.debug(f"⏭️ Payload no JSON (texto plano/binario)")
    except Exception as e:
        logging.error(f"❌ Error en frame: {e}")

async def main():
    logging.info("🚀 Iniciando captura WebSocket corregida...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--no-sandbox"])
        context = await browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")
        page = await context.new_page()

        page.on("websocket", lambda ws: ws.on("framereceived", lambda f: asyncio.create_task(intercept_ws(f, ws.url))))

        logging.info("🌐 Navegando a Caliente Sports...")
        await page.goto("https://sports.caliente.mx/es_MX/Apuestas-Futbol-Mexico", wait_until="domcontentloaded", timeout=20000)
        
        logging.info("📡 Escuchando WS... (espera 15 segundos para que llegue el tráfico)")
        await asyncio.sleep(18)  # Ventana fija para capturar sin bloquear terminal
        
        logging.info(f"📊 Total frames interceptados: {frame_counter}")
        logging.info("🔒 Navegador cerrado. Revisa datos_ligamx/ y pega aquí los FRAMES si no hay JSON.")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
