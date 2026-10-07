#!/usr/bin/env bash
# Comandia con MySQL. La primera vez pregunta los datos de conexión y los guarda en database.url
cd "$(dirname "$0")"
[ -f database.url ] || python3 comandia_cmd.py setup_mysql || exit 1
export DATABASE_URL="$(head -n1 database.url)"
[ -f .secret ] || python3 -c "import secrets;print(secrets.token_hex(32))" > .secret
export COMANDIA_SECRET="$(head -n1 .secret)"
python3 -m uvicorn app.main:app --app-dir . --host 127.0.0.1 --port 8100
