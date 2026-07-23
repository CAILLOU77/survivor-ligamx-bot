#!/usr/bin/env python3
"""Corrige el parche generador para editar solo registrar_pick_recomendado."""
from pathlib import Path

path = Path("scripts/apply_pick_lifecycle_v2.py")
text = path.read_text(encoding="utf-8")
old = 'text = text.replace(norm_line, norm_new, 1)'
new = '''registrar_pos = text.index("def registrar_pick_recomendado(")
text = text[:registrar_pos] + text[registrar_pos:].replace(norm_line, norm_new, 1)'''
if old not in text:
    raise RuntimeError("No se encontró el reemplazo ambiguo")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
