#!/usr/bin/env python3
"""Corrige el CAS para comparar el valor crudo persistido del lease."""
from pathlib import Path

path = Path("scripts/finalize_telegram_idempotency.py")
text = path.read_text(encoding="utf-8")
old_lease = '''        lease = fila[1]
        if isinstance(lease, str):'''
new_lease = '''        lease = fila[1]
        lease_original = lease
        if isinstance(lease, str):'''
old_param = '''            parametros = (locked_until, valor, completado, lease)'''
new_param = '''            parametros = (locked_until, valor, completado, lease_original)'''
if old_lease not in text or old_param not in text:
    raise RuntimeError("No se encontraron los puntos CAS esperados")
text = text.replace(old_lease, new_lease, 1).replace(old_param, new_param, 1)
path.write_text(text, encoding="utf-8")
