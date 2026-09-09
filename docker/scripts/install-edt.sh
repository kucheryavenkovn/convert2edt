#!/usr/bin/env bash
# Install 1C:EDT (1cedtcli) from the official offline distribution.
#
# Adapted from ShadobaAI/kafka-tools (.github/ci-images/docker/scripts/install-edt.sh),
# Apache License 2.0, https://github.com/ShadobaAI/kafka-tools — see THIRD_PARTY_NOTICES.md.
# Changes: source files are searched one level deep; minor message adjustments.
#
# Usage: install-edt.sh <source-dir> [keep-platform-version]
set -euo pipefail
shopt -s nullglob

source_dir="${1:?usage: install-edt.sh <source-dir> [keep-platform-version]}"
keep_platform_versions="${2:-}"
archive="$(find "$source_dir" -maxdepth 2 -type f -name '1c_edt_distr_offline_*_linux_x86_64.tar.gz' | sort -V | tail -1)"

if [ -n "$keep_platform_versions" ]; then
  # EDT platform support versions have the major.minor.patch format.
  keep_platform_versions="$(printf '%s\n' "$keep_platform_versions" | sed -n 's/^\([0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\)\(\.[0-9][0-9]*\)*$/\1/p')"
  if [ -z "$keep_platform_versions" ]; then
    echo "EDT platform support version must be in major.minor.patch[.build] format." >&2
    exit 1
  fi
fi

if [ -z "$archive" ]; then
  echo "EDT offline archive (1c_edt_distr_offline_*_linux_x86_64.tar.gz) was not found in $source_dir." >&2
  echo "Download '1C:EDT (offline) для Linux x86_64' from https://releases.1c.ru (see vendor/README.md)." >&2
  exit 1
fi
echo "EDT archive: $(basename "$archive")"

work=/tmp/edt-install
rm -rf "$work"
mkdir -p "$work"
tar -xzf "$archive" -C "$work"

installer="$(find "$work" -maxdepth 1 -type f -name '1ce-installer-cli' | head -1)"
if [ -z "$installer" ]; then
  # Some offline archives keep the CLI installer inside the .e1c.car package.
  car="$(find "$work" -maxdepth 1 -type f -name '1c-enterprise-installer-*-linux-x86_64.e1c.car' | head -1)"
  if [ -n "$car" ]; then
    unzip -q "$car" -d "$work/installer"
    chmod +x "$work/installer/data/1ce-installer-cli"
    installer="$work/installer/data/1ce-installer-cli"
  else
    echo "1ce-installer-cli was not found in EDT archive." >&2
    exit 1
  fi
fi

if ! command -v java >/dev/null 2>&1; then
  echo "Java 17 runtime was not found in PATH." >&2
  exit 1
fi

chmod +x "$installer"
if ! "$installer" --javahome "${JAVA_HOME:-/usr/lib/jvm/java-17-openjdk-amd64}" install \
  --source "$work" \
  --ignore-hardware-checks \
  --ignore-signature-warnings \
  1c-edt-product-offline \
  --components 1c-edt; then
  if ! find /opt/1C/1CE -type f \( -name 1cedtcli -o -name 1cedt \) | grep -q .; then
    echo "EDT installer failed and EDT files were not found." >&2
    exit 1
  fi
  echo "EDT installer returned a non-zero exit code after installing files; continuing." >&2
fi

# The final 1cedtcli must use the system Java 17, not a bundled JDK.
if find /opt/1C/1CE -type d -name 'axiom-jdk*' -print -quit | grep -q .; then
  echo "Embedded EDT axiom-jdk was installed unexpectedly." >&2
  exit 1
fi

mkdir -p /opt/1C/1CE/components

edtcli_dir="$(find /opt/1C/1CE -name 1cedtcli -type f -exec dirname {} \; | head -1 || true)"
if [ -z "$edtcli_dir" ]; then
  echo "1cedtcli was not found after EDT install." >&2
  exit 1
fi
ln -sfn "$edtcli_dir" /opt/1C/1CE/components/1cedtcli

if [ -n "$keep_platform_versions" ]; then
  # Remove platform support older than the target platform to keep the image slim.
  support_workspace="$work/platform-support-workspace"
  mkdir -p "$support_workspace"
  "$edtcli_dir/1cedtcli" -data "$support_workspace" -timeout 600 -command version >/dev/null
  echo "EDT platform support minimum version to keep: $keep_platform_versions"
  platform_versions_output="$("$edtcli_dir/1cedtcli" -data "$support_workspace" -timeout 600 -command platform-versions 2>&1)"
  mapfile -t platform_versions < <(
    printf '%s\n' "$platform_versions_output" \
      | sed -n 's/^\([0-9][0-9]*\.[0-9][0-9]*\(\.[0-9][0-9]*\)*\)$/\1/p'
  )
  echo "Installed EDT platform support versions:"
  if [ "${#platform_versions[@]}" -eq 0 ]; then
    echo "<none>"
  else
    printf '%s\n' "${platform_versions[@]}"
  fi

  for platform_version in "${platform_versions[@]}"; do
    if [ "$platform_version" = "$keep_platform_versions" ]; then
      echo "Keep EDT platform support $platform_version"
      continue
    elif printf '%s\n%s\n' "$platform_version" "$keep_platform_versions" | sort -VC; then
      echo "Remove EDT platform support $platform_version"
    else
      echo "Keep EDT platform support $platform_version"
      continue
    fi
    "$edtcli_dir/1cedtcli" -data "$support_workspace" -timeout 600 \
      -command uninstall-platform-support --version "$platform_version"
  done
fi

if [ -n "${JAVA_HOME:-}" ] && [ -d "$JAVA_HOME" ]; then
  ln -sfn "$JAVA_HOME" /opt/1C/1CE/jre
fi

rm -rf "$work"
echo "Installed 1C:EDT at: $edtcli_dir"
