#!/usr/bin/env python3
"""Formatea los archivos del contrato estable con la versión de Ruff del proyecto."""
import subprocess

files = ["src/ligamx_api.py", "tests/test_ligamx_contract.py"]
subprocess.run(["ruff", "check", "--fix", *files], check=True)
subprocess.run(["ruff", "format", *files], check=True)
