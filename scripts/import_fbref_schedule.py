#!/usr/bin/env python3
"""
FBref Schedule Import Audit — Survivor Liga MX (v1.35.0)

Importador/auditor LOCAL del calendario (Scores & Fixtures) de FBref para Liga MX.

Filosofía y límites (importante):
- FBref se usa como fuente de AUDITORÍA MANUAL, no como verdad automática.
- NO hace scraping automático ni peticiones de red a FBref (no requests/curl).
- NO requiere login ni cookies.
- Lee un archivo HTML guardado MANUALMENTE por el usuario (Chrome -> Guardar como
  -> "Página web, solo HTML") desde:
      data/fbref/raw/fbref_ligamx_schedule.html
- NO sobrescribe data/jornadas.json.
- NO cambia picks. NO manda Telegram. Solo genera reportes/CSV locales.
- Mantiene la decisión operativa ESPERAR / NO ENVIAR mientras no haya momios
  reales (este script no decide CERRAR jamás).

Salidas locales (NO se commitean; data/ y reports/ están en .gitignore):
- data/fbref/fbref_ligamx_schedule_full.csv
- data/fbref/fbref_ligamx_schedule_jornada1.csv
- reports/fbref_schedule_import_preview.txt
- reports/fbref_vs_jornadas_compare.txt
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Errores
# ---------------------------------------------------------------------------
class FBrefImportError(Exception):
    """Error controlado del importador (HTML faltante, columnas faltantes, etc.)."""


# ---------------------------------------------------------------------------
# Normalización de nombres de equipos
# ---------------------------------------------------------------------------
# (token_canonico, [variantes...]) — las variantes se comparan ya "limpias".
ALIAS_GROUPS: List[Tuple[str, List[str]]] = [
    ("america", ["america", "club america", "cf america", "club de futbol america"]),
    ("guadalajara", ["guadalajara", "chivas", "cd guadalajara", "chivas guadalajara"]),
    ("cruz azul", ["cruz azul"]),
    ("tigres uanl", ["tigres", "uanl", "tigres uanl"]),
    ("pumas unam", ["pumas", "unam", "pumas unam"]),
    ("monterrey", ["monterrey", "rayados", "cf monterrey"]),
    ("toluca", ["toluca", "deportivo toluca"]),
    ("tijuana", ["tijuana", "xolos", "club tijuana"]),
    ("atlas", ["atlas"]),
    ("leon", ["leon"]),
    ("pachuca", ["pachuca"]),
    ("santos", ["santos", "santos laguna"]),
    ("queretaro", ["queretaro"]),
    ("puebla", ["puebla"]),
    ("necaxa", ["necaxa"]),
    ("mazatlan", ["mazatlan", "mazatlan fc"]),
    ("atletico de san luis", ["atletico de san luis", "atletico san luis", "san luis", "atl san luis"]),
    ("juarez", ["juarez", "fc juarez"]),
]

# Nombre visible "bonito" por token canónico (para el output legible).
DISPLAY: Dict[str, str] = {
    "america": "América",
    "guadalajara": "Guadalajara",
    "cruz azul": "Cruz Azul",
    "tigres uanl": "Tigres UANL",
    "pumas unam": "Pumas UNAM",
    "monterrey": "Monterrey",
    "toluca": "Toluca",
    "tijuana": "Tijuana",
    "atlas": "Atlas",
    "leon": "León",
    "pachuca": "Pachuca",
    "santos": "Santos",
    "queretaro": "Querétaro",
    "puebla": "Puebla",
    "necaxa": "Necaxa",
    "mazatlan": "Mazatlán",
    "atletico de san luis": "Atlético de San Luis",
    "juarez": "FC Juarez",
}

PREFIJOS_EQUIPO = ("club ", "cf ", "fc ", "cd ", "deportivo ")


def quitar_acentos(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def limpiar_nombre(texto: str) -> str:
    """Minúsculas, sin acentos, sin puntuación, espacios colapsados."""
    t = quitar_acentos(str(texto or "")).lower()
    t = re.sub(r"[._\-/]", " ", t)
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return " ".join(t.split())


# Lookup variante_limpia -> token canónico.
_ALIAS_LOOKUP: Dict[str, str] = {}
for _canon, _variantes in ALIAS_GROUPS:
    for _v in _variantes:
        _ALIAS_LOOKUP[limpiar_nombre(_v)] = _canon


def canonical_key(nombre: str) -> str:
    """
    Clave canónica para COMPARACIÓN interna (sin acentos, normalizada por alias).
    No se usa para el output visible.
    """
    limpio = limpiar_nombre(nombre)
    if limpio in _ALIAS_LOOKUP:
        return _ALIAS_LOOKUP[limpio]

    # Reintento quitando prefijos comunes (club/cf/fc/cd/deportivo).
    for pref in PREFIJOS_EQUIPO:
        if limpio.startswith(pref):
            sin_pref = limpio[len(pref):].strip()
            if sin_pref in _ALIAS_LOOKUP:
                return _ALIAS_LOOKUP[sin_pref]
            return sin_pref

    return limpio


def normalizar_nombre_equipo(nombre: str) -> str:
    """Nombre visible canónico. Si no hay alias conocido, regresa el original."""
    key = canonical_key(nombre)
    return DISPLAY.get(key, str(nombre or "").strip())


# ---------------------------------------------------------------------------
# Normalización de estadios y horas
# ---------------------------------------------------------------------------
ESTADIO_STOPWORDS = {
    "estadio", "stadium", "de", "del", "la", "el", "los", "las", "y",
}


def estadio_tokens(nombre: str) -> Set[str]:
    base = limpiar_nombre(nombre)
    return {t for t in base.split() if t and t not in ESTADIO_STOPWORDS}


def estadio_parece_distinto(a: str, b: str) -> bool:
    """
    True solo si parecen estadios realmente distintos.
    Diferencias por artículo/acento (La Corregidora vs Corregidora,
    Olímpico de Universitario vs Olímpico Universitario) NO cuentan.
    """
    ta = estadio_tokens(a)
    tb = estadio_tokens(b)
    if not ta or not tb:
        return False  # falta info para afirmar diferencia
    return ta != tb


def hora_norm(h: str) -> str:
    h = str(h or "").strip().lower()
    if not h or "pendiente" in h:
        return ""
    m = re.search(r"(\d{1,2}):(\d{2})", h)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    return ""


def fecha_norm(d: str) -> str:
    d = str(d or "").strip()
    if not d or "pendiente" in d.lower():
        return ""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", d)
    if m:
        return m.group(0)
    return d


# ---------------------------------------------------------------------------
# Parser HTML (stdlib, sin dependencias externas, sin red)
# ---------------------------------------------------------------------------
class _ScheduleHTMLParser(HTMLParser):
    """Extrae celdas por su atributo data-stat (patrón de las tablas FBref)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: List[Dict[str, str]] = []
        self.datastats: Set[str] = set()
        self._cur_row: Dict[str, str] = {}
        self._cur_stat: Optional[str] = None
        self._cur_text: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag == "tr":
            self._cur_row = {}
        elif tag in ("td", "th"):
            stat = dict(attrs).get("data-stat")
            self._cur_stat = stat
            self._cur_text = []
            if stat:
                self.datastats.add(stat)

    def handle_data(self, data: str) -> None:
        if self._cur_stat is not None:
            self._cur_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cur_stat is not None:
            self._cur_row[self._cur_stat] = "".join(self._cur_text).strip()
            self._cur_stat = None
            self._cur_text = []
        elif tag == "tr":
            if self._cur_row:
                self.rows.append(self._cur_row)
            self._cur_row = {}


