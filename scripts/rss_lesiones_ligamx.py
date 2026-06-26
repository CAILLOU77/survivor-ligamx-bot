#!/usr/bin/env python3
"""
rss_lesiones_ligamx.py

Módulo de actualidad Liga MX para Survivor:
- Usa Google News RSS con filtro por sitio de prensa.
- Fuentes objetivo: Mediotiempo y ESPN México.
- Busca lesiones, bajas, suspendidos, dudas, conferencias y boletines médicos.
- Filtra ruido y notas viejas.
- Deduplica noticias similares.
- Clasifica impacto operativo.
- Exporta JSON local en reports/lesiones_noticias_ligamx.json.

No usa credenciales. No scrapea HTML. No hace bypass.
Decisión operativa: ESPERAR / NO ENVIAR.
"""

from __future__ import annotations

import json
import re
import socket
import sys
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from html import unescape
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import feedparser


OUTPUT_FILE = Path("reports/lesiones_noticias_ligamx.json")
REQUEST_TIMEOUT_SECONDS = 12
MAX_ENTRIES_PER_QUERY = 25
MAX_NEWS_AGE_DAYS = 45
DUPLICATE_SIMILARITY_THRESHOLD = 0.86

NEWS_SOURCES = [
    {"fuente": "Mediotiempo", "site": "mediotiempo.com"},
    {"fuente": "ESPN México", "site": "espn.com.mx"},
]

SEARCHES = [
    '"Liga MX" lesion',
    '"Liga MX" lesionado',
    '"Liga MX" lesionados',
    '"Liga MX" baja',
    '"Liga MX" bajas',
    '"Liga MX" suspendido',
    '"Liga MX" suspendidos',
    '"Liga MX" duda',
    '"Liga MX" conferencia',
    '"Liga MX" "boletin medico"',
    '"Liga MX" "boletín médico"',
    '"futbol mexicano" lesion',
    '"futbol mexicano" baja',
    '"futbol mexicano" suspendido',
    '"fútbol mexicano" lesion',
    '"fútbol mexicano" baja',
    '"fútbol mexicano" conferencia',
]

HIGH_IMPACT_TERMS = [
    "lesion",
    "lesionado",
    "lesionada",
    "lesionados",
    "fractura",
    "fracturado",
    "fracturada",
    "baja",
    "bajas",
    "suspendido",
    "suspendida",
    "suspendidos",
    "suspendidas",
    "descartado",
    "descartada",
    "no convocado",
    "no convocada",
]

MEDIUM_IMPACT_TERMS = [
    "duda",
    "molestia",
    "molestias",
    "conferencia",
    "rueda de prensa",
    "boletin medico",
    "boletín médico",
    "parte medico",
    "parte médico",
    "no entreno",
    "no entrenó",
    "entreno por separado",
    "entrenó por separado",
]

ROSTER_IMPACT_TERMS = [
    "convocatoria",
    "convocado",
    "convocada",
    "alta",
    "altas",
    "extranjero",
    "extranjeros",
    "refuerzo",
    "refuerzos",
    "registro",
    "plantilla",
]

LIGA_MX_TERMS = [
    "liga mx",
    "futbol mexicano",
    "fútbol mexicano",
    "apertura",
    "clausura",
    "jornada",
    "america",
    "américa",
    "chivas",
    "guadalajara",
    "cruz azul",
    "pumas",
    "tigres",
    "monterrey",
    "rayados",
    "toluca",
    "santos",
    "santos laguna",
    "pachuca",
    "leon",
    "león",
    "atlas",
    "puebla",
    "queretaro",
    "querétaro",
    "necaxa",
    "atlante",
    "tijuana",
    "xolos",
    "juarez",
    "juárez",
    "fc juarez",
    "fc juárez",
    "atletico san luis",
    "atlético san luis",
    "mazatlan",
    "mazatlán",
]

