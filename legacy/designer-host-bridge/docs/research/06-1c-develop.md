# Исследование: mussolene/1c-develop

**Источник:** https://github.com/mussolene/1c-develop, HEAD `fd6417d` (клон в temp).
**Дата исследования:** 2026-09-09. Факты — из кода, не README.

## 1. Структура (слои образов)

```
base/linux-common/Dockerfile   — python:3.12-slim-bookworm + msttcorefonts, ru_RU.UTF-8, gosu
base/linux-desktop/Dockerfile  — Xfce4, TigerVNC (Xvnc), Xvfb, xrdp+xorgxrdp, s6-overlay v1.21.8.0
client/Dockerfile              — образ 1c-developer: платформа 1С + OneScript + Vanessa + s6-сервисы
docker-compose.yml             — 4 сервиса (+ profile build), external volume onec-license-store
scripts/download-platform.sh   — скачивание платформы с releases.1c.ru по ITS-логину
scripts/prepare-platform.sh    — staging setup-full-*.run из server64_with_all_clients_*.zip
artifacts/client-vnc/rootfs    — s6-сервисы (xvfb=Xvnc, xfce, xrdp, onec), fix-attrs
artifacts/scripts/createsymlink-current.sh — /opt/1cv8/current
```

Entrypoint — `ENTRYPOINT ["/init"]` (s6-overlay).

## 2. Установка платформы

- Источник: releases.1c.ru (ITS-логин), nick `8.3.27.x → Platform83`, кандидаты имён:
  `server64_with_all_clients_<ver>.zip`, `server64_with_clients_*.zip`, `server64_*.tar.gz`, `deb64_*.tar.gz|.zip`; локальный кэш `.local/1c/platform/`; можно `PLATFORM_DIST_NAME` или прямой `PLATFORM_DOWNLOAD_URL`.
- Установка `client/Dockerfile:79-164`: staging через bind-mount →
  - deb-путь: `apt-get install *-common, *-common-nls, *-server, *-server-nls, *-client, *-client-nls` (thin/web client исключены);
  - setup-full-путь: `--mode unattended --enable-components client_full,desktop_icons,server,ws,server_admin,additional_admin_functions,ru`.
- `ARG/ENV PLATFORM_VERSION` (default 8.5.1.1343). Проверка после установки: `1cv8, 1cv8c, ragent, rmngr, ras` + `uiproxywx.so`, `ldd` без `not found`.
- Layout: `/opt/1cv8/x86_64/<версия>/` + `/opt/1cv8/common/1cestart` + symlink `/opt/1cv8/current`.

## 3. Теги в ghcr.io/mussolene (проверено запросами к registry)

| Образ | Теги |
|---|---|
| `1c-developer` | **8.5.1.1302, 8.5.1.1343, latest** |
| `linux-desktop-base`, `linux-common-base` | bookworm, latest, 8.5.1.1302, 8.5.1.1343 |
| `postgresql` | 17.7-1.1C |
| `1c82-platform` | 8.2.19.130 (wine) |

**8.3.27.x НЕТ** → платформенный слой собираем сами на `linux-desktop-base:bookworm`.

## 4. Пользователь

`usr1cv8` создаёт постинсталлер 1С (uid не закреплён). `HOME=/home/usr1cv8` (+ `.1cv8/1C/1cv8/conf/logcfg.xml`). Права: `/var/log/1C`, `/home/usr1cv8` → `usr1cv8:grp1cv8`; **`/var/1C/licenses` → `root:grp1cv8`, mode 775** (лицензию читает группа). Desktop-пользователь Xfce: `usr1cv8` (fallback root).

## 5. VNC/RDP

`xfce4`, `tigervnc-standalone-server` (Xvnc на :0, `-rfbport 5900 -SecurityTypes None -localhost no`), `xvfb`, `xrdp`. **Пароля VNC нет** — безопасность только публикацией портов на `127.0.0.1` (compose: `127.0.0.1:5900:5900`, `127.0.0.1:3389:3389`).

## 6. Лицензирование

- `onec-license-store:/var/1C/licenses` — external volume; активация **только ручная через GUI** (скриптов активации нет).
- `UseHwLicenses=1` пишется при старте в `1cestart.cfg` для root и usr1cv8.
- `nethasp.ini`: ro-маунт в `/opt/1cv8/conf/nethasp.ini`, при старте синхронизируется в 5 путей (включая профили root/usr1cv8).
- `ONEC_RUNTIME_MODE` (s6-сервис `onec/run`): `shell` (дефолт), **`license-ui`** (`1cv8c` от usr1cv8 — UI активации), `file-db`, `server`.
- `DisableUnsafeActionProtection` пишется в conf.cfg всех профилей.

## 7. OneScript

Версия **2.0.1/2.0.2** (zip EvilBeaver/OneScript → `/opt/onescript`, врапперы `/usr/local/bin/oscript|opm`). Плюс vanessa-runner/vanessa-automation через opm.
**Проблема:** CI gitsync тестируется на OneScript 1.9.2; совместимость gitsync 3.8.0 с 2.x не гарантирована → в нашем слое ставим onescript-engine 1.9.3 (deb) и переключаем врапперы на него.

## 8. EDT / gitsync

В репозитории отсутствуют (0 совпадений). EDT добавляем сами (install-edt.sh из docs/research/03,04: offline-дистрибутив + 1ce-installer-cli, platform-support только 8.3.27, системный OpenJDK 17, EDT в /opt/1C/1CE/components/1c-edt-* для edtfind).

## 9. Compose хосты/сеть

`hostname onecdev`, статический IP 172.16.1.2 — вероятно для стабильности identity лицензии. Для нашего стека: фиксированный `hostname` (+ возможно `mac_address`) одинаков для license-ui и converter, т.к. software license привязывается к параметрам окружения.

## 10. Активация (подтверждено README/docs)

```
docker exec -d -u usr1cv8 -e DISPLAY=:0 <container> /opt/1cv8/current/1cv8c
```
или `ONEC_RUNTIME_MODE=license-ui`. далее вручную через UI 1С → активация Developer License → файлы в `/var/1C/licenses`.

## Выводы для нашего образа

1. База: `ghcr.io/mussolene/linux-desktop-base:bookworm` (готовые Xfce/VNC/s6/шрифты/локаль).
2. Платформа 8.3.27: свой слой (наш `install-platform.sh`, компоненты `client_full`-аналогично: thick client + server + ru) — дистрибутив от пользователя через named context `distr`.
3. `usr1cv8` создаётся установщиком; лицензии `/var/1C/licenses` root:grp1cv8 775.
4. license-ui: их механизм `ONEC_RUNTIME_MODE=license-ui` + s6 + VNC 127.0.0.1.
5. converter: тот же образ, но наш entrypoint (без s6-сервисов), headless DESIGNER от usr1cv8.
6. OneScript 1.9.3 + gitsync + plugins; EDT 2026.2.0 offline.
