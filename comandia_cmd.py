"""Ejecuta una herramienta de Comandia: python comandia_cmd.py <herramienta> [opciones]
Herramientas: setup_mysql, actualizar_db, resumen_db, restaurar, servidor.
Reemplaza a «python -m app.<herramienta>», que no funciona cuando el sistema va compilado (versión protegida)."""
import importlib
import sys

if len(sys.argv) < 2:
    sys.exit(__doc__)
name = sys.argv.pop(1)  # lo que queda en sys.argv son las opciones de la herramienta
sys.exit(importlib.import_module("app." + name).main())
