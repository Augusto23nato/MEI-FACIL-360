#!/usr/bin/env bash
# Sobe o servidor do Lampejo em segundo plano (se ainda não estiver no ar).
cd "$(dirname "$0")"
PORT="${LSL_PORT:-4242}"
export LSL_HOST="${LSL_HOST:-127.0.0.1}"   # 127.0.0.1 = só neste computador. LSL_HOST=0.0.0.0 abre para o celular na mesma rede.
PY=".venv/bin/python"; [ -x "$PY" ] || { echo "Ambiente não instalado. Abra esta pasta no Claude Code e diga: configurar o Lampejo"; exit 1; }
if curl -s -m 2 "http://127.0.0.1:$PORT/api/health" >/dev/null; then echo "já no ar: http://127.0.0.1:$PORT"; exit 0; fi
mkdir -p runs
# HTTPS na rede (microfone no celular): só quando LSL_HOST=0.0.0.0 e o mkcert estiver instalado
IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')"
if [ "$LSL_HOST" = "0.0.0.0" ] && command -v mkcert >/dev/null && [ -n "$IP" ]; then
  if [ ! -f .certs/lsl.pem ] || ! openssl x509 -in .certs/lsl.pem -noout -ext subjectAltName 2>/dev/null | grep -q "$IP"; then
    mkdir -p .certs && mkcert -cert-file .certs/lsl.pem -key-file .certs/lsl-key.pem localhost 127.0.0.1 ::1 "$IP" >/dev/null 2>&1
  fi
fi
nohup "$PY" server.py >> runs/server.log 2>&1 &
for i in $(seq 1 40); do curl -s -m 1 "http://127.0.0.1:$PORT/api/health" >/dev/null && { echo "no ar: http://127.0.0.1:$PORT"; exit 0; }; sleep 0.5; done
echo "não subiu — veja runs/server.log"; exit 1