def cargar_html(path: str) -> str:
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise FBrefImportError(_mensaje_html_faltante(path))
    return p.read_text(encoding="utf-8", errors="ignore")


def _mensaje_html_faltante(path: str) -> str:
    return (
        f"No se encontró el HTML de FBref en: {path}\n"
        "Este importador NO hace scraping. Debes guardar la página manualmente:\n"
        "  1) Abre en Chrome la página 'Scores & Fixtures' de Liga MX en FBref.\n"
        "  2) Menú -> Guardar como... (Cmd+S).\n"
        "  3) Formato: 'Página web, solo HTML' (HTML Only).\n"
        f"  4) Guarda el archivo en: {path}\n"
        "Luego vuelve a ejecutar este comando."
    )


# data-stat requeridos (con alternativas aceptadas).
COLUMNAS_REQUERIDAS: List[Tuple[str, Set[str]]] = [
    ("Wk (gameweek/round)", {"gameweek", "round"}),
    ("Date (date)", {"date"}),
    ("Time (start_time)", {"start_time"}),
    ("Home (home_team)", {"home_team"}),
    ("Away (away_team)", {"away_team"}),
    ("Venue (venue)", {"venue"}),
]


def validar_columnas(datastats: Set[str]) -> None:
    faltan = [etiqueta for etiqueta, opciones in COLUMNAS_REQUERIDAS if not (opciones & datastats)]
    if faltan:
        raise FBrefImportError(
            "Faltan columnas esperadas en la tabla de FBref: "
            + "; ".join(faltan)
            + ".\nVerifica que guardaste la tabla 'Scores & Fixtures' completa "
            "(HTML Only) y no una vista parcial."
        )


