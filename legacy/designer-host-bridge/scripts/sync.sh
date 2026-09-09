#!/usr/bin/env bash
# Синхронизация одной партии: clone/update -> gitsync -> изоляция -> EDT -> push.
set -euo pipefail
source /opt/converter/lib.sh

t0=$(date +%s)
if sync_one_batch; then
  t1=$(date +%s)
  log "Партия завершена и запушена за $((t1 - t0)) с."
else
  t1=$(date +%s)
  log "Синхронизировано: ничего нового ($((t1 - t0)) с)."
fi
