#!/usr/bin/env python3
"""
api_role_router.py — Inventario y matriz de roles de APIs (Survivor Liga MX).

v1.36.0 — API Role Router & Health Matrix.

Qué hace:
- Ordena todas las APIs por FUNCIÓN (rol), ESTADO y USO operativo.
- Detecta si la variable de entorno está presente (SET/MISSING) SIN imprimir
  jamás el valor del secreto.
- Clasifica condiciones especiales:
    * The Odds API: ODDS_MARKETS recomendado h2h,totals,spreads. BTTS/Draw No Bet
      pueden no estar soportados -> UNSUPPORTED_MARKET_CONFIG. HTTP 422 por mercado
      no soportado NO es fallo de llave.
    * API-Football: bloqueo por plan/temporada 2026 -> PLAN_BLOCKED_2026. No rotar
      llave por plan/temporada/quota/auth; solo por fallo técnico real. Marca
      RECHECK_BEFORE_MATCH (T-48h, T-24h, T-6h, T-2h, T-60m).
    * Cerebras / OpenRouter / Fireworks: permanecen DISABLED_BY_CONFIG (no se
      activan en esta versión, aunque la llave exista).

Qué NO hace:
- No toma picks, no manda Telegram, no activa proveedores nuevos.
- No hace llamadas externas. No imprime secretos.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional


BASE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = BASE_DIR / ".env"


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
ROLE_MARKET_TRUTH = "MARKET_TRUTH"
ROLE_TEAM_NEWS = "TEAM_NEWS_LINEUPS"
ROLE_MANUAL_STATS = "MANUAL_STATS_AUDIT"
ROLE_SCHEDULE_FALLBACK = "SCHEDULE_FALLBACK"
ROLE_NEWS_RISK = "NEWS_RISK"
ROLE_PRIMARY_AI = "PRIMARY_AI_ANALYSIS"
ROLE_STABLE_AI_FALLBACK = "STABLE_AI_FALLBACK"
ROLE_FAST_SECOND_OPINION = "FAST_SECOND_OPINION"
ROLE_EMERGENCY_ROUTER = "EMERGENCY_MODEL_ROUTER"
ROLE_BACKUP_CLASSIFIER = "BACKUP_AI_CLASSIFIER"

# ---------------------------------------------------------------------------
# Estados
# ---------------------------------------------------------------------------
ST_CONFIGURED = "CONFIGURED"
ST_MISSING = "MISSING_ENV"
ST_CONFIGURED_UNKNOWN = "CONFIGURED_UNKNOWN"
ST_PLAN_BLOCKED_2026 = "PLAN_BLOCKED_2026"
ST_MANUAL_LOCAL = "MANUAL_LOCAL"
ST_DISABLED_BY_CONFIG = "DISABLED_BY_CONFIG"
ST_KEYLESS_OK = "KEYLESS_OK"
ST_OPTIONAL = "OPTIONAL_FALLBACK"
ST_ENABLED_PENDING = "ENABLED_PENDING_CODE_SUPPORT"

# Clasificación de errores
ERR_UNSUPPORTED_MARKET = "UNSUPPORTED_MARKET_CONFIG"
ERR_AUTH = "AUTH_BLOCKED"
ERR_QUOTA = "QUOTA_BLOCKED"
ERR_TECHNICAL = "TECHNICAL_ERROR"
ERR_UNKNOWN = "UNKNOWN"

# Env presence
ENV_SET = "SET"
ENV_MISSING = "MISSING"
ENV_NA = "N/A"

RECHECK_TAG = "RECHECK_BEFORE_MATCH"
RECHECK_VENTANAS = "T-48h, T-24h, T-6h, T-2h, T-60m"

RECOMMENDED_ODDS_MARKETS = ["h2h", "totals", "spreads"]
OPTIONAL_ODDS_MARKETS = {"btts", "draw_no_bet"}

_PLACEHOLDERS = {
    "", "none", "null", "tu_api_key", "your_api_key", "changeme", "replace_me",
}


# ---------------------------------------------------------------------------
# Utilidades de entorno (NUNCA imprimen el valor)
# ---------------------------------------------------------------------------
def cargar_env_local(path: Path = ENV_PATH) -> None:
    """Carga .env local sin imprimir secretos y sin sobrescribir el entorno."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _valor_util(value: Optional[str]) -> bool:
    if value is None:
        return False
    v = str(value).strip().strip('"').strip("'")
    low = v.lower()
    if low in _PLACEHOLDERS:
        return False
    if "tu_api_key" in low or "your_api_key" in low:
        return False
    return bool(v)


