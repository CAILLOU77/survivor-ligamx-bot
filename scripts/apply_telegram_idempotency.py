#!/usr/bin/env python3
"""Aplica deduplicación persistente de updates y entregas Telegram."""
from pathlib import Path

# --- Base de datos ---------------------------------------------------------
db_path = Path("src/database.py")
db = db_path.read_text(encoding="utf-8")
if "def reclamar_telegram_update(" in db:
    raise SystemExit("La idempotencia Telegram ya está aplicada")

schema_marker = "        _asegurar_columnas_survivor(cur)\n"
schema = '''        cur.execute("""
            CREATE TABLE IF NOT EXISTS telegram_updates (
                update_id BIGINT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'procesando',
                locked_until TIMESTAMP,
                last_error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS telegram_deliveries (
                idempotency_key TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'procesando',
                locked_until TIMESTAMP,
                last_error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sent_at TIMESTAMP
            )
        """)
'''
if schema_marker not in db:
    raise RuntimeError("No se encontró el punto de migración Telegram")
db = db.replace(schema_marker, schema + schema_marker, 1)

helper_marker = "\ndef _insertar_usado_cursor("
helpers = '''
def _reclamar_idempotencia(
    tabla: str,
    columna: str,
    valor: Any,
    completado: str,
    lease_seconds: int = 300,
) -> bool:
    """Adquiere una llave persistente; permite reintentos fallidos o leases vencidos."""
    if tabla not in {"telegram_updates", "telegram_deliveries"}:
        raise ValueError("Tabla de idempotencia inválida")
    ahora = datetime.now(timezone.utc)
    locked_until = ahora + timedelta(seconds=max(30, int(lease_seconds)))
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"INSERT INTO {tabla} ({columna}, status, locked_until) VALUES ({PH}, 'procesando', {PH}) "
            f"ON CONFLICT ({columna}) DO NOTHING",
            (valor, locked_until),
        )
        if cur.rowcount:
            conn.commit()
            return True
        cur.execute(f"SELECT status, locked_until FROM {tabla} WHERE {columna}={PH}", (valor,))
        fila = cur.fetchone()
        if not fila or str(fila[0]) == completado:
            conn.commit()
            return False
        estado = str(fila[0])
        lease = fila[1]
        if isinstance(lease, str):
            try:
                lease = datetime.fromisoformat(lease.replace("Z", "+00:00"))
            except ValueError:
                lease = None
        if isinstance(lease, datetime) and lease.tzinfo is None:
            lease = lease.replace(tzinfo=timezone.utc)
        vencido = not isinstance(lease, datetime) or lease <= ahora
        if estado != "fallido" and not vencido:
            conn.commit()
            return False
        cur.execute(
            f"UPDATE {tabla} SET status='procesando', locked_until={PH}, last_error=NULL, "
            f"updated_at=CURRENT_TIMESTAMP WHERE {columna}={PH} AND status<>{PH}",
            (locked_until, valor, completado),
        )
        adquirido = bool(cur.rowcount)
        conn.commit()
        return adquirido


def _finalizar_idempotencia(tabla: str, columna: str, valor: Any, status: str, error: str = "") -> None:
    if tabla not in {"telegram_updates", "telegram_deliveries"}:
        raise ValueError("Tabla de idempotencia inválida")
    sent_sql = ", sent_at=CURRENT_TIMESTAMP" if tabla == "telegram_deliveries" and status == "enviado" else ""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE {tabla} SET status={PH}, locked_until=NULL, last_error={PH}, "
            f"updated_at=CURRENT_TIMESTAMP{sent_sql} WHERE {columna}={PH}",
            (status, str(error or "")[:500] or None, valor),
        )
        conn.commit()


def reclamar_telegram_update(update_id: int, lease_seconds: int = 300) -> bool:
    return _reclamar_idempotencia("telegram_updates", "update_id", int(update_id), "procesado", lease_seconds)


def completar_telegram_update(update_id: int) -> None:
    _finalizar_idempotencia("telegram_updates", "update_id", int(update_id), "procesado")


def fallar_telegram_update(update_id: int, error: str = "") -> None:
    _finalizar_idempotencia("telegram_updates", "update_id", int(update_id), "fallido", error)


def reclamar_entrega_telegram(idempotency_key: str, lease_seconds: int = 300) -> bool:
    clave = str(idempotency_key or "").strip()
    if not clave:
        raise ValueError("La llave de idempotencia es obligatoria")
    return _reclamar_idempotencia("telegram_deliveries", "idempotency_key", clave, "enviado", lease_seconds)


def completar_entrega_telegram(idempotency_key: str) -> None:
    _finalizar_idempotencia("telegram_deliveries", "idempotency_key", str(idempotency_key), "enviado")


def fallar_entrega_telegram(idempotency_key: str, error: str = "") -> None:
    _finalizar_idempotencia("telegram_deliveries", "idempotency_key", str(idempotency_key), "fallido", error)

'''
if helper_marker not in db:
    raise RuntimeError("No se encontró el punto para helpers Telegram")
