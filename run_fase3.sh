#!/usr/bin/env bash
echo "🧪 FASE 3: Simulación Jornada Activa"
# 1. Genera datos de prueba con estructura idéntica a producción
python3 -c "
import json, datetime
from pathlib import Path
Path('data').mkdir(exist_ok=True)
mock = {'fixtures': [{'home':'Pachuca','away':'América','date':datetime.datetime.now().isoformat(),'odds':{'1':2.1,'X':3.3,'2':3.5}}]}
Path('data/mock_jornada_activa.json').write_text(json.dumps(mock, indent=2))
print('✅ Mock generado')
"
# 2. Fuerza al bot a leerlo y pasar safety gate
export TEST_MODE=true
export MOCK_DATA_FILE=data/mock_jornada_activa.json
python3 main.py --test-run
echo "✅ Revisa reports/reporte_survivor_ultimo.txt → debe decir CERRAR / ENVIAR"
