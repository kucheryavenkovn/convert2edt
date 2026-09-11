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

  # Optional: platform CLIENT (1cv8, configurator) for the gitsync engine —
  # drop client_*.deb64.zip (releases.1c.ru) next to deb64_*.zip.
  # thin-client debs are not installed (headless image).
  client_archive="$(latest_file 'client_*.deb64.zip')"
  [ -z "$client_archive" ] && client_archive="$(latest_file 'client64_*.zip')"
  [ -z "$client_archive" ] && client_archive="$(latest_file 'client_*.tar.gz')"
  if [ -n "$client_archive" ]; then
    echo "Platform archive (client): $(basename "$client_archive")"
    mkdir -p "$work/client"
    case "$client_archive" in
      *.tar.gz) tar -xzf "$client_archive" -C "$work/client" ;;
      *.zip)    unzip -q "$client_archive" -d "$work/client" ;;
    esac
    client_debs=()
    for f in "$work/client"/1c-enterprise*-client_*.deb \
             "$work/client"/1c-enterprise*-client-nls_*.deb; do
      case "$(basename "$f")" in *thin*) continue ;; esac
      client_debs+=("$f")
    done
    if [ "${#client_debs[@]}" -eq 0 ]; then
      echo "ERROR: no 1c-enterprise*-client_*.deb found in $(basename "$client_archive"):" >&2
      ls -1 "$work/client" >&2 || true
      exit 1
    fi
    apt-get update
    apt-get install -y --no-install-recommends "${client_debs[@]}"
    rm -rf /var/lib/apt/lists/*
  else
    echo "NOTE: no client_*.deb64.zip found — platform client (1cv8) NOT"
    echo "      installed; the gitsync engine in Docker requires it"
    echo "      (see vendor/README.md)."
  fi
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

# the client (1cv8) lands in the same versioned dir; check AFTER the
# /opt/1cv8/current symlink is in place
if [ -n "$client_archive" ]; then
  if [ ! -x /opt/1cv8/current/1cv8 ]; then
    echo "ERROR: 1cv8 (platform client) was not found in /opt/1cv8/current" >&2
    echo "after installing $(basename "$client_archive")." >&2
    exit 1
  fi
  echo "Platform client (1cv8) installed for the gitsync engine."
fi
