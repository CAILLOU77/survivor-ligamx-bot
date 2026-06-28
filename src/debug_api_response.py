#!/usr/bin/env python3
"""Debug: Ver respuesta cruda de The Odds API"""
import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

def debug_api():
    print("=" * 60)
    print("DEBUG: Respuesta cruda de The Odds API")
    print("=" * 60)
    
    # Obtener API key
    api_key = os.getenv("ODDS_API_KEY_PRIMARY") or os.getenv("ODDS_API_KEY")
    
    if not api_key:
        print("❌ No se encontró ODDS_API_KEY_PRIMARY ni ODDS_API_KEY")
        return
    
    print(f"✅ API Key encontrada: {api_key[:10]}...")
    
    # Parámetros
    SPORT = "soccer_mexico_ligamx"
    REGIONS = "us"
    MARKETS = "h2h"
    ODDS_FORMAT = "decimal"
    
    endpoint = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds/"
    
    print(f"\n🌐 Endpoint: {endpoint}")
    print(f"📊 Parámetros: sport={SPORT}, regions={REGIONS}, markets={MARKETS}")
    
    try:
        response = requests.get(
            endpoint,
            params={
                "apiKey": api_key,
                "regions": REGIONS,
                "markets": MARKETS,
                "oddsFormat": ODDS_FORMAT,
            },
            timeout=30,
        )
        
        print(f"\n📡 Status Code: {response.status_code}")
        print(f"📦 Response Headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"\n✅ Respuesta exitosa")
            print(f"📊 Tipo de datos: {type(data)}")
            print(f"📊 Cantidad de partidos: {len(data) if isinstance(data, list) else 'N/A'}")
            
            if isinstance(data, list) and len(data) > 0:
                print(f"\n📋 Primer partido:")
                print(json.dumps(data[0], indent=2, ensure_ascii=False)[:500])
                
                # Guardar respuesta completa para análisis
                with open('data/debug_api_response.json', 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                print(f"\n💾 Respuesta completa guardada en data/debug_api_response.json")
            else:
                print(f"\n⚠️ La API respondió pero no hay partidos")
                print(f"📦 Respuesta cruda: {json.dumps(data, indent=2, ensure_ascii=False)[:500]}")
        else:
            print(f"\n❌ Error en la respuesta")
            print(f"📦 Response Text: {response.text[:500]}")
    
    except Exception as e:
        print(f"\n❌ Excepción: {type(e).__name__}: {e}")
    
    print("=" * 60)

if __name__ == "__main__":
    debug_api()