def parse_schedule_html(html_text: str) -> Tuple[List[Dict[str, str]], Set[str]]:
    parser = _ScheduleHTMLParser()
    parser.feed(html_text)
    if not parser.rows:
        raise FBrefImportError(
            "No se encontró ninguna fila de tabla en el HTML. "
            "¿Guardaste la página correcta de FBref como HTML Only?"
        )
    return parser.rows, parser.datastats


def _es_fila_partido(row: Dict[str, str]) -> bool:
    home = (row.get("home_team") or "").strip()
    away = (row.get("away_team") or "").strip()
    if not home or not away:
        return False
    if home.lower() in {"home", "local"} or away.lower() in {"away", "visitante"}:
        return False
    return True


def construir_filas(raw_rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    filas: List[Dict[str, str]] = []
    for r in raw_rows:
        if not _es_fila_partido(r):
            continue
        home = (r.get("home_team") or "").strip()
        away = (r.get("away_team") or "").strip()
        wk = (r.get("gameweek") or r.get("round") or "").strip()
        filas.append(
            {
                "wk": wk,
                "date": (r.get("date") or "").strip(),
                "time": (r.get("start_time") or "").strip(),
                "home": home,
                "away": away,
                "venue": (r.get("venue") or "").strip(),
                "home_norm": normalizar_nombre_equipo(home),
                "away_norm": normalizar_nombre_equipo(away),
            }
        )
    return filas


def filtrar_jornada(filas: List[Dict[str, str]], jornada: int) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for f in filas:
        digits = re.sub(r"[^0-9]", "", f.get("wk", ""))
        if digits and int(digits) == jornada:
            out.append(f)
    return out


# ---------------------------------------------------------------------------
# jornadas.json helpers
# ---------------------------------------------------------------------------
def cargar_partidos(path: str) -> Tuple[List[Dict[str, Any]], bool]:
    p = Path(path)
    if not p.exists():
        return [], False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return [], True

    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)], True
    if isinstance(data, dict) and isinstance(data.get("partidos"), list):
        return [x for x in data["partidos"] if isinstance(x, dict)], True
    return [], True


def _p_home(p: Dict[str, Any]) -> str:
    return str(p.get("home_team") or p.get("local") or p.get("equipo_local") or "")


def _p_away(p: Dict[str, Any]) -> str:
    return str(p.get("away_team") or p.get("visitante") or p.get("equipo_visitante") or "")


def _p_fecha(p: Dict[str, Any]) -> str:
    return str(p.get("fecha") or p.get("date") or "")


def _p_hora(p: Dict[str, Any]) -> str:
    return str(p.get("hora") or p.get("time") or "")


def _p_estadio(p: Dict[str, Any]) -> str:
    return str(p.get("estadio") or p.get("sede") or p.get("venue") or p.get("stadium") or "")


