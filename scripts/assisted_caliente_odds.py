#!/usr/bin/env python3
"""
assisted_caliente_odds.py — CLI de importación ASISTIDA de momios (Survivor Liga MX).

v1.39.1 — Caliente Multiline Parser Fix + Chrome Capture Prep.

Flujo asistido por usuario (NO automatizado, NO stealth, NO bypass):
    1. Abre un navegador VISIBLE con Playwright (persistent context).
    2. El USUARIO completa manualmente cualquier verificación/login si aparece.
    3. El script espera a que presiones ENTER en la terminal.
    4. Captura el TEXTO VISIBLE de la página (no DOM evasivo, no red oculta).
    5. Guarda el texto de debug en reports/caliente_debug_text.txt.
    6. Parsea los eventos Liga MX 1X2 desde el texto visible.
    7. Exporta JSON a reports/momios_liga_mx.json.
    8. Genera el reporte TXT reports/assisted_odds_import_ultimo.txt.

Uso:
    python3 scripts/assisted_caliente_odds.py \
        --url "https://sports.caliente.mx/es_MX/Apuestas-Futbol-Mexico"

    # Reparsear un texto ya capturado, SIN abrir navegador:
    python3 scripts/assisted_caliente_odds.py --debug-file reports/caliente_debug_text.txt

Reglas duras respetadas:
- NO stealth. NO playwright-stealth. NO proxy. NO automatiza login.
- NO evade firewall/captcha/login/verificación. NO guarda credenciales.
- NO manda Telegram. NO cambia picks. NO imprime secretos.
- Decisión operativa SIEMPRE: ESPERAR / NO ENVIAR. Nunca marca pick listo.

NOTA: Playwright es opcional. Solo se importa si realmente abres el navegador;
así este script compila y corre `--help`/`--debug-file` aunque no esté instalado.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import assisted_odds_import as aoi  # noqa: E402


DEFAULT_URL = "https://sports.caliente.mx/es_MX/Apuestas-Futbol-Mexico"

REPORTS_DIR = BASE_DIR / "reports"
DEBUG_TEXT_PATH = REPORTS_DIR / "caliente_debug_text.txt"
JSON_PATH = REPORTS_DIR / "momios_liga_mx.json"
REPORT_TXT_PATH = REPORTS_DIR / "assisted_odds_import_ultimo.txt"

# Perfil persistente local de Playwright. Vive bajo data/ (ignorado por git),
# nunca se commitea y NO debe usarse para guardar credenciales del usuario.
DEFAULT_USER_DATA_DIR = BASE_DIR / "data" / "playwright_assisted_profile"


def _capturar_texto_visible(url: str, user_data_dir: Path, timeout_ms: int) -> str:
    """
    Abre un navegador VISIBLE (persistent context), espera ENTER del usuario y
    devuelve el texto visible del <body>. Importa Playwright de forma perezosa.

    No automatiza login/verificación: solo navega a la URL y deja que el usuario
    haga lo que tenga que hacer manualmente. No usa stealth, ni proxy, ni flags
    de evasión.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise SystemExit(
            "Playwright no está instalado. Instálalo con:\n"
            "  pip install playwright && python3 -m playwright install chromium\n"
            "O reparsea un texto ya capturado con --debug-file."
        ) from exc

    user_data_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        # headless=False => navegador VISIBLE. Sin stealth, sin proxy.
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=False,
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(url, timeout=timeout_ms)

            print("\n" + "=" * 70)
            print("NAVEGADOR ABIERTO (modo asistido).")
            print("1) Si aparece verificación/login, complétalo TÚ manualmente.")
            print("2) Asegúrate de ver los partidos Liga MX con sus momios 1X2.")
            print("3) Cuando la página muestre los momios, vuelve aquí.")
            print("=" * 70)
            input("Presiona ENTER para capturar el texto visible... ")

            texto = page.inner_text("body")
        finally:
            context.close()

    return texto


def _leer_debug_file(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"No existe el archivo de debug: {path}")
    return path.read_text(encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Importación ASISTIDA POR USUARIO de momios 1X2 Liga MX desde un "
            "sportsbook (ej. Caliente). No automatiza login/verificación, no usa "
            "stealth/proxy, no manda Telegram y no cambia picks. Decisión siempre: "
            "ESPERAR / NO ENVIAR."
        )
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"URL del sportsbook a abrir en navegador visible (default: {DEFAULT_URL}).",
    )
    parser.add_argument(
        "--debug-file",
        default=None,
        help=(
            "Reparsea un texto ya capturado desde este archivo en vez de abrir "
            "el navegador (útil para reprocesar reports/caliente_debug_text.txt)."
        ),
    )
    parser.add_argument(
        "--user-data-dir",
        default=str(DEFAULT_USER_DATA_DIR),
        help="Directorio del perfil persistente de Playwright (ignorado por git).",
    )
    parser.add_argument(
        "--esperados",
        type=int,
        default=9,
        help="Número de partidos esperados (default 9).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60000,
        help="Timeout de navegación en milisegundos (default 60000).",
    )
    args = parser.parse_args(argv)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # 1) Obtener el texto visible (navegador asistido) o desde un archivo.
    if args.debug_file:
        texto = _leer_debug_file(Path(args.debug_file))
        origen = f"debug-file: {args.debug_file}"
    else:
        texto = _capturar_texto_visible(
            url=args.url,
            user_data_dir=Path(args.user_data_dir),
            timeout_ms=args.timeout,
        )
        origen = f"navegador asistido: {aoi._host_de_url(args.url)}"

    # 2) Guardar texto de debug (local, ignorado por git).
    DEBUG_TEXT_PATH.write_text(texto, encoding="utf-8")

    # 3) Parsear eventos Liga MX 1X2.
    resultado = aoi.analizar_texto(texto, esperados=args.esperados)

    # 4) Exportar JSON de momios.
    JSON_PATH.write_text(aoi.exportar_json(resultado), encoding="utf-8")

    # 5) Generar reporte TXT.
    reporte = aoi.render_report(resultado, url=args.url)
    REPORT_TXT_PATH.write_text(reporte, encoding="utf-8")

    # 6) Resumen en consola (sin secretos).
    print(reporte, end="")
    print(f"\nOrigen: {origen}")
    print(f"Texto de debug: {DEBUG_TEXT_PATH}")
    print(f"JSON de momios: {JSON_PATH}")
    print(f"Reporte: {REPORT_TXT_PATH}")
    print(f"\nDecisión: {aoi.DEC_ESPERAR} (nunca se marca pick listo).")

    # Salida no-cero si no se encontraron eventos, para integraciones locales.
    return 0 if resultado["status"] == aoi.STATUS_OK else 2


if __name__ == "__main__":
    raise SystemExit(main())
