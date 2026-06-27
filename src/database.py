import sqlite3
import os
from datetime import datetime
import pandas as pd

DB_PATH = os.getenv("DATABASE_URL", "data/premium_history.db")
if DB_PATH.startswith("postgres://"):
    import psycopg2
    from psycopg2.extras import RealDictCursor

def get_conn():
    if DB_PATH.startswith("postgres://"):
        return psycopg2.connect(DB_PATH, cursor_factory=RealDictCursor)
    os.makedirs("data", exist_ok=True)
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            match_id TEXT,
            market TEXT,
            true_prob REAL,
            momio REAL,
            ev REAL,
            kelly_pct REAL,
            status TEXT DEFAULT 'pending',
            result REAL DEFAULT 0.0,
            profit_loss REAL DEFAULT 0.0
        )
    """)
    conn.commit()
    conn.close()

def save_pick(match_id, market, true_prob, momio, ev, kelly_pct):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO picks (match_id, market, true_prob, momio, ev, kelly_pct)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (match_id, market, true_prob, momio, ev, kelly_pct))
    conn.commit()
    conn.close()

def get_metrics():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM picks", conn)
    conn.close()
    if df.empty:
        return {"total_picks": 0, "roi": "0.00%", "win_rate": "0.00%", "avg_ev": "0.00", "sharpe": "0.00"}
    
    finished = df[df["status"] == "settled"]
    total = len(df)
    wins = len(finished[finished["profit_loss"] > 0])
    roi = (finished["profit_loss"].sum() / total) * 100 if total else 0
    win_rate = (wins / total) * 100 if total else 0
    avg_ev = df["ev"].mean() * 100
    sharpe = (avg_ev / df["ev"].std()) if df["ev"].std() > 0 else 0

    return {
        "total_picks": total,
        "roi": f"{roi:.2f}%",
        "win_rate": f"{win_rate:.1f}%",
        "avg_ev": f"{avg_ev:.2f}%",
        "sharpe": f"{sharpe:.2f}",
        "last_updated": datetime.utcnow().isoformat()
    }

if __name__ == "__main__":
    init_db()
    print("✅ DB Premium inicializada")
