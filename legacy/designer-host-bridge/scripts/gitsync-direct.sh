#!/usr/bin/env bash
# Прямой вызов gitsync (экспертный режим). Окружение GITSYNC_* настраивается из lib.
set -euo pipefail
source /opt/converter/lib.sh
setup_ssh
setup_gitsync_env
setup_storage_auth
exec gitsync "$@"
