#!/usr/bin/env python3
"""
Auto-Update System - Mantener datos frescos automáticamente
"""
import subprocess
import sys
import os
import json
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")

def ensure_jornadas_file():
    """Asegura que exista jornadas.json con estructura válida"""
    jornadas_path = BASE_DIR / "data" / "jornadas.json"
    if not jornadas_path.exists():
        jornadas_path.parent.mkdir(parents=True, exist_ok=True)
        with open(jornadas_path, 'w') as f:
            json.dump({
                "jornadas": [],
                "partidos": [],
                "ultima_actualizacion": None
            }, f, indent=2)
        log("📝 Archivo jornadas.json creado")

def run_script(script_name, description, args=None):
    log(f"🔄 {description}")
    try:
        cmd = [sys.executable, f"src/{script_name}"]
        if args:
            cmd.extend(args)
        
        result = subprocess.run(
            cmd,
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode == 0:
            log(f"✅ {description} - OK")
            return True, result.stdout
        else:
            log(f"❌ {description} - Error: {result.stderr[:200]}")
            return False, result.stderr
    except subprocess.TimeoutExpired:
        log(f"⏱️ {description} - Timeout")
        return False, "Timeout"
    except Exception as e:
        log(f"❌ {description} - Exception: {e}")
        return False, str(e)

def main():
    log("=" * 60)
    log("INICIANDO ACTUALIZACIÓN AUTOMÁTICA DE DATOS")
    log("=" * 60)
    
    # Asegurar que existe el archivo
    ensure_jornadas_file()
    
    results = {}
    
    # 1. Sincronizar fixtures desde API-Football con --apply para escribir a jornadas.json
    results['fixtures'] = run_script(
        "api_football_fixtures_sync.py",
        "Sincronizando fixtures API-Football",
        args=["--apply"]
    )
    
    # 2. Sincronizar cuotas desde The Odds API (ahora tiene datos en jornadas.json)
    results['odds'] = run_script(
        "sync_odds_api.py",
        "Sincronizando cuotas The Odds API"
    )
    
    # 3. Procesar datos de confianza
    results['confidence'] = run_script(
        "data_confidence.py",
        "Procesando análisis de confianza"
    )
    
    log("=" * 60)
    success_count = sum(1 for r in results.values() if r[0])
    total_count = len(results)
    
    if success_count == total_count:
        log(f"✅ ACTUALIZACIÓN COMPLETA ({success_count}/{total_count})")
    else:
        log(f"⚠️ ACTUALIZACIÓN PARCIAL ({success_count}/{total_count})")
    
    log("=" * 60)
    return success_count == total_count

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
