#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path


MAX_TELEGRAM_CHARS = 3500
_FINAL_SECURITY_GATE = None


def dividir_texto(texto: str, max_chars: int = MAX_TELEGRAM_CHARS) -> list[str]:
    partes = []

    while len(texto) > max_chars:
        corte = texto.rfind("\n", 0, max_chars)
        if corte == -1:
            corte = max_chars

        partes.append(texto[:corte].strip())
        texto = texto[corte:].strip()

    if texto:
        partes.append(texto)

    return partes


def _cargar_final_security_gate():
    global _FINAL_SECURITY_GATE

    if _FINAL_SECURITY_GATE is not None:
        return _FINAL_SECURITY_GATE

    module_path = Path(__file__).resolve().parents[1] / "scripts" / "final_security_gate.py"
    spec = importlib.util.spec_from_file_location("final_security_gate", module_path)

    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar final_security_gate desde {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _FINAL_SECURITY_GATE = module
    return module


def validar_reporte_para_telegram(path: Path):
    gate = _cargar_final_security_gate()
    return gate.validate_report_file(path)


def construir_advertencia_bloqueo(path: Path, result) -> str:
    lineas = [
        "🚫 NO ENVIAR: reporte bloqueado por seguridad operativa.",
        f"Reporte: {path}",
        f"Motivo: {result.message}",
        "Decisión: NO ENVIAR",
    ]

    if getattr(result, "allowed_marker", None):
        lineas.append(f"Etiqueta segura detectada: {result.allowed_marker}")

    if getattr(result, "forbidden_matches", None):
        lineas.append("Patrones prohibidos detectados:")
        for match in result.forbidden_matches:
            lineas.append(f"- {match}")

    return "\n".join(lineas)


def enviar_mensaje(token: str, chat_id: str, texto: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": texto,
        "disable_web_page_preview": True,
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))

    if not data.get("ok"):
        raise RuntimeError(f"Telegram respondió error: {data}")


def construir_mensaje_desde_reporte(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"No existe el reporte: {path}")

    texto = path.read_text(encoding="utf-8", errors="ignore").strip()

    encabezado = (
        "🔥 BOT SURVIVOR LIGA MX — SATCHEL\n"
        f"Enviado: {datetime.now().isoformat(timespec='seconds')}\n"
        + "=" * 40
        + "\n\n"
    )

    return encabezado + texto


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--report",
        default="reports/reporte_survivor_ultimo.txt",
        help="Ruta del reporte final a enviar.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Valida el reporte con el safety gate y muestra lo que se ENVIARÍA, "
            "sin enviar nada a Telegram. No requiere credenciales."
        ),
    )
    args = parser.parse_args()

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    # En modo normal se requieren credenciales; en dry-run no (no se envía nada).
    if not args.dry_run and (not token or not chat_id):
        print("⚠️ Telegram no configurado. Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID.")
        return 2

    report_path = Path(args.report)
    safety_result = validar_reporte_para_telegram(report_path)

    if not safety_result.ok:
        advertencia = construir_advertencia_bloqueo(report_path, safety_result)
        if args.dry_run:
            print("🧪 DRY-RUN — no se envió nada. Mensaje de BLOQUEO que se enviaría:")
            print(advertencia)
        else:
            enviar_mensaje(token, chat_id, advertencia)
            print("🚫 Telegram bloqueado por safety guard interno.")
        print(safety_result.message)
        return safety_result.exit_code

    mensaje = construir_mensaje_desde_reporte(report_path)
    partes = dividir_texto(mensaje)

    if args.dry_run:
        print(f"🧪 DRY-RUN — no se envió nada. Se enviarían {len(partes)} mensaje(s):")
        for idx, parte in enumerate(partes, start=1):
            print(f"----- Parte {idx}/{len(partes)} -----")
            print(parte)
        print("✅ DRY-RUN completado. Decisión: NO ENVIAR (simulación).")
        return 0

    for idx, parte in enumerate(partes, start=1):
        if len(partes) > 1:
            parte = f"Parte {idx}/{len(partes)}\n\n{parte}"

        enviar_mensaje(token, chat_id, parte)

    print(f"✅ Telegram enviado correctamente. Mensajes enviados: {len(partes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
