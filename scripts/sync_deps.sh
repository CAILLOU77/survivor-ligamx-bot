#!/usr/bin/env bash
# ===================================================================
# Sincroniza requirements.txt y requirements-dev.txt desde pyproject.toml
# ===================================================================
# Uso: bash scripts/sync_deps.sh
# Requiere: pip install pip-tools
# ===================================================================
set -euo pipefail

cd "$(dirname "$0")/.."

echo "=== Regenerando requirements.txt desde pyproject.toml ==="
pip-compile --output-file=requirements.txt pyproject.toml 2>/dev/null || {
  echo "pip-compile no encontrado. Instalando pip-tools..."
  pip install pip-tools
  pip-compile --output-file=requirements.txt pyproject.toml
}

echo "=== Regenerando requirements-dev.txt ==="
pip-compile --extra=dev --output-file=requirements-dev.txt pyproject.toml 2>/dev/null || {
  pip-compile --extra=dev --output-file=requirements-dev.txt pyproject.toml
}

echo "✅ requirements.txt y requirements-dev.txt actualizados desde pyproject.toml"
