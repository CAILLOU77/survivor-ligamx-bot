#!/usr/bin/env python3
"""
Buscador web gratis para noticias frescas Liga MX.

v1.30.0
- Usa ddgs / DuckDuckGo sin API key.
- No decide picks.
- No bloquea el bot si falla.
- Escribe:
  - data/noticias_web_frescas.json
  - data/noticias_web_frescas.txt
  - reports/buscador_web_ultimo.txt
- Inyecta sección idempotente en data/noticias_ligamx.txt para que Groq/IA la pueda leer.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"

JSON_OUT = DATA_DIR / "noticias_web_frescas.json"
TXT_OUT = DATA_DIR / "noticias_web_frescas.txt"
REPORT_OUT = REPORTS_DIR / "buscador_web_ultimo.txt"
NOTICIAS_LIGAMX = DATA_DIR / "noticias_ligamx.txt"

START_MARKER = "### INICIO_NOTICIAS_WEB_FRESCAS_DUCKDUCKGO ###"
END_MARKER = "### FIN_NOTICIAS_WEB_FRESCAS_DUCKDUCKGO ###"

MAX_RESULTS_PER_QUERY = 5

QUERIES = [
    "Liga MX Jornada 1 2026 bajas lesionados suspendidos",
    "Liga MX 2026 lesionados rotaciones rueda de prensa",
    "Liga MX bajas lesionados suspendidos hoy",
    "Liga MX noticias lesiones fichajes pretemporada",
    "América Cruz Azul Tigres Monterrey bajas lesionados Liga MX",
    "Necaxa Atlante Liga MX bajas lesionados",
    "Tijuana Tigres Liga MX bajas lesionados",
    "Atlético San Luis Cruz Azul Liga MX bajas lesionados",
    "León Atlas Liga MX bajas lesionados",
    "FC Juárez Puebla Liga MX bajas lesionados",
    "Pumas Pachuca Liga MX bajas lesionados",
    "Guadalajara Toluca Liga MX bajas lesionados",
    "Monterrey Santos Liga MX bajas lesionados",
    "Querétaro América Liga MX bajas lesionados",
]

INCLUDE_SIGNALS = [
    "liga mx",
    "apertura 2026",
    "clausura 2026",
    "futbol mexicano",
    "fútbol mexicano",
    "america",
    "américa",
    "cruz azul",
    "tigres",
    "monterrey",
    "toluca",
    "guadalajara",
    "chivas",
    "pumas",
    "pachuca",
    "necaxa",
    "atlante",
    "tijuana",
    "xolos",
    "atletico san luis",
    "atlético san luis",
    "san luis",
    "leon",
    "león",
    "atlas",
    "juarez",
    "juárez",
    "puebla",
    "santos",
    "queretaro",
    "querétaro",
]

RELEVANCE_NEWS_SIGNALS = [
    "baja",
    "bajas",
    "lesion",
    "lesión",
    "lesionado",
    "lesionados",
    "suspendido",
    "suspendidos",
    "convocado",
    "convocados",
    "fichaje",
    "fichajes",
    "rumor",
    "rumores",
    "alta",
    "altas",
    "pretemporada",
    "plantilla",
    "refuerzo",
    "refuerzos",
    "mercado",
    "alineacion",
    "alineación",
    "alineaciones",
    "probables",
    "rueda de prensa",
]

EXCLUDE_SIGNALS = [
    "laliga",
    "la liga",
    "primera división de españa",
    "atletico de madrid",
    "atlético de madrid",
    "real madrid",
    "barcelona",
    "fc barcelona",
    "progressive",
    "insurance",
    "ea sports fc",
    "ultimate team",
    "wikipedia",
    "liga mx femenil",
    "tripadvisor",
    "tourism",
    "turismo",
    "atracciones",
    "museo",
    "hoteles",
    "viajar",
    "cosas que ver",
    "cosas que hacer",
    "calendario de tv",
    "canales de tv",
    "transmisiones",
    "partidos de fútbol de hoy",
    "fútbol en vivo hoy",
    "futbol en vivo hoy",
    "en vivo",
    "horario",
    "dónde ver",
    "donde ver",
    "canal",
    "canales",
    "marcadores en directo",
    "resultados y partidos",
    "resultado final",
    "resumen del partido",
    "resumen |",
    "minuto a minuto",
    "liguilla",
    "youtube.com",
    "youtu.be",
    "facebook.com",
    "apuestas",
    "pronósticos",
    "pronosticos",
    "detalles y estadisticas",
    "detalles y estadísticas",
    "jornada 4",
    "jornada 5",
    "apertura 2024",
    "apertura 2025",
    "clausura 2025",
    "clausura 2009",
    "2008",
    "2009",
    "2022",
    "2024",
    "2025/01",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\x00", "").strip()


def normalize_result(query: str, item: Dict[str, Any], pass_name: str) -> Dict[str, str]:
    title = safe_text(item.get("title"))
    href = safe_text(item.get("href") or item.get("url"))
    body = safe_text(item.get("body") or item.get("snippet"))

    return {
        "query": query,
        "pass": pass_name,
        "title": title,
        "url": href,
        "snippet": body,
    }


def is_relevant_result(item: Dict[str, str]) -> bool:
    title = item.get("title", "")
    url = item.get("url", "")
    snippet = item.get("snippet", "")
    query = item.get("query", "")

    content_haystack = " ".join([title, url, snippet]).lower()
    full_haystack = " ".join([title, url, snippet, query]).lower()

    if any(signal in full_haystack for signal in EXCLUDE_SIGNALS):
        return False

    has_ligamx_context = any(signal in full_haystack for signal in INCLUDE_SIGNALS)
    has_news_value = any(signal in content_haystack for signal in RELEVANCE_NEWS_SIGNALS)

    return has_ligamx_context and has_news_value


def dedupe_results(results: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = set()
    clean: List[Dict[str, str]] = []

    for item in results:
        if not is_relevant_result(item):
            continue

        url = item.get("url", "").strip()
        title = item.get("title", "").strip()

        key = url.lower() if url else title.lower()
        if not key or key in seen:
            continue

        seen.add(key)
        clean.append(item)

    return clean


def load_ddgs_class() -> Tuple[Optional[Any], str, str]:
    try:
        from ddgs import DDGS  # type: ignore

        return DDGS, "ddgs", ""
    except Exception as exc_ddgs:
        try:
            from duckduckgo_search import DDGS  # type: ignore

            return DDGS, "duckduckgo_search", (
                f"No se pudo importar ddgs; fallback duckduckgo_search. "
                f"Detalle ddgs: {type(exc_ddgs).__name__}: {exc_ddgs}"
            )
        except Exception as exc_old:
            return (
                None,
                "",
                "No se pudo importar ddgs ni duckduckgo_search: "
                f"ddgs={type(exc_ddgs).__name__}: {exc_ddgs}; "
                f"duckduckgo_search={type(exc_old).__name__}: {exc_old}",
            )


def run_search_pass(ddgs: Any, timelimit: Optional[str], pass_name: str) -> Tuple[List[Dict[str, str]], List[str]]:
    all_results: List[Dict[str, str]] = []
    errors: List[str] = []

    for query in QUERIES:
        try:
            raw_results = ddgs.text(
                query,
                region="mx-es",
                safesearch="moderate",
                timelimit=timelimit,
                max_results=MAX_RESULTS_PER_QUERY,
            )

            for item in raw_results or []:
                if isinstance(item, dict):
                    all_results.append(normalize_result(query, item, pass_name))

        except Exception as exc:
            errors.append(f"{pass_name} | {query}: {type(exc).__name__}: {exc}")

    return all_results, errors


def search_duckduckgo() -> Dict[str, Any]:
    DDGS, provider, import_warning = load_ddgs_class()

    if DDGS is None:
        return {
            "ok": False,
            "error": import_warning,
            "provider": provider,
            "generated_at_utc": utc_now_iso(),
            "queries": QUERIES,
            "results": [],
        }

    all_results: List[Dict[str, str]] = []
    errors: List[str] = []
    passes_used: List[str] = []

    try:
        with DDGS(timeout=15) as ddgs:
            fresh_results, fresh_errors = run_search_pass(
                ddgs=ddgs,
                timelimit="m",
                pass_name="ultimo_mes",
            )
            all_results.extend(fresh_results)
            errors.extend(fresh_errors)
            passes_used.append("ultimo_mes")

            clean_after_fresh = dedupe_results(all_results)

            if len(clean_after_fresh) == 0:
                broad_results, broad_errors = run_search_pass(
                    ddgs=ddgs,
                    timelimit=None,
                    pass_name="sin_filtro_tiempo",
                )
                all_results.extend(broad_results)
                errors.extend(broad_errors)
                passes_used.append("sin_filtro_tiempo")

    except Exception as exc:
        return {
            "ok": False,
            "error": f"DuckDuckGo falló: {type(exc).__name__}: {exc}",
            "provider": provider,
            "import_warning": import_warning,
            "generated_at_utc": utc_now_iso(),
            "queries": QUERIES,
            "results": [],
            "query_errors": errors,
            "passes_used": passes_used,
        }

    clean_results = dedupe_results(all_results)

    return {
        "ok": True,
        "error": "",
        "provider": provider,
        "import_warning": import_warning,
        "generated_at_utc": utc_now_iso(),
        "queries": QUERIES,
        "results_count": len(clean_results),
        "results": clean_results,
        "query_errors": errors,
        "passes_used": passes_used,
    }


def build_txt(payload: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("NOTICIAS WEB FRESCAS LIGA MX — DUCKDUCKGO")
    lines.append(f"Generado UTC: {payload.get('generated_at_utc', '')}")
    lines.append(f"Proveedor: {payload.get('provider', '')}")
    lines.append(f"Pasadas usadas: {', '.join(payload.get('passes_used') or [])}")
    lines.append("")
    lines.append("IMPORTANTE:")
    lines.append("- Este archivo NO decide picks.")
    lines.append("- Sirve como insumo de noticias para auditoría IA/Groq.")
    lines.append("- CERRAR solo con mercado real, XI, lesiones y noticias confirmadas.")
    lines.append("- Si solo hay fallback técnico: NO ENVIAR.")
    lines.append("")

    import_warning = payload.get("import_warning")
    if import_warning:
        lines.append("ADVERTENCIA IMPORT:")
        lines.append(str(import_warning))
        lines.append("")

    if not payload.get("ok"):
        lines.append("ESTADO: FALLO")
        lines.append(f"ERROR: {payload.get('error', '')}")
        lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    results = payload.get("results", [])
    lines.append("ESTADO: OK")
    lines.append(f"Resultados únicos: {len(results)}")
    lines.append("")

    if not results:
        lines.append("Sin resultados frescos recuperados.")
        lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    for idx, item in enumerate(results, start=1):
        lines.append(f"{idx}. {item.get('title', '').strip()}")
        lines.append(f"   Pasada: {item.get('pass', '').strip()}")
        lines.append(f"   Query: {item.get('query', '').strip()}")
        lines.append(f"   URL: {item.get('url', '').strip()}")
        snippet = item.get("snippet", "").strip()
        if snippet:
            lines.append(f"   Resumen: {snippet}")
        lines.append("")

    query_errors = payload.get("query_errors") or []
    if query_errors:
        lines.append("ERRORES PARCIALES POR QUERY:")
        for err in query_errors:
            lines.append(f"- {err}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def build_injection_section(payload: Dict[str, Any]) -> str:
    txt = build_txt(payload).strip()

    return (
        f"{START_MARKER}\n"
        f"{txt}\n"
        f"{END_MARKER}\n"
    )


def inject_idempotent(section: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if NOTICIAS_LIGAMX.exists():
        original = NOTICIAS_LIGAMX.read_text(encoding="utf-8", errors="replace")
    else:
        original = ""

    if START_MARKER in original and END_MARKER in original:
        before = original.split(START_MARKER, 1)[0].rstrip()
        after = original.split(END_MARKER, 1)[1].lstrip()
        new_text = f"{before}\n\n{section}\n{after}".strip() + "\n"
    else:
        if original.strip():
            new_text = original.rstrip() + "\n\n" + section
        else:
            new_text = section

    NOTICIAS_LIGAMX.write_text(new_text, encoding="utf-8")


def write_outputs(payload: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    txt = build_txt(payload)
    section = build_injection_section(payload)

    JSON_OUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    TXT_OUT.write_text(txt, encoding="utf-8")
    REPORT_OUT.write_text(txt, encoding="utf-8")
    inject_idempotent(section)


def main() -> int:
    payload = search_duckduckgo()
    write_outputs(payload)

    if payload.get("ok"):
        print(f"OK Buscador web DuckDuckGo — proveedor: {payload.get('provider', '')}")
        print(f"OK Resultados: {payload.get('results_count', 0)}")
        print(f"Reporte: {REPORT_OUT}")
        print(f"Inyectado en: {NOTICIAS_LIGAMX}")
        return 0

    print("AVISO Buscador web DuckDuckGo fallo, pero dejo reporte no bloqueante.")
    print(f"Reporte: {REPORT_OUT}")
    print(f"Error: {payload.get('error', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
