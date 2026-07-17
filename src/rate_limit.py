"""Rate limiting por IP (slowapi) para el bot Survivor Liga MX.

Protege los endpoints públicos (que hacen cálculos pesados o consultan ESPN)
de abuso o scraping agresivo. Configurable por entorno:
  - RATE_LIMIT_ENABLED: "true"/"false" (por defecto true; los tests lo apagan).
  - RATE_LIMIT_DEFAULT: limite global por IP (por defecto "60/minute").
"""

import os
from slowapi import Limiter
from slowapi.util import get_remote_address

RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
DEFAULT_LIMIT = os.getenv("RATE_LIMIT_DEFAULT", "60/minute")

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[DEFAULT_LIMIT],
    enabled=RATE_LIMIT_ENABLED,
)
