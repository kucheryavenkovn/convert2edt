#!/usr/bin/env bash
# Install OneScript + gitsync with plugins for the `gitsync` sync engine.
#
# gitsync works the CLASSIC way: the platform client (1cv8, configurator)
# reads the configuration storage — it is installed from the client dist
# (client_*.deb64.zip in dist/, no license required for repository
# operations). The edtExport plugin converts Designer XML -> EDT via
# 1cedtcli (already in the image). The tool1CD plugin stays OFF: it bundles
# Windows-only binaries and would need wine on Linux.
#
# Usage: install-gitsync.sh <enabled:1|0> <onescript-version>
set -euo pipefail

enabled="${1:-1}"
oscript_version="${2:-1.9.4}"

if [ "$enabled" != "1" ]; then
  echo "gitsync engine disabled (GITSYNC_SUPPORT != 1), skipping"
  exit 0
fi

echo "Installing OneScript ${oscript_version}..."
deb="/tmp/onescript-engine_${oscript_version}_all.deb"
apt-get update
apt-get install -y --no-install-recommends curl ca-certificates
curl -fsSL -o "$deb" \
  "https://github.com/EvilBeaver/OneScript/releases/download/v${oscript_version}/onescript-engine_${oscript_version}_all.deb"
apt-get install -y --no-install-recommends "$deb"
rm -f "$deb"
rm -rf /var/lib/apt/lists/*

echo "Installing gitsync + edtfind from the oscript package hub..."
opm install gitsync
opm install edtfind

# plugin catalog is per-user; the container runs as root, so build-time
# and runtime HOME are the same (/root).
# `gitsync plugins enable` crashes flakily on this stack (Newtonsoft.Json
# TypeInitializationException) — write plugins.json directly instead.
# Set matches the local Windows setup: increment + limit + disable-support
# + edtExport; tool1CD/use-ibcmd are OFF (tool1CD needs wine on Linux).
GITSYNC_PLUGINS_DIR="${HOME}/.local/share/gitsync/plugins"
gitsync plugins init
cat > "${GITSYNC_PLUGINS_DIR}/plugins.json" <<'EOF'
{
 "increment": true,
 "limit": true,
 "check-authors": false,
 "check-comments": false,
 "smart-tags": false,
 "tool1CD": false,
 "unpackForm": false,
 "disable-support": true,
 "sync-remote": false,
 "edtExport": true,
 "replace-authors": false
}
EOF
gitsync plugins list

if ! command -v gitsync >/dev/null 2>&1; then
  launcher="$(find /usr /opt -type f -name 'gitsync' 2>/dev/null | head -1)"
  [ -n "$launcher" ] && ln -sf "$launcher" /usr/local/bin/gitsync
fi

echo "gitsync: $(gitsync --version)"
