from unittest import mock

from src.telegram import plan_persistido as pp


def _historial():
    return [
        {
            "jornada": 1,
            "equipo": "Monterrey",
            "estado": "resuelto",
            "resultado": "gano",
        },
        {
            "jornada": 2,
            "equipo": "Cruz Azul",
            "estado": "resuelto",
            "resultado": "gano",
        },
    ]


def _resultado_plan():
    return {
        "plan": [
            {
                "jornada": 3,
                "equipo": "América",
                "rival": "Santos",
                "condicion": "Local",
                "prob_ganar_pct": 72.7,
                "no_perder_pct": 89.7,
                "nivel": "ALTA",
            }
        ],
        "prob_supervivencia_total_pct": 89.7,
        "victorias_esperadas": 0.73,
        "jornadas_riesgosas": [],
        "calendario_incompleto": False,
    }


def test_plan_excluye_jornadas_cerradas_y_muestra_historial():
    calendario = [
        {"jornada": 1, "partidos": []},
        {"jornada": 2, "partidos": []},
        {"jornada": 3, "partidos": []},
        {"jornada": 4, "partidos": []},
    ]
    with (
        mock.patch(
            "src.database.temporada_survivor_actual",
            return_value="Apertura-2026",
        ),
        mock.patch("src.database.get_survivor_picks", return_value=_historial()),
        mock.patch(
            "src.planificador_survivor.cargar_calendario",
            return_value=calendario,
        ),
        mock.patch(
            "src.fuentes_datos.leer_cache",
            return_value=[{"home_team": "A", "away_team": "B"}],
        ),
        mock.patch(
            "src.poisson_model.calcular_fuerzas",
            return_value={"equipos": {}},
        ),
        mock.patch(
            "src.planificador_survivor.planificar",
            return_value=_resultado_plan(),
        ) as planificar,
    ):
        resultado = pp._plan_temporada(
            ["Monterrey", "Cruz Azul"],
            usar_momios=False,
            jornada_desde=2,
            permitir_descarga=False,
        )

    calendario_recibido = planificar.call_args.args[0]
    assert [bloque["jornada"] for bloque in calendario_recibido] == [3, 4]
    assert [item["jornada"] for item in resultado["historial_cerrado"]] == [1, 2]
    assert [item["jornada"] for item in resultado["plan"]] == [3]

    mensaje = pp.construir_mensaje_plan_persistido(resultado)
    assert "J1 · Monterrey</b> 🔒 ✅ Ganó" in mensaje
    assert "J2 · Cruz Azul</b> 🔒 ✅ Ganó" in mensaje
    assert "Plan restante desde J3" in mensaje
    assert "J1 · América" not in mensaje
    assert "J2 · América" not in mensaje


def test_fallback_sin_bd_conserva_horizonte_actual():
    calendario = [
        {"jornada": 2, "partidos": []},
        {"jornada": 3, "partidos": []},
    ]
    plan = _resultado_plan()
    with (
        mock.patch(
            "src.database.get_survivor_picks",
            side_effect=RuntimeError("sin BD"),
        ),
        mock.patch(
            "src.planificador_survivor.cargar_calendario",
            return_value=calendario,
        ),
        mock.patch(
            "src.fuentes_datos.leer_cache",
            return_value=[{"home_team": "A", "away_team": "B"}],
        ),
        mock.patch(
            "src.poisson_model.calcular_fuerzas",
            return_value={"equipos": {}},
        ),
        mock.patch(
            "src.planificador_survivor.planificar",
            return_value=plan,
        ) as planificar,
    ):
        resultado = pp._plan_temporada(
            [],
            usar_momios=False,
            jornada_desde=2,
            permitir_descarga=False,
        )

    calendario_recibido = planificar.call_args.args[0]
    assert [bloque["jornada"] for bloque in calendario_recibido] == [2, 3]
    assert resultado["historial_cerrado"] == []
