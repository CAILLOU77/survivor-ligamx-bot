import csv
from pathlib import Path

INPUT = Path('momios_finales.csv')

print(f"{'MERCADO':<12} | {'MOMIOS':<20} | {'VIG%':<6} | {'PROB_IMP':<12} | {'SEÑAL'}")
print('-'*75)

with open(INPUT, 'r', encoding='utf-8') as f:
    for r in csv.DictReader(f):
        try:
            momios = [float(r[f'momio_{i}']) for i in range(1,4) if r.get(f'momio_{i}','').strip()]
            if len(momios) < 2: continue

            prob_imp = [1/m for m in momios]
            vig = (sum(prob_imp) - 1) * 100

            m_str = ' | '.join([f'{m:.2f}' for m in momios])
            p_str = ' | '.join([f'{p*100:.1f}%' for p in prob_imp])

            # Señal educativa: vig baja + momio alto = posible valor
            senal = '🟢 +EV POTENCIAL' if vig < 7.5 and max(momios) > 2.8 else '⚪ Neutral'

            print(f"{r['id_mercado']:<12} | {m_str:<20} | {vig:<6.2f} | {p_str:<12} | {senal}")
        except: continue
