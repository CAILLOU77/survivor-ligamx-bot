import asyncio, csv, json, logging, time
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright

OUTPUT_CSV = Path("historico_ligamx_4h.csv")
DURACION_HORAS = 4
FIN_TIEMPO = time.time() + (DURACION_HORAS * 3600)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s", datefmt="%H:%M:%S")

FIELD_MAP = {1: "momio", 3: "id_liga", 5: "id_mercado", 6: "tendencia", 7: "estado", 8: "id_sel"}
mercado_cache = {}

def procesar_y_guardar():
    validos = 0
    if not mercado_cache: return 0
    if not OUTPUT_CSV.exists():
        OUTPUT_CSV.write_text("timestamp,id_mercado,id_liga,momio_1,momio_2,momio_3,vig_pct,tendencia_1,tendencia_2,tendencia_3\n")
    
    with open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as f:
        for mid, data in mercado_cache.items():
            try:
                moms = sorted([float(v["momio"]) for v in data["sels"].values()])
                if len(moms) != 3: continue
                vig = round((sum(1/m for m in moms) - 1) * 100, 2)
                if vig <= 0 or vig > 15: continue
                
                row = {
                    "timestamp": datetime.now().isoformat(),
                    "id_mercado": mid,
                    "id_liga": data["id_liga"],
                    "momio_1": moms[0], "momio_2": moms[1], "momio_3": moms[2],
                    "vig_pct": vig,
                    "tendencia_1": data["sels"].get(list(data["sels"].keys())[0], {}).get("tendencia", ""),
                    "tendencia_2": data["sels"].get(list(data["sels"].keys())[1], {}).get("tendencia", ""),
                    "tendencia_3": data["sels"].get(list(data["sels"].keys())[2], {}).get("tendencia", "")
                }
                f.write(f"{row['timestamp']},{row['id_mercado']},{row['id_liga']},{row['momio_1']},{row['momio_2']},{row['momio_3']},{row['vig_pct']},{row['tendencia_1']},{row['tendencia_2']},{row['tendencia_3']}\n")
                validos += 1
            except: continue
    mercado_cache.clear()
    return validos

async def on_ws_frame(payload, ws_url):
    try:
        if isinstance(payload, bytes): payload = payload.decode("utf-8", errors="ignore")
        if not payload or len(payload) < 20: return
        data = json.loads(payload)
        if data.get("msg_type") != "U": return
        
        for upd in data.get("updates", []):
            if upd.get("obj_type") != "P": continue
            row_data = {}
            for idx, val in upd.get("data", []):
                idx, val = int(idx), str(val)
                if idx in FIELD_MAP: row_data[FIELD_MAP[idx]] = val
            
            mid = row_data.get("id_mercado")
            if not mid: continue
            if mid not in mercado_cache:
                mercado_cache[mid] = {"id_liga": row_data.get("id_liga", ""), "sels": {}}
            
            sel_id = row_data.get("id_sel")
            if sel_id:
                mercado_cache[mid]["sels"][sel_id] = {
                    "momio": row_data.get("momio"),
                    "tendencia": row_data.get("tendencia", "")
                }
    except: pass

async def main():
    logging.info(f"🚀 Pipeline autónomo iniciado. Duración: {DURACION_HORAS}h | Output: {OUTPUT_CSV}")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
        context = await browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")
        page = await context.new_page()
        page.on("websocket", lambda ws: ws.on("framereceived", lambda pl: asyncio.create_task(on_ws_frame(pl, ws.url))))
        
        logging.info("🌐 Navegando a Caliente Sports...")
        await page.goto("https://sports.caliente.mx/es_MX/Apuestas-Futbol-Mexico", wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(5)
        logging.info("📡 Escuchando WS y guardando cada 30s...")

        try:
            while time.time() < FIN_TIEMPO:
                n = procesar_y_guardar()
                if n > 0: logging.info(f"✅ {n} mercados válidos añadidos")
                await asyncio.sleep(30)
        except KeyboardInterrupt:
            logging.info("\n🛑 Interrumpido por usuario. Guardando última tanda...")
            procesar_y_guardar()
        finally:
            await browser.close()
            logging.info(f"🔒 Cerrado. Total registros en {OUTPUT_CSV}")

if __name__ == "__main__":
    asyncio.run(main())