# ---------------------------------------------------------------------------
# Comparación FBref vs jornadas.json
# ---------------------------------------------------------------------------
def comparar(filas_jornada: List[Dict[str, str]], partidos: List[Dict[str, Any]]) -> Dict[str, Any]:
    indice: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for p in partidos:
        clave = (canonical_key(_p_home(p)), canonical_key(_p_away(p)))
        indice[clave] = p

    matched: List[Dict[str, Any]] = []
    missing: List[Dict[str, str]] = []

    for fila in filas_jornada:
        clave = (canonical_key(fila["home"]), canonical_key(fila["away"]))
        partido = indice.get(clave)
        if partido is None:
            missing.append(fila)
            continue

        diffs: List[Dict[str, str]] = []

        # Hora
        hf = hora_norm(fila["time"])
        hj = hora_norm(_p_hora(partido))
        if hf and hj and hf != hj:
            diffs.append({"campo": "HORA", "jornadas": hj, "fbref": hf, "critico": "si"})
        elif hf and not hj:
            diffs.append({"campo": "HORA", "jornadas": (_p_hora(partido) or "pendiente"), "fbref": hf, "critico": "si"})

        # Fecha
        df = fecha_norm(fila["date"])
        dj = fecha_norm(_p_fecha(partido))
        if df and dj and df != dj:
            diffs.append({"campo": "FECHA", "jornadas": dj, "fbref": df, "critico": "si"})
        elif df and not dj:
            diffs.append({"campo": "FECHA", "jornadas": (_p_fecha(partido) or "pendiente"), "fbref": df, "critico": "no"})

        # Estadio (flexible)
        ej = _p_estadio(partido)
        if ej and fila["venue"] and estadio_parece_distinto(ej, fila["venue"]):
            diffs.append({"campo": "ESTADIO", "jornadas": ej, "fbref": fila["venue"], "critico": "si"})

        matched.append({"fila": fila, "partido": partido, "diffs": diffs})

    con_diferencias = [m for m in matched if m["diffs"]]

    return {
        "matched": matched,
        "missing": missing,
        "con_diferencias": con_diferencias,
        "total_fbref": len(filas_jornada),
        "total_jornadas": len(partidos),
    }


# ---------------------------------------------------------------------------
# Escritura de CSV y reportes (todo local, gitignored)
# ---------------------------------------------------------------------------
CSV_HEADER = ["Wk", "Date", "Time", "Home", "Away", "Home_Norm", "Away_Norm", "Venue"]


def escribir_csv(path: Path, filas: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_HEADER)
        for f in filas:
            writer.writerow([
                f.get("wk", ""), f.get("date", ""), f.get("time", ""),
                f.get("home", ""), f.get("away", ""),
                f.get("home_norm", ""), f.get("away_norm", ""), f.get("venue", ""),
            ])


