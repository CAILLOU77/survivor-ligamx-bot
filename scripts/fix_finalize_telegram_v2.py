#!/usr/bin/env python3
"""Prepara el valor crudo del lease y el parche CAS final."""
from pathlib import Path

# El valor crudo evita diferencias de serialización SQLite (T vs espacio).
db_path = Path("src/database.py")
db = db_path.read_text(encoding="utf-8")
old_db = '''        lease = fila[1]
        if isinstance(lease, str):'''
new_db = '''        lease_original = fila[1]
        lease = lease_original
        if isinstance(lease, str):'''
if old_db not in db:
    raise RuntimeError("No se encontró la lectura del lease en database.py")
db_path.write_text(db.replace(old_db, new_db, 1), encoding="utf-8")

# El parche final debe comparar contra el valor exacto leído del backend.
path = Path("scripts/finalize_telegram_idempotency.py")
text = path.read_text(encoding="utf-8")
old_param = '''            parametros = (locked_until, valor, completado, lease)'''
new_param = '''            parametros = (locked_until, valor, completado, lease_original)'''
if old_param not in text:
    raise RuntimeError("No se encontró el parámetro CAS en el parche final")
path.write_text(text.replace(old_param, new_param, 1), encoding="utf-8")
# trigger v3: limpieza tolerante
