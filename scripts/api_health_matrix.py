#!/usr/bin/env python3
"""
api_health_matrix.py — CLI de la matriz de salud/roles de APIs (Survivor Liga MX).

v1.36.0 — API Role Router & Health Matrix.

- Carga .env si existe (sin imprimir secretos).
- Construye la matriz de roles/estado/uso de todas las APIs.
- Imprime el reporte y lo guarda en reports/api_health_matrix_ultimo.txt.

NO toma picks, NO manda Telegram, NO activa proveedores nuevos, NO imprime
secretos, NO hace llamadas externas.
"""
from __future__ import annotations

import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import api_role_router as router  # noqa: E402


OUTPUT_TXT = BASE_DIR / "reports" / "api_health_matrix_ultimo.txt"


def main() -> int:
    # Carga .env local (sin sobrescribir el entorno, sin imprimir secretos).
    router.cargar_env_local()

    matrix = router.build_matrix()
    reporte = router.render_report(matrix)

    OUTPUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_TXT.write_text(reporte, encoding="utf-8")

    print(reporte, end="")
    print(f"\n✅ Reporte guardado: {OUTPUT_TXT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