def env_set(env: Dict[str, str], names: List[str]) -> bool:
    """True si ALGUNA de las variables está presente y es utilizable.

    No devuelve ni registra el valor; solo un booleano.
    """
    for n in names:
        if _valor_util(env.get(n)):
            return True
    return False


def parse_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().strip('"').strip("'").lower() in {"1", "true", "yes", "on", "si", "sí"}


# ---------------------------------------------------------------------------
# The Odds API — clasificación de mercados y errores
# ---------------------------------------------------------------------------
def clasificar_odds_markets(markets_str: Optional[str]) -> Dict[str, Any]:
    """
    Clasifica la config de ODDS_MARKETS.
    - Recomendado: h2h,totals,spreads.
    - btts / draw_no_bet -> UNSUPPORTED_MARKET_CONFIG (pueden causar HTTP 422).
    """
    raw = [m.strip().lower() for m in str(markets_str or "").split(",") if m.strip()]
    notas: List[str] = []
    status = "OK"

    no_soportados = [m for m in raw if m in OPTIONAL_ODDS_MARKETS]
    if no_soportados:
        status = ERR_UNSUPPORTED_MARKET
        notas.append(
            "BTTS/Draw No Bet pueden no estar soportados (riesgo HTTP 422): "
            + ", ".join(no_soportados)
        )

    if raw == RECOMMENDED_ODDS_MARKETS:
        notas.append("Config recomendada: h2h,totals,spreads")
    elif not no_soportados and raw:
        notas.append("Config dentro de mercados soportados.")

    return {"status": status, "markets": raw, "notas": notas, "recomendado": raw == RECOMMENDED_ODDS_MARKETS}


def clasificar_error_odds(status_code: Optional[int]) -> str:
    """HTTP 422 = mercado no soportado (NO es fallo de llave)."""
    if status_code == 422:
        return ERR_UNSUPPORTED_MARKET
    if status_code in (401, 403):
        return ERR_AUTH
    if status_code == 429:
        return ERR_QUOTA
    if status_code in (500, 502, 503, 504):
        return ERR_TECHNICAL
    return ERR_UNKNOWN


# ---------------------------------------------------------------------------
# API-Football — clasificación de bloqueo de plan/temporada y rotación
# ---------------------------------------------------------------------------
_SEASON_MARKERS = ["season", "temporada", "2026"]
_PLAN_MARKERS = [
    "plan", "subscription", "subscribe", "upgrade", "not allowed for your",
    "free plan", "access restricted", "not available in your plan",
]
_QUOTA_MARKERS = ["quota", "rate limit", "too many requests", "requests limit", "daily limit"]
_AUTH_MARKERS = ["invalid api key", "unauthorized", "invalid token", "missing api key"]
_TECH_MARKERS = [
    "timeout", "connection", "temporarily unavailable", "server error",
    "bad gateway", "gateway timeout", "service unavailable",
]


