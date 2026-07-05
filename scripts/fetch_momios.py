#!/usr/bin/env python3
"""
fetch_momios.py — Baja los momios de Liga MX y los guarda en data/momios.json.

Fuente: odds-api.io (el proveedor ya configurado por ODDS_API_IO_KEY). Baja los
TRES mercados más importantes por partido:
    - 1X2 (ML)         -> el que mueve el pick de Survivor (quién gana / no pierde)
    - Over/Under 2.5   -> totales, para los picks generales
    - Hándicap asiático -> qué tan favorito es un equipo

Guarda un snapshot en data/momios.json con timestamp. El pick (/picks) y el plan
(/plan) usan esos momios automáticamente: en vivo si hay, o desde este archivo
como respaldo (caché) mientras el proveedor no publique líneas nuevas.

Uso:
    python3 scripts/fetch_momios.py

Reglas del proyecto: datos reales, nada inventado. Sin ODDS_API_IO_KEY no baja
nada (no falla, solo avisa). Informativo / revisión humana.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import comparador_mercado as cm  # noqa: E402


def main() -> int:
    print("💰 Bajando momios de Liga MX (odds-api.io con key, o Pinnacle/ESPN gratis)...")
    momios, fuente = cm.momios_para_uso(guardar_si_hay=True, incluir_gratis=True)
    if not momios:
        print("ℹ️  Todavía no hay líneas publicadas (ni odds-api.io ni ESPN).")
        print("    Vuelve a intentarlo más cerca de los partidos.")
        return 0

    n_ml = sum(1 for m in momios.values() if m.get("ml"))
    n_tot = sum(1 for m in momios.values() if m.get("totals"))
    n_hdp = sum(1 for m in momios.values() if m.get("handicap"))
    print(f"✅ {len(momios)} partidos desde {fuente} (guardados en data/momios.json)")
    print(f"   1X2: {n_ml} · Over/Under: {n_tot} · Hándicap: {n_hdp}")
    print("   El pick y el plan ya los usarán (en vivo o desde este archivo).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
