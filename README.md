# 1C CONVERTER

Конвертация конфигураций 1С официальными инструментами — в Linux Docker
или локально на Windows, без Host Bridge и без GUI-сессий:

```
                          1C CONVERTER

        Docker (Linux)                    Windows (локально)
   ┌──────────────────────────┐   ┌──────────────────────────┐
   │ ibcmd   1cedtcli  gitsync│   │ платформа 1С (ibcmd/1cv8)│
   │ ctool1cd  + edtExport    │   │ 1C:EDT (1cedtcli)  git   │
   │                          │   │ ctool1cd.exe  oscript    │
   │  thin orchestrator       │   │  thin orchestrator       │
   │  (Python: 1c-convert)    │   │  (Python: 1c-convert)    │
   └──────────────────────────┘   └──────────────────────────┘

       хранилище 1С ──> CF ──> XML ──> EDT ──> git-история
       движок tool1cd: без конфигуратора и лицензии (ctool1cd)
       движок gitsync: официальный стек (+ инкрементально, быстрее)
```

> Логика преобразования основана на подходах, уже реализованных в
> [arkuznetsov/1CFilesConverter](https://github.com/arkuznetsov/1CFilesConverter).
> Docker-сборка основана на проверенных подходах из
> [ShadobaAI/kafka-tools](https://github.com/ShadobaAI/kafka-tools).
> Собственных парсеров форматов 1С нет: используются `ibcmd`, `1cedtcli`,
> конфигуратор (для движка gitsync) и `ctool1cd` (GPL-3, реверс-инжиниринг
> хранилища — наш [PR #295](https://github.com/e8tools/tool1cd/pull/295)
> в upstream).

## Состав образа (дерево зависимостей)

```
convert2edt/converter:latest          (Dockerfile, compose.yaml)
│
├── debian:bookworm-slim ............... базовый образ (ARG BASE_IMAGE)
│     └── java-17-openjdk, boost 1.74, zlib, git, python3, xvfb + openbox
│         + x11vnc + dbus-x11 (GUI-стек для 1cv8, лицензия через VNC)
│
├── 1С:Предприятие 8.3.27.2342 ......... закрытый дистрибутив (vendor/platform/)
│     └── deb: common(+nls), server(+nls) -> /opt/1cv8/current -> ibcmd
│
├── клиент платформы (1cv8, DESIGNER) . закрытый дистрибутив (vendor/platform/,
│     │  опционально: client_*.deb64.zip) — нужен движку gitsync
│     │  (configurator-бэкенд) и license-gui; batch-режиму нужен X -> xvfb
│     └── deb: client(+nls) -> /opt/1cv8/current/1cv8 (без thin-client)
│
├── 1C:EDT 2026.1.3 offline ............ закрытый дистрибутив (vendor/edt/)
│     └── 1ce-installer-cli -> /opt/1C/1CE/components/1cedtcli -> 1cedtcli
│
├── e8tools/tool1cd @ 625ac1a (GPL-3) . собирается из исходников в builder-стадии
│     └── ctool1cd + libtool1cd.so .... чтение хранилищ (depot ver100 — в upstream)
│
├── OneScript 1.9.4 + gitsync 3.8 ..... публичные источники (GitHub, hub.oscript.io)
│     └── gitsync-plugins 2.0.3: edtExport (+ increment/limit/disable-support)
│         плагин tool1CD НЕ используется (виндовые бинарники; wine не ставим)
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

Два взаимозаменяемых движка (`[worktree] engine` в sync.toml, см. ниже):

```
tool1cd (по умолчанию, без конфигуратора и лицензии):
    для каждой версии N:
        ctool1cd -drc N            → ver-N.cf        (прямо из 1cv8ddb.1CD)
        ibcmd: cf → temp IB → XML                   (без лицензии)
        1cedtcli: XML → EDT (очистка + полный реимпорт)
        git commit: автор/дата/комментарий версии N (из таблиц VERSIONS/USERS)

gitsync (официальный стек, быстрее за счёт инкрементальности):
    gitsync init/sync (конфигуратор читает хранилище; расширения — через -e)
    → XML → плагин edtExport (1cedtcli) → git-коммиты сам gitsync
```

Повторный `1cedtcli import` в существующий проект EDT CLI **не поддерживает**:
падает на перезаписи бинарных ресурсов (Picture.png и т.п.), причём exit code
при этом может быть 0 — ошибка ловится нашей строгой проверкой результата.
Поэтому, как и в плагине gitsync `edtExport`, перед импортом каждой версии
каталог проекта **полностью очищается** и выполняется полный import
(VCS-каталоги вроде `.git` сохраняются). Диффы между версиями вычисляет git:
при фиксированной версии EDT вывод импорта детерминирован, поэтому в дифф
попадают только реальные изменения конфигурации.

`storage-sync` возобновляемый: состояние (последняя синхронизированная
версия **на каждый проект**) хранится в `<worktree>/.storage-sync.json`;
повторный запуск — 0 коммитов. Проект кладётся в `<worktree>/<project-name>`
(по умолчанию `configuration`). Сопоставление авторов — файл `--authors`
формата `ИмяИзХранилища=Git Имя <email>`; без мапинга —
`Имя <slug@--domain>`.

### Статистика прогонов (A/B движков)

Каждый прогон синхронизации пишется в `<worktree>/.storage-sync-stats.json`
(в git не коммитится): движок, проект, длительность и по-версионные тайминги.
Для `tool1cd` — по фазам: хранилище→cf (`dump_sec`), cf→XML (`xml_sec`),
XML→EDT (`edt_sec`), commit. Для `gitsync` внутренние фазы извне недоступны —
замеряется версия целиком (по маркерам лога) и прогон вместе с `init`.
Тот же отчёт показывает веб-помощник (`config-server`), секция
«Статистика прогонов»: таблица прогонов (движок/проект/версий/секунд/
среднее на версию) + детализация последнего прогона по версиям.

Полные результаты замеров всех вариантов (движки × бэкенды gitsync ×
окружения Docker/Windows, конфигурации и расширения) — на отдельной
странице: **[docs/benchmarks.md](docs/benchmarks.md)**.

Кратко (fixtures, Docker, 5 версий конфигурации): tool1cd 318.8 с (~64 с/
версию), gitsync configurator/configurator **161.6 с** (~30 с/версию,
инкрементально), gitsync configurator/ibcmd 270.7 с. gitsync быстрее за
счёт инкрементального конвейера, но требует лицензию при
configurator-бэкенде (в Docker — через `license-gui`).

### Хранилище расширений в тот же monorepo

Отдельное хранилище расширения синкается **в тот же worktree** отдельным
проектом (работает **обоими движками**: tool1cd — depot v100 через ctool1cd;
gitsync — штатно через `-Extension`, с автоматическим отключением плагина
increment, чей `-update`-дамп расширений платформой не поддерживается):

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
`dp2epf`; клиент платформы есть в образе и локально, нужна лицензия).
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
`[worktree]` — git-репозиторий монорепо (+ `engine`); `[gitsync]` —
селективные бэкенды gitsync-движка; `[configuration]` — хранилище
конфигурации (`project` = имя каталога в worktree **и** имя EDT-проекта —
можно любое); `[[extension]]` — хранилища расширений (сколько нужно), у
каждого может быть `base_project` — базовый EDT-проект (обычно проект
конфигурации); `[external]` — опциональный шаг внешних обработок:
флажок `enabled` + `xml_dir` → EDT-проект (`project`, тоже с
`base_project`). Пути указываются внутри контейнера (см. монтирования в
`compose.yaml`; fixtures смонтированы в `/work/fixtures`).

### Движок выгрузки хранилищ (`[worktree] engine`)

| engine | Чтение версий хранилища | XML→EDT | Требования |
|---|---|---|---|
| `tool1cd` (по умолчанию) | `ctool1cd` напрямую из `1cv8ddb.1CD` (в т.ч. хранилища расширений, depot v100) | `ibcmd` + `1cedtcli` (наш конвейер) | без конфигуратора и лицензии |
| `gitsync` | конфигуратор 1С или плагин `tool1CD` — см. `[gitsync] storage_backend` | плагин gitsync `edtExport` → `1cedtcli` | oscript + gitsync + EDT; при configurator-бэкендах — 1cv8 и лицензия |

Селективные бэкенды gitsync (секция `[gitsync]`, дефолты `configurator`):

| этап | `configurator` | альтернатива |
|---|---|---|
| чтение хранилища (`storage_backend`) | штатный конфигуратор (1cv8); **хранилища расширений поддерживаются штатно через `-Extension`** (в т.ч. `gitsync init -e`); нужна лицензия | `ctool1cd` — плагин `tool1CD`: читает `1cv8ddb.1CD` напрямую; только Windows (плагин тащит виндовые бинарники; в Docker без wine недоступен), хранилища расширений плагин не умеет |
| выгрузка XML (`xml_backend`) | `DESIGNER /DumpConfigToFiles` | `ibcmd` — плагин `use-ibcmd` (нативный) |

Хранилища расширений через gitsync: `init`/`sync` получают `-e`, плагин
`increment` автоматически отключается (инкрементальный `-update`-дамп
расширений платформой не поддерживается — «Объект метаданных … не существует
в конфигурации»; проверено на платформе 8.3.27.2342, gitsync 3.8.0).

Отличия движка `gitsync`: git-историю формирует сам gitsync (файл AUTHORS,
коммиты на русском), каждый проект — **отдельный** git-репозиторий
`<worktree>/<project>` в src-layout (`<project>/src/` — корень EDT-проекта,
служебные `VERSION`/`AUTHORS` рядом) из-за детекции `src` в gitsync
(issue oscript-library/gitsync-plugins#53); резюм — по файлу `VERSION`.
Для секций доступны `storage_user`/`storage_pwd` (gitsync ходит в хранилище
конфигуратором; tool1cd-движок эти ключи игнорирует). Один worktree должен
обслуживаться одним движком — не смешивайте.

### Движок gitsync внутри Docker

В образ встраиваются OneScript + gitsync + плагин `edtExport` (нативно,
без wine: виндовые бинарники плагина `tool1CD` не используются) и — при
наличии `client_*.deb64.zip` в `vendor/platform/` (см.
[vendor/README.md](vendor/README.md)) — **клиент платформы** `1cv8`:
gitsync читает хранилище классическим путём через конфигуратор. Сборка:
`docker compose build converter`.

Конфигуратору при открытии ИБ нужна **лицензия** (это требование 1С, не
оркестратора; tool1cd-движок работает без неё). Варианты:

1. **Программная лицензия через VNC** (одноразово, по подходу kafka-tools
   `client`): поднимается Xvfb + openbox + x11vnc, лицензия сохраняется в
   volume `v8home` (`/root/.1cv8`) и переживает `--rm`:

   ```bash
   docker compose run --rm -p 127.0.0.1:5900:5900 converter license-gui
   # 5900 на хосте занят (напр., локальный VNC)? -> -p 127.0.0.1:15900:5900
   # затем VNC-клиент -> vnc://127.0.0.1:5900 (без пароля, только loopback)
   # в диалоге 1С: «Получить программную лицензию» (логин releases.1c.ru)
   ```

   MAC контейнера зафиксирован (`V8_MAC_ADDRESS` в .env, по умолчанию
   `02:42:AC:11:00:99`) — программная лицензия привязана к MAC, не меняйте
   его после активации.

2. **Файлы `*.lic`** — положить в `./licenses` (монтируется как
   `/var/1C/licenses`).

Механика `base_project`: обе import-команды (базовый проект + расширение
с `--base-project-name`) выполняются одним EDT-скриптом в одной сессии —
отдельными вызовами EDT 2026.1 базу «не видит» («Не найдено открытого
проекта»). Базовый проект должен уже существовать в worktree (синкните
конфигурацию первой секцией — `sync-all` делает это по порядку).

### Помощники создания конфига

Оба помощника поддерживают выбор движка и бэкендов gitsync:

```bash
# CLI-мастер (интерактивный опрос, пишет /work/sync.toml)
docker compose run --rm -T converter 1c-convert init-config

# Веб-помощник: форма в браузере, предпросмотр и сохранение sync.toml,
# ход синхронизации в живую + раздел «Статистика прогонов (A/B)»
docker compose run --rm --publish 127.0.0.1:18080:8080 converter 1c-convert config-server
# → http://127.0.0.1:18080
```

Хранилище монтируется read-only (`STORAGE_HOST_PATH` в `.env` → `/storage`)
и перед обработкой копируется в `cache/tmp` (требуется `data/pack` рядом
с БД и локальный доступ к файлу). `ctool1cd` читает формат напрямую
(реверс-инжиниринг, лицензия 1С не требуется); запись в хранилище не
выполняется никогда.

## Версии и переменные среды

Ничего не захардкожено: версии детектируются или задаются переменными.

**Docker-канал** (`.env` → compose):

| Переменная | Что задаёт |
|---|---|
| `VENDOR_DIR` | каталог закрытых дистрибутивов 1С для сборки (named context, в образ не попадают; по умолчанию `./vendor`) |
| `CLIENT_DIST_DIR` | каталог с клиентом платформы `client_*.deb64.zip` для gitsync-движка (по умолчанию `./dist`; без него клиент в образ не ставится — gitsync/configurator в Docker недоступны) |
| `BASE_IMAGE` | родительский базовый образ (по умолчанию `debian:bookworm-slim`) |
| `TOOL1CD_REF` | коммит e8tools/tool1cd — исходники ctool1cd качаются с GitHub при сборке (по умолчанию `625ac1a`, с depot ver100) |
| `GITSYNC_SUPPORT` | 1 = ставить OneScript + gitsync + плагины в образ (по умолчанию 1) |
| `OSCRIPT_VERSION` | версия OneScript в образе (по умолчанию 1.9.4) |
| `V8_MAC_ADDRESS` | MAC контейнера — программная лицензия привязана к MAC; не менять после активации license-gui (по умолчанию `02:42:AC:11:00:99`) |
| `PLATFORM_VERSION` | метка образа (фактическая платформа — из `vendor/platform/`) |
| `EDT_VERSION` | метка образа (фактический EDT — из `vendor/edt/`) |
| `EDT_PLATFORM_SUPPORT` | какой platform-support оставить в образе (напр. `8.3.27`) |
| `V8_VERSION` | версия для `1cedtcli import --version` (пусто = автодетект) |

Итого о родительских проектах при сборке образа: базовый образ и исходники
tool1cd приходят из публичных источников (`docker.io`, GitHub) и пинятся
переменными; закрытые дистрибутивы 1С — только из локального `VENDOR_DIR`,
из сети не качаются никогда. Локальный режим добавляет
`CONVERT_CTOOL1CD_REF` (mingw-сборка ctool1cd.exe).

**Локальный режим** (переменные среды перед `run-local.ps1/.cmd`, шапка скрипта):

| Переменная | Что задаёт | По умолчанию |
|---|---|---|
| `CONVERT_PLATFORM_MASK` | маска платформы для автопоиска | `8.3.` |
| `CONVERT_EDT_VERSION` | точная версия компонента EDT | новейший `1c-edt-*` |
| `CONVERT_JAVA_HOME` | JDK/JRE для EDT | machine `JAVA_HOME` / axiom-jdk-full |
| `CONVERT_V8_VERSION` | версия для EDT import | детектированная платформа |
| `CONVERT_CTOOL1CD_REF` | коммит e8tools/tool1cd для сборки | `625ac1a` (ver100) |

Пример: `$env:CONVERT_PLATFORM_MASK='8.3.'; $env:CONVERT_EDT_VERSION='2026.2.0'; .\run-local.ps1`

## Зависимости и установка

Единый каталог зависимостей — по трём сценариям. Что установлено и чего
не хватает на конкретной машине — покажет `scripts\local\check-deps.ps1`
(секция `-Engine gitsync` проверяет стек oscript/gitsync/edtfind).

### A. Сборка Docker-образа (хост: любая ОС)

| Зависимость | Зачем | Установка |
|---|---|---|
| Docker Desktop / Engine (BuildKit) | сборка и запуск | docker.com; в Docker Desktop включить BuildKit (по умолчанию) |
| `vendor/platform/deb64_8_3_27_*.zip` | платформа: `ibcmd` (обязательно) | releases.1c.ru → Platform83 |
| `vendor/edt/1c_edt_distr_offline_*.tar.gz` | 1C:EDT: `1cedtcli` (обязательно) | releases.1c.ru → DevelopmentTools10 |
| `vendor/platform/client_8_3_27_*.deb64.zip` | клиент `1cv8` — движок `gitsync` + `license-gui` (опционально) | releases.1c.ru → Platform83 → «Клиентская часть для Linux» |

Из сети при сборке качаются только публичные исходники: `debian:bookworm-slim`
(docker.io), e8tools/tool1cd (GitHub), OneScript + gitsync + плагины
(GitHub / hub.oscript.io) — пины в `.env` (`TOOL1CD_REF`, `OSCRIPT_VERSION`).

```powershell
docker compose build converter
```

### B. Запуск в Docker (на хосте больше ничего не нужно)

Всё нужное уже в образе. Дополнительно — только данные:

| Что | Когда нужно | Как |
|---|---|---|
| `STORAGE_HOST_PATH` / `EXT_STORAGE_HOST_PATH` в `.env` | storage-команды | путь к хранилищу на хосте (монтируется ro) |
| лицензия 1С | только движок `gitsync` (configurator-бэкенд) и Designer-операции | разово `license-gui` через VNC (см. ниже) или `*.lic` в `./licenses`; tool1cd-движок работает без лицензии |
| `V8_MAC_ADDRESS` | после активации программной лицензии | не менять (лицензия привязана к MAC) |

### C. Запуск без Docker (Windows)

| Зависимость | Зачем | Установка |
|---|---|---|
| Python 3.11+ | оркестратор `1c-convert` (tomllib) | python.org |
| git | коммиты версий | git-scm.com |
| Платформа 1С 8.3 (ibcmd + 1cv8) | ibcmd: XML-выгрузка (tool1cd-движок, без лицензии); 1cv8: configurator-бэкенд gitsync (операции с ИБ требуют лицензию) | releases.1c.ru |
| 1C:EDT (1cedtcli) | XML ↔ EDT | releases.1c.ru (offline-установщик; кладёт `1c-edt-*` и axiom-jdk в `1C\1CE\components`) |
| ctool1cd.exe | движок `tool1cd`: чтение хранилища | ничего не ставить: run-local.ps1 соберёт из upstream (нужен MSYS2/mingw) или возьмёт релиз beta2 |
| oscript + opm | движок `gitsync` | oscript.io (или ovm) |
| gitsync + gitsync-plugins ≥ 2.0.1 (edtExport) + edtfind | движок `gitsync` | `opm install gitsync`; плагины: `gitsync plugins install gitsync-plugins@2.0.3` + `gitsync plugins enable edtExport` (или всё ставит `run-gitsync.ps1` сам, edtfind — локально в `tools\oscript`) |

```powershell
scripts\local\check-deps.ps1     # проверка с подсказками, что поставить
scripts\local\sync.cmd           # sync-all по scripts\local\sync.local.toml
scripts\local\run-gitsync.cmd    # gitsync-движок одной командой (без конфига)
```

Результаты замеров всех вариантов (движки × бэкенды × окружения) — в
[docs/benchmarks.md](docs/benchmarks.md).

## Локальный запуск без Docker (Windows) — детали

Оба движка и все бэкенды работают и локально: движок задаётся в
`scripts\local\sync.local.toml` (`engine = "tool1cd" | "gitsync"` + секция
`[gitsync]` с `storage_backend`/`xml_backend`). Исключение:
`storage_backend = "ctool1cd"` (плагин tool1CD) доступен **только на
Windows** — в Linux он требует wine, который мы не используем.

`run-local.ps1` — тот же конвейер нативными инструментами:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\local\run-local.ps1
```

- использует установленные платформу 1С (ibcmd/1cv8), 1C:EDT (1cedtcli),
  git и python; `ctool1cd.exe` при отсутствии **собирается из upstream
  e8tools/tool1cd** через MSYS2/mingw (`scripts\local\build-ctool1cd-mingw.sh`,
  включает depot ver100 → хранилища расширений работают и локально);
  fallback — релиз beta2 (без ver100);
- **Java для EDT**: EDT 2026.2 требует Java 25 — скрипт берёт Axiom Full
  (machine `JAVA_HOME` или `components\axiom-jdk-full-*`) и prepends её
  в PATH. Если в PATH первым стоит чужой JDK (например Liberica 11),
  EDT-лаунчер молча показывает диалог о версии Java и «виснет» — из
  machine PATH такой JDK следует убрать;
- preflight проверяет локальный 1cedtcli; если он не отвечает —
  автоматический docker-шим (`scripts\local\edt_docker_shim.py`,
  EDT-шаг через образ), остальное остаётся нативным;
- конфиг — `scripts\local\sync.local.toml` (пример рядом, Windows-пути);
- предупреждение: EDT локальной машины может отличаться от EDT в образе —
  для одного монорепо держите один канал (docker ИЛИ local).

### Альтернатива: выгрузка хранилища через gitsync (без Docker)

`scripts/local/run-gitsync.ps1` — отдельный сценарий на официальном стеке
oscript-library/gitsync + плагин `edtExport` (конфигуратор читает хранилище,
`1cedtcli` конвертирует в EDT, ring не нужен):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\local\run-gitsync.ps1
# fixtures\crs\cf -> output\local-gitsync (5 версий = 5 коммитов)
```

Скрипт сам: находит платформу/EDT/Java, ставит `edtfind` локально в
`tools\oscript` (через `OSCRIPT_CONFIG=lib.additional` — OneScript 1.9.4
игнорирует OSLIB, а заданный lib.additional отключает поиск в
`<gitsync>\oscript_modules`, поэтому недостающие пакеты зеркалируются туда),
включает плагин `edtExport`, делает `gitsync init` (с временным отключением
edtExport — баг плагина 2.x) и `gitsync sync`. Тот же движок доступен из
общего конфига: `[worktree] engine = "gitsync"` + `sync-all` (см. выше).

## Быстрый старт

### Docker

```powershell
# 1. дистрибутивы (см. vendor/README.md)
#    vendor/platform/deb64_8_3_27_*.zip
#    vendor/edt/1c_edt_distr_offline_*_linux_x86_64.tar.gz
#    vendor/platform/client_8_3_27_*.deb64.zip  # опционально: gitsync-движок

# 2. сборка
docker compose build converter

# 2-альтернатива. готовый образ из релиза (без vendor/ и сборки):
#   CONVERTER_IMAGE=ghcr.io/kucheryavenkovn/convert2edt:v1.0.0 в .env
#   docker compose pull converter

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

### gitsync-движок в Docker (одноразовая подготовка лицензии)

```powershell
# клиент платформы должен быть в vendor/platform/ (пересобрать образ, если добавили)
docker compose run --rm -p 127.0.0.1:15900:5900 converter license-gui
# → VNC-клиент на 127.0.0.1:15900 → «Получить программную лицензию»
# лицензия живёт в volume v8home + ./licenses, MAC зафиксирован

# затем в sync.toml: engine = "gitsync" (+ секция [gitsync] при необходимости)
docker compose run --rm converter sync-all
```

### Локально на Windows (без Docker)

```powershell
scripts\local\check-deps.ps1                    # что стоит / что добить
scripts\local\sync.cmd                          # sync-all по sync.local.toml
scripts\local\run-gitsync.cmd                   # или: gitsync-движок напрямую
```

Прямой вызов инструментов образа:

```bash
docker compose run --rm converter ibcmd --help
docker compose run --rm converter 1cedtcli -help
docker compose run --rm converter 1c-convert info
```

## Структура

```
Dockerfile                  # один образ: платформа (ibcmd + 1cv8) + EDT + ctool1cd
                             # + OneScript/gitsync + GUI/VNC-стек для license-gui
compose.yaml                # сервис converter (input/output/cache монтируются с host;
                             # volume v8home — программная лицензия, MAC зафиксирован)
docker/scripts/             # install-platform.sh, install-edt.sh (kafka-tools, Apache-2.0),
                             # install-gitsync.sh (oscript+gitsync+плагины), license-gui.sh (VNC)
converter/onec_convert/     # тонкий оркестратор (Python): pipeline (tool1cd-движок),
                             # gitsync.py (gitsync-движок + бэкенды), syncall, initconfig (TUI+web)
scripts/local/              # Windows-режим без Docker: run-local, run-gitsync, check-deps,
                             # sync.local.toml(.example), build-ctool1cd-mingw.sh
vendor/                     # закрытые дистрибутивы 1С: deb64 + клиент + EDT (не в git)
sync.toml.example           # шаблон конфига синхронизации (engine + [gitsync])
tests/fixtures/             # тестовая конфигурация 1Cv8.cf + хранилища crs/cf, crs/ext
tests/smoke/                # smoke test CF → XML → EDT → XML → CF
legacy/designer-host-bridge/# старая архитектура (DESIGNER + Windows Host Bridge) — deprecated
docs/comparison.md          # сравнение возможностей с 1CFilesConverter
docs/benchmarks.md          # результаты замеров: движки × бэкенды × окружения
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
  (gitsync + конфигуратор 1С читает хранилище) доступен как альтернативный
  движок: `[worktree] engine = "gitsync"` (см. выше) или
  `scripts/local/run-gitsync.ps1`; DESIGNER + Host Bridge — в `legacy/`.
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
