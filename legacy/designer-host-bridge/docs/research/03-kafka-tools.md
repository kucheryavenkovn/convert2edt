# Исследование: ShadobaAI/kafka-tools — Docker runtime для 1С

**Источник:** https://github.com/ShadobaAI/kafka-tools, `master`.
**Дата исследования:** 2026-09-09.

## Краткий вывод

Заявление подтверждается: в репозитории есть полноценные CI-образы для 1С (**ibcmd, 1cedtcli/EDT, OneScript, JRE 17, vanessa-runner, Coverage41C**), и они **реально опубликованы в ghcr.io с анонимным pull** (проверено запросами к registry). Путь в README устарел: фактически всё живёт в `.github/ci-images/`.

## Структура

```
.github/
├── ci-images/
│   ├── distr/.gitkeep                # закрытые дистрибутивы (локально)
│   ├── docker/
│   │   ├── Dockerfile                # единственный 1С-Dockerfile, multi-stage
│   │   └── scripts/
│   │       ├── install-edt.sh
│   │       ├── install-platform.sh
│   │       └── install-oscript.sh
│   ├── images.yml                    # registry, profiles, теги
│   └── scripts/
│       ├── build_image.py            # оркестратор buildx (named contexts)
│       ├── download_distribution.py  # скачивание с releases.1c.ru
│       └── cleanup_ghcr.py
├── actions/ (edt2xml, xml2cf, package-zip)
└── workflows/ (build-ci-images.yml, release-1c-artifacts.yml)
```

## Dockerfile (multi-stage, `debian:bookworm-slim`)

Стадии: `runtime-base` → `edt-runtime-base` (openjdk-17-jre-headless, gtk) и `platform-runtime-base` (libgssapi-krb5-2, libicu72, libgsf, unixodbc, ru_RU.UTF-8) → installer-стадии → финальные `edtcli`, `ibcmd`, `client`.

**ARG:** `BASE_IMAGE`, `EDT_VERSION`, `EDT_PLATFORM_SUPPORT`, `PLATFORM_VERSION`, `PLATFORM_COMPONENTS` (`server` для ibcmd-образа; `client_thin,server,ru` для client), `REVISION`.

**ENV / пути:**
- Платформа: deb-пакеты (`dpkg -i 1c-enterprise*-{common,server}_*.deb`) или `setup-full-*.run --mode unattended`; симлинк `/opt/1cv8/current`; `PATH=/opt/1cv8/current:...`
- EDT: `/opt/1C/1CE`, `PATH=/opt/1C/1CE/components/1cedtcli:...`; JRE — системный OpenJDK 17 (`JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64`); bundled axiom-jdk запрещён.
- OneScript: `/opt/oscript`, `OSCRIPTBIN=/opt/oscript/bin`, `systemLanguage = ru`.
- Ring входит в состав установки EDT (`/opt/1C/1CE/components/ring`), в PATH не выносится.
- **git/ssh в образы НЕ ставятся.**
- `WORKDIR /work`, локаль ru_RU.UTF-8.

## Публикация в registry

`ghcr.io`, публичный анонимный pull (проверено):

| Образ | Состав (labels) | Размер |
|---|---|---|
| `ghcr.io/shadobaai/edtcli:latest` | EDT **2026.1.2** | ~1.67 GB |
| `ghcr.io/shadobaai/ibcmd:latest` | платформа **8.5.1.1423** (common+server) | ~0.97 GB |
| `ghcr.io/shadobaai/client:latest` | платформа 8.5.1.1423 + Coverage41C + Xvfb | ~1.98 GB |

Тег только `latest` (старые версии удаляются). Для воспроизводимости пиновать по digest или собирать своё.

## Как скачиваются дистрибутивы

`download_distribution.py`:
- Платформа и EDT — с **releases.1c.ru** по логину/паролю портала (секреты `RELEASES_ONEC_USERNAME` / `RELEASES_ONEC_PASSWORD`). Парсинг HTML login-формы, страница `version_files?nick=PlatformXX&ver=...`, короткая версия `8.3.27` → полный релиз, ищутся `deb64_*.zip` / `server64_*.zip` / `1c_edt_distr_offline_*_linux_x86_64.tar.gz`.
- OneScript — публично, `oscript.io/api/archive/<token>`.
- Дистрибутивы подаются в buildx через **BuildKit named contexts** (`--build-context distr=...`) — не попадают в финальные слои.

## gitsync

В репозитории **нет** ничего про gitsync/хранилище. CI-пайплайн — только EDT → XML → ibcmd → CF/CFE.

## Оценка переиспользования

1. **Напрямую `FROM ghcr.io/shadobaai/ibcmd:latest` не подходит:**
   - там платформа **8.5.1**, а нам нужна **8.3.27**;
   - в ibcmd-образе нет **толстого клиента** (`PLATFORM_COMPONENTS=server`), а gitsync работает с хранилищем только через `1cv8` DESIGNER;
   - нет git/ssh/gitsync.
2. **Как референс — отличный:** multi-stage с изоляцией закрытых дистрибутивов, install-скрипты, чистка мусора, `1cedtcli uninstall-platform-support` для старых platform-support, авторизация на releases.1c.ru.
3. **Решение:** собирать собственный образ по их схеме (их Dockerfile + скрипты как основа), с `PLATFORM_VERSION=8.3.27.xxxx`, `PLATFORM_COMPONENTS=common,server,client,ru` (нужен толстый клиент + ibcmd), плюс EDT + OneScript + gitsync + git + ssh. Для сборки нужны дистрибутивы 8.3.27 (логин releases.1c.ru или локально скачанные deb-архивы).
4. Юридический нюанс: образы с проприетарными дистрибутивами 1С нельзя публиковать публично; свой registry — только приватный.
