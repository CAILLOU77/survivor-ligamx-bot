#!/usr/bin/env python3
"""Aplica el ciclo Survivor v2 de forma determinista sobre database.py."""
from pathlib import Path

path = Path("src/database.py")
text = path.read_text(encoding="utf-8")
if "def cancelar_survivor_pick(" in text:
    raise SystemExit("El ciclo v2 ya está aplicado")

text = text.replace("import logging\n", "import json\nimport logging\n", 1)
text = text.replace(
    'SURVIVOR_ESTADOS = {"recomendado", "confirmado", "bloqueado", "resuelto"}',
    'SURVIVOR_ESTADOS = {"recomendado", "confirmado", "bloqueado", "resuelto", "cancelado"}',
    1,
)

old_schema = '''                prob_victoria_pct REAL DEFAULT 0,
                estado TEXT NOT NULL DEFAULT 'recomendado',
                resultado TEXT,
                marcador_real TEXT,
                origen TEXT NOT NULL DEFAULT 'modelo',
                confirmado_at TIMESTAMP,
                bloqueado_at TIMESTAMP,
                resuelto_at TIMESTAMP,
                PRIMARY KEY (temporada, jornada)'''
new_schema = '''                prob_victoria_pct REAL DEFAULT 0,
                espn_event_id TEXT,
                match_key TEXT,
                kickoff_utc TEXT,
                probability_snapshot TEXT,
                model_version TEXT,
                decision_reason TEXT,
                selected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                estado TEXT NOT NULL DEFAULT 'recomendado',
                resultado TEXT,
                marcador_real TEXT,
                origen TEXT NOT NULL DEFAULT 'modelo',
                confirmado_at TIMESTAMP,
                bloqueado_at TIMESTAMP,
                resuelto_at TIMESTAMP,
                cancelled_at TIMESTAMP,
                PRIMARY KEY (temporada, jornada)'''
if old_schema not in text:
    raise RuntimeError("No se encontró el schema survivor_picks")
text = text.replace(old_schema, new_schema, 1)

index_marker = '''        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_survivor_picks_equipo_activo'''
text = text.replace(
    index_marker,
    '''        _asegurar_columnas_survivor(cur)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_survivor_picks_match_activo
            ON survivor_picks (match_key)
            WHERE match_key IS NOT NULL AND match_key <> '' AND estado <> 'cancelado'
        """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_survivor_picks_equipo_activo''',
    1,
)

helper_marker = "\ndef _insertar_usado_cursor("
helper = '''
def _asegurar_columnas_survivor(cur: Any) -> None:
    """Migración aditiva e idempotente para SQLite y PostgreSQL/Neon."""
    columnas = {
        "espn_event_id": "TEXT",
        "match_key": "TEXT",
        "kickoff_utc": "TEXT",
        "probability_snapshot": "TEXT",
        "model_version": "TEXT",
        "decision_reason": "TEXT",
        "selected_at": "TIMESTAMP",
        "cancelled_at": "TIMESTAMP",
    }
    if USE_POSTGRES:
        for nombre, definicion in columnas.items():
            cur.execute(f"ALTER TABLE survivor_picks ADD COLUMN IF NOT EXISTS {nombre} {definicion}")
        cur.execute("UPDATE survivor_picks SET selected_at=created_at WHERE selected_at IS NULL")
        return
    cur.execute("PRAGMA table_info(survivor_picks)")
    existentes = {str(fila[1]) for fila in cur.fetchall()}
    for nombre, definicion in columnas.items():
        if nombre not in existentes:
            cur.execute(f"ALTER TABLE survivor_picks ADD COLUMN {nombre} {definicion}")
    cur.execute("UPDATE survivor_picks SET selected_at=created_at WHERE selected_at IS NULL")


def _snapshot_json(snapshot: Optional[Dict[str, Any]]) -> Optional[str]:
    if snapshot is None:
        return None
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _snapshot_decode(valor: Any) -> Optional[Dict[str, Any]]:
    if not valor:
        return None
    try:
        data = json.loads(str(valor))
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None

'''
if helper_marker not in text:
    raise RuntimeError("No se encontró punto para helpers")
text = text.replace(helper_marker, "\n" + helper + "def _insertar_usado_cursor(", 1)

