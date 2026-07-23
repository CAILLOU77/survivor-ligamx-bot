#!/usr/bin/env python3
"""Flujo integrado API de predicciones → formato → entrega durable Telegram."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from unittest import mock

from src import database as db
from src import telegram_notifier as notifier
from src.telegram import envio


class _ApiResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class _ApiClient:
    def __init__(self, data):
        self._response = _ApiResponse(data)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url):
        return self._response


def _predicciones():
    return {
        "fuente_datos": "ESPN",
        "total_pronosticos": 1,
        "pronosticos": [
            {
                "espn_event_id": "401999001",
                "match_key": "espn:401999001",
                "kickoff_utc": "2026-07-25T02:00:00Z",
                "fecha": "2026-07-25T02:00:00Z",
                "local": "América",
                "visitante": "Toluca",
                "pick_1x2": "Gana Local",
                "prob_local_pct": 55.0,
                "prob_empate_pct": 25.0,
                "prob_visitante_pct": 20.0,
                "pick_ou": "Over",
                "prob_over_pct": 60.0,
                "pick_btts": "Sí",
                "prob_btts_si_pct": 55.0,
                "marcador_mas_probable": "2-1",
                "no_perder_local_pct": 80.0,
                "no_perder_visitante_pct": 45.0,
            }
        ],
    }


def test_lote_repetido_cruza_todo_el_flujo_y_solo_se_entrega_una_vez():
    respuesta_telegram = mock.Mock(status_code=200, text="ok")
    cliente_api = _ApiClient(_predicciones())

    with tempfile.TemporaryDirectory() as carpeta:
        with (
            mock.patch.object(db, "USE_POSTGRES", False),
            mock.patch.object(db, "PH", "?"),
            mock.patch.object(db, "SQLITE_PATH", str(Path(carpeta) / "e2e.db")),
            mock.patch.object(notifier, "TELEGRAM_TOKEN", "tok"),
            mock.patch.object(notifier, "CHAT_ID", "chat"),
            mock.patch.dict(
                os.environ,
                {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "chat"},
                clear=False,
            ),
            mock.patch.object(
                notifier.httpx,
                "AsyncClient",
                lambda *args, **kwargs: cliente_api,
            ),
            mock.patch.object(envio.requests, "post", return_value=respuesta_telegram) as post,
        ):
            db.init_db()

            assert asyncio.run(notifier.notify_predicciones())
            assert asyncio.run(notifier.notify_predicciones())

            with db.get_db() as conn:
                fila = conn.execute(
                    "SELECT COUNT(*), MIN(status) FROM telegram_deliveries"
                ).fetchone()

    assert post.call_count == 1
    assert fila is not None
    assert fila[0] == 1
    assert fila[1] == "enviado"