db = db.replace(helper_marker, "\n" + helpers + "def _insertar_usado_cursor(", 1)
db = db.replace("from datetime import datetime, timezone", "from datetime import datetime, timedelta, timezone", 1)
db_path.write_text(db, encoding="utf-8")

# --- Webhook ---------------------------------------------------------------
api_path = Path("src/api.py")
api = api_path.read_text(encoding="utf-8")
start = api.index("    enviado = True\n", api.index("async def telegram_webhook("))
return_line = '    return {"ok": enviado, "comando": cmd}\n'
end = api.index(return_line, start) + len(return_line)
original = api[start:end]
original_without_return = original[: original.rfind(return_line)]
indented = "".join("    " + line if line.strip() else line for line in original_without_return.splitlines(keepends=True))
wrapped = '''    update_id_raw = update.get("update_id")
    update_id = update_id_raw if isinstance(update_id_raw, int) and not isinstance(update_id_raw, bool) else None
    update_reclamado = False
    if update_id is not None:
        from src.database import reclamar_telegram_update

        update_reclamado = reclamar_telegram_update(update_id)
        if not update_reclamado:
            return {"ok": True, "duplicado": True, "update_id": update_id}

    try:
''' + indented + '''        if not enviado:
            raise HTTPException(status_code=502, detail="No se pudo entregar la respuesta en Telegram")
    except Exception as exc:
        if update_reclamado and update_id is not None:
            from src.database import fallar_telegram_update

            fallar_telegram_update(update_id, type(exc).__name__)
        raise
    else:
        if update_reclamado and update_id is not None:
            from src.database import completar_telegram_update

            completar_telegram_update(update_id)
        return {"ok": enviado, "comando": cmd, "update_id": update_id}
'''
api = api[:start] + wrapped + api[end:]
api_path.write_text(api, encoding="utf-8")

# --- Entrega saliente por partes ------------------------------------------
envio_path = Path("src/telegram/envio.py")
envio = envio_path.read_text(encoding="utf-8")
envio = envio.replace("import json\n", "import hashlib\nimport json\n", 1)
envio = envio.replace("def enviar_mensaje(mensaje: str) -> bool:", "def enviar_mensaje(mensaje: str, idempotency_key: Optional[str] = None) -> bool:", 1)
envio = envio.replace(
    '''    ok = True
    for parte in _dividir_mensaje(mensaje):
        try:
            resp = requests.post(url, data={"chat_id": chat_id, "text": parte, "parse_mode": "HTML"}, timeout=20)
            if resp.status_code != 200:
                ok = False
                print(f"Telegram HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as exc:  # pragma: no cover
            # requests puede incluir la URL (y por tanto el bot token) en la
            # excepción; registra solo el tipo para no filtrar credenciales.
            logger.error("Error enviando Telegram (%s)", type(exc).__name__)
            ok = False
    return ok''',
    '''    ok = True
    for indice, parte in enumerate(_dividir_mensaje(mensaje), start=1):
        clave_parte = None
        if idempotency_key:
            digest = hashlib.sha256(parte.encode("utf-8")).hexdigest()[:16]
            clave_parte = f"{idempotency_key}:parte:{indice}:{digest}"
            try:
                from src.database import reclamar_entrega_telegram

                if not reclamar_entrega_telegram(clave_parte):
                    continue
            except Exception:
                logger.warning("No se pudo reclamar la entrega Telegram", exc_info=True)
                ok = False
                continue
        try:
            resp = requests.post(url, data={"chat_id": chat_id, "text": parte, "parse_mode": "HTML"}, timeout=20)
            if resp.status_code == 200:
                if clave_parte:
                    from src.database import completar_entrega_telegram

                    completar_entrega_telegram(clave_parte)
            else:
                if clave_parte:
                    from src.database import fallar_entrega_telegram

                    fallar_entrega_telegram(clave_parte, f"HTTP {resp.status_code}")
                ok = False
                print(f"Telegram HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as exc:  # pragma: no cover
            if clave_parte:
                try:
                    from src.database import fallar_entrega_telegram

                    fallar_entrega_telegram(clave_parte, type(exc).__name__)
                except Exception:
                    logger.warning("No se pudo marcar la entrega Telegram como fallida", exc_info=True)
            # Nunca registrar URL ni token de Telegram.
            logger.error("Error enviando Telegram (%s)", type(exc).__name__)
            ok = False
    return ok''',
    1,
)
envio_path.write_text(envio, encoding="utf-8")

Path("tests/test_telegram_idempotency.py").write_text('''#!/usr/bin/env python3
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
''', encoding="utf-8")
