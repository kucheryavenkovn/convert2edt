#!/usr/bin/env bash
# Диагностика конвейера. Выполняется от usr1cv8 (см. entrypoint).
set -uo pipefail
source /opt/converter/lib.sh

PASS=0; FAIL=0
ok()   { printf '[PASS] %s\n' "$1"; PASS=$((PASS + 1)); }
bad()  { printf '[FAIL] %s\n' "$1"; FAIL=$((FAIL + 1)); }
info() { printf '       %s\n' "$1"; }

# --- 1. oscript -----------------------------------------------------------------
if timeout 60 oscript -version >/dev/null 2>&1; then
  ok "oscript $(oscript -version 2>/dev/null | head -1)"
else
  bad "oscript"
fi

# --- 2. gitsync -----------------------------------------------------------------
if timeout 60 gitsync usage >/dev/null 2>&1; then
  ok "gitsync"
else
  bad "gitsync (gitsync usage)"
fi

# --- 3. gitsync plugins -----------------------------------------------------------
plugins_out="$(timeout 60 gitsync plugins list 2>/dev/null || true)"
missing_plugins=""
for p in use-ibcmd edtExport limit check-authors; do
  printf '%s' "$plugins_out" | grep -qi "$p" || missing_plugins="$missing_plugins $p"
done
if [ -z "$missing_plugins" ]; then
  ok "gitsync plugins (use-ibcmd, edtExport, limit, check-authors включены)"
else
  bad "gitsync plugins: не включены:$missing_plugins"
  info "GITSYNC_PLUGINS_PATH=$GITSYNC_PLUGINS_PATH"
fi

# --- 4. git / ssh -----------------------------------------------------------------
if git --version >/dev/null 2>&1; then ok "git $(git --version | awk '{print $3}')"; else bad "git"; fi
if ssh -V 2>&1 | grep -q OpenSSH; then ok "ssh ($(ssh -V 2>&1 | head -1))"; else bad "ssh"; fi

# --- 5. 1cv8: локальный (вариант A) или wrapper к Host Bridge (вариант B) --------
plat_ver="$(container_platform_version)"
if bridge_mode; then
  wp="$(wrapper_1cv8_path)"
  if [ -n "$wp" ] && [ -x "$wp" ]; then
    ok "1cv8 wrapper (Host Bridge): $wp"
  else
    bad "1cv8 wrapper не найден в /opt/1cv8/x86_64/*/1cv8"
  fi
  setup_bridge_auth
  health="$(timeout 360 curl -fsS ${BRIDGE_TOKEN:+-H "Authorization: Bearer $BRIDGE_TOKEN"} "$BRIDGE_URL/health" 2>/dev/null || true)"
  if [ -n "$health" ]; then
    h_status="$(printf '%s' "$health" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("status",""))' 2>/dev/null || true)"
    h_platform="$(printf '%s' "$health" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("platform",""))' 2>/dev/null || true)"
    h_license="$(printf '%s' "$health" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("licenseCheck",""))' 2>/dev/null || true)"
    h_storage="$(printf '%s' "$health" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("storageAccess",""))' 2>/dev/null || true)"
    if [ "$h_status" = "ok" ]; then ok "Host Bridge health (platform=$h_platform)"; else bad "Host Bridge health: status=$h_status"; fi
    if [ "$h_license" = "ok" ]; then ok "Host Bridge licenseCheck (реальный smoke на Windows)"; else bad "Host Bridge licenseCheck=$h_license"; fi
    if [ "$h_storage" = "ok" ]; then ok "Host Bridge storageAccess"; else bad "Host Bridge storageAccess=$h_storage"; fi
  else
    bad "Host Bridge недоступен: $BRIDGE_URL/health (проверьте сервис, токен, firewall)"
  fi
else
  if [ -n "$plat_ver" ] && [ -x "/opt/1cv8/x86_64/$plat_ver/1cv8" ]; then
    ok "1cv8 executable ($plat_ver)"
  else
    bad "1cv8 executable (не найден в /opt/1cv8/x86_64/*/1cv8)"
  fi
fi

# --- 6. ibcmd -----------------------------------------------------------------------
if [ -n "$plat_ver" ] && [ -x "/opt/1cv8/x86_64/$plat_ver/ibcmd" ]; then
  ok "ibcmd executable ($plat_ver)"
else
  bad "ibcmd executable"
fi

# --- 7. 1cedtcli ----------------------------------------------------------------------
edt_dir=""
for d in /opt/1C/1CE/components/1c-edt-*-x86_64; do
  if [ -x "$d/1cedtcli" ]; then edt_dir="$d"; break; fi
