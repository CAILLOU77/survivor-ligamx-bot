import os, json, requests
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(override=True)
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_alert(message: str):
    if not TOKEN or not CHAT_ID: return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    return requests.post(url, json={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10).ok

if __name__ == "__main__":
    report = Path("reports/reporte_survivor_ultimo.txt")
    if not report.exists(): exit()

    content = report.read_text()
    if "CERRAR" in content and "ENVIAR" in content:
        # Leer métricas del CSV calibrado si existe
        ev_csv = Path("data/poisson_calibrated_ev.csv")
        vig_ok, ev_ok = True, False
        if ev_csv.exists():
            import pandas as pd
            df = pd.read_csv(ev_csv)
            vig_ok = (df["vig_pct"].mean() < 8)
            ev_ok = ((df[["ev_1","ev_2","ev_3"]].max(axis=1) > 0.04).any())

        if vig_ok and ev_ok:
            lines = [l for l in content.split("\n") if l.strip()][:10]
            send_alert("🚨 <b>PICK VALIDADO +EV</b>\n" + "\n".join(lines))
        else:
            send_alert("📊 <b>Señal técnica detectada</b>\nVIG/EV fuera de umbral. Revisa dashboard.")
