#!/usr/bin/env python3
"""Smoke checks sin secretos para los servicios de producción del ecosistema."""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Callable
from typing import Any
from urllib.request import Request, urlopen

SURVIVOR_BASE_URL = "https://survivor-ligamx-bot.onrender.com"
LIGAMX_BASE_URL = "https://ligamx-api.onrender.com"

JsonObject = dict[str, Any]
Fetcher = Callable[[str], JsonObject]
Validator = Callable[[JsonObject], None]


class SmokeError(RuntimeError):
    """Indica que un servicio no cumplió su contrato mínimo de producción."""


def obtener_json(
    url: str,
    *,
    attempts: int = 6,
    timeout: float = 20.0,
    delay: float = 10.0,
    sleep: Callable[[float], None] = time.sleep,
) -> JsonObject:
    """Obtiene JSON con reintentos para tolerar el cold start de Render."""
    if attempts < 1:
        raise ValueError("attempts debe ser al menos 1")

    last_error: Exception | None = None
    request = Request(url, headers={"User-Agent": "survivor-production-smoke/1.0"})
    for attempt in range(1, attempts + 1):
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - URLs operativas controladas
                if response.status != 200:
                    raise SmokeError(f"HTTP {response.status}")
                payload = json.load(response)
            if not isinstance(payload, dict):
                raise SmokeError("la respuesta JSON no es un objeto")
            return payload
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                sleep(delay * attempt)

    assert last_error is not None
    raise SmokeError(f"{url}: {type(last_error).__name__}: {last_error}") from last_error


def validar_ligamx(payload: JsonObject) -> None:
    if payload.get("status") != "ok":
        raise SmokeError("Liga MX API no reportó status=ok")


def validar_survivor(payload: JsonObject) -> None:
    if payload.get("status") != "ok":
        raise SmokeError("Survivor no reportó status=ok")

    dependencies = payload.get("dependencias")
    if not isinstance(dependencies, dict):
        raise SmokeError("Survivor no devolvió el mapa de dependencias")

    required = ("base_de_datos", "espn", "ligamx_api", "telegram_webhook")
    failed = [name for name in required if dependencies.get(name) != "ok"]
    if failed:
        raise SmokeError(f"Dependencias degradadas: {', '.join(failed)}")


def validar_fuentes(payload: JsonObject) -> None:
    if payload.get("ok_global") is not True:
        raise SmokeError("El healthcheck de fuentes no reportó ok_global=true")

    sources = payload.get("fuentes")
    if not isinstance(sources, dict):
        raise SmokeError("No se devolvió el mapa de fuentes")

    required = ("espn", "thesportsdb", "ligamx_api")
    failed: list[str] = []
    for name in required:
        detail = sources.get(name)
        if not isinstance(detail, dict) or detail.get("ok") is not True:
            failed.append(name)
    if failed:
        raise SmokeError(f"Fuentes degradadas: {', '.join(failed)}")


def ejecutar_smoke(
    *,
    survivor_base_url: str = SURVIVOR_BASE_URL,
    ligamx_base_url: str = LIGAMX_BASE_URL,
    fetch: Fetcher = obtener_json,
) -> None:
    """Valida ambos servicios; despierta primero la API hermana para evitar falsos fallos."""
    survivor = survivor_base_url.rstrip("/")
    ligamx = ligamx_base_url.rstrip("/")
    checks: tuple[tuple[str, str, Validator], ...] = (
        ("Liga MX API", f"{ligamx}/health", validar_ligamx),
        ("Survivor", f"{survivor}/health", validar_survivor),
        ("Fuentes Survivor", f"{survivor}/health/fuentes", validar_fuentes),
    )

    for name, url, validator in checks:
        payload = fetch(url)
        validator(payload)
        print(f"OK {name}: {url}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Valida los contratos mínimos de producción.")
    parser.add_argument(
        "--survivor-url",
        default=os.getenv("SURVIVOR_BASE_URL", SURVIVOR_BASE_URL),
    )
    parser.add_argument(
        "--ligamx-url",
        default=os.getenv("LIGAMX_BASE_URL", LIGAMX_BASE_URL),
    )
    parser.add_argument("--attempts", type=int, default=6)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--delay", type=float, default=10.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    def fetch(url: str) -> JsonObject:
        return obtener_json(
            url,
            attempts=args.attempts,
            timeout=args.timeout,
            delay=args.delay,
        )

    try:
        ejecutar_smoke(
            survivor_base_url=args.survivor_url,
            ligamx_base_url=args.ligamx_url,
            fetch=fetch,
        )
    except SmokeError as exc:
        print(f"ERROR smoke de producción: {exc}")
        return 1

    print("Smoke de producción completado correctamente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
