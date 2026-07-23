#!/usr/bin/env python3
"""Finaliza concurrencia, cron y pruebas de idempotencia Telegram."""
from pathlib import Path

# CAS seguro: dos reintentos no pueden reclamar la misma fila fallida/vencida.
p = Path("src/database.py")
s = p.read_text(encoding="utf-8")
old = '''        cur.execute(
            f"UPDATE {tabla} SET status='procesando', locked_until={PH}, last_error=NULL, "
            f"updated_at=CURRENT_TIMESTAMP WHERE {columna}={PH} AND status<>{PH}",
            (locked_until, valor, completado),
        )
'''
new = '''        if estado == "fallido":
            condicion_reclamo = "status='fallido'"
            parametros = (locked_until, valor, completado)
        else:
            condicion_reclamo = f"locked_until={PH}"
            parametros = (locked_until, valor, completado, lease)
        cur.execute(
            f"UPDATE {tabla} SET status='procesando', locked_until={PH}, last_error=NULL, "
            f"updated_at=CURRENT_TIMESTAMP WHERE {columna}={PH} AND status<>{PH} "
            f"AND {condicion_reclamo}",
            parametros,
        )
'''
if old not in s:
    raise RuntimeError("No se encontró el reclamo Telegram para hacerlo CAS")
p.write_text(s.replace(old, new, 1), encoding="utf-8")

# Idempotencia diaria en endpoints cron y metadatos del pick Survivor.
p = Path("src/telegram/envio.py")
s = p.read_text(encoding="utf-8")
s = s.replace(
    '''def enviar_pronosticos(equipos_usados: Optional[List[str]] = None, incluir_contexto: bool = True) -> Dict[str, Any]:''',
    '''def enviar_pronosticos(
    equipos_usados: Optional[List[str]] = None,
    incluir_contexto: bool = True,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:''',
    1,
)
s = s.replace("    enviado = enviar_mensaje(mensaje)\n    return {\n        \"enviado\": enviado,", "    enviado = enviar_mensaje(mensaje, idempotency_key=idempotency_key)\n    return {\n        \"enviado\": enviado,", 1)
s = s.replace(
    "def enviar_momios_estado(solo_si_hay: bool = False) -> Dict[str, Any]:",
    "def enviar_momios_estado(solo_si_hay: bool = False, idempotency_key: Optional[str] = None) -> Dict[str, Any]:",
    1,
)
s = s.replace(
    "    enviado = enviar_mensaje(construir_mensaje_momios(momios, fuente))",
    "    enviado = enviar_mensaje(construir_mensaje_momios(momios, fuente), idempotency_key=idempotency_key)",
    1,
)
s = s.replace(
    "    enviado = enviar_mensaje(construir_recordatorio(j, dias))",
    '''    clave = f"recordatorio:{hoy.isoformat()}:J{j.get('jornada')}:{dias_antes}"
    enviado = enviar_mensaje(construir_recordatorio(j, dias), idempotency_key=clave)''',
    1,
)
# Conservar el contrato estable y auditoría al registrar la recomendación.
s = s.replace('''    fecha = ""
    equipo_key = canonical_team_key(equipo)''', '''    fecha = ""
    partido_match: Dict[str, Any] = {}
    equipo_key = canonical_team_key(equipo)''', 1)
s = s.replace('''            fecha = str(pronostico.get("fecha") or "")
            break''', '''            fecha = str(pronostico.get("fecha") or "")
            partido_match = pronostico
            break''', 1)
s = s.replace('''            prob_victoria_pct=float(pick.get("prob_victoria_pct") or pick.get("prob_ganar_pct") or 0.0),
            fecha=fecha,
        )''', '''            prob_victoria_pct=float(pick.get("prob_victoria_pct") or pick.get("prob_ganar_pct") or 0.0),
            fecha=fecha,
            espn_event_id=partido_match.get("espn_event_id"),
            match_key=str(partido_match.get("match_key") or ""),
            kickoff_utc=str(partido_match.get("kickoff_utc") or partido_match.get("fecha") or ""),
            probability_snapshot={
                "no_perder_pct": float(pick.get("no_perder_pct") or 0.0),
                "prob_victoria_pct": float(pick.get("prob_victoria_pct") or pick.get("prob_ganar_pct") or 0.0),
            },
            model_version=os.getenv("SURVIVOR_MODEL_VERSION", "survivor-v1"),
            decision_reason=str(pick.get("razon") or pick.get("motivo") or ""),
        )''', 1)
p.write_text(s, encoding="utf-8")

# Solo los endpoints programados usan llave diaria; comandos manuales conservan reenvío.
p = Path("src/api.py")
s = p.read_text(encoding="utf-8")
s = s.replace(
    "    return telegram_pronosticos.enviar_pronosticos()",
    '''    clave = f"cron:pronosticos:{datetime.now(timezone.utc).date().isoformat()}"
    return telegram_pronosticos.enviar_pronosticos(idempotency_key=clave)''',
    1,
)
s = s.replace(
    "    return telegram_pronosticos.enviar_momios_estado(solo_si_hay=solo_si_hay)",
    '''    clave = f"cron:momios:{datetime.now(timezone.utc).date().isoformat()}" if solo_si_hay else None
    return telegram_pronosticos.enviar_momios_estado(solo_si_hay=solo_si_hay, idempotency_key=clave)''',
    1,
)
p.write_text(s, encoding="utf-8")

