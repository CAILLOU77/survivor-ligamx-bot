#!/usr/bin/env python3
"""Corrige la importación datetime del parche Telegram."""
from pathlib import Path

path = Path("scripts/apply_telegram_idempotency.py")
text = path.read_text(encoding="utf-8")
old = 'db = db.replace("from datetime import datetime, timezone", "from datetime import datetime, timedelta, timezone", 1)'
new = 'db = db.replace("from datetime import date", "from datetime import date, datetime, timedelta, timezone", 1)'
if old not in text:
    raise RuntimeError("No se encontró la importación antigua del parche")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
