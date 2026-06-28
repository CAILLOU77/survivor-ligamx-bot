import random
from src.database import get_db

def get_unsettled_picks():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM picks WHERE status='pending' AND created_at < NOW() - INTERVAL '3 hours'")
        picks = [dict(zip([col[0] for col in cur.description], row)) for row in cur.fetchall()]
    return picks

def settle_pick(pick_id, result, profit_loss):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE picks SET status='settled', result=%s, profit_loss=%s WHERE id=%s", 
                   (result, profit_loss, pick_id))
        conn.commit()

def run_backtest():
    picks = get_unsettled_picks()
    settled_count = 0
    
    for pick in picks:
        # Simulación: 60% win rate basado en EV > 4%
        win_prob = 0.6 if pick['ev'] > 0.04 else 0.5
        
        if random.random() < win_prob:
            result = 1
            profit_loss = pick['kelly_pct'] * (pick['momio'] - 1)
        else:
            result = 0
            profit_loss = -pick['kelly_pct']
        
        settle_pick(pick['id'], result, profit_loss)
        settled_count += 1
    
    print(f"✅ Settled {settled_count} picks")
    return settled_count

if __name__ == "__main__":
    run_backtest()
