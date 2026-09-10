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
    выгрузка XML версии N                            # 1cv8 DESIGNER (gitsync) — вне этого проекта
    1c-convert xml-to-edt <xml-N> <worktree>/project # очистка + полный реимпорт
    git add / git commit                             # автор/дата/комментарий версии N
```

Шаг чтения хранилища конфигурации `ibcmd` выполнить не может (см.
«Ограничения»): для него остаётся gitsync-стек (legacy) или отдельный
extractor-профиль.

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

- Хранилище конфигураций (crs) `ibcmd` не читает (проверено по `ibcmd help`
  8.3.27): забор версий из хранилища возможен только через 1cv8 DESIGNER
  (gitsync-стек в `legacy/` или отдельный extractor-профиль).
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
