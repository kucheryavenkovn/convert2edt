#!/usr/bin/env bash
# Общие функции конвейера. Подключается из entrypoint/doctor/sync/migrate.
# Выполняется от пользователя usr1cv8 (entrypoint делает gosu).

RUN_USER=usr1cv8
RUN_HOME=/home/usr1cv8

log()  { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# --- Параметры окружения ------------------------------------------------------
: "${STORAGE_PATH:=/storage}"
: "${REPO_DIR:=/repo}"
: "${CACHE_DIR:=/cache}"
: "${STATE_DIR:=/state}"
: "${CONFIG_DIR:=/config}"
: "${GIT_BRANCH:=main}"
: "${PROJECT_NAME:=}"
: "${STORAGE_USER:=Администратор}"
: "${STORAGE_PASSWORD_FILE:=/run/secrets/storage_password}"
: "${GIT_SSH_KEY_FILE:=/run/secrets/git_ssh_key}"
# Вариант B (Host Bridge): BRIDGE_URL задан → 1cv8 выполняется на Windows через wrapper.
: "${BRIDGE_URL:=}"
: "${BRIDGE_TOKEN_FILE:=/run/secrets/bridge_token}"
: "${BRIDGE_DOCKER_ROOT:=/bridge}"

bridge_mode() { [ -n "$BRIDGE_URL" ]; }

setup_bridge_auth() {
  if [ -f "$BRIDGE_TOKEN_FILE" ]; then
    BRIDGE_TOKEN="$(cat "$BRIDGE_TOKEN_FILE")"
    export BRIDGE_TOKEN
  fi
}

# Путь к wrapper-«1cv8» (симлинк в каталоге версии — v8runner берёт версию из пути).
wrapper_1cv8_path() {
  find /opt/1cv8/x86_64 -mindepth 2 -maxdepth 2 \( -type f -o -type l \) -name 1cv8 2>/dev/null | sort -V | tail -1
}

require_env() {
  local name="$1"
  [ -n "${!name:-}" ] || die "Не задана обязательная переменная окружения: $name"
}

# PROJECT_PATH обязан быть относительным путём внутри репозитория.
validate_project_path() {
  require_env PROJECT_PATH
  case "$PROJECT_PATH" in
    ""|/*|.|..|*../*|*/..|*/../*)
      die "PROJECT_PATH должен быть относительным путём внутри git-репозитория без '..': '${PROJECT_PATH}'" ;;
  esac
}

workdir_path() { printf '%s/%s' "$REPO_DIR" "$PROJECT_PATH"; }

# --- SSH для git (дом usr1cv8) -------------------------------------------------
setup_ssh() {
  local ssh_dir="$RUN_HOME/.ssh"
  mkdir -p "$ssh_dir"
  chmod 700 "$ssh_dir"
  local opts="-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$ssh_dir/known_hosts"
  if [ -f "$GIT_SSH_KEY_FILE" ]; then
    cp "$GIT_SSH_KEY_FILE" "$ssh_dir/id_converter"
    chmod 600 "$ssh_dir/id_converter"
    opts="-i $ssh_dir/id_converter $opts"
  fi
  export GIT_SSH_COMMAND="ssh $opts"
}

# --- Пароль хранилища ----------------------------------------------------------
setup_storage_auth() {
  export GITSYNC_STORAGE_USER="$STORAGE_USER"
  if [ -f "$STORAGE_PASSWORD_FILE" ]; then
    GITSYNC_STORAGE_PASSWORD="$(cat "$STORAGE_PASSWORD_FILE")"
    export GITSYNC_STORAGE_PASSWORD
  fi
}

# --- Служебный clone репозитория ----------------------------------------------
repo_prepare() {
  require_env GIT_REMOTE
  if [ -d "$REPO_DIR/.git" ]; then
    log "Служебный clone: fetch + checkout $GIT_BRANCH + pull --ff-only"
    git -C "$REPO_DIR" fetch --prune origin
    git -C "$REPO_DIR" checkout "$GIT_BRANCH"
    git -C "$REPO_DIR" pull --ff-only origin "$GIT_BRANCH"
  else
    if [ -n "$(ls -A "$REPO_DIR" 2>/dev/null || true)" ]; then
      die "$REPO_DIR не пуст, но не является git-репозиторием. Очистите volume repo-cache."
    fi
    log "Первичный clone $GIT_REMOTE ($GIT_BRANCH) -> $REPO_DIR"
    git clone --branch "$GIT_BRANCH" --single-branch "$GIT_REMOTE" "$REPO_DIR"
  fi
  git -C "$REPO_DIR" config core.quotepath false
}

# WORKDIR внутри корневого репозитория /repo; вложенного .git нет.
ensure_workdir() {
  validate_project_path
  local wd; wd="$(workdir_path)"
  mkdir -p "$wd"
  local top
  top="$(git -C "$wd" rev-parse --show-toplevel 2>/dev/null)" \
    || die "$wd не находится внутри git-репозитория $REPO_DIR"
  local real_top real_repo
  real_top="$(cd "$top" && pwd -P)"
  real_repo="$(cd "$REPO_DIR" && pwd -P)"
  [ "$real_top" = "$real_repo" ] \
    || die "WORKDIR $wd принадлежит другому репозиторию ($real_top), ожидался $real_repo"
  [ ! -e "$wd/.git" ] || die "В WORKDIR $wd обнаружен вложенный .git — запрещено (monorepo)"
  printf '%s' "$wd"
}

# --- Контроль изоляции PROJECT_PATH --------------------------------------------
check_isolation() {
  local before="$1" after="$2"
  [ "$before" = "$after" ] && return 0
  local bad
  bad="$(git -C "$REPO_DIR" diff --name-only "$before" "$after" \
        | grep -v "^${PROJECT_PATH}/" || true)"
  if [ -n "$bad" ]; then
    printf 'КРИТИЧЕСКАЯ ОШИБКА: коммиты содержат изменения вне %s:\n%s\n' "$PROJECT_PATH" "$bad" >&2
    printf 'Push отменён. Служебный clone: %s\n' "$REPO_DIR" >&2
    return 1
  fi
}

# --- Окружение gitsync ----------------------------------------------------------
setup_gitsync_env() {
  export GITSYNC_STORAGE_PATH="$STORAGE_PATH"
  export GITSYNC_WORKDIR="$(workdir_path)"
  export GITSYNC_V8VERSION="${ONEC_VERSION_MASK:-8.3}"
  export GITSYNC_DOMAIN_EMAIL="${DOMAIN_EMAIL:-localhost}"

  if bridge_mode; then
    # 1cv8 — wrapper к Host Bridge; всё временное (ИБ v8r_TempDB, /Out, mxl-отчёты)
    # обязано лежать в общем staging /bridge, чтобы Windows-1cv8 и Linux-ibcmd видели одни файлы.
    setup_bridge_auth
    local wp; wp="$(wrapper_1cv8_path)"
    [ -n "$wp" ] || die "wrapper 1cv8 не найден в /opt/1cv8/x86_64/*/1cv8 (образ собран без Dockerfile.bridge?)"
    export GITSYNC_V8_PATH="$wp"
    export GITSYNC_TEMP="$BRIDGE_DOCKER_ROOT/gitsync-temp"
    log "bridge mode: BRIDGE_URL=$BRIDGE_URL V8_PATH=$wp TEMP=$GITSYNC_TEMP"
  else
    export GITSYNC_TEMP="$CACHE_DIR/gitsync-temp"
  fi

  # edtExport
  export GITSYNC_PROJECT_NAME="${PROJECT_NAME:-$(basename "$PROJECT_PATH")}"
  export GITSYNC_WORKSPACE_LOCATION="$CACHE_DIR/edt-workspace"
  [ -n "${EDT_VERSION:-}" ] && export GITSYNC_EDT_VERSION="$EDT_VERSION"

  # use-ibcmd
  export GITSYNC_IBCMD_DATA="$CACHE_DIR/ibcmd-data"
  export GITSYNC_IBCMD_THREADS="${IBCMD_THREADS:-0}"
  if [ "${INCREMENTAL:-true}" = "true" ]; then
    export GITSYNC_IBCMD_INCREMENT=true
  else
    export GITSYNC_IBCMD_INCREMENT=false
  fi

  mkdir -p "$GITSYNC_TEMP" "$GITSYNC_WORKSPACE_LOCATION" "$GITSYNC_IBCMD_DATA" 2>/dev/null || true
}

# Маркеры EDT-проекта после конвертации.
verify_edt_project() {
  local wd; wd="$(workdir_path)"
  local ok=0
  { [ -f "$wd/DT-INF/PROJECT.PMF" ] || [ -f "$wd/src/Configuration/Configuration.mdo" ]; } && ok=1
  [ "$ok" = "1" ] || die "$wd не похож на проект EDT (нет DT-INF/PROJECT.PMF или src/Configuration/Configuration.mdo)"
}

# Один прогон gitsync sync. Глобальные: SYNC_HEAD_BEFORE/SYNC_HEAD_AFTER.
run_gitsync_sync() {
  local wd; wd="$(ensure_workdir)"
  setup_gitsync_env
  setup_storage_auth

  if [ ! -f "$wd/VERSION" ]; then
    log "Первый запуск: gitsync init (создание VERSION/AUTHORS)"
    gitsync init "$STORAGE_PATH" "$wd"
  fi

  # AUTHORS из /config приоритетнее сгенерированного gitsync init.
  if [ -f "$CONFIG_DIR/AUTHORS" ]; then
    cp "$CONFIG_DIR/AUTHORS" "$wd/AUTHORS"
  elif [ ! -f "$wd/AUTHORS" ]; then
    log "ПРЕДУПРЕЖДЕНИЕ: нет $CONFIG_DIR/AUTHORS; используется AUTHORS из gitsync init."
    log "Скопируйте config/AUTHORS.example -> config/AUTHORS и сопоставьте авторов хранилища."
  fi

  SYNC_HEAD_BEFORE="$(git -C "$REPO_DIR" rev-parse HEAD)"

  log "gitsync sync: $STORAGE_PATH -> $wd"
  gitsync sync --disable-auto-src "$STORAGE_PATH" "$wd"

  SYNC_HEAD_AFTER="$(git -C "$REPO_DIR" rev-parse HEAD)"
}

push_repo() {
  log "git push origin $GIT_BRANCH"
  git -C "$REPO_DIR" push origin "$GIT_BRANCH"
}

# Полный цикл одной партии: clone/update -> gitsync -> проверки -> push.
# Возврат: 0 = были коммиты (запушено), 1 = новых версий нет, при ошибке die/fail.
sync_one_batch() {
  setup_ssh
  repo_prepare
  run_gitsync_sync

  if [ "$SYNC_HEAD_BEFORE" = "$SYNC_HEAD_AFTER" ]; then
    log "Новых версий хранилища нет — 0 коммитов."
    return 1
  fi

  check_isolation "$SYNC_HEAD_BEFORE" "$SYNC_HEAD_AFTER" \
    || die "Обнаружены изменения вне PROJECT_PATH=$PROJECT_PATH. Push отменён."
  verify_edt_project
  push_repo
  return 0
}

# --- Версия платформы контейнера -----------------------------------------------
container_platform_version() {
  local dir
  dir="$(find /opt/1cv8 -mindepth 3 -maxdepth 3 -type d -regex '.*/x86_64/[0-9][0-9.]*' 2>/dev/null | sort -V | tail -1)"
  [ -n "$dir" ] && basename "$dir"
}

# Версия из файла ver хранилища: {0,2,8,3,27,2325,"Designer"} -> 8.3.27.2325
storage_platform_version() {
  local ver="$STORAGE_PATH/ver" line nums
  [ -f "$ver" ] || return 1
  line="$(tr -d '\0' < "$ver" | tr ',' ' ')"
  nums="$(printf '%s' "$line" | grep -oE '[0-9]+' | tr '\n' ' ')"
  set -- $nums
  # формат: 0 2 8 3 27 2325 -> берем 8.3.27.2325 (с 3-го числа)
  if [ "$#" -ge 6 ]; then
    printf '%s.%s.%s.%s' "$3" "$4" "$5" "$6"
  else
    return 1
  fi
}

# --- Лицензии -------------------------------------------------------------------
license_files_count() {
  find /var/1C/licenses -maxdepth 1 -type f -name '*.lic' 2>/dev/null | wc -l
}

# Реальный smoke: создание временной файловой ИБ тем же способом, что и
# v8runner внутри gitsync (CREATEINFOBASE). Конфигуратор без лицензии падает
# с ошибкой лицензирования в /Out — это и проверяем.
license_smoke_test() {
  local tmp="$CACHE_DIR/doctor-license-smoke"
  rm -rf "$tmp"; mkdir -p "$tmp"
  local out="$tmp/out.txt"
  timeout 300 /opt/1cv8/current/1cv8 CREATEINFOBASE "File=$tmp/ib" /Out "$out" >/dev/null 2>&1
  local code=$?
  local bad=""
  [ -f "$out" ] && bad="$(grep -iE 'лиценз|license|ключ' "$out" | head -3 | tr '\n' ' ' || true)"
  if [ "$code" -ne 0 ] || [ -n "$bad" ]; then
    printf 'exitCode=%s; %s (подробности: %s)\n' "$code" "${bad:-нет деталей в /Out}" "$out" >&2
    return 1
  fi
  rm -rf "$tmp"
  return 0
}
