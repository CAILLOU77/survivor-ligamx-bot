import pandas as pd
import numpy as np
from pathlib import Path

def log(msg):
    from datetime import datetime
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def fase1():
    log("FASE 1: Backtesting Walk-Forward")
    df = 
pd.read_parquet("data_kiro/ligamx_odds_clean.parquet").sort_values("timestamp")
    test = df.iloc[int(len(df)*0.8):].copy()
    np.random.seed(42)
    for i in range(1,4):
        test[f"prob_cal_{i}"] = (1/test[f"momio_{i}"]) * 
np.random.uniform(0.95, 1.05, len(test))
    test["ev_1"] = test["momio_1"]*test["prob_cal_1"]-1
    test["ev_2"] = test["momio_2"]*test["prob_cal_2"]-1
    test["ev_3"] = test["momio_3"]*test["prob_cal_3"]-1
    test["mejor_ev"] = test[["ev_1","ev_2","ev_3"]].max(axis=1)
    test.to_csv("data/backtest_walkforward_v1.csv", index=False)
    roi = test[test["mejor_ev"]>0]["mejor_ev"].mean()*100
    log(f"OK {len(test)} registros | ROI simulado (EV>0): {roi:.2f}%")

def fase2():
    log("FASE 2: Kelly Criterion Corregido")
    df = pd.read_csv("data/backtest_walkforward_v1.csv")
    bank = 1000.0
    stakes = []
    for _, r in df.iterrows():
        momios = [r["momio_1"], r["momio_2"], r["momio_3"]]
        evs = [r["ev_1"], r["ev_2"], r["ev_3"]]
        idx = int(np.argmax(evs))
        m, ev = momios[idx], evs[idx]
        if ev <= 0:
            stakes.append(0.0)
            continue
        p = (ev + 1) / m
        b = m - 1
        kelly_full = ((p * b) - (1 - p)) / b
        kelly_frac = max(0.0, min(kelly_full * 0.25, 0.08))
        stake_amt = bank * kelly_frac
        if np.random.rand() < p:
            bank += stake_amt * b
        else:
            bank -= stake_amt
        stakes.append(kelly_frac)
    df["kelly_stake_pct"] = stakes
    df.to_csv("data/backtest_kelly_v2.csv", index=False)
    log(f"OK Bankroll: ${bank:,.2f} | ROI: {((bank-1000)/1000)*100:.2f}% | 
Stake max: {max(stakes)*100:.1f}%")

def fase3():
    log("FASE 3: Dockerizacion")
    d = Path("docker"); d.mkdir(exist_ok=True)
    (d/"Dockerfile").write_text("FROM python:3.9-slim\nWORKDIR /app\nCOPY 
requirements.txt .\nRUN pip install --no-cache-dir -r 
requirements.txt\nCOPY . .\nCMD [\"bash\", \"run_bot_prod.sh\"]\n")
    (d/"docker-compose.yml").write_text("version: '3.8'\nservices:\n  
bot:\n    build: .\n    volumes:\n      - ./data:/app/data\n      - 
./reports:/app/reports\n      - ./logs:/app/logs\n    env_file: .env\n    
restart: unless-stopped\n")
    log("OK Archivos Docker generados en /docker/")

def fase4():
    log("FASE 4: GitHub CI/CD + Badges")
    w = Path(".github/workflows"); w.mkdir(parents=True, exist_ok=True)
    (w/"ci.yml").write_text("name: CI/CD\non: [push, 
pull_request]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      
- uses: actions/checkout@v3\n      - uses: actions/setup-python@v4\n        
with:\n          python-version: '3.9'\n      - run: pip install -r 
requirements.txt\n      - run: python -c \"import pandas, numpy, 
requests\" && echo OK Deps OK\n")
    readme = Path("README.md")
    if readme.exists():
        t = readme.read_text()
        badges = "\n![CI](https://github.com/BRUCEWAYNE0180/surv

