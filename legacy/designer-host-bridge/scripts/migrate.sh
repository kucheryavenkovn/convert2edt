#!/usr/bin/env bash
# Первичная миграция: цикл партий (GITSYNC_LIMIT = MIGRATE_BATCH_LIMIT версий
# на прогон gitsync), push после каждой партии. Продолжение с прерванной версии
# гарантируется файлом VERSION (штатная механика gitsync).
set -euo pipefail
source /opt/converter/lib.sh

export GITSYNC_LIMIT="${MIGRATE_BATCH_LIMIT:-500}"
log "Миграция: батчи по ${GITSYNC_LIMIT} версий хранилища."

batch=0
t_total=$(date +%s)
while true; do
  batch=$((batch + 1))
  t0=$(date +%s)
  if sync_one_batch; then
    t1=$(date +%s)
    log "Батч #$batch запушен за $((t1 - t0)) с. Продолжаем."
    sleep 1
  else
    log "Новых версий нет — миграция завершена (батчей: $((batch - 1)))."
    break
  fi
done
log "Общее время миграции: $(( $(date +%s) - t_total )) с."
