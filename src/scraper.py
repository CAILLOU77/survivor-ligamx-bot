import os
import json
import requests
from dotenv import load_dotenv

# Cargar la API Key desde el archivo .env de forma segura
load_dotenv()

FAILOVER_STATUS_CODES = {500, 502, 503, 504}
NO_ROTATE_STATUS_CODES = {401, 403, 429}


def key_valida(value):
    if not value:
        return False

    value = value.strip()
    return bool(value) and "AQUÍ_" not in value and "tu_api_key" not in value.lower()


def odds_api_keys():
    primary = os.getenv("ODDS_API_KEY_PRIMARY") or os.getenv("ODDS_API_KEY")
    backup = os.getenv("ODDS_API_KEY_BACKUP")

    keys = []
    seen = set()

    for label, value in [("primary", primary), ("backup", backup)]:
        if not key_valida(value):
            continue

        value = value.strip()
        if value in seen:
            continue

        keys.append((label, value))
        seen.add(value)

    return keys


def fetch_odds_with_failover(sport, regions, markets, odds_format):
    keys = odds_api_keys()

    if not keys:
        print("❌ Error: No se detectó ODDS_API_KEY_PRIMARY ni ODDS_API_KEY válida en .env")
        return None

    endpoint = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"

    for idx, (label, api_key) in enumerate(keys):
        try:
            print(f"🎰 The Odds API: intentando llave {label}...")
            response = requests.get(
                endpoint,
                params={
                    "apiKey": api_key,
                    "regions": regions,
                    "markets": markets,
                    "oddsFormat": odds_format,
                },
                timeout=30,
            )

            if response.status_code == 200:
                print(f"✅ The Odds API: conexión exitosa con llave {label}.")
                return response.json()

            if response.status_code in FAILOVER_STATUS_CODES:
                print(f"⚠️ The Odds API error técnico {response.status_code} con llave {label}.")
                if idx < len(keys) - 1:
                    print("➡️ Probando llave backup por falla técnica del servidor.")
                    continue
                print("❌ The Odds API sigue con error técnico. No hay más llaves de respaldo.")
                return None

            if response.status_code in NO_ROTATE_STATUS_CODES:
                print(
                    f"⛔ The Odds API respondió {response.status_code}. "
                    "No se rota llave por auth/cuota/rate limit."
                )
                return None

            print(f"❌ Error The Odds API ({response.status_code}): {response.text[:300]}")
            return None

        except (requests.Timeout, requests.ConnectionError) as exc:
            print(f"⚠️ Falla técnica de red con The Odds API usando llave {label}: {type(exc).__name__}")
            if idx < len(keys) - 1:
                print("➡️ Probando llave backup por timeout/conexión.")
                continue
            print("❌ The Odds API no respondió y no hay más backup.")
            return None

    return None

def obtener_datos_mercado():
    print("📈 Bot: Revisando estado del mercado/momios...")
    
    # Parámetros de conexión oficiales para la Liga MX en The Odds API
    SPORT = "soccer_mexico_ligamx"
    REGIONS = "us"  # Región que incluye las casas operantes en México
    MARKETS = "h2h" # Mercado 1X2 (Local, Empate, Visitante)
    ODDS_FORMAT = "decimal"

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
        partidos_reales = fetch_odds_with_failover(SPORT, REGIONS, MARKETS, ODDS_FORMAT)

        if partidos_reales is None:
            return None
        
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
            
            jornada_procesada.append(partido_limpio)

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
