#!/usr/bin/env bash
# Prepara o Lampejo num contêiner novo da nuvem: ambiente Python + configuração (sem chaves).
# A chave do ElevenLabs vem do proxy do ambiente (Network secrets).
set -e
cd "$(dirname "$0")/.."
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/python -c "import requests, PIL, playwright" 2>/dev/null || \
  .venv/bin/pip install -q requests Pillow "playwright==1.63.0"
chmod +x aula.sh iniciar.sh tools/drawio tools/render_diagram.sh
if [ ! -f .lampejo/config.env ]; then
  mkdir -p .lampejo
  cat > .lampejo/config.env <<EOF
# Lampejo — configuração da nuvem (a chave real é injetada pelo proxy)
LSL_ELEVEN_KEY=proxy-injected
LSL_ELEVEN_VOICE=SAz9YHcvj6GT2YYXdXww
LSL_ELEVEN_VOICE_NAME=River
LSL_DRAWIO=$PWD/tools/drawio
PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
EOF
  chmod 600 .lampejo/config.env
fi
echo "Lampejo pronto"
