#!/usr/bin/env bash
# Entrypoint converter-контейнера.
# Вариант A (полный образ): работает от usr1cv8 (лицензии платформы в volume) + Xvfb.
# Вариант B (Dockerfile.bridge): платформы в контейнере нет, работает от root.
set -euo pipefail

log() { printf '[entrypoint] %s\n' "$*"; }

# Пользователь: usr1cv8 если есть (вариант A), иначе root (вариант B).
if getent passwd usr1cv8 >/dev/null 2>&1; then
  RUN_USER=usr1cv8
  RUN_HOME=/home/usr1cv8
else
  RUN_USER=root
  RUN_HOME=/root
fi

chown_volume() {
  [ "$RUN_USER" = root ] && return 0
  [ -d "$1" ] && chown -R "$RUN_USER:$RUN_USER" "$1" 2>/dev/null || true
}

prepare() {
  mkdir -p /repo /cache /state /config /bridge 2>/dev/null || true
  chown_volume /repo; chown_volume /cache; chown_volume /state
  if [ "$RUN_USER" = usr1cv8 ]; then
    mkdir -p /var/1C/licenses /var/log/1C
    chown root:grp1cv8 /var/1C/licenses 2>/dev/null || true
    chmod 775 /var/1C/licenses 2>/dev/null || true
    mkdir -p /home/usr1cv8 && chown usr1cv8:grp1cv8 /home/usr1cv8
  fi

  # Xvfb нужен только при локальном 1cv8 (вариант A): некоторым сборкам платформы
  # требуется GUI-инициализация даже в batch-режиме.
  if [ "$RUN_USER" = usr1cv8 ] && [ -z "${BRIDGE_URL:-}" ]; then
    export DISPLAY="${DISPLAY:-:99}"
    if command -v xdpyinfo >/dev/null 2>&1 && ! xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then
      if command -v Xvfb >/dev/null 2>&1; then
        log "Запуск фиктивного X-сервера Xvfb $DISPLAY"
        gosu usr1cv8 /usr/bin/Xvfb "$DISPLAY" -screen 0 1280x1024x24 >/dev/null 2>&1 &
        for _ in $(seq 1 20); do
          xdpyinfo -display "$DISPLAY" >/dev/null 2>&1 && break
          sleep 0.5
        done
      fi
    fi
  fi
}

run_cmd() {
  export HOME="$RUN_HOME" USER="$RUN_USER" LOGNAME="$RUN_USER"
  if [ "$RUN_USER" = usr1cv8 ]; then
    exec gosu usr1cv8 env HOME="$RUN_HOME" USER="$RUN_USER" LOGNAME="$RUN_USER" \
      DISPLAY="${DISPLAY:-:99}" bash "/opt/converter/$1" "${@:2}"
  else
    exec bash "/opt/converter/$1" "${@:2}"
  fi
}

cmd="${1:-help}"
shift || true

case "$cmd" in
  doctor|migrate|sync)
    prepare
    run_cmd "$cmd.sh" "$@"
    ;;
  gitsync)
    prepare
    run_cmd gitsync-direct.sh "$@"
    ;;
  shell|bash)
    prepare
    if [ "$RUN_USER" = usr1cv8 ]; then
      export HOME="$RUN_HOME"
      exec gosu usr1cv8 bash "${@:-}"
    else
      exec bash "${@:-}"
    fi
    ;;
  help|--help|*)
    cat <<'EOF'
Команды:
  doctor   — проверка окружения (bridge/платформа, лицензия, EDT, git, storage)
  migrate  — первичная миграция всей истории (батчами MIGRATE_BATCH_LIMIT)
  sync     — инкрементальная синхронизация новых версий
  gitsync  — прямой вызов gitsync (экспертный режим)
  shell    — интерактивная оболочка
EOF
    ;;
esac
