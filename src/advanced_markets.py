#!/usr/bin/env python3
"""
Advanced Markets Analysis - Handicap Asiático, Goles por Equipo, etc.
"""
import json
import sys
from pathlib import Path
from scipy.stats import poisson
import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
JORNADAS_PATH = BASE_DIR / "data" / "jornadas.json"

def calculate_asian_handicap(home_expected, away_expected, handicap_line):
    """Calcula Handicap Asiático"""
    home_goals = np.random.poisson(home_expected, 10000)
    away_goals = np.random.poisson(away_expected, 10000)
    home_adjusted = home_goals + handicap_line
    
    home_wins = np.sum(home_adjusted > away_goals) / 10000
    away_wins = np.sum(home_adjusted < away_goals) / 10000
    push = np.sum(home_adjusted == away_goals) / 10000
    
    return {
        "home": round(home_wins, 4),
        "away": round(away_wins, 4),
        "push": round(push, 4),
        "handicap_line": handicap_line
    }

def calculate_team_goals_prob(home_expected, away_expected, goal_range=5):
    """Calcula probabilidades de goles por equipo"""
    home_probs = {str(i): round(poisson.pmf(i, home_expected), 4) for i in range(goal_range + 1)}
    away_probs = {str(i): round(poisson.pmf(i, away_expected), 4) for i in range(goal_range + 1)}
    
    return {
        "home_goals": home_probs,
        "away_goals": away_probs
    }

def calculate_exact_score(home_expected, away_expected, max_goals=4):
    """Calcula probabilidades de marcador exacto"""
    scores = {}
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            prob = poisson.pmf(h, home_expected) * poisson.pmf(a, away_expected)
            scores[f"{h}-{a}"] = round(prob, 4)
    
    sorted_scores = dict(sorted(scores.items(), key=lambda x: x[1], reverse=True)[:10])
    return sorted_scores

def analyze_match(partido):
    """Analiza mercados avanzados para un partido"""
    home_odds = partido.get('momio_1', 2.0)
    draw_odds = partido.get('momio_x', 3.5)
    away_odds = partido.get('momio_2', 3.5)
    
    total_margin = 1/home_odds + 1/draw_odds + 1/away_odds
    home_prob = (1/home_odds) / total_margin
    away_prob = (1/away_odds) / total_margin
    
    home_expected = home_prob * 2.5
    away_expected = away_prob * 2.5
    
    asian_handicap = calculate_asian_handicap(home_expected, away_expected, -0.5)
    team_goals = calculate_team_goals_prob(home_expected, away_expected)
    exact_score = calculate_exact_score(home_expected, away_expected)
    
    return {
        "partido": partido.get('local', 'Unknown') + ' vs ' + partido.get('visita', 'Unknown'),
        "expected_goals": {
            "home": round(home_expected, 2),
            "away": round(away_expected, 2)
        },
        "asian_handicap": asian_handicap,
        "team_goals": team_goals,
        "exact_score": exact_score
    }

def main():
    """Analiza todos los partidos en jornadas.json"""
    if not JORNADAS_PATH.exists():
        print("❌ Error: No existe jornadas.json")
        return []
    
    with open(JORNADAS_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    partidos = data if isinstance(data, list) else data.get('partidos', [])
    
    if not partidos:
        print("⚠️ No hay partidos para analizar")
        return []
    
    print(f"📊 Analizando {len(partidos)} partidos...")
    print("=" * 60)
    
    results = []
    for partido in partidos[:5]:
        analysis = analyze_match(partido)
        results.append(analysis)
        print(f"✅ {analysis['partido']}")
    
    print("=" * 60)
    print(f"✅ Análisis completado: {len(results)} partidos")
    
    return results

if __name__ == "__main__":
    results = main()
    if results:
        print(json.dumps(results, indent=2, ensure_ascii=False))
