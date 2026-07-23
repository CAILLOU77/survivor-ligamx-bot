#!/usr/bin/env python3
"""Idempotencia persistente para updates y entregas Telegram."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock

from src import database as db
from src.telegram import envio


def _backend(tmp_path: Path):
    return (
        mock.patch.object(db, "USE_POSTGRES", False),
        mock.patch.object(db, "PH", "?"),
        mock.patch.object(db, "SQLITE_PATH", str(tmp_path / "telegram.db")),
    )


def test_update_duplicado_se_procesa_una_sola_vez_y_persiste():
    with tempfile.TemporaryDirectory() as carpeta:
        patches = _backend(Path(carpeta))
        with patches[0], patches[1], patches[2]:
            db.init_db()
            assert db.reclamar_telegram_update(9001)
            db.completar_telegram_update(9001)
            assert not db.reclamar_telegram_update(9001)
            db.init_db()
            assert not db.reclamar_telegram_update(9001)


def test_update_fallido_puede_reintentarse():
    with tempfile.TemporaryDirectory() as carpeta:
        patches = _backend(Path(carpeta))
        with patches[0], patches[1], patches[2]:
            db.init_db()
            assert db.reclamar_telegram_update(9002)
            db.fallar_telegram_update(9002, "temporal")
            assert db.reclamar_telegram_update(9002)


def test_entrega_por_partes_omite_las_ya_enviadas():
    respuesta = mock.Mock(status_code=200, text="ok")
    with (
        mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "chat"}),
        mock.patch.object(envio.requests, "post", return_value=respuesta) as post,
        mock.patch("src.database.reclamar_entrega_telegram", side_effect=[True, False]),
        mock.patch("src.database.completar_entrega_telegram") as completar,
    ):
        assert envio.enviar_mensaje("hola", idempotency_key="alerta:1")
        assert envio.enviar_mensaje("hola", idempotency_key="alerta:1")
    post.assert_called_once()
    completar.assert_called_once()
