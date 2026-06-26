#!/usr/bin/env python3
"""
team_normalizer.py — normalización central de equipos Liga MX.

Objetivo:
- Tener una sola fuente de verdad para limpiar, comparar y mostrar nombres.
- Evitar duplicación entre momios, FBref y watchdog/API odds.
- No cambia picks.
- No envía Telegram.
- No toca .env, data/, reports/ ni results/.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Set, Tuple


ALIAS_GROUPS: List[Tuple[str, List[str]]] = [
    ("america", ["america", "américa", "club america", "club américa", "cf america", "club de futbol america"]),
    ("guadalajara", ["guadalajara", "chivas", "cd guadalajara", "chivas guadalajara"]),
    ("cruz azul", ["cruz azul"]),
    ("tigres uanl", ["tigres", "uanl", "tigres uanl"]),
    ("pumas unam", ["pumas", "unam", "pumas unam"]),
    ("monterrey", ["monterrey", "rayados", "cf monterrey"]),
    ("toluca", ["toluca", "deportivo toluca"]),
    ("tijuana", ["tijuana", "xolos", "club tijuana", "tijuana xolos de caliente"]),
    ("atlas", ["atlas"]),
    ("leon", ["leon", "león", "club leon", "club león"]),
    ("pachuca", ["pachuca"]),
    ("santos", ["santos", "santos laguna"]),
    ("queretaro", ["queretaro", "querétaro", "queretaro fc", "querétaro fc", "gallos"]),
    ("puebla", ["puebla"]),
    ("necaxa", ["necaxa"]),
    ("mazatlan", ["mazatlan", "mazatlán", "mazatlan fc", "mazatlán fc"]),
    ("atletico de san luis", ["atletico de san luis", "atlético de san luis", "atletico san luis", "atlético san luis", "san luis", "atl san luis"]),
    ("juarez", ["juarez", "juárez", "fc juarez", "fc juárez", "bravos"]),
    ("atlante", ["atlante"]),
]

DISPLAY: Dict[str, str] = {
    "america": "América",
    "guadalajara": "Guadalajara",
    "cruz azul": "Cruz Azul",
    "tigres uanl": "Tigres UANL",
    "pumas unam": "Pumas UNAM",
    "monterrey": "Monterrey",
    "toluca": "Toluca",
    "tijuana": "Tijuana",
    "atlas": "Atlas",
    "leon": "León",
    "pachuca": "Pachuca",
    "santos": "Santos",
    "queretaro": "Querétaro",
    "puebla": "Puebla",
    "necaxa": "Necaxa",
    "mazatlan": "Mazatlán",
    "atletico de san luis": "Atlético de San Luis",
    "juarez": "FC Juarez",
    "atlante": "Atlante",
}

PREFIXES = ("club ", "cf ", "fc ", "cd ", "deportivo ")


def strip_accents(text: str) -> str:
    """Quita acentos sin cambiar el resto del texto."""
    normalized = unicodedata.normalize("NFD", str(text or ""))
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def clean_team_name(name: str) -> str:
    """Minúsculas, sin acentos, puntuación normalizada y espacios colapsados."""
    text = strip_accents(str(name or "")).lower()
    text = re.sub(r"[._/'-]", " ", text)
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return " ".join(text.split())


_ALIAS_LOOKUP: Dict[str, str] = {}
for _canonical, _variants in ALIAS_GROUPS:
    _ALIAS_LOOKUP[clean_team_name(_canonical)] = _canonical
    for _variant in _variants:
        _ALIAS_LOOKUP[clean_team_name(_variant)] = _canonical


def canonical_team_key(name: str) -> str:
    """
    Clave canónica para comparación interna.

    Ejemplos:
    - América / Club America -> america
    - Chivas -> guadalajara
    - FC Juárez -> juarez
    - Tijuana Xolos de Caliente -> tijuana
    """
    cleaned = clean_team_name(name)

    if cleaned in _ALIAS_LOOKUP:
        return _ALIAS_LOOKUP[cleaned]

    for prefix in PREFIXES:
        if cleaned.startswith(prefix):
            without_prefix = cleaned[len(prefix):].strip()
            return _ALIAS_LOOKUP.get(without_prefix, without_prefix)

    return cleaned


def display_team_name(name: str) -> str:
    """Nombre visible canónico cuando se conoce; si no, conserva el original limpio."""
    key = canonical_team_key(name)
    return DISPLAY.get(key, str(name or "").strip())


def team_aliases(name: str) -> Set[str]:
    """Devuelve alias limpios para comparación flexible."""
    cleaned = clean_team_name(name)
    canonical = canonical_team_key(name)

    aliases = {cleaned, canonical}

    for prefix in PREFIXES:
        if cleaned.startswith(prefix):
            aliases.add(cleaned[len(prefix):].strip())

    for group_canonical, variants in ALIAS_GROUPS:
        if canonical == group_canonical:
            aliases.add(clean_team_name(group_canonical))
            aliases.update(clean_team_name(v) for v in variants)

    return {a for a in aliases if a}


def teams_match(a: str, b: str) -> bool:
    """Comparación tolerante por alias y contención segura."""
    aliases_a = team_aliases(a)
    aliases_b = team_aliases(b)

    if aliases_a & aliases_b:
        return True

    for x in aliases_a:
        for y in aliases_b:
            if x and y and (x in y or y in x):
                return True

    return False


# Alias semántico para módulos que solo necesitan clave de comparación.
normalize_team_name = canonical_team_key
