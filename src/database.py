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
from typing import Any, Dict, List, cast, Optional
import logging

logger = logging.getLogger(__name__)

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
    except Exception:
        try:
            conn.rollback()
        except Exception:
            logger.debug("Exception silenciada en get_db", exc_info=True)
        raise
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
        # Historial del PICK DE SURVIVOR por jornada (racha: sobrevive/gana/cae).
        cur.execute("""
            CREATE TABLE IF NOT EXISTS survivor_historial (
                jornada TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                fecha TEXT,
                equipo TEXT,
                rival TEXT,
                condicion TEXT,
                local TEXT,
                visitante TEXT,
                no_perder_pct REAL,
                prob_victoria_pct REAL,
                marcador_real TEXT,
                estado TEXT DEFAULT 'pendiente',
                resuelto INTEGER DEFAULT 0
            )
        """)
        # Historial de pronósticos (track-record: marcador exacto + aciertos).
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pronosticos_historial (
                clave TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                fecha TEXT,
                local TEXT,
                visitante TEXT,
                pick_1x2 TEXT,
                prob_local REAL,
                prob_empate REAL,
                prob_visitante REAL,
                marcador_predicho TEXT,
                marcador_real TEXT,
                resultado_real TEXT,
                acierto_1x2 INTEGER,
                acierto_marcador INTEGER,
                resuelto INTEGER DEFAULT 0
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
        return cast(int, cur.rowcount)


def clear_equipos_usados() -> int:
    """Vacía la lista de equipos usados (reinicia la temporada). Devuelve filas borradas."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM survivor_usados")
        conn.commit()
        return cast(int, cur.rowcount)


# ---------------------------------------------------------------------------
# Historial de pronósticos (track-record del modelo: aciertos 1X2 y marcador).
# ---------------------------------------------------------------------------
def _clave_pronostico(local: str, visitante: str, fecha: str) -> str:
    return f"{_norm_equipo(local)}|{_norm_equipo(visitante)}|{str(fecha or '')[:10]}"


def registrar_pronostico(
    local: str,
    visitante: str,
    pick_1x2: str,
    prob_local: float,
    prob_empate: float,
    prob_visitante: float,
    marcador_predicho: str,
    fecha: str = "",
) -> bool:
    """Guarda un pronóstico si no existe (dedup por equipos+fecha). True si se insertó."""
    clave = _clave_pronostico(local, visitante, fecha)
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT 1 FROM pronosticos_historial WHERE clave = {PH}", (clave,))
        if cur.fetchone():
            return False
        cur.execute(
            f"""INSERT INTO pronosticos_historial
                (clave, fecha, local, visitante, pick_1x2, prob_local, prob_empate,
                 prob_visitante, marcador_predicho)
                VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH})""",
            (
                clave,
                str(fecha or "")[:10],
                str(local),
                str(visitante),
                str(pick_1x2),
                float(prob_local or 0),
                float(prob_empate or 0),
                float(prob_visitante or 0),
                str(marcador_predicho or ""),
            ),
        )
        conn.commit()
        return True


def historial_pronosticos(limit: int = 50, offset: int = 0, solo_resueltos: bool = False) -> list:
    """Historial de pronósticos (más recientes primero) como lista de dicts."""
    with get_db() as conn:
        cur = conn.cursor()
        filtro = "WHERE resuelto = 1" if solo_resueltos else ""
        cur.execute(
            f"SELECT * FROM pronosticos_historial {filtro} ORDER BY created_at DESC, clave LIMIT {PH} OFFSET {PH}",
            (limit, offset),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, fila)) for fila in cur.fetchall()]


def settle_pronosticos(resultados) -> int:
    """
    Resuelve pronósticos pendientes con resultados reales. `resultados`: lista de
    {home_team, away_team, home_goals, away_goals, fecha}. Rellena marcador real,
    resultado (1/X/2), y aciertos (1X2 y marcador exacto). Devuelve # resueltos.
    """
    # Índice de resultados por clave (equipos+fecha) y por equipos (respaldo).
    por_clave: Dict[str, Any] = {}
    por_equipos: Dict[str, Any] = {}
    for r in resultados:
        try:
            hg, ag = int(r.get("home_goals")), int(r.get("away_goals"))
        except (TypeError, ValueError):
            continue
        info: Optional[Dict[str, Any]] = {
            "hg": hg,
            "ag": ag,
            "home": r.get("home_team", ""),
            "away": r.get("away_team", ""),
        }
        por_clave[_clave_pronostico(r.get("home_team", ""), r.get("away_team", ""), r.get("fecha", ""))] = info
        por_equipos.setdefault(f"{_norm_equipo(r.get('home_team', ''))}|{_norm_equipo(r.get('away_team', ''))}", info)
    settled = 0
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT clave, local, visitante, pick_1x2, marcador_predicho FROM pronosticos_historial WHERE resuelto = 0"
        )
        pendientes = cur.fetchall()
        for clave, local, visitante, pick_1x2, marcador_pred in pendientes:
            info = por_clave.get(clave)
            if info is None:
                info = por_equipos.get(f"{_norm_equipo(local)}|{_norm_equipo(visitante)}")
            if info is None:
                continue
            hg, ag = info["hg"], info["ag"]
            res = "1" if hg > ag else ("2" if ag > hg else "X")
            pick_map = {"gana local": "1", "empate": "X", "gana visitante": "2"}
            pick_norm = pick_map.get(str(pick_1x2 or "").strip().lower())
            acierto_1x2 = 1 if pick_norm == res else 0
            marcador_real = f"{hg}-{ag}"
            acierto_marcador = 1 if str(marcador_pred or "").strip() == marcador_real else 0
            cur.execute(
                f"""UPDATE pronosticos_historial SET marcador_real={PH}, resultado_real={PH},
                    acierto_1x2={PH}, acierto_marcador={PH}, resuelto=1 WHERE clave={PH}""",
                (marcador_real, res, acierto_1x2, acierto_marcador, clave),
            )
            settled += 1
        conn.commit()
    return settled


def rentabilidad_pronosticos() -> dict:
    """Track-record: aciertos 1X2 y de marcador exacto sobre los pronósticos resueltos."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*), COALESCE(SUM(acierto_1x2),0), COALESCE(SUM(acierto_marcador),0)
            FROM pronosticos_historial WHERE resuelto = 1
        """)
        row = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM pronosticos_historial WHERE resuelto = 0")
        pend = cur.fetchone()[0] or 0
    n = row[0] or 0
    a1x2 = row[1] or 0
    amarc = row[2] or 0
    return {
        "resueltos": n,
        "pendientes": pend,
        "aciertos_1x2": a1x2,
        "acierto_1x2_pct": round(100.0 * a1x2 / n, 1) if n else None,
        "aciertos_marcador_exacto": amarc,
        "acierto_marcador_pct": round(100.0 * amarc / n, 1) if n else None,
    }


# ---------------------------------------------------------------------------
# Historial del PICK DE SURVIVOR (racha real: sobrevive / gana / cae por jornada)
# ---------------------------------------------------------------------------
def registrar_survivor_pick(
    jornada: str,
    equipo: str,
    rival: str,
    condicion: str,
    local: str,
    visitante: str,
    no_perder_pct: float,
    prob_victoria_pct: float,
    fecha: str = "",
) -> bool:
    """
    Registra (o actualiza si aún está pendiente) el pick de Survivor de una
    jornada. Una fila por jornada. Si ya está RESUELTO, no se sobreescribe.
    Devuelve True si insertó/actualizó.
    """
    if not jornada or not equipo:
        return False
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT resuelto FROM survivor_historial WHERE jornada = {PH}", (str(jornada),))
        row = cur.fetchone()
        if row is not None:
            if row[0]:  # ya resuelto: bloqueado
                return False
            cur.execute(
                f"""UPDATE survivor_historial SET fecha={PH}, equipo={PH}, rival={PH},
                    condicion={PH}, local={PH}, visitante={PH}, no_perder_pct={PH},
                    prob_victoria_pct={PH} WHERE jornada={PH}""",
                (
                    str(fecha or "")[:10],
                    str(equipo),
                    str(rival or ""),
                    str(condicion or ""),
                    str(local or ""),
                    str(visitante or ""),
                    float(no_perder_pct or 0),
                    float(prob_victoria_pct or 0),
                    str(jornada),
                ),
            )
        else:
            cur.execute(
                f"""INSERT INTO survivor_historial
                    (jornada, fecha, equipo, rival, condicion, local, visitante,
                     no_perder_pct, prob_victoria_pct)
                    VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH})""",
                (
                    str(jornada),
                    str(fecha or "")[:10],
                    str(equipo),
                    str(rival or ""),
                    str(condicion or ""),
                    str(local or ""),
                    str(visitante or ""),
                    float(no_perder_pct or 0),
                    float(prob_victoria_pct or 0),
                ),
            )
        conn.commit()
        return True


def settle_survivor(resultados) -> int:
    """
    Resuelve picks de Survivor pendientes con resultados reales. Determina si el
    equipo elegido GANÓ (punto), EMPATÓ (sobrevive sin punto) o PERDIÓ (eliminado).
    Devuelve # resueltos.
    """
    por_equipos: Dict[str, Any] = {}
    for r in resultados:
        try:
            hg, ag = int(r.get("home_goals")), int(r.get("away_goals"))
        except (TypeError, ValueError):
            continue
        clave = f"{_norm_equipo(r.get('home_team', ''))}|{_norm_equipo(r.get('away_team', ''))}"
        por_equipos.setdefault(clave, {"hg": hg, "ag": ag})
    settled = 0
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT jornada, condicion, local, visitante FROM survivor_historial WHERE resuelto = 0")
        pendientes = cur.fetchall()
        for jornada, condicion, local, visitante in pendientes:
            info = por_equipos.get(f"{_norm_equipo(local)}|{_norm_equipo(visitante)}")
            if info is None:
                continue
            hg, ag = info["hg"], info["ag"]
            es_local = str(condicion or "").strip().lower() == "local"
            gf, gc = (hg, ag) if es_local else (ag, hg)
            estado = "gano" if gf > gc else ("empate" if gf == gc else "perdio")
            cur.execute(
                f"""UPDATE survivor_historial SET marcador_real={PH}, estado={PH}, resuelto=1
                    WHERE jornada={PH}""",
                (f"{hg}-{ag}", estado, jornada),
            )
            settled += 1
        conn.commit()
    return settled


def resumen_survivor() -> dict:
    """
    Track-record del Survivor: jornadas jugadas, sobrevividas (gana+empata),
    victorias, empates, si sigue VIVO y en qué jornada cayó. Cronológico por fecha.
    """
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT jornada, fecha, equipo, rival, condicion, marcador_real, estado "
            "FROM survivor_historial WHERE resuelto = 1 ORDER BY fecha, jornada"
        )
        filas = cur.fetchall()
        cur.execute("SELECT COUNT(*) FROM survivor_historial WHERE resuelto = 0")
        pendientes = cur.fetchone()[0] or 0

    jugadas = len(filas)
    victorias = empates = sobrevividas = 0
    eliminado_en = None
    racha = 0
    detalle = []
    vivo = True
    for jornada, fecha, equipo, rival, condicion, marcador, estado in filas:
        detalle.append(
            {
                "jornada": jornada,
                "fecha": fecha,
                "equipo": equipo,
                "rival": rival,
                "condicion": condicion,
                "marcador": marcador,
                "estado": estado,
            }
        )
        if estado == "perdio":
            if eliminado_en is None:
                eliminado_en = jornada
                vivo = False
        else:
            if estado == "gano":
                victorias += 1
            elif estado == "empate":
                empates += 1
            sobrevividas += 1
        if vivo:
            racha += 1
    return {
        "jugadas": jugadas,
        "pendientes": pendientes,
        "sobrevividas": sobrevividas,
        "victorias": victorias,
        "empates": empates,
        "eliminado_en": eliminado_en,
        "sigue_vivo": vivo,
        "racha": racha,
        "detalle": detalle,
    }


def get_survivor_picks_recientes(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Picks de Survivor recientes (pendientes o resueltos) para comparar
    con resultados reales. Devuelve lista de dicts con:
    {jornada, equipo, rival, condicion, local, visitante, ...}
    """
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT jornada, equipo, rival, condicion, local, visitante, "
            f"no_perder_pct, prob_victoria_pct, marcador_real, estado, resuelto "
            f"FROM survivor_historial ORDER BY fecha DESC LIMIT {PH}",
            (limit,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, fila)) for fila in cur.fetchall()]


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
