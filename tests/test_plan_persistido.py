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


def _tendencias():
    return {
        "undes_fc": {
            "senal": 0.02,
            "razones": ["ataque en forma"],
        }
    }


def _resultados_torneo():
    return [
        {"fecha": "2026-07-10", "home_team": "Unders FC", "away_team": "Grande", "home_goals": 2, "away_goals": 1},
        {"fecha": "2026-07-11", "home_team": "Debil", "away_team": "Solido", "home_goals": 0, "away_goals": 1},
    ]


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
            "src.tendencias_torneo.cargar_resultados_torneo_actual",
            return_value={"fuente": "no_disponible", "resultados": []},
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
    assert resultado["tendencias_aplicadas"] is False

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
            "src.tendencias_torneo.cargar_resultados_torneo_actual",
            return_value={"fuente": "no_disponible", "resultados": []},
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
    assert resultado["tendencias_aplicadas"] is False


def test_tendencias_aplica_ajuste_de_fuerzas_cuando_hay_resultados():
    calendario = [
        {"jornada": 3, "partidos": [{"fecha": "2026-07-20"}]},
    ]
    with (
        mock.patch(
            "src.database.temporada_survivor_actual",
            return_value="Apertura-2026",
        ),
        mock.patch("src.database.get_survivor_picks", return_value=[]),
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
            return_value={
                "equipos": {
                    "undes fc": {
                        "ataque_local": 1.0,
                        "defensa_local": 1.0,
                    }
                }
            },
        ),
        mock.patch(
            "src.tendencias_torneo.cargar_resultados_torneo_actual",
            return_value={
                "fuente": "mock",
                "resultados": _resultados_torneo(),
            },
        ),
        mock.patch(
            "src.tendencias_torneo.calcular_tendencias",
            return_value=_tendencias(),
        ) as calc_tend,
        mock.patch(
            "src.tendencias_torneo.ajustar_fuerzas",
            wraps=lambda f, t: {"equipos": {"undes fc": {"ataque_local": 1.02}}},
        ) as ajustar_f,
        mock.patch(
            "src.planificador_survivor.planificar",
            return_value=_resultado_plan(),
        ) as planificar,
    ):
        resultado = pp._plan_temporada(
            [],
            usar_momios=False,
            jornada_desde=3,
            permitir_descarga=False,
        )

    calc_tend.assert_called_once()
    ajustar_f.assert_called_once()
    # El planificador recibe fuerzas ajustadas
    fuerzas_para_plan = planificar.call_args.args[1]
    assert fuerzas_para_plan["equipos"]["undes fc"]["ataque_local"] == 1.02
    assert resultado["tendencias_aplicadas"] is True

    mensaje = pp.construir_mensaje_plan_persistido(resultado)
    assert "Tendencias del torneo en vivo aplicadas" in mensaje


def test_tendencias_no_rompe_si_falla_la_capa():
    calendario = [{"jornada": 3, "partidos": []}]
    with (
        mock.patch(
            "src.database.temporada_survivor_actual",
            return_value="Apertura-2026",
        ),
        mock.patch("src.database.get_survivor_picks", return_value=[]),
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
            "src.tendencias_torneo.cargar_resultados_torneo_actual",
            side_effect=RuntimeError("sin red"),
        ),
        mock.patch(
            "src.planificador_survivor.planificar",
            return_value=_resultado_plan(),
        ) as planificar,
    ):
        resultado = pp._plan_temporada(
            [],
            usar_momios=False,
            jornada_desde=3,
            permitir_descarga=False,
        )

    # No debería reventar: el plan se construye sin tendencias
    planificar.assert_called_once()
    assert resultado["tendencias_aplicadas"] is False
