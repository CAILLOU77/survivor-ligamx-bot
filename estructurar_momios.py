import csv
from collections import defaultdict

INPUT = 'ligamx_clean.csv'
OUTPUT = 'momios_1x2_estructurados.csv'

mercados = defaultdict(list)
with open(INPUT, 'r', encoding='utf-8') as f:
    for row in csv.DictReader(f):
        mercados[row['id_mercado']].append(row)

resultados = []
for mid, sels in mercados.items():
    if len(sels) < 2: continue
    momios = [float(s['momio']) for s in sels]
    margen = round((sum(1/m for m in momios) - 1) * 100, 2)
    sels.sort(key=lambda x: float(x['momio']))

    fila = {'id_mercado': mid, 'id_liga': sels[0]['id_liga'], 'num_opciones': len(sels), 'margen_casa_pct': margen, 'timestamp': sels[0]['timestamp']}
    for i, s in enumerate(sels, 1):
        fila[f'opcion_{i}_id'] = s['id_seleccion']
        fila[f'opcion_{i}_momio'] = s['momio']
        fila[f'opcion_{i}_prob'] = s['prob_implied_pct']
        fila[f'opcion_{i}_tendencia'] = s['tendencia']
    resultados.append(fila)

# FIX: Calcular TODAS las columnas posibles antes de escribir
base_keys = ['id_mercado', 'id_liga', 'num_opciones', 'margen_casa_pct', 'timestamp']
all_keys = set(base_keys)
for r in resultados: all_keys.update(r.keys())
fieldnames = base_keys + sorted([k for k in all_keys if k not in base_keys])

# Rellenar vacíos para evitar ValueError
for r in resultados:
    for k in fieldnames: r.setdefault(k, '')

with open(OUTPUT, 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    w.writerows(resultados)
print(f'✅ {len(resultados)} mercados estructurados → {OUTPUT}')
