#!/usr/bin/env python3
"""Debug: ejecutar scraper y mostrar output completo"""
import subprocess
import sys
import os

def main():
    print("=" * 60)
    print("DEBUG: Ejecutando scraper con output completo")
    print("=" * 60)
    
    result = subprocess.run(
        [sys.executable, "src/scraper.py"],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    
    print("\n📤 STDOUT:")
    print(result.stdout)
    
    print("\n📥 STDERR:")
    print(result.stderr)
    
    print(f"\n🔢 Return code: {result.returncode}")
    
    # Verificar si se creó/modificó jornadas.json
    jornadas_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "jornadas.json")
    if os.path.exists(jornadas_path):
        import json
        with open(jornadas_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if isinstance(data, list):
            print(f"\n📊 jornadas.json tiene {len(data)} partidos (lista)")
        else:
            partidos = data.get('partidos', [])
            print(f"\n📊 jornadas.json tiene {len(partidos)} partidos (dict)")
    else:
        print("\n❌ jornadas.json no existe")
    
    print("=" * 60)
    return result.returncode

if __name__ == "__main__":
    sys.exit(main())
