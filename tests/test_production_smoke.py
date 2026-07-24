#!/usr/bin/env python3
"""Pruebas del monitor de producción sin tocar servicios reales."""

from __future__ import annotations

import io
from unittest import mock

import pytest

from src import production_smoke as smoke


class _Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False


def _survivor_ok():
    return {
        "status": "ok",
        "dependencias": {
            "base_de_datos": "ok",
            "espn": "ok",
            "ligamx_api": "ok",
            "telegram_webhook": "ok",
        },
    }


def _fuentes_ok():
    return {
        "ok_global": True,
        "fuentes": {
            "espn": {"ok": True},
            "thesportsdb": {"ok": True},
            "ligamx_api": {"ok": True},
        },
    }


def test_obtener_json_reintenta_tras_cold_start():
    sleep = mock.Mock()
    responses = [TimeoutError("cold start"), _Response(b'{"status": "ok"}')]

    with mock.patch.object(smoke, "urlopen", side_effect=responses) as urlopen:
        payload = smoke.obtener_json(
            "https://example.test/health",
            attempts=2,
            timeout=1,
            delay=3,
            sleep=sleep,
        )

    assert payload == {"status": "ok"}
    assert urlopen.call_count == 2
    sleep.assert_called_once_with(3)


def test_obtener_json_falla_despues_de_agotar_reintentos():
    with mock.patch.object(smoke, "urlopen", side_effect=TimeoutError("offline")):
        with pytest.raises(smoke.SmokeError, match="TimeoutError"):
            smoke.obtener_json(
                "https://example.test/health",
                attempts=2,
                delay=0,
                sleep=mock.Mock(),
            )


def test_validadores_aceptan_contratos_sanos():
    smoke.validar_ligamx({"status": "ok"})
    smoke.validar_survivor(_survivor_ok())
    smoke.validar_fuentes(_fuentes_ok())


def test_validar_survivor_rechaza_dependencia_degradada():
    payload = _survivor_ok()
    payload["dependencias"]["telegram_webhook"] = "error"

    with pytest.raises(smoke.SmokeError, match="telegram_webhook"):
        smoke.validar_survivor(payload)


def test_validar_fuentes_rechaza_fallo_aunque_haya_mapa():
    payload = _fuentes_ok()
    payload["fuentes"]["espn"] = {"ok": False}

    with pytest.raises(smoke.SmokeError, match="espn"):
        smoke.validar_fuentes(payload)


def test_ejecutar_smoke_despierta_primero_ligamx():
    seen: list[str] = []
    payloads = {
        "https://liga.test/health": {"status": "ok"},
        "https://survivor.test/health": _survivor_ok(),
        "https://survivor.test/health/fuentes": _fuentes_ok(),
    }

    def fetch(url: str):
        seen.append(url)
        return payloads[url]

    smoke.ejecutar_smoke(
        survivor_base_url="https://survivor.test/",
        ligamx_base_url="https://liga.test/",
        fetch=fetch,
    )

    assert seen == [
        "https://liga.test/health",
        "https://survivor.test/health",
        "https://survivor.test/health/fuentes",
    ]


def test_main_devuelve_error_si_un_contrato_falla():
    with mock.patch.object(smoke, "ejecutar_smoke", side_effect=smoke.SmokeError("degradado")):
        assert smoke.main(["--attempts", "1"]) == 1
