import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.telegram_pronosticos import _plan_temporada, _rec_desde_plan

plan = _plan_temporada([])
print('=== PLAN COMPLETO ===')
for j in sorted(plan.keys()):
    eq = plan[j]
    if isinstance(eq, str) and 'leon' in eq.lower():
        print(f'  J{j}: {eq}  <--- LEÓN')
    else:
        print(f'  J{j}: {eq}')

# Ver si León aparece
found = any(isinstance(eq, str) and 'leon' in eq.lower() for eq in plan.values())
if found:
    print('\\n✅ León SÍ está en el plan')
else:
    print('\\n❌ León NO está en el plan')
