import requests
import os
from src.database import get_db

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram no configurado")
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(url, data=data)
        return response.status_code == 200
    except Exception as e:
        print(f"Error enviando Telegram: {e}")
        return False

def check_high_ev_picks():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT match_id, market, true_prob, ev, kelly_pct, momio
            FROM picks
            WHERE status = 'pending' AND ev > 0.05
            ORDER BY ev DESC
            LIMIT 3
        """)
        picks = cur.fetchall()
    
    if not picks:
        return "No hay picks con EV > 5%"
    
    message = "🔥 <b>ALERTA: PICKS DE ALTO VALOR</b> 🔥\n\n"
    
    for pick in picks:
        match_id, market, true_prob, ev, kelly_pct, momio = pick
        message += f"📊 <b>{match_id}</b>\n"
        message += f"   Mercado: {market}\n"
        message += f"   EV: {ev:.2%}\n"
        message += f"   Probabilidad: {true_prob:.2%}\n"
        message += f"   Momio: {momio}\n"
        message += f"   Kelly: {kelly_pct:.2f}%\n\n"
    
    message += "⏰ Actúa rápido, estos picks tienen alto valor esperado"
    
    return message

def send_high_ev_alerts():
    message = check_high_ev_picks()
    if "No hay picks" not in message:
        success = send_telegram_message(message)
        return {"status": "sent" if success else "failed", "message": message}
    return {"status": "no_picks", "message": message}

if __name__ == "__main__":
    result = send_high_ev_alerts()
    print(result)
