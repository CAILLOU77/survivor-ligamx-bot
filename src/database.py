import psycopg2
import os
from contextlib import contextmanager

DATABASE_URL = os.getenv('DATABASE_URL')

@contextmanager
def get_db():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS picks (
                id SERIAL PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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

def save_pick(match_id, market, true_prob, momio, ev, kelly_pct):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO picks (match_id, market, true_prob, momio, ev, kelly_pct)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (match_id, market, true_prob, momio, ev, kelly_pct))
        conn.commit()

def get_metrics():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                COUNT(*) as total_picks,
                SUM(CASE WHEN result = 1 THEN 1 ELSE 0 END) as wins,
                SUM(profit_loss) as total_profit,
                AVG(profit_loss) as avg_profit
            FROM picks
            WHERE status = 'settled'
        """)
        row = cur.fetchone()
        return {
            'total_picks': row[0] or 0,
            'wins': row[1] or 0,
            'win_rate': (row[1] / row[0] * 100) if row[0] > 0 else 0,
            'total_profit': row[2] or 0.0,
            'avg_profit': row[3] or 0.0
        }
