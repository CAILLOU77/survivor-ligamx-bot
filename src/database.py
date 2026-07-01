#!/usr/bin/env python3
"""
database.py — Capa de persistencia unificada (Postgres en prod, SQLite en local).

Una sola puerta de acceso (`get_db`) para TODO el proyecto, evitando la
inconsistencia anterior (algunos endpoints abrían SQLite directamente con la
cadena de conexión de Postgres, lo que rompía en Render).

Backend según `DATABASE_URL`:
- `postgres://...` o `postgresql://...`  -> PostgreSQL (psycopg2), como en Render.
- cualquier otro valor / vacío           -> SQLite local (archivo), para dev/tests.

Las funciones públicas (init_db, save_pick, get_metrics, get_history,
settle_pick) funcionan igual en ambos backends.
"""
import os
import unicodedata
from contextlib import contextmanager

DATABASE_URL = os.getenv("DATABASE_URL", "") or ""


def _es_postgres(url: str) -> bool:
    return url.startswith("postgres://") or url.startswith("postgresql://")


USE_POSTGRES = _es_postgres(DATABASE_URL)
# Placeholder de parámetros según el backend (Postgres usa %s, SQLite usa ?).
PH = "%s" if USE_POSTGRES else "?"
# Ruta del archivo SQLite cuando no hay Postgres.
SQLITE_PATH = DATABASE_URL if (DATABASE_URL and not USE_POSTGRES) else os.path.join("data", "premium_history.db")


@contextmanager
def get_db():
    """Conexión al backend activo. Cierra siempre al salir."""
    if USE_POSTGRES:
        import psycopg2
        # Neon/algunas URLs ya incluyen `sslmode=...` (y `channel_binding=...`)
        # en la query string; pasarlo TAMBIÉN como kwarg provoca error de
        # "parámetro duplicado". Solo forzamos sslmode si la URL no lo trae.
        if "sslmode=" in DATABASE_URL:
            conn = psycopg2.connect(DATABASE_URL)
        else:
            conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    else:
        import sqlite3
        carpeta = os.path.dirname(SQLITE_PATH)
        if carpeta:
            os.makedirs(carpeta, exist_ok=True)
        conn = sqlite3.connect(SQLITE_PATH)
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    """Crea la tabla `picks` si no existe (sintaxis adaptada por backend)."""
    if USE_POSTGRES:
        id_col = "id SERIAL PRIMARY KEY"
    else:
        id_col = "id INTEGER PRIMARY KEY AUTOINCREMENT"
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS picks (
                {id_col},
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                match_id TEXT,
                market TEXT,
                true_prob REAL,
                momio REAL,
                ev REAL,
                kelly_pct REAL,
                status TEXT DEFAULT 'pending',
                result REAL DEFAULT 0.0,
                profit_loss REAL DEFAULT 0.0
            )
        """)
        # Equipos ya usados en el Survivor (persisten entre deploys, en Neon).
        cur.execute("""
            CREATE TABLE IF NOT EXISTS survivor_usados (
                equipo_norm TEXT PRIMARY KEY,
                equipo TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


def _norm_equipo(s: str) -> str:
    """Normaliza un nombre de equipo (minúsculas, sin acentos, espacios colapsados)."""
    base = unicodedata.normalize("NFKD", str(s or "")).lower()
    base = "".join(c for c in base if not unicodedata.combining(c))
    return " ".join(base.split())


def add_equipo_usado(equipo: str) -> bool:
    """Marca un equipo como usado en el Survivor. True si se agregó, False si ya estaba."""
    norm = _norm_equipo(equipo)
    if not norm:
        return False
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT 1 FROM survivor_usados WHERE equipo_norm = {PH}", (norm,))
        if cur.fetchone():
            return False
        cur.execute(
            f"INSERT INTO survivor_usados (equipo_norm, equipo) VALUES ({PH}, {PH})",
            (norm, str(equipo).strip()),
        )
        conn.commit()
        return True


def get_equipos_usados() -> list:
    """Lista de equipos usados (nombres tal como se guardaron), del más antiguo al reciente."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT equipo FROM survivor_usados ORDER BY created_at")
        return [r[0] for r in cur.fetchall()]


def remove_equipo_usado(equipo: str) -> int:
    """Quita un equipo de la lista de usados. Devuelve filas afectadas (0 o 1)."""
    norm = _norm_equipo(equipo)
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"DELETE FROM survivor_usados WHERE equipo_norm = {PH}", (norm,))
        conn.commit()
        return cur.rowcount


def clear_equipos_usados() -> int:
    """Vacía la lista de equipos usados (reinicia la temporada). Devuelve filas borradas."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM survivor_usados")
        conn.commit()
        return cur.rowcount


def save_pick(match_id, market, true_prob, momio, ev, kelly_pct):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""INSERT INTO picks (match_id, market, true_prob, momio, ev, kelly_pct)
                VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, {PH})""",
            (match_id, market, true_prob, momio, ev, kelly_pct),
        )
        conn.commit()


def get_metrics():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                COUNT(*) as total_picks,
                SUM(CASE WHEN result = 1 THEN 1 ELSE 0 END) as wins,
                SUM(profit_loss) as total_profit,
                AVG(profit_loss) as avg_profit
            FROM picks
            WHERE status = 'settled'
        """)
        row = cur.fetchone()
        total = row[0] or 0
        wins = row[1] or 0
        return {
            "total_picks": total,
            "wins": wins,
            "win_rate": (wins / total * 100) if total > 0 else 0,
            "total_profit": row[2] or 0.0,
            "avg_profit": row[3] or 0.0,
        }


def get_history(limit: int = 20, offset: int = 0):
    """Historial paginado de picks (más recientes primero) como lista de dicts."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT * FROM picks ORDER BY id DESC LIMIT {PH} OFFSET {PH}",
            (limit, offset),
        )
        cols = [d[0] for d in cur.description]
        filas = [dict(zip(cols, fila)) for fila in cur.fetchall()]
        return filas


def settle_pick(pick_id: int, result: float = 0.0, profit_loss: float = 0.0):
    """Marca un pick como 'settled' con su resultado y P/L."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE picks SET status='settled', result={PH}, profit_loss={PH} WHERE id={PH}",
            (result, profit_loss, pick_id),
        )
        conn.commit()
        return cur.rowcount