def escribir_preview(path: Path, jornada: int, filas_jornada: List[Dict[str, str]], total_full: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lineas = [
        "FBREF SCHEDULE IMPORT — PREVIEW (auditoría manual, NO autoritativo)",
        "-" * 70,
        f"Partidos totales en HTML: {total_full}",
        f"Jornada filtrada: {jornada}",
        f"Partidos en jornada {jornada}: {len(filas_jornada)}",
        "",
    ]
    for i, f in enumerate(filas_jornada, start=1):
        lineas.append(
            f"{i:>2}. {f['home_norm']} vs {f['away_norm']}  "
            f"| fecha={f['date'] or '?'} hora={f['time'] or '?'} "
            f"| estadio={f['venue'] or '?'}"
        )
        if f["home_norm"] != f["home"] or f["away_norm"] != f["away"]:
            lineas.append(f"      (FBref: {f['home']} vs {f['away']})")
    lineas += [
        "",
        "Nota: este preview es solo para revisión manual. No modifica jornadas.json.",
    ]
    path.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def escribir_compare(
    path: Path,
    jornada: int,
    jornadas_path: str,
    jornadas_existe: bool,
    resultado: Dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lineas = [
        "FBREF vs JORNADAS — COMPARACIÓN (auditoría manual)",
        "-" * 70,
        f"Jornada: {jornada}",
        f"Fuente jornadas: {jornadas_path}",
    ]

    if not jornadas_existe:
        lineas += [
            "",
            f"AVISO: no se encontró {jornadas_path}. No hay con qué comparar.",
            "Se generó solo el preview de FBref para revisión manual.",
        ]

    lineas += [
        "",
        f"FBref jornada {jornada}: {resultado['total_fbref']} partidos",
        f"jornadas.json: {resultado['total_jornadas']} partidos",
        f"matched: {len(resultado['matched'])}",
        f"missing (en FBref, sin match en jornadas): {len(resultado['missing'])}",
        f"partidos_con_diferencias: {len(resultado['con_diferencias'])}",
        "",
        "== MATCHED ==",
    ]

    if resultado["matched"]:
        for m in resultado["matched"]:
            f = m["fila"]
            estado = "OK" if not m["diffs"] else "DIFERENCIAS"
            lineas.append(f"- {f['home_norm']} vs {f['away_norm']} [{estado}]")
            for d in m["diffs"]:
                marca = "‼" if d.get("critico") == "si" else "·"
                lineas.append(
                    f"    {marca} {d['campo']}: jornadas='{d['jornadas']}' | fbref='{d['fbref']}'"
                )
    else:
        lineas.append("- (ninguno)")

    lineas += ["", "== MISSING (revisar nombres/alias o que falte el partido) =="]
    if resultado["missing"]:
        for f in resultado["missing"]:
            lineas.append(f"- {f['home_norm']} vs {f['away_norm']} (FBref: {f['home']} vs {f['away']})")
    else:
        lineas.append("- (ninguno)")

    lineas += [
        "",
        "== PARTIDOS CON DIFERENCIAS ==",
    ]
    if resultado["con_diferencias"]:
        for m in resultado["con_diferencias"]:
            f = m["fila"]
            campos = ", ".join(d["campo"] for d in m["diffs"])
            lineas.append(f"- {f['home_norm']} vs {f['away_norm']}: {campos}")
    else:
        lineas.append("- (ninguno)")

    lineas += [
        "",
        "DECISIÓN:",
        "NO sobrescribir automáticamente.",
        "Primero revisar diferencias de hora/estadio.",
        "Mantener ESPERAR / NO ENVIAR mientras no existan momios reales.",
    ]

    path.write_text("\n".join(lineas) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Importador/auditor LOCAL del calendario FBref Liga MX. "
            "No hace scraping ni red; lee HTML guardado manualmente. "
            "No sobrescribe jornadas.json, no cambia picks, no manda Telegram."
        )
    )
    parser.add_argument(
        "--html",
        default="data/fbref/raw/fbref_ligamx_schedule.html",
        help="Ruta al HTML de FBref guardado manualmente (HTML Only).",
    )
    parser.add_argument("--jornada", type=int, default=1, help="Jornada a auditar (default 1).")
    parser.add_argument(
        "--jornadas-json",
        default="data/jornadas.json",
        help="Ruta a jornadas.json para comparar (no se modifica).",
    )
    parser.add_argument("--out-dir", default="data/fbref", help="Directorio de CSV de salida.")
    parser.add_argument("--reports-dir", default="reports", help="Directorio de reportes de salida.")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = construir_parser().parse_args(argv)

    print("📅 FBREF SCHEDULE IMPORT AUDIT — SURVIVOR LIGA MX (v1.35.0)")
    print("=" * 64)
    print("Modo: auditoría manual local (sin red, sin scraping, sin Telegram).")

    try:
        html_text = cargar_html(args.html)
        raw_rows, datastats = parse_schedule_html(html_text)
        validar_columnas(datastats)
    except FBrefImportError as exc:
        print("")
        print(f"❌ {exc}")
        return 2

    filas = construir_filas(raw_rows)
    if not filas:
        print("")
        print("❌ No se detectaron filas de partidos en la tabla (revisa el HTML).")
        return 2

    filas_jornada = filtrar_jornada(filas, args.jornada)

    out_dir = Path(args.out_dir)
    reports_dir = Path(args.reports_dir)

    csv_full = out_dir / "fbref_ligamx_schedule_full.csv"
    csv_jornada = out_dir / f"fbref_ligamx_schedule_jornada{args.jornada}.csv"
    preview_txt = reports_dir / "fbref_schedule_import_preview.txt"
    compare_txt = reports_dir / "fbref_vs_jornadas_compare.txt"

    escribir_csv(csv_full, filas)
    escribir_csv(csv_jornada, filas_jornada)
    escribir_preview(preview_txt, args.jornada, filas_jornada, len(filas))

    partidos, jornadas_existe = cargar_partidos(args.jornadas_json)
    resultado = comparar(filas_jornada, partidos)
    escribir_compare(compare_txt, args.jornada, args.jornadas_json, jornadas_existe, resultado)

    print("")
    print(f"✅ Partidos en HTML: {len(filas)} | jornada {args.jornada}: {len(filas_jornada)}")
    print(f"✅ CSV completo:  {csv_full}")
    print(f"✅ CSV jornada:   {csv_jornada}")
    print(f"✅ Preview:       {preview_txt}")
    print(f"✅ Comparación:   {compare_txt}")
    print("")
    if jornadas_existe:
        print(
            f"📊 matched={len(resultado['matched'])} "
            f"missing={len(resultado['missing'])} "
            f"con_diferencias={len(resultado['con_diferencias'])}"
        )
    else:
        print(f"⚠️ No se encontró {args.jornadas_json}; solo se generó el preview de FBref.")
    print("")
    print("DECISIÓN: NO sobrescribir automáticamente. Revisar hora/estadio primero.")
    print("Mantener ESPERAR / NO ENVIAR mientras no existan momios reales.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
