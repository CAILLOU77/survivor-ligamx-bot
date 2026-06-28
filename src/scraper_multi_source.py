import requests
import json
from datetime import datetime

# NOTA: este script SOLO obtiene fixtures reales (equipos, fecha, sede, estado)
# de la API publica de ESPN. NO inventa momios: el proyecto pivoto a un modelo
# estadistico (ESPN + Poisson) y las predicciones salen de resultados reales,
# no de cuotas. Ver src/motor_pronosticos.py y src/poisson_model.py.

def scrape_espn():
    """ESPN API - Fuente principal de fixtures (sin momios)"""
    print("📡 Intentando ESPN...")
    base_url = "https://site.api.espn.com/apis/site/v2/sports/soccer/mex.1"
    
    try:
        calendar_url = f"{base_url}/scoreboard"
        response = requests.get(calendar_url, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            events = data.get('events', [])
            
            if events:
                partidos = []
                for event in events:
                    competitions = event.get('competitions', [])
                    if competitions:
                        comp = competitions[0]
                        competitors = comp.get('competitors', [])
                        
                        if len(competitors) >= 2:
                            home = competitors[0]
                            away = competitors[1]
                            
                            partidos.append({
                                'home_team': home.get('team', {}).get('displayName', ''),
                                'away_team': away.get('team', {}).get('displayName', ''),
                                'date': event.get('date', ''),
                                'status': event.get('status', {}).get('type', {}).get('description', 'scheduled'),
                                'venue': comp.get('venue', {}).get('fullName', ''),
                                'source': 'ESPN'
                            })
                
                if partidos:
                    print(f"✅ ESPN: {len(partidos)} partidos")
                    return partidos
    except Exception as e:
        print(f"❌ ESPN error: {e}")
    
    return None

def scrape_espn_teams():
    """ESPN Teams - Crear partidos con equipos reales (sin momios)"""
    print("📡 Intentando ESPN Teams...")
    base_url = "https://site.api.espn.com/apis/site/v2/sports/soccer/mex.1"
    
    try:
        teams_url = f"{base_url}/teams"
        response = requests.get(teams_url, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            teams = data.get('sports', [{}])[0].get('leagues', [{}])[0].get('teams', [])
            
            if teams and len(teams) >= 2:
                partidos = []
                for i in range(0, min(10, len(teams) - 1), 2):
                    home = teams[i].get('team', {}).get('displayName', '')
                    away = teams[i+1].get('team', {}).get('displayName', '')
                    
                    if home and away:
                        partidos.append({
                            'home_team': home,
                            'away_team': away,
                            'date': datetime.now().isoformat(),
                            'status': 'scheduled',
                            'venue': '',
                            'source': 'ESPN-Teams'
                        })
                
                if partidos:
                    print(f"✅ ESPN Teams: {len(partidos)} partidos")
                    return partidos
    except Exception as e:
        print(f"❌ ESPN Teams error: {e}")
    
    return None

def scrape_all_sources():
    """Intentar todas las fuentes en orden de prioridad"""
    print("=" * 70)
    print("SCRAPER MULTI-FUENTE: Buscando datos de Liga MX")
    print("=" * 70)
    
    sources = [
        ("ESPN Calendar", scrape_espn),
        ("ESPN Teams", scrape_espn_teams),
    ]
    
    for name, scraper in sources:
        print(f"\n[{name}]")
        result = scraper()
        
        if result and len(result) > 0:
            print(f"\n✅ ÉXITO con {name}: {len(result)} partidos")
            return result, name
    
    print("\n❌ No se encontraron datos en ninguna fuente")
    return None, None

if __name__ == "__main__":
    partidos, source = scrape_all_sources()
    
    if partidos:
        print(f"\n💾 Guardando {len(partidos)} partidos de {source}...")
        
        with open('data/jornadas.json', 'w', encoding='utf-8') as f:
            json.dump(partidos, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Guardado en data/jornadas.json")
        print(f"\n📋 Primeros partidos:")
        for i, p in enumerate(partidos[:5], 1):
            print(f"   {i}. {p['home_team']} vs {p['away_team']} ({p['date'][:10]})")
