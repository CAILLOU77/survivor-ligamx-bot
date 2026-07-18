def _jornada_actual_num() -> Optional[int]:
    """Número de la próxima jornada por jugar (según data/calendario.json).
    Siempre toma la primera jornada del calendario como predeterminada.
    Así /pick y /plan SIEMPRE coinciden aunque el calendario sea futuro."""
    try:
        cal = _cargar_calendario_local()
        if cal:
            return int(cal[0].get("jornada", 1))
        return None
    except Exception:  # pragma: no cover
        return None