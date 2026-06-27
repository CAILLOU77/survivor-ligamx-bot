#!/usr/bin/env python3
"""
Tests unitarios para src/generar_reporte.py.

Cubren funciones puras (buscar_valor, extraer_partidos, extraer_pick_desde_log,
formatear_bajas) y la lógica de seguridad extraer_decision_final_real (con
cargar_json mockeado). No modifican la lógica de producción.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import generar_reporte as gr  # noqa: E402


class TestBuscarValor(unittest.TestCase):
    def test_encuentra_primera_clave(self):
        self.assertEqual(gr.buscar_valor({"local": "America"}, gr.LOCAL_KEYS), "America")

    def test_default_si_no_hay(self):
        self.assertEqual(gr.buscar_valor({}, gr.LOCAL_KEYS, "X"), "X")

    def test_ignora_vacios(self):
        self.assertEqual(
            gr.buscar_valor({"local": "", "equipo_local": "Toluca"}, gr.LOCAL_KEYS),
            "Toluca",
        )


class TestExtraerPartidos(unittest.TestCase):
    def test_lista(self):
        self.assertEqual(len(gr.extraer_partidos([{"a": 1}, "x", {"b": 2}])), 2)

    def test_dict_partidos(self):
        self.assertEqual(len(gr.extraer_partidos({"partidos": [{"a": 1}]})), 1)

    def test_dict_jornadas_doble_conteo_conocido(self):
        # QUIRK documentado: la clave "jornadas" también empieza con "jornada",
        # por lo que el segundo loop (keys que empiezan con "jornada") vuelve a
        # procesar la lista y suma el dict envoltorio como un "partido" extra.
        # Comportamiento real actual = 3 (2 partidos + 1 dict envoltorio).
        data = {"jornadas": [{"partidos": [{"a": 1}, {"b": 2}]}]}
        self.assertEqual(len(gr.extraer_partidos(data)), 3)

    def test_dict_jornadaN(self):
        data = {"jornada1": [{"a": 1}]}
        self.assertEqual(len(gr.extraer_partidos(data)), 1)

    def test_tipo_invalido(self):
        self.assertEqual(gr.extraer_partidos(42), [])


class TestExtraerPickDesdeLog(unittest.TestCase):
    def test_extrae_candidato(self):
        log = "👉 CANDIDATO TÉCNICO: America (Local)"
        pick = gr.extraer_pick_desde_log(log)
        self.assertIn("America", pick["equipo"])

    def test_extrae_rival_y_prob(self):
        log = (
            "Enfrentando a: Toluca\n"
            "Probabilidad matemática de avanzar de jornada: 84.6%\n"
        )
        pick = gr.extraer_pick_desde_log(log)
        self.assertEqual(pick["rival"], "Toluca")
        self.assertEqual(pick["probabilidad"], "84.6%")

    def test_toma_ultimo_estado(self):
        log = "ESTADO: PRIMERO\nESTADO: ULTIMO"
        pick = gr.extraer_pick_desde_log(log)
        self.assertEqual(pick["estado_auditor"], "ULTIMO")

    def test_log_vacio_valores_default(self):
        pick = gr.extraer_pick_desde_log("")
        self.assertEqual(pick["equipo"], "NO DETECTADO")


class TestFormatearBajas(unittest.TestCase):
    def test_lesiones_y_suspendidos(self):
        partido = {
            "lesiones": [{"jugador": "J1", "detalle": "rodilla"}],
            "suspendidos": [{"jugador": "J2", "detalle": "roja"}],
        }
        out = gr.formatear_bajas(partido)
        self.assertIn("Lesión: J1", out)
        self.assertIn("Suspensión: J2", out)

    def test_revisadas_sin_bajas(self):
        self.assertEqual(
            gr.formatear_bajas({"bajas_revisadas": True}),
            "Revisadas por IA, sin bajas confirmadas",
        )

    def test_no_revisadas(self):
        self.assertEqual(gr.formatear_bajas({}), "No revisadas")


class TestDecisionFinalReal(unittest.TestCase):
    """Lógica de seguridad: mapeo de la decisión del pre-cierre."""

    def test_no_enviar_es_solo_referencia(self):
        with mock.patch.object(gr, "cargar_json",
                               return_value={"decision_final": "ESPERAR / NO ENVIAR"}):
            res = gr.extraer_decision_final_real()
        self.assertEqual(res["estado_pick_tecnico"], "SOLO REFERENCIA / NO ENVIAR")
        self.assertIn("ESPERAR / NO ENVIAR", res["decision_final"])
        # Debe rellenar un motivo por defecto.
        self.assertTrue(res["mensaje"])

    def test_cerrar_es_apto(self):
        with mock.patch.object(gr, "cargar_json",
                               return_value={"decision_final": "CERRAR"}):
            res = gr.extraer_decision_final_real()
        self.assertEqual(res["estado_pick_tecnico"], "APTO SEGÚN PRE-CIERRE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
