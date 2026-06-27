#!/usr/bin/env python3
"""
dashboard_odds.py — Dashboard de momios Liga MX (HTML sin dependencias).

Lee el dataset generado por src/odds_dataset.py (CSV) y produce:
- Distribución del VIG (histograma).
- Resumen de tendencias (subió/bajó/estable) por mercado.
- Tabla del último snapshot por mercado (momios + true_prob + trend).
- Backtesting opcional (ROI / Win Rate / Brier) si se pasa un CSV de resultados
  con columnas: id_mercado, resultado (1=local, 2=empate, 3=visitante).

Salida: reports/dashboard_odds.html + reports/dashboard_odds.txt (gitignored).
Sin red, sin scraping. Decisión operativa: ESPERAR / NO ENVIAR.
"""
from __future__ import annotations

import argparse
import csv
import html
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

BASE_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = BASE_DIR / "src"
import sys
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from backtesting import distribucion_vig, resumen_trend, evaluar_dataset  # noqa: E402
from odds_dataset import leer_dataset, DATASET_PATH  # noqa: E402

DEC_ESPERAR = "ESPERAR / NO ENVIAR"


def latest_por_mercado(filas: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Último snapshot por id_mercado (preserva orden de aparición)."""
    ultimo: Dict[str, Dict[str, Any]] = {}
    orden: List[str] = []
    for fila in filas:
        mid = str(fila.get("id_mercado", ""))
        if mid not in ultimo:
            orden.append(mid)
        ultimo[mid] = fila
    return [ultimo[mid] for mid in orden]


def cargar_resultados(path: Optional[Path]) -> Dict[str, int]:
    if not path or not Path(path).exists():
        return {}
    salida: Dict[str, int] = {}
    with Path(path).open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            try:
                salida[str(row["id_mercado"])] = int(row["resultado"])
            except (KeyError, TypeError, ValueError):
                continue
    return salida


def construir_contexto(
    filas: Sequence[Dict[str, Any]],
    resultados: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    vig_values = [f.get("vig_pct") for f in filas]
    contexto: Dict[str, Any] = {
        "total_filas": len(filas),
        "vig_dist": distribucion_vig(vig_values),
        "trend": resumen_trend(filas),
        "mercados": latest_por_mercado(filas),
        "backtest": None,
    }
    if resultados:
        filas_eval = []
        for fila in latest_por_mercado(filas):
            mid = str(fila.get("id_mercado", ""))
            if mid in resultados:
                f2 = dict(fila)
                f2["resultado"] = resultados[mid]
                filas_eval.append(f2)
        if filas_eval:
            contexto["backtest"] = evaluar_dataset(filas_eval)
    return contexto


def construir_texto(contexto: Dict[str, Any]) -> str:
    lineas = [
        "# DASHBOARD DE MOMIOS — SURVIVOR LIGA MX",
        "",
        f"Filas (snapshots): {contexto['total_filas']}",
        "",
        "Distribución del VIG:",
    ]
    for b in contexto["vig_dist"]:
        lineas.append(f"  {b['rango']:>10} | {'#' * b['conteo']} ({b['conteo']})")
    lineas.append("")
    lineas.append("Tendencias por mercado (subió/bajó/estable):")
    for col, d in contexto["trend"].items():
        lineas.append(f"  {col}: ↑{d['subio']} ↓{d['bajo']} ={d['estable']}")
    if contexto.get("backtest"):
        b = contexto["backtest"]
        lineas += [
            "",
            "Backtesting (estrategia favorito por true_prob):",
            f"  Apuestas: {b['n_apuestas']} | Aciertos: {b['aciertos']}",
            f"  Win Rate: {b['win_rate'] * 100:.1f}%",
            f"  ROI: {b['roi'] * 100:.1f}%",
            f"  Ganancia neta (stake 1): {b['ganancia_neta']}",
            f"  Brier promedio: {b['brier_promedio']}",
        ]
    lineas += [
        "",
        "DECISIÓN GENERAL:",
        f"- {DEC_ESPERAR}.",
        "- Dashboard informativo. No cierra ni envía picks.",
    ]
    return "\n".join(lineas) + "\n"


def _barra_html(conteo: int, maximo: int) -> str:
    ancho = 0 if maximo <= 0 else int(100 * conteo / maximo)
    return (
        f'<div style="background:#2d7;height:18px;width:{ancho}%;'
        f'display:inline-block"></div> {conteo}'
    )


def construir_html(contexto: Dict[str, Any]) -> str:
    max_vig = max([b["conteo"] for b in contexto["vig_dist"]] or [0])
    filas_vig = "".join(
        f"<tr><td>{html.escape(b['rango'])}</td><td>{_barra_html(b['conteo'], max_vig)}</td></tr>"
        for b in contexto["vig_dist"]
    )

    filas_trend = "".join(
        f"<tr><td>{col}</td><td>↑{d['subio']}</td><td>↓{d['bajo']}</td><td>={d['estable']}</td></tr>"
        for col, d in contexto["trend"].items()
    )

    filas_mkt = ""
    for m in contexto["mercados"]:
        filas_mkt += (
            "<tr>"
            f"<td>{html.escape(str(m.get('id_mercado', '')))}</td>"
            f"<td>{html.escape(str(m.get('momio_1', '')))}</td>"
            f"<td>{html.escape(str(m.get('momio_2', '')))}</td>"
            f"<td>{html.escape(str(m.get('momio_3', '')))}</td>"
            f"<td>{html.escape(str(m.get('vig_pct', '')))}%</td>"
            "</tr>"
        )

    backtest_html = ""
    if contexto.get("backtest"):
        b = contexto["backtest"]
        backtest_html = (
            "<h2>Backtesting (favorito por true_prob)</h2><ul>"
            f"<li>Apuestas: {b['n_apuestas']} | Aciertos: {b['aciertos']}</li>"
            f"<li>Win Rate: {b['win_rate'] * 100:.1f}%</li>"
            f"<li>ROI: {b['roi'] * 100:.1f}%</li>"
            f"<li>Ganancia neta (stake 1): {b['ganancia_neta']}</li>"
            f"<li>Brier promedio: {b['brier_promedio']}</li>"
            "</ul>"
        )

    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<title>Dashboard Momios Liga MX</title>
<style>body{{font-family:system-ui,Arial,sans-serif;margin:24px;color:#222}}
table{{border-collapse:collapse;margin:12px 0}}td,th{{border:1px solid #ccc;padding:6px 10px}}
h1{{color:#176}}small{{color:#777}}</style></head>
<body>
<h1>Dashboard de Momios — Survivor Liga MX</h1>
<small>Snapshots: {contexto['total_filas']} · Decisión: {DEC_ESPERAR}</small>
<h2>Distribución del VIG</h2>
<table><tr><th>Rango</th><th>Conteo</th></tr>{filas_vig}</table>
<h2>Tendencias por mercado</h2>
<table><tr><th>Mercado</th><th>Subió</th><th>Bajó</th><th>Estable</th></tr>{filas_trend}</table>
<h2>Último snapshot por mercado</h2>
<table><tr><th>id_mercado</th><th>momio_1</th><th>momio_2</th><th>momio_3</th><th>vig</th></tr>{filas_mkt}</table>
{backtest_html}
<p><strong>{DEC_ESPERAR}</strong> — dashboard informativo, no cierra ni envía picks.</p>
</body></html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Dashboard de momios Liga MX.")
    parser.add_argument("--dataset", default=str(DATASET_PATH))
    parser.add_argument("--resultados", default="")
    parser.add_argument("--html", default=str(BASE_DIR / "reports" / "dashboard_odds.html"))
    parser.add_argument("--txt", default=str(BASE_DIR / "reports" / "dashboard_odds.txt"))
    args = parser.parse_args()

    filas = leer_dataset(Path(args.dataset))
    if not filas:
        print(f"⚠️ Dataset vacío o inexistente: {args.dataset}")
        print("➡️ Corre src/odds_dataset.py para generarlo primero.")
        return 1

    resultados = cargar_resultados(Path(args.resultados)) if args.resultados else {}
    contexto = construir_contexto(filas, resultados)

    html_path = Path(args.html)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(construir_html(contexto), encoding="utf-8")

    txt = construir_texto(contexto)
    Path(args.txt).write_text(txt, encoding="utf-8")

    print(txt)
    print(f"📊 HTML: {html_path}")
    print(f"📄 TXT: {args.txt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
