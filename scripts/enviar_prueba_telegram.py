#!/usr/bin/env python3
"""
enviar_prueba_telegram.py — Envía un mensaje de PRUEBA a tu Telegram para revisar
el formato (layout móvil) SIN depender de datos reales de ESPN.

Uso:
    python3 scripts/enviar_prueba_telegram.py

Requiere en el entorno (o en .env):
    TELEGRAM_BOT_TOKEN=...
    TELEGRAM_CHAT_ID=...

Informativo. No envía picks reales; los datos son de ejemplo.
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import telegram_pronosticos as tp  # noqa: E402


def _resultado_demo():
    return {
        "generado_utc": "2026-07-16T18:00:00Z",
        "fuente_datos": "ESPN (PRUEBA)",
        "total_pronosticos": 3,
        "pronosticos": [
            {
                "local": "América",
                "visitante": "Cruz Azul",
                "pick_1x2": "Gana Local",
                "prob_local_pct": 55.2,
                "prob_empate_pct": 24.1,
                "prob_visitante_pct": 20.7,
                "prob_pick_pct": 55.2,
                "nivel_confianza": "ALTA",
                "pick_ou": "Over",
                "prob_over_pct": 58.0,
                "pick_btts": "Sí",
                "marcador_mas_probable": "2-1",
                "explicacion_1x2": "América domina de local con mejor ataque esta temporada.",
                "mercado": {
                    "1x2": {
                        "momios": {"local": "1.80", "empate": "3.40", "visita": "4.20"},
                        "favorito_mercado": "América",
                        "hay_valor": True,
                        "valor_en": "América",
                    },
                    "over_under": {
                        "momios": {"over": "1.90", "under": "1.90"},
                        "linea": 2.5,
                        "mercado_ve": "explosivo",
                    },
                },
            },
            {
                "local": "Tigres",
                "visitante": "Rayados",
                "pick_1x2": "Empate",
                "prob_local_pct": 38.0,
                "prob_empate_pct": 33.0,
                "prob_visitante_pct": 29.0,
                "prob_pick_pct": 33.0,
                "nivel_confianza": "MEDIA",
                "pick_ou": "Under",
                "prob_over_pct": 40.0,
                "pick_btts": "No",
                "marcador_mas_probable": "1-1",
            },
            {
                "local": "Toluca",
                "visitante": "Puebla",
                "pick_1x2": "Gana Local",
                "prob_local_pct": 62.0,
                "prob_empate_pct": 21.0,
                "prob_visitante_pct": 17.0,
                "prob_pick_pct": 62.0,
                "nivel_confianza": "ALTA",
                "pick_ou": "Over",
                "prob_over_pct": 64.0,
                "pick_btts": "Sí",
                "marcador_mas_probable": "3-1",
            },
        ],
    }


def main() -> int:
    tops = [
        {
            "equipo": "América",
            "rival": "Cruz Azul",
            "condicion": "Local",
            "no_perder_pct": 79.3,
            "prob_victoria_pct": 55.2,
            "nivel": "ALTA",
            "razon": "local fuerte vs un rival en mala racha de visitante",
        },
        {
            "equipo": "Toluca",
            "rival": "Puebla",
            "condicion": "Local",
            "no_perder_pct": 83.0,
            "prob_victoria_pct": 62.0,
            "nivel": "ALTA",
        },
        {
            "equipo": "Tigres",
            "rival": "Rayados",
            "condicion": "Local",
            "no_perder_pct": 71.0,
            "prob_victoria_pct": 38.0,
            "nivel": "MEDIA",
        },
    ]
    contexto = {
        "home": "América",
        "away": "Cruz Azul",
        "prediccion_api": {
            "prob_local_pct": 54.0,
            "prob_empate_pct": 25.0,
            "prob_visita_pct": 21.0,
            "goles_esp": "1.9-1.0",
        },
        "forma_local": "WWDWL",
        "forma_visita": "LDLWD",
        "en_riesgo_local": [],
        "en_riesgo_visita": ["J. Rodríguez (amarillas)"],
        "h2h": {
            "team1": {"name": "América", "wins": 6},
            "team2": {"name": "Cruz Azul", "wins": 4},
            "played": 14,
            "draws": 4,
            "seasons_covered": 8,
        },
        # Alineación CONFIRMADA (XI) del pick #1.
        "alineacion": {
            "disponible": True,
            "equipos": [
                {
                    "equipo": "América",
                    "condicion": "home",
                    "formacion": "4-3-3",
                    "titulares": [
                        "Malagón",
                        "Fuentes",
                        "Cáceres",
                        "Reyes",
                        "Espinoza",
                        "Fidalgo",
                        "Sánchez",
                        "dos Santos",
                        "Rodríguez",
                        "Martín",
                        "Aguirre",
                    ],
                },
                {
                    "equipo": "Cruz Azul",
                    "condicion": "away",
                    "formacion": "4-2-3-1",
                    "titulares": [
                        "Mier",
                        "Piovi",
                        "Rivero",
                        "Escobar",
                        "Rotondi",
                        "Ditta",
                        "Faravelli",
                        "Lira",
                        "Sepúlveda",
                        "Antuna",
                        "Gutiérrez",
                    ],
                },
            ],
        },
        # Impacto del XI (fuerza + ausentes clave).
        "impacto_xi": {
            "América": {"fuerza_xi_pct": 96.0, "ausentes_clave": []},
            "Cruz Azul": {
                "fuerza_xi_pct": 88.5,
                "ausentes_clave": [{"jugador": "C. Rodríguez", "importancia_pct": 11.0}],
            },
        },
        # Jugadores a seguir del pick #1.
        "jugadores_seguir": {
            "local": ["Henry Martín", "Álvaro Fidalgo", "Brian Rodríguez"],
            "visita": ["Ángel Sepúlveda", "Ignacio Rivero"],
        },
    }

    # Goleadores por equipo -> "⭐ A seguir" por partido.
    goleadores_map = {
        "América": [{"nombre": "Henry Martín", "goles": 8}, {"nombre": "Brian Rodríguez", "goles": 5}],
        "Cruz Azul": [{"nombre": "Ángel Sepúlveda", "goles": 6}],
        "Tigres": [{"nombre": "A. Gignac", "goles": 7}, {"nombre": "J. Brunetta", "goles": 4}],
        "Rayados": [{"nombre": "G. Berterame", "goles": 6}],
        "Toluca": [{"nombre": "Paulinho", "goles": 9}, {"nombre": "A. Pereira", "goles": 5}],
        "Puebla": [{"nombre": "R. Ormeño", "goles": 4}],
    }
    # Porteros + vallas invictas -> "🧤 Muro" cuando el partido lo amerita.
    porteros_map = {
        "América": {"nombre": "L. Malagón", "vallas_invictas": 6},
        "Cruz Azul": {"nombre": "K. Mier", "vallas_invictas": 4},
        "Tigres": {"nombre": "N. Guzmán", "vallas_invictas": 5},
        "Rayados": {"nombre": "E. Andrada", "vallas_invictas": 3},
        "Toluca": {"nombre": "T. Volpi", "vallas_invictas": 4},
        "Puebla": {"nombre": "J. Rangel", "vallas_invictas": 2},
    }

    msg = tp.construir_mensaje(
        _resultado_demo(),
        tops=tops,
        contexto_pick=contexto,
        advertencia="⚠️ PRUEBA DE FORMATO — datos de ejemplo, no es un pick real.",
        goleadores_map=goleadores_map,
        porteros_map=porteros_map,
    )
    ok = tp.enviar_mensaje(msg)
    print("✅ Enviado a Telegram." if ok else "❌ No se envió. Revisa TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