old_select_fields = '''no_perder_pct, prob_victoria_pct, estado, resultado, marcador_real,
                   origen, created_at, updated_at, confirmado_at, bloqueado_at, resuelto_at'''
new_select_fields = '''no_perder_pct, prob_victoria_pct, espn_event_id, match_key, kickoff_utc,
                   probability_snapshot, model_version, decision_reason, selected_at,
                   estado, resultado, marcador_real, origen, created_at, updated_at,
                   confirmado_at, bloqueado_at, resuelto_at, cancelled_at'''
if old_select_fields not in text:
    raise RuntimeError("No se encontró select individual")
text = text.replace(old_select_fields, new_select_fields, 1)

old_list_fields = '''no_perder_pct, prob_victoria_pct, estado, resultado, marcador_real,
                       origen, created_at, updated_at, confirmado_at, bloqueado_at, resuelto_at'''
new_list_fields = '''no_perder_pct, prob_victoria_pct, espn_event_id, match_key, kickoff_utc,
                       probability_snapshot, model_version, decision_reason, selected_at,
                       estado, resultado, marcador_real, origen, created_at, updated_at,
                       confirmado_at, bloqueado_at, resuelto_at, cancelled_at'''
if old_list_fields not in text:
    raise RuntimeError("No se encontró select listado")
text = text.replace(old_list_fields, new_list_fields, 1)

zip_marker = '''    columnas = [descripcion[0] for descripcion in cur.description]
    return dict(zip(columnas, fila))'''
zip_new = '''    columnas = [descripcion[0] for descripcion in cur.description]
    pick = dict(zip(columnas, fila))
    pick["probability_snapshot"] = _snapshot_decode(pick.get("probability_snapshot"))
    return pick'''
text = text.replace(zip_marker, zip_new, 1)
list_return = '''        columnas = [descripcion[0] for descripcion in cur.description]
        return [dict(zip(columnas, fila)) for fila in cur.fetchall()]'''
list_new = '''        columnas = [descripcion[0] for descripcion in cur.description]
        picks = [dict(zip(columnas, fila)) for fila in cur.fetchall()]
        for pick in picks:
            pick["probability_snapshot"] = _snapshot_decode(pick.get("probability_snapshot"))
        return picks'''
text = text.replace(list_return, list_new, 1)

sig_old = '''    prob_victoria_pct: float = 0.0,
    fecha: str = "",
) -> bool:'''
sig_new = '''    prob_victoria_pct: float = 0.0,
    fecha: str = "",
    espn_event_id: Optional[str] = None,
    match_key: str = "",
    kickoff_utc: str = "",
    probability_snapshot: Optional[Dict[str, Any]] = None,
    model_version: str = "",
    decision_reason: str = "",
) -> bool:'''
if sig_old not in text:
    raise RuntimeError("No se encontró firma registrar_pick_recomendado")
text = text.replace(sig_old, sig_new, 1)

norm_line = '''    norm = _survivor_equipo_key(equipo)
    with get_db() as conn:'''
norm_new = '''    norm = _survivor_equipo_key(equipo)
    espn_id = str(espn_event_id).strip() if espn_event_id not in (None, "") else None
    match_key = str(match_key or "").strip()
    if not match_key and espn_id:
        match_key = f"espn:{espn_id}"
    snapshot_json = _snapshot_json(probability_snapshot)
    with get_db() as conn:'''
text = text.replace(norm_line, norm_new, 1)

values_old = '''            float(no_perder_pct or 0),
            float(prob_victoria_pct or 0),
        )'''
values_new = '''            float(no_perder_pct or 0),
            float(prob_victoria_pct or 0),
            espn_id,
            match_key or None,
            str(kickoff_utc or ""),
            snapshot_json,
            str(model_version or ""),
            str(decision_reason or ""),
        )'''
text = text.replace(values_old, values_new, 1)

update_old = '''                    condicion={PH}, local={PH}, visitante={PH}, no_perder_pct={PH},
                    prob_victoria_pct={PH}, updated_at=CURRENT_TIMESTAMP
                    WHERE temporada={PH} AND jornada={PH} AND estado='recomendado'""",'''
