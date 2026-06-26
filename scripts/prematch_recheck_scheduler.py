#!/usr/bin/env python3
"""
prematch_recheck_scheduler.py — CLI del Pre-Match Recheck Scheduler.

v1.38.0 — Survivor Liga MX.

Uso:
    python3 scripts/prematch_recheck_scheduler.py --jornada 1
    python3 scripts/prematch_recheck_scheduler.py --jornada 1 --now "2026-07-16T12:00:00"

- Carga .env si existe (sin imprimir secretos).
- Construye la API Health Matrix (api_role_router.build_matrix).
- Lee data/jornadas.json (si falta, no rompe).
- Opcionalmente usa Data Confidence como contexto local (sin llamadas externas).
- Imprime y guarda reports/prematch_recheck_ultimo.txt.

NO hace llamadas externas, NO manda Telegram, NO cambia/cierra picks, NO activa
APIs nuevas, NO imprime secretos, NO usa CERRAR, NO crea launchd/cron.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import api_role_router as router  # noqa: E402
import prematch_recheck as pr  # noqa: E402

try:
    import data_confidence as dc  # noqa: E402
except Exception:  # pragma: no cover
    dc = None


OUTPUT_TXT = BASE_DIR / "reports" / "prematch_recheck_ultimo.txt"
JORNADAS_PATH = BASE_DIR / "data" / "jornadas.json"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Programador/checklist local de rechecks pre-partido (no red, no Telegram, no picks)."
    )
    parser.add_argument("--jornada", type=int, default=1, help="Jornada a programar (default 1).")
    parser.add_argument(
        "--now",
        default=None,
        help="Fecha/hora ISO para pruebas determinísticas, p. ej. 2026-07-16T12:00:00.",
    )
    args = parser.parse_args(argv)

    # Carga .env local (sin sobrescribir el entorno, sin imprimir secretos).
    router.cargar_env_local()

    now = pr.parse_now(args.now)
    matrix = router.build_matrix()
    partidos, jornadas_existe = pr.cargar_partidos(JORNADAS_PATH, args.jornada)

    # Contexto opcional de Data Confidence (no debe romper si falla).
    data_confidence_ctx = None
    if dc is not None:
        try:
            data_confidence_ctx = dc.evaluar(BASE_DIR, matrix)
        except Exception:
            data_confidence_ctx = None

    resultado = pr.construir_resultado(
        now=now,
        jornada=args.jornada,
        partidos=partidos,
        jornadas_existe=jornadas_existe,
        matrix=matrix,
        data_confidence_ctx=data_confidence_ctx,
    )

    reporte = pr.render_report(resultado)

    OUTPUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_TXT.write_text(reporte, encoding="utf-8")

    print(reporte, end="")
    print(f"\n✅ Reporte guardado: {OUTPUT_TXT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
