import sqlite3
import pandas as pd
from datetime import datetime
import os

DB_PATH = "data/history.db"

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS picks_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            match_id TEXT,
            true_prob REAL,
            ev REAL,
            kelly_pct REAL,
            status TEXT DEFAULT 'pending',
            result REAL DEFAULT 0.0
        )
    """)
    conn.commit()
    conn.close()

def save_pick(match_id, true_prob, ev, kelly_pct):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO picks_log (timestamp, match_id, true_prob, ev, kelly_pct) VALUES (?,?,?,?,?)",
        (datetime.utcnow().isoformat(), match_id, true_prob, ev, kelly_pct)
    )
    conn.commit()
    conn.close()

def get_roi_history():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM picks_log ORDER BY timestamp DESC", conn)
    conn.close()
    if df.empty: return {"total_picks": 0, "roi_simulado": "0.00%", "win_rate": "0.00%"}
    
    # Simulación rápida de ROI basado en EV acumulado
    roi = (df["ev"].sum() / len(df)) * 100
    win_rate = len(df[df["ev"] > 0.04]) / len(df) * 100
    return {
        "total_picks": len(df),
        "roi_simulado": f"{roi:.2f}%",
        "win_rate": f"{win_rate:.1f}%",
        "last_updated": datetime.utcnow().isoformat()
    }

if __name__ == "__main__":
    init_db()
    print("✅ DB iniciada")
    print(get_roi_history())
