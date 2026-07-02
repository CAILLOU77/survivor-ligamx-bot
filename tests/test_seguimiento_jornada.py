#!/usr/bin/env python3
"""Tests de seguimiento_jornada: lista priorizada por hora + veredicto por XI."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import seguimiento_jornada as seg  # noqa: E402


def _picks():
    return [
        {"equipo": "Cruz Azul", "rival": "Querétaro", "condicion": "Local",
         "no_perder_pct": 88.0, "prob_victoria_pct": 64.0, "nivel": "ALTA"},
        {"equipo": "América", "rival": "Pachuca", "condicion": "Local",
         "no_perder_pct": 78.0, "prob_victoria_pct": 52.0, "nivel": "MEDIA"},
    ]


class TestFmtCuando(unittest.TestCase):
    def test_formatea_dia_hora(self):
        # 2026-07-18 es sábado
        self.assertEqual(seg.fmt_cuando("2026-07-18T19:00:00"), "sáb 19:00")

    def test_invalido_vacio(self):
        self.assertEqual(seg.fmt_cuando(""), "")
        self.assertEqual(seg.fmt_cuando(None), "")


class TestVeredicto(unittest.TestCase):
    def test_pendiente_sin_xi(self):
        self.assertEqual(seg.veredicto_xi(None)["estado"], "PENDIENTE")

    def test_confirma_xi_completo(self):
        self.assertEqual(seg.veredicto_xi(90.0)["estado"], "CONFIRMA")

    def test_descarta_xi_mermado(self):
        self.assertEqual(seg.veredicto_xi(60.0)["estado"], "DESCARTA")

    def test_duda_intermedio(self):
        self.assertEqual(seg.veredicto_xi(78.0)["estado"], "DUDA")

    def test_umbrales_cautelosos_frontera(self):
        # Cautelosos: confirma solo >=88, descarta <75.
        self.assertEqual(seg.veredicto_xi(88.0)["estado"], "CONFIRMA")
        self.assertEqual(seg.veredicto_xi(87.9)["estado"], "DUDA")
        self.assertEqual(seg.veredicto_xi(75.0)["estado"], "DUDA")
        self.assertEqual(seg.veredicto_xi(74.9)["estado"], "DESCARTA")

    def test_frontera_confirma(self):
        self.assertEqual(seg.veredicto_xi(88.0)["estado"], "CONFIRMA")
        self.assertEqual(seg.veredicto_xi(87.9)["estado"], "DUDA")

    def test_frontera_descarta(self):
        self.assertEqual(seg.veredicto_xi(74.9)["estado"], "DESCARTA")
        self.assertEqual(seg.veredicto_xi(75.0)["estado"], "DUDA")


class TestListaSeguimiento(unittest.TestCase):
    def test_ordena_por_hora(self):
        horarios = {
            seg.canonical_team_key("Cruz Azul"): "2026-07-19T19:00:00",  # domingo
            seg.canonical_team_key("América"): "2026-07-17T21:00:00",    # viernes
        }
        items = seg.lista_seguimiento(_picks(), horarios=horarios)
        # América (viernes) debe ir primero aunque sea el 2º del ranking
        self.assertEqual(items[0]["equipo"], "América")
        self.assertEqual(items[1]["equipo"], "Cruz Azul")

    def test_veredicto_por_fuerza_xi(self):
        fuerza = {seg.canonical_team_key("Cruz Azul"): 92.0}
        items = seg.lista_seguimiento(_picks(), fuerza_xi=fuerza, n=2)
        caz = next(i for i in items if i["equipo"] == "Cruz Azul")
        self.assertEqual(caz["veredicto"]["estado"], "CONFIRMA")
        ame = next(i for i in items if i["equipo"] == "América")
        self.assertEqual(ame["veredicto"]["estado"], "PENDIENTE")  # sin XI

    def test_respeta_n(self):
        self.assertEqual(len(seg.lista_seguimiento(_picks(), n=1)), 1)


if __name__ == "__main__":
    unittest.main()


class TestRenderDecisivo(unittest.TestCase):
    def test_encabezado_da_el_pick(self):
        import telegram_pronosticos as tp
        items = seg.lista_seguimiento(_picks(), n=2)
        msg = tp.construir_mensaje_seguimiento(items, recomendado=_picks()[0])
        self.assertIn("TU PICK DE SURVIVOR", msg)
        self.assertIn("Cruz Azul", msg)          # el recomendado va en el encabezado
        self.assertIn("Respaldo", msg)            # los demás son respaldo, no menú


class TestAlternativaConRespaldo(unittest.TestCase):
    def _items(self):
        picks = [
            {"equipo": "Monterrey", "rival": "Santos", "condicion": "Local",
             "no_perder_pct": 84.0, "prob_victoria_pct": 60.0, "nivel": "ALTA"},
            {"equipo": "Necaxa", "rival": "Atlante", "condicion": "Local",
             "no_perder_pct": 74.0, "prob_victoria_pct": 50.0, "nivel": "MEDIA"},
        ]
        horarios = {
            seg.canonical_team_key("Necaxa"): "2026-07-16T19:00:00",     # juega antes
            seg.canonical_team_key("Monterrey"): "2026-07-18T19:00:00",  # juega al final
        }
        return seg.lista_seguimiento(picks, horarios=horarios, n=2)

    def test_pick_tardio_sugiere_alternativa_temprana(self):
        items = self._items()
        rec = {"equipo": "Monterrey"}
        alt = seg.alternativa_con_respaldo(items, rec)
        self.assertIsNotNone(alt)
        self.assertEqual(alt["equipo"], "Necaxa")

    def test_pick_temprano_no_sugiere(self):
        items = self._items()
        # Si el pick es Necaxa (el que juega antes), hay partidos después -> None.
        alt = seg.alternativa_con_respaldo(items, {"equipo": "Necaxa"})
        self.assertIsNone(alt)