update_new = '''                    condicion={PH}, local={PH}, visitante={PH}, no_perder_pct={PH},
                    prob_victoria_pct={PH}, espn_event_id={PH}, match_key={PH}, kickoff_utc={PH},
                    probability_snapshot={PH}, model_version={PH}, decision_reason={PH},
                    updated_at=CURRENT_TIMESTAMP
                    WHERE temporada={PH} AND jornada={PH} AND estado='recomendado'""",'''
text = text.replace(update_old, update_new, 1)

insert_old = '''                    (temporada, jornada, fecha, equipo_norm, equipo, rival, condicion, local,
                     visitante, no_perder_pct, prob_victoria_pct, estado, origen)
                    VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH},
                            'recomendado', 'modelo')""",'''
insert_new = '''                    (temporada, jornada, fecha, equipo_norm, equipo, rival, condicion, local,
                     visitante, no_perder_pct, prob_victoria_pct, espn_event_id, match_key,
                     kickoff_utc, probability_snapshot, model_version, decision_reason, estado, origen)
                    VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH},
                            {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, 'recomendado', 'modelo')""",'''
text = text.replace(insert_old, insert_new, 1)

confirm_cancel_marker = '''        if existente and estado in {"bloqueado", "resuelto"}:'''
text = text.replace(
    confirm_cancel_marker,
    '''        if existente and estado == "cancelado":
            raise ValueError(f"La jornada {jornada} fue cancelada y no puede confirmarse.")
        if existente and estado in {"bloqueado", "resuelto"}:''',
    1,
)

cancel_marker = "\ndef bloquear_survivor_pick("
cancel_fn = '''
def cancelar_survivor_pick(temporada: str, jornada: int) -> Dict[str, Any]:
    """Cancela de forma idempotente un pick aún no bloqueado y libera el equipo."""
    temporada = normalizar_temporada(temporada)
    jornada = _validar_jornada(jornada)
    with get_db() as conn:
        cur = conn.cursor()
        _bloquear_operacion_survivor(cur, temporada, jornada)
        pick = _pick_desde_cursor(cur, temporada, jornada)
        if pick is None:
            raise ValueError("No existe un pick para esa jornada.")
        if pick["estado"] == "cancelado":
            conn.commit()
            return pick
        if pick["estado"] in {"bloqueado", "resuelto"}:
            raise ValueError(f"Un pick {pick['estado']} no puede cancelarse.")
        cur.execute(
            f"""UPDATE survivor_picks SET estado='cancelado', cancelled_at=CURRENT_TIMESTAMP,
                updated_at=CURRENT_TIMESTAMP WHERE temporada={PH} AND jornada={PH}
                AND estado IN ('recomendado', 'confirmado')""",
            (temporada, jornada),
        )
        cur.execute(
            f"DELETE FROM survivor_equipos_usados WHERE temporada={PH} AND jornada={PH}",
            (temporada, jornada),
        )
        conn.commit()
        actualizado = _pick_desde_cursor(cur, temporada, jornada)
        if actualizado is None:
            raise RuntimeError("No se pudo recuperar el pick cancelado.")
        return actualizado

'''
text = text.replace(cancel_marker, "\n" + cancel_fn + "def bloquear_survivor_pick(", 1)

text = text.replace(
    '''        if pick["estado"] == "recomendado":
            raise ValueError("Primero debes confirmar el pick.")''',
    '''        if pick["estado"] in {"recomendado", "cancelado"}:
            raise ValueError("Primero debes confirmar un pick activo.")''',
    1,
)
text = text.replace(
    '''        if pick["estado"] == "recomendado":
            raise ValueError("No se puede resolver un pick que aún no fue confirmado.")''',
    '''        if pick["estado"] in {"recomendado", "cancelado"}:
            raise ValueError("No se puede resolver un pick no confirmado o cancelado.")''',
    1,
)

settle_maps = '''    por_equipos: Dict[str, Any] = {}
    por_equipos_canon: Dict[str, Any] = {}
    por_clave_canon: Dict[str, Any] = {}'''
