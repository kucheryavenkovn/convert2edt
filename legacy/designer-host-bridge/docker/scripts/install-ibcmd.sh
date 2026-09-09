#!/usr/bin/env bash
# Установка ТОЛЬКО ibcmd/rac из deb64-архива (пакеты common+server).
# Клиентские пакеты не ставятся: 1cv8 в контейнере нет (вариант B — Host Bridge).
set -euo pipefail
shopt -s nullglob

source_dir="${1:?usage: install-ibcmd.sh <source-dir>}"

work=/tmp/ibcmd-install
rm -rf "$work"
mkdir -p "$work"
trap 'rm -rf "$work"' EXIT

archive="$(find "$source_dir" -maxdepth 1 -type f -name 'deb64_*.zip' | sort -V | tail -1)"
if [ -z "$archive" ]; then
  archive="$(find "$source_dir" -maxdepth 1 -type f -name 'deb64_*.tar.gz' | sort -V | tail -1)"
fi
if [ -z "$archive" ]; then
  echo "ERROR: deb64_*.zip (сервер 1С для DEB-based Linux) не найден в $source_dir." >&2
  echo "ibcmd обязателен для плагина use-ibcmd. См. distr/README.md." >&2
  exit 1
fi

echo "ibcmd archive: $(basename "$archive")"
case "$archive" in
  *.tar.gz) tar -xzf "$archive" -C "$work" ;;
  *.zip)    unzip -q "$archive" -d "$work" ;;
esac

cd "$work"
debs=(
  1c-enterprise*-common_*.deb
  1c-enterprise*-common-nls_*.deb
  1c-enterprise*-server_*.deb
  1c-enterprise*-server-nls_*.deb
)
if [ "${#debs[@]}" -lt 4 ]; then
  echo "ERROR: ожидались deb-пакеты common/server (+nls), найдено ${#debs[@]}:" >&2
  ls -1 1c-enterprise*.deb >&2 || true
  exit 1
fi
apt-get update
apt-get install -y --no-install-recommends $(printf ' ./%s' "${debs[@]}")
rm -rf /var/lib/apt/lists/*

# sanity: ibcmd и rac обязаны быть
ibcmd_dir="$(find /opt/1cv8 -maxdepth 3 -type f -name ibcmd -exec dirname {} \; | sort -V | tail -1)"
if [ -z "$ibcmd_dir" ]; then
  echo "ERROR: ibcmd не найден после установки пакетов." >&2
  exit 1
fi
mkdir -p /opt/1cv8
ln -sfn "$ibcmd_dir" /opt/1cv8/current
echo "Installed ibcmd at: $ibcmd_dir"

# Кандидат на wrapper: каталог версии, куда Dockerfile положит symlink 1cv8
echo "version dir: $(basename "$ibcmd_dir")"
