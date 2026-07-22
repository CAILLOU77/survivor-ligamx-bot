import time
from functools import wraps
from typing import Any, Callable, Dict, Optional


def ttl_cache(segundos: int = 600):
    """
    Decorador de caché simple con tiempo de vida (TTL).
    No soporta argumentos en la función (ideal para funciones de generación global).
    """

    def deco(fn: Callable[..., Any]):
        estado: Dict[str, Any] = {"t": 0.0, "valor": None}

        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            ahora = time.monotonic()
            # Si el valor es None o el tiempo ha expirado, refrescar
            if estado["valor"] is None or ahora - estado["t"] > segundos:
                estado["valor"] = fn(*args, **kwargs)
                estado["t"] = ahora
            return estado["valor"]

        def cache_clear():
            estado["t"] = 0.0
            estado["valor"] = None

        wrapper.cache_clear = cache_clear  # type: ignore[attr-defined]
        return wrapper

    return deco
