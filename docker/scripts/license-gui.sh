#!/usr/bin/env bash
# Интерактивное получение программной лицензии 1С через VNC.
# Одноразовая процедура для gitsync-движка в Docker (подход kafka-tools `client`:
# GUI-стек openbox+xvfb+x11vnc, лицензия персистится в volume).
#
# Запуск (MAC зафиксирован в compose, volume v8home монтируется сервисом;
# VNC-порт контейнера 5900, публикуется явно, чтобы не мешать 8080):
#   docker compose run --rm -p 127.0.0.1:5900:5900 converter license-gui
# если 5900 на хосте занят (например, локальный VNC-сервер) — другой порт:
#   docker compose run --rm -p 127.0.0.1:15900:5900 converter license-gui
#   (подключаться тогда к 127.0.0.1:15900)
#
# Затем подключиться VNC-клиентом к 127.0.0.1:5900 (без пароля; порт
# пробрасывается только на loopback). В окне 1С:Предприятия появится диалог
# лицензии — «Получить программную лицензию» (нужен логин/пароль
# releases.1c.ru). Лицензия сохраняется в /root/.1cv8 (volume v8home) и
# подхватывается всеми последующими запусками контейнера.
#
# Останов: Ctrl+C (или docker stop).
set -euo pipefail

DISPLAY_NUM=":99"
RESOLUTION="1280x900x24"
VNC_PORT="${VNC_PORT:-5900}"
export DISPLAY="${DISPLAY_NUM}"

CLIENT_PID=""
VNC_PID=""
XVFB_PID=""

cleanup() {
  [ -n "$CLIENT_PID" ] && kill "$CLIENT_PID" 2>/dev/null || true
  [ -n "$VNC_PID" ] && kill "$VNC_PID" 2>/dev/null || true
  [ -n "$XVFB_PID" ] && kill "$XVFB_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "[license-gui] Xvfb ${DISPLAY_NUM} (${RESOLUTION})..."
Xvfb "${DISPLAY_NUM}" -screen 0 "${RESOLUTION}" -nolisten tcp &
XVFB_PID=$!
sleep 1

echo "[license-gui] openbox..."
openbox &
sleep 1

echo "[license-gui] x11vnc на порту ${VNC_PORT} (только loopback хоста)..."
x11vnc -display "${DISPLAY_NUM}" -rfbport "${VNC_PORT}" \
       -nopw -forever -shared -noxdamage -quiet &
VNC_PID=$!
sleep 1

# пустая файловая ИБ: конфигуратор откроется и покажет диалог лицензии.
# NB: запускаем 1cv8.real (без xvfb-run-враппера) — X уже поднят нами (:99),
# иначе врапер создаст свой Xvfb и окно не попадёт в VNC.
rm -rf /tmp/lic-ib /tmp/lic-data
ibcmd infobase create --db-path=/tmp/lic-ib --data=/tmp/lic-data \
                      --create-database >/dev/null 2>&1 || true

echo
echo "=============================================================="
echo "  VNC:      vnc://127.0.0.1:${VNC_PORT}  (без пароля)"
echo "  В 1С:     Получить программную лицензию (releases.1c.ru)"
echo "  Лицензия: /root/.1cv8 (volume v8home, переживает --rm)"
echo "  Стоп:     Ctrl+C"
echo "=============================================================="
echo

/opt/1cv8/current/1cv8.real DESIGNER /F/tmp/lic-ib &
CLIENT_PID=$!

wait "${CLIENT_PID}" 2>/dev/null || true
echo "[license-gui] клиент 1С закрыт; VNC ещё активен — Ctrl+C для выхода"
wait
