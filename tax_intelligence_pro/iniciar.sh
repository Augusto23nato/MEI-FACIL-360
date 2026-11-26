#!/usr/bin/env bash
# Inicia o TAX INTELLIGENCE PRO em http://127.0.0.1:8360
#   ./iniciar.sh          servidor
#   ./iniciar.sh demo     carrega a base de demonstração antes
#   ./iniciar.sh testes   roda a suíte de testes
set -euo pipefail
cd "$(dirname "$0")"
case "${1:-}" in
  demo) python3 exemplos/demo.py ;;
  testes) exec python3 -m pytest -q tests ;;
esac
exec python3 -m tip.servidor