def clasificar_error_apifootball(status_code: Optional[int] = None, mensaje: str = "") -> Dict[str, Any]:
    """
    Clasifica una respuesta/erro de API-Football.

    Devuelve {clasificacion, rotar, motivo}.
    - Plan/temporada -> PLAN_BLOCKED_2026, rotar=False.
    - Quota -> QUOTA_BLOCKED, rotar=False.
    - Auth -> AUTH_BLOCKED, rotar=False.
    - Técnico real (timeout/conexión/5xx) -> TECHNICAL_ERROR, rotar=True.
    Regla: SOLO se rota llave por fallo técnico real.
    """
    text = (mensaje or "").lower()

    es_tecnico = status_code in {500, 502, 503, 504} or any(m in text for m in _TECH_MARKERS)
    es_season = any(m in text for m in _SEASON_MARKERS)
    es_plan = any(m in text for m in _PLAN_MARKERS)
    es_quota = any(m in text for m in _QUOTA_MARKERS)
    es_auth = status_code in {401, 403} or any(m in text for m in _AUTH_MARKERS)

    if (es_plan or es_season) and not es_tecnico:
        return {"clasificacion": ST_PLAN_BLOCKED_2026, "rotar": False, "motivo": "plan/temporada"}
    if es_quota and not es_tecnico:
        return {"clasificacion": ERR_QUOTA, "rotar": False, "motivo": "quota"}
    if es_auth and not es_tecnico:
        return {"clasificacion": ERR_AUTH, "rotar": False, "motivo": "auth"}
    if es_tecnico:
        return {"clasificacion": ERR_TECHNICAL, "rotar": True, "motivo": "tecnico"}

    # Desconocido no técnico: por seguridad, no rotamos.
    return {"clasificacion": ERR_UNKNOWN, "rotar": False, "motivo": "desconocido"}


def debe_rotar_llave(clasificacion_error: Dict[str, Any]) -> bool:
    """Solo se rota por fallo técnico real."""
    return bool(clasificacion_error.get("rotar"))


def clasificar_estado_apifootball(env: Dict[str, str]) -> str:
    """
    Estado de API-Football para la matriz (sin llamadas externas).
    - Si una bandera indica bloqueo de temporada/plan 2026 -> PLAN_BLOCKED_2026.
    - Si hay llave -> CONFIGURED_UNKNOWN (no se puede verificar sin llamada).
    - Si no hay llave -> MISSING_ENV.
    """
    if not env_set(env, APIFOOTBALL_KEY_ENVS):
        return ST_MISSING

    if (
        parse_bool(env.get("APIFOOTBALL_PLAN_BLOCKED_2026"))
        or parse_bool(env.get("APIFOOTBALL_SEASON_2026_BLOCKED"))
    ):
        return ST_PLAN_BLOCKED_2026

    return ST_CONFIGURED_UNKNOWN


# ---------------------------------------------------------------------------
# Definición de proveedores y construcción de la matriz
# ---------------------------------------------------------------------------
ODDS_KEY_ENVS = ["ODDS_API_KEY_PRIMARY", "ODDS_API_KEY", "ODDS_API_KEY_BACKUP"]
APIFOOTBALL_KEY_ENVS = [
    "FOOTBALL_API_KEY_1", "FOOTBALL_API_KEY_2", "APIFOOTBALL_KEY", "FOOTBALL_API_KEY",
]
THESPORTSDB_KEY_ENVS = ["THESPORTSDB_API_KEY"]
GROQ_KEY_ENVS = ["GROQ_API_KEY_PRIMARY", "GROQ_API_KEY", "GROQ_API_KEY_BACKUP"]
GEMINI_KEY_ENVS = ["GEMINI_API_KEY", "GEMINI_API_KEY_BACKUP"]
CEREBRAS_KEY_ENVS = ["CEREBRAS_API_KEY"]
OPENROUTER_KEY_ENVS = ["OPENROUTER_API_KEY"]
FIREWORKS_KEY_ENVS = ["FIREWORKS_API_KEY"]

# Proveedores deshabilitados por configuración en esta versión.
DISABLED_PROVIDERS = ("Cerebras", "OpenRouter", "Fireworks")


def _record(
    name: str,
    role: str,
    *,
    env: str = ENV_NA,
    enabled: Optional[bool] = None,
    status: str,
    uso: str,
    notas: Optional[List[str]] = None,
    recheck: bool = False,
    activo: bool = False,
) -> Dict[str, Any]:
    return {
        "name": name,
        "role": role,
        "env": env,
        "enabled": enabled,
        "status": status,
        "uso": uso,
        "notas": list(notas or []),
        "recheck": recheck,
        "activo": activo,
    }


