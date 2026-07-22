"""Configuración de pytest para survivor-ligamx-bot.

Desactiva el rate limiting (slowapi) durante los tests. Varios tests llaman a
los endpoints directamente (sin servidor HTTP ni objeto ``Request``), y con el
limiter activo slowapi rechaza esas llamadas con
``parameter `request` must be an instance of starlette.requests.Request``.

``src/rate_limit.py`` lee ``RATE_LIMIT_ENABLED`` al importarse y su docstring
documenta la intención: "por defecto true; los tests lo apagan". Este conftest
materializa ese comportamiento y debe ejecutarse antes de importar cualquier
módulo del proyecto (pytest carga conftest.py antes de los módulos de test).
"""

import os

# setdefault: no sobreescribe si el entorno ya lo fija explícitamente.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
