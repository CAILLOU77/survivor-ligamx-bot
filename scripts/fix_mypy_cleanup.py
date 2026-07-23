#!/usr/bin/env python3
from pathlib import Path

path = Path("src/database.py")
text = path.read_text(encoding="utf-8")
old = '''        if estado == "fallido":
            condicion_reclamo = "status='fallido'"
            parametros = (locked_until, valor, completado)'''
new = '''        parametros: tuple[Any, ...]
        if estado == "fallido":
            condicion_reclamo = "status='fallido'"
            parametros = (locked_until, valor, completado)'''
if old not in text:
    raise RuntimeError("No se encontró el bloque CAS para tipar")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
# trigger v3: limpiar antes del gate estructural
