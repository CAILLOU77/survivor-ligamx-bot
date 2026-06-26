#!/usr/bin/env python3
"""
final_audit_readiness.py — CLI del Data Confidence Score (Survivor Liga MX).

v1.37.0 — Final Audit Readiness.

- Carga .env si existe (sin imprimir secretos).
- Construye la API Health Matrix (src/api_role_router.build_matrix).
- Lee entradas locales (watchdog_state, FBref, noticias) si existen.
- Calcula el Data Confidence Score, lo imprime y lo guarda en
  reports/data_confidence_ultimo.txt.

NO toma picks, NO cierra picks, NO manda Telegram, NO activa APIs nuevas,
NO hace llamadas externas, NO imprime secretos, NO usa CERRAR.
"""
from __future__ import annotations

import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import api_role_router as router  # noqa: E402
import data_confidence as dc  # noqa: E402


OUTPUT_TXT = BASE_DIR / "reports" / "data_confidence_ultimo.txt"


def main() -> int:
    # Carga .env local (sin sobrescribir el entorno, sin imprimir secretos).
    router.cargar_env_local()

    matrix = router.build_matrix()
    resultado = dc.evaluar(BASE_DIR, matrix)
    reporte = dc.render_report(resultado)

    OUTPUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_TXT.write_text(reporte, encoding="utf-8")

    print(reporte, end="")
    print(f"\n✅ Reporte guardado: {OUTPUT_TXT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
