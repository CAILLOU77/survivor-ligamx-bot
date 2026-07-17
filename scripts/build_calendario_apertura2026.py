#!/usr/bin/env python3
"""
build_calendario_apertura2026.py — Genera data/calendario.json (Apertura 2026).

Fuente: calendario OFICIAL Liga MX BBVA Apertura 2026 (PDF oficial subido al
repo). Los emparejamientos se transcribieron leyendo los logos de cada partido
en el PDF, página por página, y se verificaron contra los fixtures públicos de
proveedores (ESPN/365scores) para la jornada 1. NO es scraping ni datos
inventados: es la transcripción fiel del calendario oficial.

Liga MX Apertura 2026: 18 equipos, 17 jornadas (fase regular, una vuelta).
NOTA: Atlante regresa a Liga MX comprando la franquicia de Mazatlán FC, así que
en este torneo juega Atlante (NO Mazatlán). El histórico de ESPN aún no tiene a
Atlante, por lo que el planificador lo omitirá hasta que haya partidos reales.

Los nombres de equipo usan EXACTAMENTE los que devuelve ESPN (incluye "FC Juarez"
sin acento), porque poisson_model._norm solo pasa a minúsculas/colapsa espacios
y NO quita acentos. Si cambias un nombre, debe seguir casando con el histórico.

Uso:
    python3 scripts/build_calendario_apertura2026.py            # escribe
    python3 scripts/build_calendario_apertura2026.py --dry-run  # solo valida
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

BASE_DIR = Path(__file__).resolve().parents[1]
CALENDARIO_PATH = BASE_DIR / "data" / "calendario.json"

# Los 18 equipos del Apertura 2026 con el nombre EXACTO del histórico ESPN.
EQUIPOS = {
    "América",
    "Atlante",
    "Atlas",
    "Atlético de San Luis",
    "Cruz Azul",
    "FC Juarez",
    "Guadalajara",
    "León",
    "Monterrey",
    "Necaxa",
    "Pachuca",
    "Puebla",
    "Pumas UNAM",
    "Querétaro",
    "Santos",
    "Tigres UANL",
    "Tijuana",
    "Toluca",
}

# (local, visitante) por jornada — transcrito del PDF oficial (orden = orden del PDF).
JORNADAS: List[List[Tuple[str, str]]] = [
    # J1
    [
        ("Necaxa", "Atlante"),
        ("Tijuana", "Tigres UANL"),
        ("Atlético de San Luis", "Cruz Azul"),
        ("León", "Atlas"),
        ("FC Juarez", "Puebla"),
        ("Pumas UNAM", "Pachuca"),
        ("Guadalajara", "Toluca"),
        ("Monterrey", "Santos"),
        ("Querétaro", "América"),
    ],
    # J2
    [
        ("Cruz Azul", "Puebla"),
        ("Toluca", "Pumas UNAM"),
        ("Tigres UANL", "Atlético de San Luis"),
        ("Atlante", "América"),
        ("Tijuana", "León"),
        ("Guadalajara", "FC Juarez"),
        ("Santos", "Atlas"),
        ("Necaxa", "Monterrey"),
        ("Pachuca", "Querétaro"),
    ],
    # J3
    [
        ("Puebla", "Guadalajara"),
        ("Atlético de San Luis", "Tijuana"),
        ("FC Juarez", "Pumas UNAM"),
        ("Querétaro", "Tigres UANL"),
        ("León", "Pachuca"),
        ("Atlas", "Monterrey"),
        ("Cruz Azul", "Atlante"),
        ("América", "Santos"),
        ("Toluca", "Necaxa"),
    ],
    # J4
    [
        ("Atlante", "Toluca"),
        ("Monterrey", "FC Juarez"),
        ("Atlas", "Tigres UANL"),
        ("Pumas UNAM", "Querétaro"),
        ("América", "Atlético de San Luis"),
        ("Santos", "Guadalajara"),
        ("Tijuana", "Cruz Azul"),
        ("Necaxa", "León"),
        ("Pachuca", "Puebla"),
    ],
    # J5
    [
        ("Puebla", "Santos"),
        ("FC Juarez", "América"),
        ("Querétaro", "Toluca"),
        ("Guadalajara", "Tijuana"),
        ("León", "Monterrey"),
        ("Tigres UANL", "Atlante"),
        ("Cruz Azul", "Atlas"),
        ("Atlético de San Luis", "Pachuca"),
        ("Pumas UNAM", "Necaxa"),
    ],
    # J6
    [
        ("Necaxa", "Cruz Azul"),
        ("Atlante", "León"),
        ("Tijuana", "Pumas UNAM"),
        ("Atlas", "Querétaro"),
        ("Pachuca", "Guadalajara"),
        ("América", "Puebla"),
        ("Santos", "Tigres UANL"),
        ("Toluca", "FC Juarez"),
        ("Monterrey", "Atlético de San Luis"),
    ],
    # J7
    [
        ("Puebla", "Toluca"),
        ("FC Juarez", "Pachuca"),
        ("Atlético de San Luis", "Guadalajara"),
        ("Querétaro", "Monterrey"),
        ("Tigres UANL", "Necaxa"),
        ("América", "Tijuana"),
        ("Atlas", "Atlante"),
        ("Pumas UNAM", "León"),
        ("Cruz Azul", "Santos"),
    ],
    # J8
    [
        ("Necaxa", "Puebla"),
        ("Atlante", "Pachuca"),
        ("Tijuana", "Querétaro"),
        ("León", "Atlético de San Luis"),
        ("Toluca", "Atlas"),
        ("Cruz Azul", "América"),
        ("Santos", "FC Juarez"),
        ("Guadalajara", "Pumas UNAM"),
        ("Monterrey", "Tigres UANL"),
    ],
    # J9
    [
        ("Puebla", "Atlante"),
        ("FC Juarez", "Tigres UANL"),
        ("Atlas", "Pumas UNAM"),
        ("Atlético de San Luis", "Necaxa"),
        ("Monterrey", "Cruz Azul"),
        ("América", "Guadalajara"),
        ("Pachuca", "Tijuana"),
        ("Toluca", "Santos"),
        ("Querétaro", "León"),
    ],
    # J10
    [
        ("Atlante", "Monterrey"),
        ("Tijuana", "Atlas"),
        ("Guadalajara", "Querétaro"),
        ("Santos", "Pachuca"),
        ("Tigres UANL", "Puebla"),
        ("Cruz Azul", "Toluca"),
        ("Pumas UNAM", "Atlético de San Luis"),
        ("León", "FC Juarez"),
        ("Necaxa", "América"),
    ],
    # J11
    [
        ("Querétaro", "Atlante"),
        ("Puebla", "León"),
        ("Tigres UANL", "Toluca"),
        ("FC Juarez", "Tijuana"),
        ("Atlas", "Guadalajara"),
        ("América", "Monterrey"),
        ("Pachuca", "Necaxa"),
        ("Atlético de San Luis", "Santos"),
        ("Pumas UNAM", "Cruz Azul"),
    ],
    # J12
    [
        ("Necaxa", "Atlas"),
        ("Atlante", "Pumas UNAM"),
        ("Tijuana", "Puebla"),
        ("Guadalajara", "Tigres UANL"),
        ("Santos", "Querétaro"),
        ("León", "América"),
        ("Toluca", "Atlético de San Luis"),
        ("Cruz Azul", "FC Juarez"),
        ("Monterrey", "Pachuca"),
    ],
    # J13
    [
        ("Atlético de San Luis", "Querétaro"),
        ("FC Juarez", "Atlante"),
        ("Tigres UANL", "León"),
        ("Guadalajara", "Necaxa"),
        ("Puebla", "Monterrey"),
        ("Atlas", "América"),
        ("Toluca", "Tijuana"),
        ("Pachuca", "Cruz Azul"),
        ("Santos", "Pumas UNAM"),
    ],
    # J14
    [
        ("Necaxa", "FC Juarez"),
        ("Atlante", "Atlético de San Luis"),
        ("León", "Toluca"),
        ("Monterrey", "Guadalajara"),
        ("Pumas UNAM", "Tigres UANL"),
        ("Atlas", "Puebla"),
        ("América", "Pachuca"),
        ("Querétaro", "Cruz Azul"),
        ("Tijuana", "Santos"),
    ],
    # J15
    [
        ("Atlético de San Luis", "Atlas"),
        ("FC Juarez", "Querétaro"),
        ("Puebla", "Pumas UNAM"),
        ("Pachuca", "Tigres UANL"),
        ("Guadalajara", "Atlante"),
        ("Monterrey", "Tijuana"),
        ("América", "Toluca"),
        ("Santos", "Necaxa"),
        ("Cruz Azul", "León"),
    ],
    # J16
    [
        ("Atlético de San Luis", "FC Juarez"),
        ("Necaxa", "Tijuana"),
        ("Atlante", "Santos"),
        ("Atlas", "Pachuca"),
        ("Tigres UANL", "Cruz Azul"),
        ("Toluca", "Monterrey"),
        ("Pumas UNAM", "América"),
        ("Querétaro", "Puebla"),
        ("León", "Guadalajara"),
    ],
    # J17
    [
        ("Puebla", "Atlético de San Luis"),
        ("FC Juarez", "Atlas"),
        ("Tijuana", "Atlante"),
        ("Santos", "León"),
        ("Pachuca", "Toluca"),
        ("Pumas UNAM", "Monterrey"),
        ("Tigres UANL", "América"),
        ("Guadalajara", "Cruz Azul"),
        ("Querétaro", "Necaxa"),
    ],
]

# Rango de fechas (inicio, fin) por jornada, transcrito del PDF oficial.
# Todas en 2026. Formato ISO (YYYY-MM-DD).
FECHAS: List[Tuple[str, str]] = [
    ("2026-07-16", "2026-07-18"),  # J1  16,17,18 jul
    ("2026-07-21", "2026-07-26"),  # J2  21,24,25,26 jul
    ("2026-07-31", "2026-08-02"),  # J3  31 jul, 1, 2 ago
    ("2026-08-15", "2026-08-17"),  # J4  15,16,17 ago
    ("2026-08-21", "2026-08-23"),  # J5  21,22,23 ago
    ("2026-08-28", "2026-08-30"),  # J6  28,29,30 ago
    ("2026-09-04", "2026-09-06"),  # J7  4,5,6 sep
    ("2026-09-11", "2026-09-13"),  # J8  11,12,13 sep
    ("2026-09-18", "2026-09-20"),  # J9  18,19,20 sep
    ("2026-09-25", "2026-09-27"),  # J10 25,26,27 sep
    ("2026-10-09", "2026-10-11"),  # J11 9,10,11 oct
    ("2026-10-16", "2026-10-18"),  # J12 16,17,18 oct
    ("2026-10-20", "2026-10-21"),  # J13 doble: 20,21 oct (mar/mié)
    ("2026-10-23", "2026-10-25"),  # J14 23,24,25 oct
    ("2026-10-30", "2026-11-01"),  # J15 30,31 oct, 1 nov
    ("2026-11-06", "2026-11-08"),  # J16 6,7,8 nov
    ("2026-11-20", "2026-11-22"),  # J17 20,21,22 nov
]


def validar(jornadas: List[List[Tuple[str, str]]]) -> List[str]:
    """Devuelve lista de errores de integridad (vacía si todo OK)."""
    errores: List[str] = []
    if len(jornadas) != 17:
        errores.append(f"Se esperaban 17 jornadas, hay {len(jornadas)}.")

    pares_vistos: Dict[frozenset, int] = {}
    partidos_por_equipo: Dict[str, int] = {e: 0 for e in EQUIPOS}
    locales: Dict[str, int] = {e: 0 for e in EQUIPOS}

    for i, jornada in enumerate(jornadas, start=1):
        if len(jornada) != 9:
            errores.append(f"J{i}: se esperaban 9 partidos, hay {len(jornada)}.")
        equipos_jornada: List[str] = []
        for home, away in jornada:
            for t in (home, away):
                if t not in EQUIPOS:
                    errores.append(f"J{i}: equipo desconocido '{t}'.")
                equipos_jornada.append(t)
                partidos_por_equipo[t] = partidos_por_equipo.get(t, 0) + 1
            locales[home] = locales.get(home, 0) + 1
            par = frozenset((home, away))
            if len(par) != 2:
                errores.append(f"J{i}: un equipo juega contra sí mismo ({home}).")
                continue
            pares_vistos[par] = pares_vistos.get(par, 0) + 1
        # cada jornada debe usar a los 18 equipos exactamente una vez
        if sorted(equipos_jornada) != sorted(EQUIPOS):
            faltan = EQUIPOS - set(equipos_jornada)
            repes = [t for t in set(equipos_jornada) if equipos_jornada.count(t) > 1]
            errores.append(
                f"J{i}: no usa a los 18 exactamente una vez (faltan={sorted(faltan)}, repetidos={sorted(repes)})."
            )

    # round-robin a una vuelta: cada par exactamente una vez
    repetidos = {tuple(sorted(p)): c for p, c in pares_vistos.items() if c > 1}
    if repetidos:
        errores.append(f"Pares repetidos (deben jugar solo una vez): {repetidos}")
    total_pares_posibles = len(EQUIPOS) * (len(EQUIPOS) - 1) // 2  # 153
    if len(pares_vistos) != total_pares_posibles:
        faltantes = total_pares_posibles - len(pares_vistos)
        errores.append(
            f"Faltan {faltantes} enfrentamientos para round-robin completo "
            f"({len(pares_vistos)}/{total_pares_posibles})."
        )

    for e, n in partidos_por_equipo.items():
        if n != 17:
            errores.append(f"{e}: juega {n} partidos (deberían ser 17).")

    # Validación de fechas: 17 rangos, inicio<=fin, y jornadas en orden temporal.
    if len(FECHAS) != 17:
        errores.append(f"Se esperaban 17 rangos de fechas, hay {len(FECHAS)}.")
    else:
        from datetime import date

        prev_fin = None
        for i, (ini, fin) in enumerate(FECHAS, start=1):
            try:
                d_ini = date.fromisoformat(ini)
                d_fin = date.fromisoformat(fin)
            except ValueError:
                errores.append(f"J{i}: fecha inválida ({ini}/{fin}).")
                continue
            if d_ini > d_fin:
                errores.append(f"J{i}: fecha_inicio ({ini}) posterior a fecha_fin ({fin}).")
            if prev_fin and d_ini <= prev_fin:
                errores.append(f"J{i}: empieza ({ini}) antes de que termine la jornada previa ({prev_fin}).")
            prev_fin = d_fin

    return errores


def construir() -> List[dict]:
    return [
        {
            "jornada": i,
            "fecha_inicio": FECHAS[i - 1][0],
            "fecha_fin": FECHAS[i - 1][1],
            "partidos": [{"home_team": h, "away_team": a} for h, a in jornada],
        }
        for i, jornada in enumerate(JORNADAS, start=1)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Genera data/calendario.json (Apertura 2026).")
    parser.add_argument("--dry-run", action="store_true", help="Solo valida, no escribe.")
    parser.add_argument("--output", default=str(CALENDARIO_PATH))
    args = parser.parse_args()

    errores = validar(JORNADAS)
    if errores:
        print("❌ Errores de integridad en el calendario:")
        for e in errores:
            print(f"   - {e}")
        return 1
    print(
        "✅ Calendario válido: 17 jornadas, 9 partidos c/u, round-robin completo "
        "(153 enfrentamientos únicos), cada equipo juega 17 veces."
    )

    calendario = construir()
    if args.dry_run:
        print("(dry-run: no se escribió nada)")
        return 0

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(calendario, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"📝 Calendario escrito en {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