Path("tests/test_telegram_delivery_v2.py").write_text('''#!/usr/bin/env python3
"""Regresiones de webhook, leases y entrega multipart Telegram."""
from __future__ import annotations

import os
import tempfile
from datetime import date
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from src import database as db
from src.api import app
from src.telegram import envio


def _sqlite_temporal(tmp: Path):
    return (
        mock.patch.object(db, "USE_POSTGRES", False),
        mock.patch.object(db, "PH", "?"),
        mock.patch.object(db, "SQLITE_PATH", str(tmp / "telegram-v2.db")),
    )


def test_lease_abandonado_se_recupera_una_sola_vez():
    with tempfile.TemporaryDirectory() as carpeta:
        patches = _sqlite_temporal(Path(carpeta))
        with patches[0], patches[1], patches[2]:
            db.init_db()
            assert db.reclamar_telegram_update(7001)
            with db.get_db() as conn:
                conn.execute("UPDATE telegram_updates SET locked_until='2000-01-01T00:00:00+00:00' WHERE update_id=7001")
                conn.commit()
            assert db.reclamar_telegram_update(7001)
            assert not db.reclamar_telegram_update(7001)


def test_webhook_repetido_no_encola_dos_tareas():
    cliente = TestClient(app)
    payload = {"update_id": 7101, "message": {"chat": {"id": 123}, "text": "/pick"}}
    headers = {"X-Telegram-Bot-Api-Secret-Token": "ok"}
    with (
        mock.patch.dict(os.environ, {"TELEGRAM_WEBHOOK_SECRET": "ok", "TELEGRAM_CHAT_ID": "123"}),
        mock.patch("src.database.reclamar_telegram_update", side_effect=[True, False]),
        mock.patch("src.database.completar_telegram_update") as completar,
        mock.patch("src.telegram_pronosticos.enviar_mensaje", return_value=True),
        mock.patch("src.api.BackgroundTasks.add_task") as tarea,
    ):
        primero = cliente.post("/telegram/webhook", json=payload, headers=headers)
        segundo = cliente.post("/telegram/webhook", json=payload, headers=headers)
    assert primero.status_code == 200
    assert segundo.json()["duplicado"] is True
    tarea.assert_called_once()
    completar.assert_called_once_with(7101)


def test_ack_fallido_de_comando_pesado_es_reintentable():
    cliente = TestClient(app)
    payload = {"update_id": 7102, "message": {"chat": {"id": 123}, "text": "/pick"}}
    headers = {"X-Telegram-Bot-Api-Secret-Token": "ok"}
    with (
        mock.patch.dict(os.environ, {"TELEGRAM_WEBHOOK_SECRET": "ok", "TELEGRAM_CHAT_ID": "123"}),
        mock.patch("src.database.reclamar_telegram_update", return_value=True),
        mock.patch("src.database.fallar_telegram_update") as fallar,
        mock.patch("src.telegram_pronosticos.enviar_mensaje", return_value=False),
        mock.patch("src.api.BackgroundTasks.add_task"),
    ):
        respuesta = cliente.post("/telegram/webhook", json=payload, headers=headers)
    assert respuesta.status_code == 502
    fallar.assert_called_once_with(7102, "HTTPException")


def test_reintento_multipart_no_reenvia_parte_exitosa():
    r_ok = mock.Mock(status_code=200, text="ok")
    r_error = mock.Mock(status_code=500, text="error")
    with (
        mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "chat"}),
        mock.patch.object(envio, "_dividir_mensaje", return_value=["a", "b"]),
        mock.patch.object(envio.requests, "post", side_effect=[r_ok, r_error, r_ok]) as post,
        mock.patch("src.database.reclamar_entrega_telegram", side_effect=[True, True, False, True]),
        mock.patch("src.database.completar_entrega_telegram") as completar,
        mock.patch("src.database.fallar_entrega_telegram") as fallar,
    ):
        assert not envio.enviar_mensaje("mensaje", idempotency_key="alerta:multipart")
        assert envio.enviar_mensaje("mensaje", idempotency_key="alerta:multipart")
    assert post.call_count == 3
    assert completar.call_count == 2
    fallar.assert_called_once()


def test_recordatorio_programado_usa_clave_determinista():
    jornada = {"jornada": 3, "fecha_inicio": "2026-07-24", "fecha_fin": "2026-07-26"}
    with (
        mock.patch.object(envio, "proxima_jornada", return_value=jornada),
        mock.patch.object(envio, "enviar_mensaje", return_value=True) as enviar,
    ):
        resultado = envio.enviar_recordatorio_si_aplica(dias_antes=1, hoy=date(2026, 7, 23))
    assert resultado["enviado"] is True
    assert enviar.call_args.kwargs["idempotency_key"] == "recordatorio:2026-07-23:J3:1"
''', encoding="utf-8")
