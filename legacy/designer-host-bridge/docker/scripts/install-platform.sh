#!/usr/bin/env bash
# Установка платформы 1С 8.3.27 в образ.
# Поддерживаются два варианта дистрибутивов (см. distr/README.md):
#   1) server64*.zip/.tar.gz — setup-full со всеми компонентами (толстый клиент внутри);
#   2) deb64_*.zip (сервер: common/server/ws/crs) + client_*.deb64.zip (толстый клиент).
# Дистрибутивы подаются read-only через BuildKit named context `distr`.
# Адаптировано из ShadobaAI/kafka-tools и mussolene/1c-develop.
set -euo pipefail
shopt -s nullglob

source_dir="${1:?usage: install-platform.sh <source-dir> [components]}"
components="${2:-server,client,ru}"

work=/tmp/platform-install
rm -rf "$work"
mkdir -p "$work"
trap 'rm -rf "$work"' EXIT

latest_file() {
  local f
  f="$(find "$source_dir" -maxdepth 1 -type f -name "$1" | sort -V | tail -1)"
  printf '%s' "$f"
}

setup_archive="$(latest_file 'server64*.zip')"
[ -z "$setup_archive" ] && setup_archive="$(latest_file 'server64*.tar.gz')"

if [ -n "$setup_archive" ]; then
  # ---------------------------------------------------------------- setup-full
  echo "Platform archive: $(basename "$setup_archive")"
  case "$setup_archive" in
    *.tar.gz) tar -xzf "$setup_archive" -C "$work" ;;
    *.zip)    unzip -q "$setup_archive" -d "$work" ;;
  esac
  installer="$(find "$work" -maxdepth 2 -type f -name 'setup-full-*-x86_64.run' | sort -V | tail -1)"
  if [ -z "$installer" ]; then
    echo "setup-full-*-x86_64.run не найден в $(basename "$setup_archive")." >&2
    exit 1
  fi
  chmod +x "$installer"
  # Нужны: server (ragent/rac/ibcmd) и client (толстый клиент 1cv8 — gitsync).
  "$installer" --mode unattended --unattendedmodeui none --enable-components "$components"
else
  # ------------------------------------------------- deb64 (server) + client
  server_archive="$(latest_file 'deb64_*.zip')"
  [ -z "$server_archive" ] && server_archive="$(latest_file 'deb64_*.tar.gz')"
  client_archive="$(latest_file 'client_*.zip')"
  [ -z "$client_archive" ] && client_archive="$(latest_file 'client_*.deb64.zip')"

  if [ -z "$server_archive" ]; then
    echo "ERROR: в $source_dir нет ни server64*, ни deb64_* — см. distr/README.md." >&2
    exit 1
  fi
  echo "Platform archive (server): $(basename "$server_archive")"
  case "$server_archive" in
    *.tar.gz) tar -xzf "$server_archive" -C "$work" ;;
    *.zip)    unzip -q "$server_archive" -d "$work" ;;
  esac

  if [ -z "$client_archive" ]; then
    echo "ERROR: deb64-архив не содержит толстый клиент, а отдельный client_*.zip не найден." >&2
    echo "Конфигуратор 1cv8 обязателен для gitsync. Скачайте с той же страницы релиза" >&2
    echo "«Клиент 1С:Предприятия (64-bit) для DEB-based Linux» (client_*_*.deb64.zip)" >&2
    echo "или полную «Технологическую платформу для Linux» (server64*), см. distr/README.md." >&2
    exit 1
  fi
  echo "Platform archive (client): $(basename "$client_archive")"
  case "$client_archive" in
    *.tar.gz) tar -xzf "$client_archive" -C "$work" ;;
    *.zip)    unzip -q "$client_archive" -d "$work" ;;
  esac

  cd "$work"
  # Ставим: common(+nls), server(+nls), client(+nls). thin-client/ws/crs не нужны.
  debs=(
    1c-enterprise*-common_*.deb
    1c-enterprise*-common-nls_*.deb
    1c-enterprise*-server_*.deb
    1c-enterprise*-server-nls_*.deb
    1c-enterprise*-client_*.deb
    1c-enterprise*-client-nls_*.deb
  )
  if [ "${#debs[@]}" -lt 6 ]; then
    echo "ERROR: ожидались 6 deb-пакетов (common/server/client + nls), найдено ${#debs[@]}:" >&2
    ls -1 1c-enterprise*.deb >&2 || true
    exit 1
  fi
  apt-get update
  apt-get install -y --no-install-recommends \
    $(printf ' ./%s' "${debs[@]}")
  rm -rf /var/lib/apt/lists/*
fi

# Санитарная проверка динамических библиотек ключевых бинарей.
bin_dir="$(find /opt/1cv8 -maxdepth 3 -type f -name 1cv8 -exec dirname {} \; | sort -V | tail -1)"
if [ -n "$bin_dir" ]; then
  missing="$(ldd "$bin_dir/1cv8" 2>/dev/null | grep 'not found' || true)"
  if [ -n "$missing" ]; then
    echo "WARNING: 1cv8 имеет недостающие библиотеки:" >&2
    printf '%s\n' "$missing" >&2
  fi
fi

# /opt/1cv8/current — стабильный путь для PATH. Автопоиск v8find работает по
# /opt/1cv8/x86_64/8.?.*.* напрямую, симлинк ему не виден (и не мешает).
current_dir="$(find /opt/1cv8 -maxdepth 3 -type f \( -name ibcmd -o -name 1cv8 \) -exec dirname {} \; | sort -V | tail -1)"
if [ -z "$current_dir" ]; then
  echo "ERROR: после установки не найдены 1cv8/ibcmd в /opt/1cv8." >&2
  exit 1
fi
mkdir -p /opt/1cv8
ln -sfn "$current_dir" /opt/1cv8/current
echo "Installed 1C platform at: $current_dir"
