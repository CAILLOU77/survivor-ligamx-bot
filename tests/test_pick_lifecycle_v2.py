#!/usr/bin/env python3
"""Persistencia, identidad e idempotencia del ciclo Survivor v2."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

from src import database as db


def _backend(tmp_path: Path):
    return (
        mock.patch.object(db, "USE_POSTGRES", False),
        mock.patch.object(db, "PH", "?"),
        mock.patch.object(db, "SQLITE_PATH", str(tmp_path / "survivor.db")),
    )


def test_migracion_aditiva_desde_schema_legacy():
    with tempfile.TemporaryDirectory() as carpeta:
        ruta = Path(carpeta) / "survivor.db"
        conn = sqlite3.connect(ruta)
        conn.execute(
            "CREATE TABLE survivor_picks (temporada TEXT, jornada INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, equipo_norm TEXT, equipo TEXT, estado TEXT, PRIMARY KEY (temporada, jornada))"
        )
        conn.commit()
        conn.close()
        with _backend(Path(carpeta))[0], _backend(Path(carpeta))[1], _backend(Path(carpeta))[2]:
            db.init_db()
            with db.get_db() as migrated:
                columnas = {fila[1] for fila in migrated.execute("PRAGMA table_info(survivor_picks)")}
        assert {
            "espn_event_id",
            "match_key",
            "kickoff_utc",
            "probability_snapshot",
            "model_version",
            "decision_reason",
            "selected_at",
            "cancelled_at",
        } <= columnas


def test_snapshot_identidad_y_reintento_persisten_tras_reinicio():
    with tempfile.TemporaryDirectory() as carpeta:
        patches = _backend(Path(carpeta))
        with patches[0], patches[1], patches[2]:
            db.init_db()
            args = dict(
                temporada="Apertura-2026",
                jornada=3,
                equipo="América",
                rival="Toluca",
                local="América",
                visitante="Toluca",
                fecha="2026-08-01",
                espn_event_id="401877045",
                match_key="espn:401877045",
                kickoff_utc="2026-08-01T01:00:00Z",
                probability_snapshot={"home": 0.61, "draw": 0.24, "away": 0.15},
                model_version="survivor-2",
                decision_reason="Mayor probabilidad de no perder",
            )
            assert db.registrar_pick_recomendado(**args)
            assert db.registrar_pick_recomendado(**args)
            pick = db.get_survivor_pick("Apertura-2026", 3)
            assert pick is not None
            assert pick["match_key"] == "espn:401877045"
            assert pick["probability_snapshot"]["home"] == 0.61
            assert pick["model_version"] == "survivor-2"
            with db.get_db() as conn:
                assert conn.execute("SELECT COUNT(*) FROM survivor_picks").fetchone()[0] == 1
            db.init_db()
            assert db.get_survivor_pick("Apertura-2026", 3)["match_key"] == "espn:401877045"


def test_cancelacion_idempotente_libera_equipo():
    with tempfile.TemporaryDirectory() as carpeta:
        patches = _backend(Path(carpeta))
        with patches[0], patches[1], patches[2]:
            db.init_db()
            partido = {
                "local": "América",
                "visitante": "Toluca",
                "rival": "Toluca",
                "condicion": "Local",
                "fecha": "2026-08-01",
            }
            with mock.patch.object(db, "_partido_del_calendario", return_value=partido):
                db.confirmar_survivor_pick("Apertura-2026", 3, "América")
            cancelado = db.cancelar_survivor_pick("Apertura-2026", 3)
            repetido = db.cancelar_survivor_pick("Apertura-2026", 3)
            assert cancelado["estado"] == repetido["estado"] == "cancelado"
            assert "América" not in db.get_equipos_usados("Apertura-2026")


def test_resolucion_prefiere_match_key_estable():
    with tempfile.TemporaryDirectory() as carpeta:
        patches = _backend(Path(carpeta))
        with patches[0], patches[1], patches[2]:
            db.init_db()
            db.registrar_pick_recomendado(
                "Apertura-2026",
                3,
                "América",
                local="América",
                visitante="Toluca",
                match_key="espn:401877045",
                espn_event_id="401877045",
            )
            partido = {
                "local": "América",
                "visitante": "Toluca",
                "rival": "Toluca",
                "condicion": "Local",
                "fecha": "2026-08-01",
            }
            with mock.patch.object(db, "_partido_del_calendario", return_value=partido):
                db.confirmar_survivor_pick("Apertura-2026", 3, "América")
            db.bloquear_survivor_pick("Apertura-2026", 3)
            assert (
                db.settle_survivor(
                    [
                        {
                            "match_key": "espn:401877045",
                            "home_team": "Nombre cambiado",
                            "away_team": "Otro alias",
                            "home_goals": 2,
                            "away_goals": 0,
                        }
                    ]
                )
                == 1
            )
            pick = db.get_survivor_pick("Apertura-2026", 3)
            assert pick["estado"] == "resuelto"
            assert pick["resultado"] == "gano"