text = text.replace(
    settle_maps,
    '''    por_match_key: Dict[str, Any] = {}
    por_equipos: Dict[str, Any] = {}
    por_equipos_canon: Dict[str, Any] = {}
    por_clave_canon: Dict[str, Any] = {}''',
    1,
)
text = text.replace(
    '''        info = {"hg": hg, "ag": ag}
        clave_legacy =''',
    '''        info = {"hg": hg, "ag": ag}
        match_key_resultado = str(resultado.get("match_key") or "").strip()
        if not match_key_resultado and resultado.get("espn_event_id") not in (None, ""):
            match_key_resultado = f"espn:{str(resultado['espn_event_id']).strip()}"
        if match_key_resultado:
            por_match_key[match_key_resultado] = info
        clave_legacy =''',
    1,
)
text = text.replace(
    '''            """SELECT temporada, jornada, fecha, equipo, condicion, local, visitante
               FROM survivor_picks WHERE estado='bloqueado'"""''',
    '''            """SELECT temporada, jornada, fecha, equipo, condicion, local, visitante, match_key
               FROM survivor_picks WHERE estado='bloqueado'"""''',
    1,
)
text = text.replace(
    '''        for temporada, jornada, fecha, equipo, condicion, local, visitante in cur.fetchall():''',
    '''        for temporada, jornada, fecha, equipo, condicion, local, visitante, match_key in cur.fetchall():''',
    1,
)
text = text.replace(
    '''            info_nuevo: Optional[Dict[str, Any]] = por_clave_canon.get(f"{clave}|{fecha_pick}") if fecha_pick else None
            info_nuevo = info_nuevo or por_equipos_canon.get(clave)''',
    '''            info_nuevo: Optional[Dict[str, Any]] = por_match_key.get(str(match_key or ""))
            if info_nuevo is None:
                info_nuevo = por_clave_canon.get(f"{clave}|{fecha_pick}") if fecha_pick else None
            info_nuevo = info_nuevo or por_equipos_canon.get(clave)''',
    1,
)

path.write_text(text, encoding="utf-8")
Path("tests/test_pick_lifecycle_v2.py").write_text('''#!/usr/bin/env python3
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
        conn.execute("CREATE TABLE survivor_picks (temporada TEXT, jornada INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, equipo_norm TEXT, equipo TEXT, estado TEXT, PRIMARY KEY (temporada, jornada))")
        conn.commit()
        conn.close()
        with _backend(Path(carpeta))[0], _backend(Path(carpeta))[1], _backend(Path(carpeta))[2]:
            db.init_db()
            with db.get_db() as migrated:
                columnas = {fila[1] for fila in migrated.execute("PRAGMA table_info(survivor_picks)")}
        assert {"espn_event_id", "match_key", "kickoff_utc", "probability_snapshot", "model_version", "decision_reason", "selected_at", "cancelled_at"} <= columnas


def test_snapshot_identidad_y_reintento_persisten_tras_reinicio():
    with tempfile.TemporaryDirectory() as carpeta:
        patches = _backend(Path(carpeta))
        with patches[0], patches[1], patches[2]:
            db.init_db()
            args = dict(
                temporada="Apertura-2026", jornada=3, equipo="América", rival="Toluca",
                local="América", visitante="Toluca", fecha="2026-08-01",
                espn_event_id="401877045", match_key="espn:401877045",
                kickoff_utc="2026-08-01T01:00:00Z",
                probability_snapshot={"home": 0.61, "draw": 0.24, "away": 0.15},
                model_version="survivor-2", decision_reason="Mayor probabilidad de no perder",
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
            partido = {"local": "América", "visitante": "Toluca", "rival": "Toluca", "condicion": "Local", "fecha": "2026-08-01"}
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
                "Apertura-2026", 3, "América", local="América", visitante="Toluca",
                match_key="espn:401877045", espn_event_id="401877045",
            )
            partido = {"local": "América", "visitante": "Toluca", "rival": "Toluca", "condicion": "Local", "fecha": "2026-08-01"}
            with mock.patch.object(db, "_partido_del_calendario", return_value=partido):
                db.confirmar_survivor_pick("Apertura-2026", 3, "América")
            db.bloquear_survivor_pick("Apertura-2026", 3)
            assert db.settle_survivor([{
                "match_key": "espn:401877045", "home_team": "Nombre cambiado",
                "away_team": "Otro alias", "home_goals": 2, "away_goals": 0,
            }]) == 1
            pick = db.get_survivor_pick("Apertura-2026", 3)
            assert pick["estado"] == "resuelto"
            assert pick["resultado"] == "gano"
''', encoding="utf-8")
