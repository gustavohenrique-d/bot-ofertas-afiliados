#!/usr/bin/env bash
# Chamado pelo cron na VM. Uso: scripts/rodar_slot.sh 08   (08, 12, 18 ou 21)
set -euo pipefail

SLOT="${1:?informe o horário: 08, 12, 18 ou 21}"
PASTA="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PASTA"

# flock impede duas execuções ao mesmo tempo (ex.: um horário atrasado)
# O log principal fica em logs/bot.log; cron.log guarda só erros graves (tracebacks).
exec flock -n "$PASTA/logs/.bot.lock" \
    "$PASTA/.venv/bin/python" main.py --slot "$SLOT" >> "$PASTA/logs/cron.log" 2>&1
