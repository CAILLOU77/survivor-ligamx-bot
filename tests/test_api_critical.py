#!/usr/bin/env python3
"""Cobertura de regresión para las rutas web y Telegram más críticas."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest import mock

import pytest
from fastapi.testclient import TestClient

import src.api as apimod
import src.auth as authmod


@pytest.fixture(autouse=True)
def api_key_configurada():
    anterior = authmod.API_KEY
    authmod.API_KEY = "testkey"
    yield
    authmod.API_KEY = anterior


@pytest.fixture
def client():
    return TestClient(apimod.app)


def _headers_api():
    return {"X-API-Key": "testkey"}


def _respuesta_ok():
    return mock.Mock(status_code=200)


def _health(client: TestClient, telegram_env: dict, secreto="secret", estado=None, secreto_error=None):
    estado = estado or {"estado": "no_iniciada", "ok": False}
    secreto_patch = (
        mock.patch("src.telegram.configuracion.obtener_secreto_webhook", side_effect=secreto_error)
        if secreto_error
        else mock.patch("src.telegram.configuracion.obtener_secreto_webhook", return_value=secreto)
    )
    with (
        mock.patch.dict(os.environ, telegram_env, clear=False),
        mock.patch("src.database.get_equipos_usados", return_value=[]),
        mock.patch("requests.get", return_value=_respuesta_ok()),
        secreto_patch,
        mock.patch("src.telegram.configuracion.estado_sincronizacion_telegram", return_value=estado),
    ):
        return client.get("/health")


def test_root_redirige_al_dashboard_sin_cache(client):
    respuesta = client.get("/", follow_redirects=False)

    assert respuesta.status_code == 307
    assert respuesta.headers["location"] == "/dashboard"
    assert respuesta.headers["cache-control"] == "no-store"


def test_dashboard_entrega_html_con_headers_de_seguridad(client):
    respuesta = client.get("/dashboard")

    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith("text/html")
    assert "Mi Survivor · Liga MX" in respuesta.text
    for nombre, valor in apimod.DASHBOARD_SECURITY_HEADERS.items():
        assert respuesta.headers[nombre] == valor


@pytest.mark.parametrize(
    ("asset", "content_type", "contenido"),
    [
        ("app.css", "text/css", ":root"),
        ("app.js", "application/javascript", '"use strict"'),
    ],
)
def test_dashboard_entrega_solo_assets_permitidos(client, asset, content_type, contenido):
    respuesta = client.get(f"/dashboard/assets/{asset}")

    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith(content_type)
    assert contenido in respuesta.text
    assert respuesta.headers["x-content-type-options"] == "nosniff"


def test_dashboard_rechaza_asset_no_permitido(client):
    respuesta = client.get("/dashboard/assets/index.html")

    assert respuesta.status_code == 404
    assert respuesta.json()["detail"] == "Asset no encontrado"


def test_alerts_pronosticos_usa_clave_diaria_determinista(client):
    resultado = {"enviado": True, "detalle": "ok"}
    instante = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    with (
        mock.patch.object(apimod, "datetime", wraps=datetime) as fecha,
        mock.patch("src.telegram_pronosticos.enviar_pronosticos", return_value=resultado) as enviar,
    ):
        fecha.now.return_value = instante
        respuesta = client.post("/alerts/pronosticos", headers=_headers_api())

    assert respuesta.status_code == 200
    assert respuesta.json() == resultado
    enviar.assert_called_once_with(idempotency_key="cron:pronosticos:2026-07-23")


def test_alerts_momios_silencioso_usa_clave_diaria(client):
    resultado = {"enviado": False, "hay_lineas": False}
    instante = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    with (
        mock.patch.object(apimod, "datetime", wraps=datetime) as fecha,
        mock.patch("src.telegram_pronosticos.enviar_momios_estado", return_value=resultado) as enviar,
    ):
        fecha.now.return_value = instante
        respuesta = client.post("/alerts/momios?solo_si_hay=true", headers=_headers_api())

    assert respuesta.status_code == 200
    assert respuesta.json() == resultado
    enviar.assert_called_once_with(solo_si_hay=True, idempotency_key="cron:momios:2026-07-23")


def test_alerts_high_ev_delega_y_marca_deprecacion(client):
    with mock.patch("src.telegram_pronosticos.enviar_pronosticos", return_value={"enviado": True}) as enviar:
        respuesta = client.post("/alerts/high-ev", headers=_headers_api())

    assert respuesta.status_code == 200
    assert respuesta.json()["enviado"] is True
    assert "deprecado" in respuesta.json()["nota"].lower()
    enviar.assert_called_once_with()


def test_webhook_falla_cerrado_sin_chat_id(client):
    payload = {"message": {"chat": {"id": 123}, "text": "/usados"}}
    headers = {"X-Telegram-Bot-Api-Secret-Token": "secret"}
    with (
        mock.patch.dict(
            os.environ,
            {"TELEGRAM_CHAT_ID": "", "TELEGRAM_WEBHOOK_SECRET": "secret", "RENDER": ""},
            clear=False,
        ),
        mock.patch("src.telegram.configuracion.obtener_secreto_webhook", return_value="secret"),
    ):
        respuesta = client.post("/telegram/webhook", json=payload, headers=headers)

    assert respuesta.status_code == 503
    assert respuesta.json()["detail"] == "TELEGRAM_CHAT_ID no configurado"


def test_webhook_reporta_fallo_real_de_envio_en_comando_ligero(client):
    payload = {"message": {"chat": {"id": 123}, "text": "/usados"}}
    headers = {"X-Telegram-Bot-Api-Secret-Token": "secret"}
    with (
        mock.patch.dict(
            os.environ,
            {"TELEGRAM_CHAT_ID": "123", "TELEGRAM_WEBHOOK_SECRET": "secret", "RENDER": ""},
            clear=False,
        ),
        mock.patch("src.telegram.configuracion.obtener_secreto_webhook", return_value="secret"),
        mock.patch("src.telegram_webhook.responder", return_value="respuesta") as responder,
        mock.patch("src.telegram_pronosticos.enviar_mensaje", return_value=False) as enviar,
    ):
        respuesta = client.post("/telegram/webhook", json=payload, headers=headers)

    assert respuesta.status_code == 502
    assert respuesta.json()["detail"] == "No se pudo entregar la respuesta en Telegram"
    responder.assert_called_once_with("usados", "")
    enviar.assert_called_once_with("respuesta")


def test_health_marca_telegram_deshabilitado_en_local(client):
    respuesta = _health(
        client,
        {
            "TELEGRAM_BOT_TOKEN": "",
            "TELEGRAM_CHAT_ID": "",
            "TELEGRAM_WEBHOOK_SECRET": "",
            "RENDER": "",
        },
        secreto="",
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "ok"
    assert respuesta.json()["dependencias"]["telegram_webhook"] == "deshabilitado"


def test_health_marca_telegram_ok_con_configuracion_local(client):
    respuesta = _health(
        client,
        {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_CHAT_ID": "123",
            "TELEGRAM_WEBHOOK_SECRET": "secret",
            "RENDER": "",
        },
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "ok"
    assert respuesta.json()["dependencias"]["telegram_webhook"] == "ok"


def test_health_marca_telegram_sincronizando_en_render(client):
    respuesta = _health(
        client,
        {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_CHAT_ID": "123",
            "TELEGRAM_WEBHOOK_SECRET": "secret",
            "RENDER": "true",
        },
        estado={"estado": "sincronizando", "ok": False},
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "degradado"
    assert respuesta.json()["dependencias"]["telegram_webhook"] == "sincronizando"


def test_health_marca_error_de_telegram_en_render(client):
    respuesta = _health(
        client,
        {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_CHAT_ID": "",
            "TELEGRAM_WEBHOOK_SECRET": "",
            "RENDER": "true",
        },
        secreto="",
        estado={"estado": "error", "ok": False, "error": "faltan credenciales"},
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "degradado"
    assert respuesta.json()["dependencias"]["telegram_webhook"] == "error: faltan credenciales"


def test_health_captura_excepcion_al_leer_configuracion_telegram(client):
    respuesta = _health(
        client,
        {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_CHAT_ID": "123",
            "TELEGRAM_WEBHOOK_SECRET": "secret",
            "RENDER": "true",
        },
        secreto_error=RuntimeError("estado roto"),
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "degradado"
    assert respuesta.json()["dependencias"]["telegram_webhook"] == "error: estado roto"