EXCLUDE_TERMS = [
    "aficionados",
    "aficionado",
    "fanaticos",
    "fanáticos",
    "conductor",
    "arrolla",
    "arrollados",
    "accidente",
    "celebraban",
    "video",
    "arbitros",
    "árbitros",
    "arbitro",
    "árbitro",
    "partido suspendido",
    "partidos suspendidos",
    "abejas",
    "tormenta electrica",
    "tormenta eléctrica",
    "copa del mundo",
    "mundial 2026",
    "francia vs irak",
    "wyndham clark",
]

USER_AGENT = "Mozilla/5.0 SurvivorLigaMXBot/1.0 GoogleNewsRSSMonitor"


@dataclass(frozen=True)
class NewsItem:
    fecha: str
    fuente_prensa: str
    titulo: str
    enlace: str
    consulta: str
    impacto: str
    razon_impacto: str


def normalize_text(text: str) -> str:
    text = unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.lower().strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^a-z0-9ñ\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_text(text: str) -> str:
    text = unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_google_title(title: str) -> str:
    title = clean_text(title)
    title = re.sub(r"\s+-\s+Mediotiempo\s*$", "", title, flags=re.I)
    title = re.sub(r"\s+-\s+ESPN.*$", "", title, flags=re.I)
    return title.strip()


def contains_any(text: str, terms: list[str]) -> bool:
    normalized = normalize_text(text)
    return any(normalize_text(term) in normalized for term in terms)


def classify_impact(title: str, summary: str) -> tuple[str, str]:
    full_text = f"{title} {summary}"

    if contains_any(full_text, HIGH_IMPACT_TERMS):
        return "ALTA", "Lesión, baja, suspensión, descarte o ausencia directa."

    if contains_any(full_text, MEDIUM_IMPACT_TERMS):
        return "MEDIA", "Duda, molestia, conferencia o parte médico."

    if contains_any(full_text, ROSTER_IMPACT_TERMS):
        return "ROSTER", "Movimiento de plantilla, convocatoria, registro o extranjeros."

    return "BAJA", "Contexto general sin impacto directo confirmado."


def parse_entry_date(entry: Any) -> datetime:
    parsed_time = getattr(entry, "published_parsed", None) or getattr(
        entry, "updated_parsed", None
    )

    if parsed_time:
        try:
            return datetime(*parsed_time[:6], tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pass

    return datetime.now(timezone.utc)


def is_recent(entry_date: datetime) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_NEWS_AGE_DAYS)
    return entry_date >= cutoff


def is_relevant(title: str, summary: str, entry_date: datetime) -> bool:
    full_text = f"{title} {summary}"

    if not is_recent(entry_date):
        return False

    if contains_any(full_text, EXCLUDE_TERMS):
        return False

    has_liga_context = contains_any(full_text, LIGA_MX_TERMS)
    has_action = (
        contains_any(full_text, HIGH_IMPACT_TERMS)
        or contains_any(full_text, MEDIUM_IMPACT_TERMS)
        or contains_any(full_text, ROSTER_IMPACT_TERMS)
    )

    return has_liga_context and has_action


def duplicate_key(title: str, summary: str) -> str:
    return normalize_text(f"{title} {summary}")[:700]


def is_duplicate(candidate: str, existing: list[str]) -> bool:
    for old in existing:
        if candidate == old:
            return True

        similarity = SequenceMatcher(None, candidate, old).ratio()
        if similarity >= DUPLICATE_SIMILARITY_THRESHOLD:
            return True

    return False


def build_google_news_rss_url(site: str, search: str) -> str:
    params = urlencode(
        {
            "q": f"site:{site} {search}",
            "hl": "es-419",
            "gl": "MX",
            "ceid": "MX:es-419",
        }
    )
    return f"https://news.google.com/rss/search?{params}"