done
if [ -n "$edt_dir" ]; then
  ws="$(mktemp -d)"
  edt_ver_out="$(timeout 600 "$edt_dir/1cedtcli" -data "$ws" -timeout 300 -command version 2>/dev/null | tail -1 || true)"
  rm -rf "$ws"
  if [ -n "$edt_ver_out" ]; then
    ok "1cedtcli ($edt_ver_out)"
  else
    bad "1cedtcli: не удалось выполнить -command version"
  fi
else
  bad "1cedtcli (нет /opt/1C/1CE/components/1c-edt-*-x86_64/1cedtcli)"
fi

# --- 8. Java ----------------------------------------------------------------------------
if java -version >/dev/null 2>&1; then ok "java ($(java -version 2>&1 | head -1))"; else bad "java"; fi

# --- 9-10. Лицензии: локальный volume (A) или уже проверено через bridge /health (B)
if ! bridge_mode; then
  lic_mount_info="$(grep ' /var/1C/licenses ' /proc/mounts || true)"
  lic_count="$(license_files_count)"
  if [ -d /var/1C/licenses ]; then
    if [ -n "$lic_mount_info" ]; then
      ok "/var/1C/licenses mounted (volume onec-license-store)"
    else
      bad "/var/1C/licenses НЕ является смонтированным volume (лицензия потеряется при пересоздании контейнера)"
    fi
    if [ "$lic_count" -gt 0 ]; then
      ok "файлы лицензии обнаружены ($lic_count шт.)"
    else
      bad "файлов лицензии (*.lic) нет — выполните активацию через license-ui"
    fi
  else
    bad "/var/1C/licenses отсутствует"
  fi

  if [ -n "$plat_ver" ]; then
    smoke_msg="$(license_smoke_test 2>&1)"
    smoke_code=$?
    if [ "$smoke_code" -eq 0 ]; then
      ok "1C runtime licensing smoke test (CREATEINFOBASE)"
    else
      bad "1C runtime licensing smoke test: ${smoke_msg:-см. /cache/doctor-license-smoke}"
    fi
  fi
fi

# --- 11. Хранилище ---------------------------------------------------------------------------
if [ -f "$STORAGE_PATH/1cv8ddb.1CD" ] || [ -f "$STORAGE_PATH/1cv8ddb.1cd" ]; then
  ok "storage available ($STORAGE_PATH)"
else
  bad "storage: не найдено хранилище 1С в $STORAGE_PATH (нет 1cv8ddb.1CD)"
fi
stor_ver="$(storage_platform_version || true)"
if [ -n "$stor_ver" ] && [ -n "$plat_ver" ]; then
  newer="$(printf '%s\n%s\n' "$plat_ver" "$stor_ver" | sort -V | tail -1)"
  if [ "$newer" = "$plat_ver" ] || [ "$plat_ver" = "$stor_ver" ]; then
    ok "платформа контейнера ($plat_ver) >= версии хранилища ($stor_ver)"
  else
    bad "платформа контейнера ($plat_ver) МЛАДШЕ версии хранилища ($stor_ver) — пересоберите образ"
  fi
fi

# --- 12. Git remote -----------------------------------------------------------------------------
if [ -n "${GIT_REMOTE:-}" ]; then
  setup_ssh
  if timeout 60 git ls-remote --heads "$GIT_REMOTE" >/dev/null 2>&1; then
    ok "Git remote available ($GIT_REMOTE)"
  else
    bad "Git remote недоступен: $GIT_REMOTE (проверьте git_ssh_key и сеть)"
  fi
else
  bad "GIT_REMOTE не задан"
fi

# --- 13. PROJECT_PATH внутри корневого репозитория ------------------------------------------------
if [ -n "${PROJECT_PATH:-}" ]; then
  validate_ok=1
  validate_project_path >/dev/null 2>&1 || validate_ok=0
  if [ "$validate_ok" = "1" ]; then
    ok "PROJECT_PATH синтаксис корректен ($PROJECT_PATH)"
    if ( repo_prepare ) >/dev/null 2>&1; then
      wd="$(ensure_workdir 2>/dev/null || true)"
      if [ -n "$wd" ]; then
        ok "/repo/$PROJECT_PATH внутри корневого git-репозитория (вложенного .git нет)"
      else
        bad "не удалось проверить WORKDIR /repo/$PROJECT_PATH"
      fi
    else
      bad "не удалось подготовить служебный clone /repo (см. ошибки выше)"
    fi
  else
    bad "PROJECT_PATH некорректен: $PROJECT_PATH"
  fi
else
  bad "PROJECT_PATH не задан"
fi

# --- Итог -----------------------------------------------------------------------------------------
echo
if [ "$FAIL" -gt 0 ]; then
  printf 'DOCTOR: %s PASS, %s FAIL\n' "$PASS" "$FAIL"
  exit 1
fi
printf 'DOCTOR: все проверки пройдены (%s PASS)\n' "$PASS"
