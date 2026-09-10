# 1C CONVERTER

Конвертация конфигураций 1С целиком внутри Linux Docker — официальными
инструментами, без Windows, без DESIGNER, без Host Bridge:

```
                      1C CONVERTER

            ┌──────────────────────────────┐
            │         Linux Docker         │
            │                              │
            │   ibcmd          1cedtcli    │
            │     │               │        │
            │     └───── XML ──────┘       │
            │                              │
            │    thin orchestrator         │
            │    (Python: 1c-convert)      │
            └──────────────────────────────┘

                 ↙        ↓        ↘
               CF        XML       EDT
               (ИБ: file — сейчас, client/server — архитектурно готово)
```

> Логика преобразования основана на подходах, уже реализованных в
> [arkuznetsov/1CFilesConverter](https://github.com/arkuznetsov/1CFilesConverter).
> Docker-сборка основана на проверенных подходах из
> [ShadobaAI/kafka-tools](https://github.com/ShadobaAI/kafka-tools).
> Проект не реализует собственные парсеры форматов 1С и использует официальные
> `ibcmd` и `1cedtcli`.

## Состав образа (дерево зависимостей)

```
convert2edt/converter:latest          (Dockerfile, compose.yaml)
│
├── debian:bookworm-slim ............... базовый образ (ARG BASE_IMAGE)
│     └── java-17-openjdk, boost 1.74, zlib, git, python3 (пакеты Debian)
│
├── 1С:Предприятие 8.3.27.2342 ......... закрытый дистрибутив (vendor/platform/)
│     └── deb: common(+nls), server(+nls) -> /opt/1cv8/current -> ibcmd
│
├── 1C:EDT 2026.1.3 offline ............ закрытый дистрибутив (vendor/edt/)
│     └── 1ce-installer-cli -> /opt/1C/1CE/components/1cedtcli -> 1cedtcli
│
├── e8tools/tool1cd @ 625ac1a (GPL-3) . собирается из исходников в builder-стадии
│     └── ctool1cd + libtool1cd.so .... чтение хранилищ конфигураций
│     └── изменения: только sed (GUI не собирается) — depot-ver100 уже в upstream (PR #295)
│
└── converter/onec_convert (наш код) ... тонкая orchestration-обвязка (Python)
      └── алгоритмы: 1CFilesConverter (пере-реализация), схема Docker: kafka-tools
```

Пины версий задаётся build-аргументами (`TOOL1CD_REF`,
`EDT_PLATFORM_SUPPORT` и др.), версии инструментов попадают в labels образа
(`onec.converter.*`). Лицензии и обязательные notice'ы — в
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

**Изменения во внешних проектах: только конфигурация сборки.**
Поддержка хранилищ расширений (depot version 100) принята в upstream —
[PR #295](https://github.com/e8tools/tool1cd/pull/295) (слит, образ собирает
vanilla upstream). Оставшаяся правка сборки:

| Проект | Изменение | Тип |
|---|---|---|
| e8tools/tool1cd | sed: GUI-поддиректория (gtool1cd) исключена из сборки | только конфигурация сборки, код не тронут |

Скрипты установки платформы/EDT адаптированы из kafka-tools (notice в
заголовках файлов), код 1CFilesConverter не копировался — вызовы
ibcmd/1cedtcli пере-реализованы на Python; из их tests взят только fixture
`1Cv8.cf`. Закрытые дистрибутивы 1С не модифицируются.

## Сценарии

| Команда | Что делает | Путь |
|---|---|---|
| `cf-to-edt` | *.cf → EDT-проект | cf → temp IB → XML → EDT |
| `edt-to-cf` | EDT-проект → *.cf | EDT → XML → temp IB → cf |
| `cf-to-xml` | *.cf → XML Конфигуратора | cf → temp IB → XML |
| `xml-to-cf` | XML → *.cf | XML → temp IB → cf |
| `xml-to-edt` | XML → EDT-проект | напрямую `1cedtcli` (без ИБ) |
| `edt-to-xml` | EDT-проект → XML | напрямую `1cedtcli` (без ИБ) |
| `ib-to-xml` | файловая ИБ → XML | `ibcmd config export` |
| `ib-to-edt` | файловая ИБ → EDT | XML → EDT |
| `storage-info` | хранилище: версии, авторы, даты, комментарии | `ctool1cd` (без платформы) |
| `storage-to-cf` | хранилище → *.cf нужной версии | `ctool1cd -drc N` |
| `storage-to-xml` | хранилище → XML версии | cf → temp IB → XML |
| `storage-to-edt` | хранилище → EDT версии | cf → temp IB → XML → EDT |
| `storage-sync` | хранилище → git-история (1 версия = 1 коммит) | весь конвейер + git |
| `dp-xml-to-edt` | XML внешних отчётов/обработок → EDT-проект | `1cedtcli import` |
| `sync-all` | всё сразу по TOML-конфигу | `sync.toml` |
| `info` | версии ibcmd / 1cedtcli / платформы | |
| `detect` | определить тип источника | |

`--sync` (инкрементальный экспорт `ibcmd config export --sync`) включается
автоматически, когда в целевом каталоге XML уже есть `Configuration.xml` +
`ConfigDumpInfo.xml` — ровно как в `1CFilesConverter`. Управление:
`--sync auto|force|off`.

EDT workspace создаётся заново на каждый запуск — как в upstream
(`1CFilesConverter`/`kafka-tools`): повторный import в «тёплый» workspace
отклоняется EDT («проект уже существует»). Workspace живёт в `cache/`
(монтируемый volume): при падении сохраняется для диагностики, при успехе
удаляется.

### Цикл по версиям (хранилище → git)

Повторный `1cedtcli import` в существующий проект EDT CLI **не поддерживает**:
падает на перезаписи бинарных ресурсов (Picture.png и т.п.), причём exit code
при этом может быть 0 — ошибка ловится нашей строгой проверкой результата.
Поэтому, как и в плагине gitsync `edtExport`, перед импортом каждой версии
каталог проекта **полностью очищается** и выполняется полный import
(VCS-каталоги вроде `.git` сохраняются). Диффы между версиями вычисляет git:
при фиксированной версии EDT вывод импорта детерминирован, поэтому в дифф
попадают только реальные изменения конфигурации.

```
для каждой версии N хранилища:
    1c-convert storage-sync <storage> <worktree>     # всё ниже — внутри
        ctool1cd -drc N            → ver-N.cf        (прямо из 1cv8ddb.1CD, без платформы)
        ibcmd: cf → temp IB → XML                   (без лицензии)
        1cedtcli: XML → EDT (очистка + полный реимпорт)
        git commit: автор/дата/комментарий версии N (из таблиц VERSIONS/USERS)
```

`storage-sync` возобновляемый: состояние (последняя синхронизированная
версия **на каждый проект**) хранится в `<worktree>/.storage-sync.json`;
повторный запуск — 0 коммитов. Проект кладётся в `<worktree>/<project-name>`
(по умолчанию `configuration`). Сопоставление авторов — файл `--authors`
формата `ИмяИзХранилища=Git Имя <email>`; без мапинга —
`Имя <slug@--domain>`.

### Хранилище расширений в тот же monorepo

Отдельное хранилище расширения синкается **в тот же worktree** отдельным
проектом:

```bash
1c-convert storage-sync /storage-ext /work/output/storage-git \
    --extension Расширение1 --project-name extension
```

```
storage-git/
├── configuration/   # EDT-проект конфигурации (хранилище /storage)
├── extension/       # EDT-проект расширения  (хранилище /storage-ext)
└── .storage-sync.json   # {"projects": {"configuration": 4, "extension": 2}}
```

Механика изоляции: каждый проект синкается только в свой каталог
(`git add -A -- <project-name>`), `ensure_git_repo` делает `git init` лишь
если `.git` отсутствует (существующая история никогда не сбрасывается),
полный реимпорт EDT очищает только `<worktree>/<project-name>` (не корень
worktree и не соседние проекты), state ведётся на каждый проект отдельно.
В EDT оба проекта в одном workspace ассоциируются сами. Маунт второго
хранилища — `EXT_STORAGE_HOST_PATH` в `.env` (→ `/storage-ext`).

Шаг расширения по версии: `ctool1cd -drc N` → temp-ИБ (дамп загружается
**как конфигурация**: `ibcmd infobase create --load=...` + `config export`
без `--extension`) → `1cedtcli import` в отдельный каталог.

> Обходной путь (зафиксирован): `ibcmd config load --extension=<имя>`
> при загрузке дампа из хранилища расширеня (depot ver 100) молча теряет
> объекты расширения (общие модули, роли) — проверено на реальном
> хранилище; XML при загрузке «как конфигурация» сохраняет все объекты и
> маркеры расширения (`ConfigurationExtensionPurpose`). Имя расширения
> (`--extension`) используется для журнала/каталога; register-имя в ИБ
> больше не применяется.

> Примечание: поддержка хранилищ расширений (depot version 100) принята
> в upstream `ctool1cd` (наш [PR #295](https://github.com/e8tools/tool1cd/pull/295));
> образ собирает vanilla upstream без патчей.

## Внешние отчёты и обработки (EPF/ERF)

Опциональный шаг синхронизации — флажок в конфиге:

```toml
[external]
enabled = true                  # false / секции нет → шаг пропускается
xml_dir = "/work/fixtures/dp-xml"   # XML-выгрузка внешних отчётов/обработок
project = "external"            # EDT-проект в worktree (накапливает обработки)
base_project = "configuration"  # базовый EDT-проект
```

Шаг: `1cedtcli import` XML-каталога → EDT-проект внешних отчётов и обработок
(`src/ExternalReports/…`, `src/ExternalDataProcessors/…`; при заданном
`base_project` — с `--base-project-name`). Обратно: `edt-to-xml`.
Известные quirks EDT 2026.1 CLI: для external-проектов `--version` обязательна
и должна быть короткой (`8.3.27`, не `8.3.27.2342`), иначе NPE — оркестратор
нормализует сам.

Ограничение (зафиксировано по результатам проверки): **бинарник .erf/.epf ↔
Designer-XML** средствами `ibcmd + 1cedtcli` в headless невозможен: CLI
импортирует/экспортирует только XML, `build` бинарник не создаёт
(автокомпиляция в `bin/` — поведение EDT IDE, см. доку «Проект внешних
отчетов и обработок»). Официальный путь с бинарником — 1cv8 DESIGNER
(`/DumpExternalDataProcessorOrReportToFiles` /
`/LoadExternalDataProcessorOrReportFromFiles`, как в upstream `dp2xml`/
`dp2epf`) — доступен через Host Bridge (см. ниже) и требует лицензию.
Поэтому: бинарник → EDT-проект = сначала получите XML (одноразовый
Designer-dump), далее всё автоматизировано.

## Деплой

| Что | Как |
|---|---|
| CF из EDT-проекта | `1c-convert edt-to-cf <project> <out.cf>` (далее штатно: ИБ, dt...) |
| CFE расширения | `1c-convert edt-to-cf` по проекту расширения выдаёт .cf контейнер |
| XML внешних обработок | `1c-convert edt-to-xml <worktree>/external <xml-dir>` |
| push | git на вашей стороне (`sync-all` не пушит) |

## Конфиг синхронизации (sync.toml)

Единый конфиг путей для `sync-all` (копия `sync.toml.example`):
`[worktree]` — git-репозиторий монорепо; `[configuration]` — хранилище
конфигурации (`project` = имя каталога в worktree **и** имя EDT-проекта —
можно любое); `[[extension]]` — хранилища расширений (сколько нужно), у
каждого может быть `base_project` — базовый EDT-проект (обычно проект
конфигурации); `[external]` — опциональный шаг внешних обработок:
флажок `enabled` + `xml_dir` → EDT-проект (`project`, тоже с
`base_project`). Пути указываются внутри контейнера (см. монтирования в
`compose.yaml`; fixtures смонтированы в `/work/fixtures`).

Механика `base_project`: обе import-команды (базовый проект + расширение
с `--base-project-name`) выполняются одним EDT-скриптом в одной сессии —
отдельными вызовами EDT 2026.1 базу «не видит» («Не найдено открытого
проекта»). Базовый проект должен уже существовать в worktree (синкните
конфигурацию первой секцией — `sync-all` делает это по порядку).

### Помощники создания конфига

```bash
# CLI-мастер (интерактивный опрос, пишет /work/sync.toml)
docker compose run --rm -T converter 1c-convert init-config

# Веб-помощник: форма в браузере, предпросмотр и сохранение sync.toml
docker compose run --rm --publish 127.0.0.1:18080:8080 converter 1c-convert config-server
# → http://127.0.0.1:18080
```

Хранилище монтируется read-only (`STORAGE_HOST_PATH` в `.env` → `/storage`)
и перед обработкой копируется в `cache/tmp` (требуется `data/pack` рядом
с БД и локальный доступ к файлу). `ctool1cd` читает формат напрямую
(реверс-инжиниринг, лицензия 1С не требуется); запись в хранилище не
выполняется никогда.

## Быстрый старт

```powershell
# 1. дистрибутивы (см. vendor/README.md)
#    vendor/platform/deb64_8_3_27_*.zip
#    vendor/edt/1c_edt_distr_offline_*_linux_x86_64.tar.gz

# 2. сборка
docker compose build converter

# 3. smoke test (CF → XML → EDT → XML → CF)
Copy-Item tests\fixtures\1Cv8.cf input\
docker compose run --rm converter bash /work/tests/smoke/run_smoke.sh /work/input/1Cv8.cf

# 4. конвертация
docker compose run --rm converter `
    cf-to-edt /work/input/1Cv8.cf /work/output/configuration

# 5. хранилище → git (в .env: STORAGE_HOST_PATH=E:/crs/gitsync)
docker compose run --rm converter storage-info /storage
docker compose run --rm converter storage-sync /storage /work/output/storage-git

# 6. всё сразу по конфигу (хранилища + расширения + внешние обработки)
cp sync.toml.example sync.toml   # пути уже указывают на fixtures
docker compose run --rm converter sync-all
```

Прямой вызов инструментов образа:

```bash
docker compose run --rm converter ibcmd --help
docker compose run --rm converter 1cedtcli -help
docker compose run --rm converter 1c-convert info
```

## Структура

```
Dockerfile                  # один образ: платформа (ibcmd) + EDT (1cedtcli) + 1c-convert
compose.yaml                # сервис converter (input/output/cache монтируются с host)
docker/scripts/             # install-platform.sh, install-edt.sh (из kafka-tools, Apache-2.0)
converter/onec_convert/     # тонкий оркестратор (Python, без логики конвертации)
vendor/                     # официальные дистрибутивы 1С (не в git; в образ — через named context)
tests/fixtures/             # тестовая конфигурация 1Cv8.cf (из 1CFilesConverter, MPL-2.0)
tests/smoke/                # smoke test CF → XML → EDT → XML → CF
legacy/designer-host-bridge/# старая архитектура (DESIGNER + Windows Host Bridge) — deprecated
docs/comparison.md          # сравнение возможностей с 1CFilesConverter
THIRD_PARTY_NOTICES.md      # лицензионные уведомления upstream
```

## Версии

Версии платформы/EDT не зашиты в код оркестратора: фактическая версия
платформы определяется по `/opt/1cv8/current`, EDT — по установленному
каталогу. В `.env` задаются только метка образа и `EDT_PLATFORM_SUPPORT`
(какую версию platform-support оставить в образе). Обновление платформы =
замена архива в `vendor/platform/` + пересборка, код не меняется.

## Дистрибутивы и лицензии 1С

`vendor/` содержит только официально скачанные дистрибутивы
(releases.1c.ru); они не коммитятся, не публикуются и не попадают в
release-артефакты. В docker-образ попадают только установленные каталоги.
Файлы лицензий 1С кладите в `./licenses` (монтируется как
`/var/1C/licenses`). Лицензионные требования 1С не обходятся.

Credentials ИБ/СУБД передаются через environment (`V8_IB_PWD`,
`V8_DB_SRV_PWD`) или файлы-секреты (`*_FILE`, docker secrets) и
маскируются в логах.

## Проверка результатов

`exit code == 0` не считается единственным признаком успеха (Этап 17
спецификации): после `1cedtcli` проверяются stdout/stderr (шаблоны ошибок),
`.metadata/.log` workspace, наличие и структура результата
(`Configuration.xml`; `.project`, `src`, `src/Configuration/Configuration.mdo`).
После `ibcmd` — наличие и размер файла результата.

## Ограничения

- Хранилище конфигураций читается `ctool1cd` напрямую из `1cv8ddb.1CD`
  (реверс-инжиниринг формата, GPL-3): покрывающая практика сообщества
  многолетняя, но это не официальный инструмент 1С. Официальный путь
  (gitsync + 1cv8 DESIGNER + лицензия) сохранён в `legacy/`.
- `ibcmd` хранилище читать не умеет (проверено по `ibcmd help` 8.3.27),
  поэтому extractor построен на `ctool1cd`.
- Инкрементальный import XML→EDT в существующий проект EDT CLI не
  поддерживает (ошибка перезаписи бинарных ресурсов, exit code 0): по каждой
  версии выполняется полная очистка каталога и полный реимпорт — механика
  плагина gitsync `edtExport`; диффы вычисляет git.
- Основной pipeline — конфигурации (CF/XML/EDT/file IB). Расширения
  (CFE), EPF/ERF — в перспективе (в upstream `1CFilesConverter` есть
  `ext2edt/ext2cfe/dp2*`; наша обвязка их пока не портировала).
- Client/server ИБ: параметры подключения реализованы
  (`V8_DB_SRV_*`, `--dbms/--db-server/--db-name`), но проверено только на
  файловых ИБ.
- Бинарное равенство исходного и итогового CF не гарантируется
  (и не требуется): проверяется читаемость итогового CF платформой.
- Если операция невозможна средствами `ibcmd + 1cedtcli`, она документируется
  как unsupported; DESIGNER как fallback не подключается (см. `legacy/`).