def fetch_feed(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return response.read()


def process_query(
    source_name: str,
    site: str,
    search: str,
) -> tuple[list[NewsItem], dict[str, Any]]:
    url = build_google_news_rss_url(site, search)

    status = {
        "fuente_prensa": source_name,
        "site": site,
        "consulta": search,
        "url": url,
        "ok": False,
        "entries": 0,
        "relevantes": 0,
        "error": "",
    }

    items: list[NewsItem] = []

    try:
        raw = fetch_feed(url)
        parsed = feedparser.parse(raw)
        entries = getattr(parsed, "entries", [])[:MAX_ENTRIES_PER_QUERY]

        status["ok"] = True
        status["entries"] = len(entries)

        if getattr(parsed, "bozo", False):
            status["error"] = "feed_bozo_possible_format_issue"

        for entry in entries:
            raw_title = clean_text(getattr(entry, "title", ""))
            title = clean_google_title(raw_title)
            summary = clean_text(
                getattr(entry, "summary", "")
                or getattr(entry, "description", "")
            )
            link = clean_text(getattr(entry, "link", ""))

            if not title or not link:
                continue

            entry_date = parse_entry_date(entry)

            if not is_relevant(title, summary, entry_date):
                continue

            impact, reason = classify_impact(title, summary)

            if impact == "BAJA":
                continue

            items.append(
                NewsItem(
                    fecha=entry_date.isoformat(),
                    fuente_prensa=source_name,
                    titulo=title,
                    enlace=link,
                    consulta=search,
                    impacto=impact,
                    razon_impacto=reason,
                )
            )

        status["relevantes"] = len(items)

    except HTTPError as exc:
        status["error"] = f"HTTP {exc.code}"
        print(f"[ERROR] HTTP {exc.code}: {source_name} | {search}", file=sys.stderr)
    except URLError as exc:
        status["error"] = f"URL error: {exc}"
        print(f"[ERROR] No respondió: {source_name} | {search} | {exc}", file=sys.stderr)
    except socket.timeout:
        status["error"] = "timeout"
        print(f"[ERROR] Timeout: {source_name} | {search}", file=sys.stderr)
    except Exception as exc:
        status["error"] = f"unexpected: {exc}"
        print(f"[ERROR] Fallo inesperado: {source_name} | {search} | {exc}", file=sys.stderr)

    return items, status


def collect_news() -> tuple[list[NewsItem], list[dict[str, Any]]]:
    unique_items: list[NewsItem] = []
    seen_keys: list[str] = []
    statuses: list[dict[str, Any]] = []

    for source in NEWS_SOURCES:
        for search in SEARCHES:
            query_items, status = process_query(
                source_name=source["fuente"],
                site=source["site"],
                search=search,
            )
            statuses.append(status)

            for item in query_items:
                key = duplicate_key(item.titulo, item.razon_impacto)

                if is_duplicate(key, seen_keys):
                    continue

                seen_keys.append(key)
                unique_items.append(item)

    impact_order = {"ALTA": 0, "ROSTER": 1, "MEDIA": 2}
    unique_items.sort(
        key=lambda item: (
            impact_order.get(item.impacto, 99),
            item.fecha,
        ),
        reverse=False,
    )
    return unique_items, statuses


def export_json(items: list[NewsItem], statuses: list[dict[str, Any]]) -> None:
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "generado_en": datetime.now(timezone.utc).isoformat(),
        "total": len(items),
        "max_news_age_days": MAX_NEWS_AGE_DAYS,
        "fuentes": NEWS_SOURCES,
        "busquedas": SEARCHES,
        "feed_statuses": statuses,
        "noticias": [asdict(item) for item in items],
        "nota_enlace": "Google News RSS puede entregar enlace de Google News, no siempre URL original directa del portal.",
        "decision_operativa": "ESPERAR / NO ENVIAR",
    }

    OUTPUT_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    items, statuses = collect_news()
    export_json(items, statuses)

    ok_queries = sum(1 for status in statuses if status["ok"])
    total_entries = sum(int(status["entries"]) for status in statuses)

    print(f"OK: {len(items)} noticias útiles exportadas a {OUTPUT_FILE}")
    print(f"Consultas OK: {ok_queries}/{len(statuses)}")
    print(f"Entradas revisadas: {total_entries}")

    if items:
        print("\nNoticias útiles:")
        for idx, item in enumerate(items[:10], start=1):
            print(f"{idx}. [{item.impacto}] {item.fecha} | {item.fuente_prensa} | {item.titulo}")

    print("Decisión: ESPERAR / NO ENVIAR")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
