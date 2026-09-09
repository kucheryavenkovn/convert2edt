#!/usr/bin/env bash
# Install 1C:Enterprise platform (server component with ibcmd) into the image.
#
# Adapted from ShadobaAI/kafka-tools (.github/ci-images/docker/scripts/install-platform.sh),
# Apache License 2.0, https://github.com/ShadobaAI/kafka-tools — see THIRD_PARTY_NOTICES.md.
# Changes: setup-full (server64*) archive support is adopted from the previous
# crs2edt project; ru-nls deb packages are installed; server-only components.
#
# Usage: install-platform.sh <source-dir> [setup-full-components]
set -euo pipefail
shopt -s nullglob

source_dir="${1:?usage: install-platform.sh <source-dir> [components]}"
components="${2:-server,ru}"

work=/tmp/platform-install
rm -rf "$work"
mkdir -p "$work"
trap 'rm -rf "$work"' EXIT

latest_file() {
  find "$source_dir" -maxdepth 2 -type f -name "$1" | sort -V | tail -1
}

setup_archive="$(latest_file 'server64*.zip')"
[ -z "$setup_archive" ] && setup_archive="$(latest_file 'server64*.tar.gz')"

if [ -n "$setup_archive" ]; then
  echo "Platform archive: $(basename "$setup_archive")"
  case "$setup_archive" in
    *.tar.gz) tar -xzf "$setup_archive" -C "$work" ;;
    *.zip)    unzip -q "$setup_archive" -d "$work" ;;
  esac
  installer="$(find "$work" -maxdepth 2 -type f -name 'setup-full-*-x86_64.run' | sort -V | tail -1)"
  if [ -z "$installer" ]; then
    echo "setup-full-*-x86_64.run was not found in $(basename "$setup_archive")." >&2
    exit 1
  fi
  chmod +x "$installer"
  "$installer" --mode unattended --unattendedmodeui none --enable-components "$components"
else
  server_archive="$(latest_file 'deb64_*.zip')"
  [ -z "$server_archive" ] && server_archive="$(latest_file 'deb64_*.tar.gz')"

  if [ -z "$server_archive" ]; then
    echo "ERROR: neither server64* nor deb64_* platform archive was found in $source_dir." >&2
    echo "See vendor/README.md (official distributions from releases.1c.ru only)." >&2
    exit 1
  fi
  echo "Platform archive (server): $(basename "$server_archive")"
  case "$server_archive" in
    *.tar.gz) tar -xzf "$server_archive" -C "$work" ;;
    *.zip)    unzip -q "$server_archive" -d "$work" ;;
  esac

  cd "$work"
  debs=(
    1c-enterprise*-common_*.deb
    1c-enterprise*-common-nls_*.deb
    1c-enterprise*-server_*.deb
    1c-enterprise*-server-nls_*.deb
  )
  if [ "${#debs[@]}" -lt 4 ]; then
    echo "ERROR: expected 4 deb packages (common/server + nls), found ${#debs[@]}:" >&2
    ls -1 1c-enterprise*.deb >&2 || true
    exit 1
  fi
  apt-get update
  apt-get install -y --no-install-recommends \
    $(printf ' ./%s' "${debs[@]}")
  rm -rf /var/lib/apt/lists/*
fi

# /opt/1cv8/current is a stable path for wrappers and PATH.
current_dir="$(find /opt/1cv8 -maxdepth 3 -type f -name ibcmd -exec dirname {} \; | sort -V | tail -1)"
if [ -z "$current_dir" ]; then
  echo "ERROR: ibcmd was not found under /opt/1cv8 after install." >&2
  exit 1
fi
mkdir -p /opt/1cv8
ln -sfn "$current_dir" /opt/1cv8/current

missing="$(ldd "$current_dir/ibcmd" 2>/dev/null | grep 'not found' || true)"
if [ -n "$missing" ]; then
  echo "ERROR: ibcmd has missing shared libraries:" >&2
  printf '%s\n' "$missing" >&2
  exit 1
fi
echo "Installed 1C platform at: $current_dir"
