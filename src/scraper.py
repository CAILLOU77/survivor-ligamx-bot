import os
import json
import requests
from dotenv import load_dotenv

# Cargar la API Key desde el archivo .env de forma segura
load_dotenv()
API_KEY = os.getenv("ODDS_API_KEY")

def obtener_datos_mercado():
    print("📈 Bot: Revisando estado del mercado/momios...")
    
    if not API_KEY or "AQUÍ_" in API_KEY:
        print("❌ Error: No se ha detectado una API Key válida en tu archivo .env")
        return None

    # Parámetros de conexión oficiales para la Liga MX en The Odds API
    SPORT = "soccer_mexico_ligamx"
    REGIONS = "us"  # Región que incluye las casas operantes en México
    MARKETS = "h2h" # Mercado 1X2 (Local, Empate, Visitante)
    ODDS_FORMAT = "decimal"

    url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds/?apiKey={API_KEY}&regions={REGIONS}&markets={MARKETS}&oddsFormat={ODDS_FORMAT}"
    
    # Base de datos local de Estadios y Altitudes para enriquecer la información
    DATOS_ESTADIOS = {
        "Club América": {"estadio": "Estadio Azteca", "altitud_metros": 2240},
        "Cruz Azul": {"estadio": "Estadio Ciudad de los Deportes", "altitud_metros": 2240},
        "Chivas Guadalajara": {"estadio": "Estadio Akron", "andres_metros": 1566},
        "Tigres UANL": {"estadio": "Estadio Universitario", "altitud_metros": 540},
        "Monterrey": {"estadio": "Estadio BBVA", "altitud_metros": 540},
        "Pumas UNAM": {"estadio": "Estadio Olímpico Universitario", "altitud_metros": 2240},
        "Toluca": {"estadio": "Estadio Nemesio Díez", "altitud_metros": 2660},
        "Tijuana": {"estadio": "Estadio Caliente", "altitud_metros": 20}
    }

    try:
        response = requests.get(url)
        
        if response.status_code != 200:
            print(f"❌ Error del servidor de apuestas ({response.status_code}): {response.text}")
            return None
            
        partidos_reales = response.json()
        
        if not partidos_reales:
            print("⚠️ Nota: The Odds API aún no publica mercado real para la jornada actual.")
            return None

        jornada_procesada = []
        
        for partido in partidos_reales:
            local = partido.get("home_team")
            visita = partido.get("away_team")
            
            bookmakers = partido.get("bookmakers", [])
            if not bookmakers:
                continue
                
            outcomes = bookmakers[0].get("markets", [])[0].get("outcomes", [])
            
            partido_limpio = {
                "home_team": local,
                "away_team": visita,
                "bookmakers": {
                    "markets": {
                        "outcomes": outcomes
                    }
                }
            }
            
            info_estadio = DATOS_ESTADIOS.get(local, {"estadio": "Estadio Local", "altitud_metros": 500})
            partido_limpio["estadio_nombre"] = info_estadio["estadio"]
            partido_limpio["altitud_estadio"] = info_estadio["altitud_metros"]
            
            jornada_processed.append(partido_limpio)

        os.makedirs('data', exist_ok=True)
        with open('data/jornadas.json', 'w', encoding='utf-8') as f:
            json.dump(jornada_procesada, f, indent=4, ensure_ascii=False)
            
        print(f"✅ Bot: Se descargaron e integraron {len(jornada_procesada)} partidos reales del mercado.")
        return jornada_procesada

    except Exception as e:
        print(f"❌ Error en la conexión en tiempo real: {e}")
        return None

if __name__ == "__main__":
    obtener_datos_mercado()