def _record_opcional_ia(env: Dict[str, str], name: str, role: str, key_envs: List[str], enabled_env: str, uso: str) -> Dict[str, Any]:
    has = env_set(env, key_envs)
    enabled = parse_bool(env.get(enabled_env), default=False)
    env_status = ENV_SET if has else ENV_MISSING

    if not enabled:
        status = ST_DISABLED_BY_CONFIG
        notas = [f"{enabled_env}=false. No se activa hasta que el código lo soporte."]
    else:
        status = ST_ENABLED_PENDING
        notas = [
            f"{enabled_env}=true pero el código aún no lo soporta; NO se usa en esta versión.",
        ]

    # Estos proveedores NUNCA se marcan activos en v1.36.0.
    return _record(name, role, env=env_status, enabled=enabled, status=status, uso=uso, notas=notas, activo=False)


def build_matrix(env: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    env = dict(os.environ if env is None else env)
    matrix: List[Dict[str, Any]] = []

    # 1) The Odds API — MARKET_TRUTH
    odds_set = env_set(env, ODDS_KEY_ENVS)
    markets_info = clasificar_odds_markets(env.get("ODDS_MARKETS"))
    odds_notas: List[str] = []
    odds_markets_str = env.get("ODDS_MARKETS", "").strip()
    odds_notas.append(f"ODDS_MARKETS={odds_markets_str or 'h2h,totals,spreads (default recomendado)'}")
    odds_notas.extend(markets_info["notas"])
    odds_notas.append("HTTP 422 por mercado no soportado = UNSUPPORTED_MARKET_CONFIG (no es fallo de llave).")
    matrix.append(_record(
        "The Odds API", ROLE_MARKET_TRUTH,
        env=ENV_SET if odds_set else ENV_MISSING,
        status=ST_CONFIGURED if odds_set else ST_MISSING,
        uso="mercado real / h2h-1X2 / totals / spreads / movimiento de momios",
        notas=odds_notas,
        activo=odds_set,
    ))

    # 2) API-Football — TEAM_NEWS_LINEUPS
    af_set = env_set(env, APIFOOTBALL_KEY_ENVS)
    af_status = clasificar_estado_apifootball(env)
    matrix.append(_record(
        "API-Football", ROLE_TEAM_NEWS,
        env=ENV_SET if af_set else ENV_MISSING,
        status=af_status,
        uso="fixtures / alineaciones / lesiones / suspendidos / titulares",
        notas=[
            f"{RECHECK_TAG}: puede actualizarse antes de cada partido ({RECHECK_VENTANAS}).",
            "No rotar llave por plan/temporada/quota/auth; solo por fallo técnico real.",
            "Temporada 2026 bloqueada por plan se clasifica como PLAN_BLOCKED_2026 (no error técnico).",
        ],
        recheck=True,
        activo=af_set and af_status != ST_PLAN_BLOCKED_2026,
    ))

    # 3) FBref / Stathead — MANUAL_STATS_AUDIT
    matrix.append(_record(
        "FBref / Stathead", ROLE_MANUAL_STATS,
        env=ENV_NA,
        status=ST_MANUAL_LOCAL,
        uso="calendario manual / local-visitante / estadio / stats cuando haya partidos jugados",
        notas=[
            "No scraping, no red, no sobrescribe data/jornadas.json.",
            "No es verdad automática; auditoría manual local.",
        ],
        activo=False,
    ))

    # 4) TheSportsDB / ESPN — SCHEDULE_FALLBACK
    sdb_set = env_set(env, THESPORTSDB_KEY_ENVS)
    matrix.append(_record(
        "TheSportsDB / ESPN", ROLE_SCHEDULE_FALLBACK,
        env=ENV_SET if sdb_set else ENV_NA,
        status=ST_OPTIONAL,
        uso="confirmar calendario / detectar diferencias de horario o sede",
        notas=["Fuente secundaria, no verdad única."],
        activo=False,
    ))

    # 5) DuckDuckGo / Web News — NEWS_RISK
    matrix.append(_record(
        "DuckDuckGo / Web News", ROLE_NEWS_RISK,
        env=ENV_NA,
        status=ST_KEYLESS_OK,
        uso="bajas de último momento / lesiones / cambio de DT / viaje raro / estadio cambiado / crisis interna",
        notas=["Sin llave; señal de riesgo, no verdad de mercado."],
        activo=False,
    ))

    # 6) Groq — PRIMARY_AI_ANALYSIS
    groq_set = env_set(env, GROQ_KEY_ENVS)
    matrix.append(_record(
        "Groq", ROLE_PRIMARY_AI,
        env=ENV_SET if groq_set else ENV_MISSING,
        status=ST_CONFIGURED if groq_set else ST_MISSING,
        uso="análisis principal / resumen de riesgo / conclusión operativa",
        notas=["No rota por auth/cuota/rate-limit; solo failover técnico a Gemini."],
        activo=groq_set,
    ))

    # 7) Gemini — STABLE_AI_FALLBACK
    gem_set = env_set(env, GEMINI_KEY_ENVS)
    matrix.append(_record(
        "Gemini", ROLE_STABLE_AI_FALLBACK,
        env=ENV_SET if gem_set else ENV_MISSING,
        status=ST_CONFIGURED if gem_set else ST_MISSING,
        uso="fallback si Groq falla técnicamente / segunda lectura",
        notas=["Solo entra por falla técnica de Groq, no por auth/cuota/plan."],
        activo=gem_set,
    ))

    # 8) Cerebras — FAST_SECOND_OPINION (DISABLED_BY_CONFIG)
    matrix.append(_record_opcional_ia(
        env, "Cerebras", ROLE_FAST_SECOND_OPINION, CEREBRAS_KEY_ENVS, "CEREBRAS_ENABLED",
        uso="(futuro) revisión rápida / 'qué se nos escapa' / contradicciones",
    ))

    # 9) OpenRouter — EMERGENCY_MODEL_ROUTER (DISABLED_BY_CONFIG)
    rec_or = _record_opcional_ia(
        env, "OpenRouter", ROLE_EMERGENCY_ROUTER, OPENROUTER_KEY_ENVS, "OPENROUTER_ENABLED",
        uso="(futuro) último respaldo / modelos alternativos",
    )
    rec_or["notas"].append("Al implementarse: manejar content=None de forma segura.")
    matrix.append(rec_or)

    # 10) Fireworks — BACKUP_AI_CLASSIFIER (DISABLED_BY_CONFIG)
    matrix.append(_record_opcional_ia(
        env, "Fireworks", ROLE_BACKUP_CLASSIFIER, FIREWORKS_KEY_ENVS, "FIREWORKS_ENABLED",
        uso="(futuro) clasificador alternativo de riesgo / fallback técnico",
    ))

    return matrix


def proveedor_activo(record: Dict[str, Any]) -> bool:
    """Helper: ¿este proveedor está activo operativamente? (trio siempre False)."""
    if record.get("name") in DISABLED_PROVIDERS:
        return False
    return bool(record.get("activo"))


# ---------------------------------------------------------------------------
# Render del reporte (sin secretos)
# ---------------------------------------------------------------------------
def render_report(matrix: List[Dict[str, Any]]) -> str:
    lineas: List[str] = ["# API HEALTH MATRIX — SURVIVOR LIGA MX", ""]

    for rec in matrix:
        lineas.append(rec["name"])
        lineas.append(f"Role: {rec['role']}")
        if rec["env"] != ENV_NA:
            lineas.append(f"Env: {rec['env']}")
        if rec["enabled"] is not None:
            lineas.append(f"Enabled: {str(rec['enabled']).lower()}")
        lineas.append(f"Status: {rec['status']}")
        lineas.append(f"Operational Use: {rec['uso']}")
        if rec["notas"]:
            lineas.append("Notes: " + " | ".join(rec["notas"]))
        lineas.append("")

    lineas += [
        "DECISIÓN:",
        "- APIs inventariadas.",
        "- No activar proveedores nuevos todavía.",
        "- No cambiar pick.",
        "- No enviar Telegram.",
        "- Mantener ESPERAR / NO ENVIAR.",
    ]

    return "\n".join(lineas) + "\n"
