import httpx
import asyncio
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
API_BASE = "https://survivor-ligamx-bot.onrender.com"
SEEN_PICKS_FILE = "data/seen_picks.cache"

def load_seen():
    if not os.path.exists(SEEN_PICKS_FILE): return set()
    with open(SEEN_PICKS_FILE, "r") as f: return set(line.strip() for line in f if line.strip())

def save_seen(seen_set):
    os.makedirs(os.path.dirname(SEEN_PICKS_FILE), exist_ok=True)
    with open(SEEN_PICKS_FILE, "w") as f: f.write("\n".join(seen_set))

async def notify_new_picks():
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ Faltan credenciales en .env"); return

    seen = load_seen()
    print("📡 Consultando API pública...")

    try:
        async with httpx.AsyncClient(timeout=40.0) as client:
            resp = await client.get(f"{API_BASE}/picks/latest")
            resp.raise_for_status()
            data = resp.json()

        if data.get("status") != "active" or not data.get("picks"):
            print("ℹ️ Sin picks válidos ahora."); return

        sent_count = 0
        for p in data["picks"]:
            if sent_count >= 3: break # Máx 3 alertas por ciclo

            # Filtrar solo picks recientes (últimas 24h)
            try:
                pick_time = datetime.fromisoformat(str(p.get("timestamp", "")))
                if datetime.utcnow() - pick_time > timedelta(hours=24): continue
            except: pass

            uid = f"{p.get('match','')}_{p.get('market','')}"
            ev = p.get("expected_value", 0)

            if uid not in seen and ev > 0.04:
                msg = (f"🎯 *PICK DETECTADO*\n⚽ {p.get('match', 'N/A')}\n"
                       f"📊 EV: `{ev:.2%}` | Prob: `{p.get('true_prob', 0):.1%}`\n"
                       f"💰 Kelly: `{p.get('kelly_stake', 0):.1f}%`\n🕒 {str(p.get('timestamp', ''))[:19]}")
                url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
                async with httpx.AsyncClient() as tg:
                    await tg.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
                print(f"📤 Enviado: {p.get('match')}")
                seen.add(uid)
                sent_count += 1

        save_seen(seen)
        print(f"✅ Proceso completado ({sent_count} alertas enviadas).")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(notify_new_picks())
