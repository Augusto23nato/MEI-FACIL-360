#!/usr/bin/env bash
# ./aula.sh "<conceito>" — cria a aula e abre o slide 1 no navegador.
cd "$(dirname "$0")"
CONCEITO="${1:?uso: ./aula.sh \"conceito\"}"; PORT="${LSL_PORT:-4242}"
./iniciar.sh >/dev/null || { ./iniciar.sh; exit 1; }
BODY=$(.venv/bin/python -c 'import json,sys; print(json.dumps({"concept": sys.argv[1]}))' "$CONCEITO")
R=$(curl -s -X POST "http://127.0.0.1:$PORT/api/sessions" -H 'Content-Type: application/json' -d "$BODY")
CAMINHO=$(printf '%s' "$R" | sed -nE 's/.*"url": *"([^"]+)".*/\1/p')
[ -n "$CAMINHO" ] || { echo "falhou ao criar a aula: $R"; exit 1; }
URL="http://127.0.0.1:$PORT$CAMINHO"
if [ -z "$LAMPEJO_NO_OPEN" ]; then
  open -a "Google Chrome" "$URL" 2>/dev/null || open "$URL" 2>/dev/null || xdg-open "$URL" >/dev/null 2>&1 || true
fi
echo "$URL"
