# sync.toml — полный справочник конфигурации синхронизации

Конфиг читает `1c-convert sync-all --config <путь>` (Docker: `/work/sync.toml`,
локально: `scripts/local/sync.local.toml`). Создать его можно мастером
`init-config`, веб-формой `config-server` или руками из `sync.toml.example`
(пути в примере указывают на fixtures — рабочая конфигурация «из коробки»).

**Пути** указываются в терминах той среды, где выполняется `sync-all`:
внутрь контейнера смонтированы `./input`, `./output`, `./cache`, `./fixtures`
(→ `/work/...`), хранилища — `/storage`, `/storage-ext`; локально — обычные
Windows-пути (прямой и обратный слэш равнозначны).

## Обзор секций

```toml
[worktree]      # куда и каким движком выгружать (обязательно)
[gitsync]       # бэкенды движка gitsync (опционально)
[configuration] # хранилище основной конфигурации (обычно 1 секция)
[[extension]]   # хранилища расширений (0..N секций)
[external]      # внешние отчёты/обработки → EDT-проект (опционально)
```

Порядок выполнения: `configuration` → все `[[extension]]` по порядку →
`[external]`. Ошибка в секции не останавливает остальные — итоговый отчёт
в конце (`sync-all завершился с ошибками: ...`).

---

## [worktree] — репозиторий и движок

| Ключ | Тип | По умолчанию | Описание |
|---|---|---|---|
| `path` | str | — (обязателен) | Каталог git-монорепозитория. Создаётся при отсутствии. **Смысл различается по движку** — см. ниже |
| `engine` | str | `"tool1cd"` | `"tool1cd"` — наш конвейер ctool1cd+ibcmd+1cedtcli (без лицензии); `"gitsync"` — oscript-library/gitsync + плагин edtExport |
| `authors_file` | str | нет | Файл мапинга авторов: `ИмяИзХранилища=Git Имя <email>` (по строке). Только для `engine = "tool1cd"`; gitsync использует свой `AUTHORS` (создаёт сам, формат тот же) |
| `domain` | str | `"storage.local"` | Домен email для авторов без мапинга: `Имя <slug@domain>` |

### Что означает `path` для каждого движка

**tool1cd** — классический монорепозиторий: один `.git` в корне `path`,
каждый проект — подкаталог:

```
<path>/
├── .git                        # один репозиторий
├── configuration/             # EDT-проект конфигурации
├── extension/                 # EDT-проект расширения
├── external/                  # EDT-проект внешних обработок
├── .storage-sync.json         # state: последняя версия ПО КАЖДОМУ проекту
└── .storage-sync-stats.json   # статистика прогонов (A/B)
```

**gitsync** — каталог-контейнер независимых репозиториев (требование
src-layout, issue gitsync-plugins#53):

```
<path>/
├── configuration/             # ОТДЕЛЬНЫЙ git-репозиторий
│   ├── .git
│   └── src/                   # EDT-проект + служебные VERSION/AUTHORS
├── extension/
│   └── src/...
└── .storage-sync-stats.json   # наша статистика (общая на контейнер)
```

Резюм в обоих случаях автоматический: повторный `sync-all` довыгрузит только
новые версии хранилища (tool1cd — по `.storage-sync.json`, gitsync — по
`VERSION` внутри проекта).

---

## [gitsync] — бэкенды движка gitsync

Секция игнорируется при `engine = "tool1cd"`. Все ключи опциональны.

| Ключ | Значения | По умолчанию |
|---|---|---|
| `storage_backend` | `configurator` \| `ctool1cd` | `configurator` |
| `xml_backend` | `configurator` \| `ibcmd` | `configurator` |
| `ib_connection` | `/S<server>\<ref>` (клиент-серверная ИБ) или `/F<путь>` | пусто = временная файловая ИБ |
| `ib_user` / `ib_pwd` | пользователь/пароль ИБ для `ib_connection` | пусто |
| `ibcmd_dbms` | СУБД для use-ibcmd: `MSSQLServer`\|`PostgreSQL`\|`IBMDB2`\|`OracleDatabase` | пусто (плагин) |
| `ibcmd_db_server` / `ibcmd_db_name` | сервер/имя БД | пусто |
| `ibcmd_db_user` / `ibcmd_db_pwd` | пользователь/пароль СУБД | пусто |

### `storage_backend` — чтение хранилища (версии, авторы, дамп)

| | `configurator` | `ctool1cd` |
|---|---|---|
| Как | конфигуратор 1С (1cv8) подключается к хранилищу | плагин tool1CD читает `1cv8ddb.1CD` напрямую |
| Файловое хранилище | да | да |
| **Сервер хранилища (crs), `tcp://host:port/rep`** | **да** | нет (плагин работает только с файлом БД хранилища) |
| Хранилища расширений | да, штатно через `-Extension` (передаётся в `init -e` и `sync -e`) | **нет** (валидация запрещает) |
| Лицензия 1С | нужна (операции с ИБ) | не нужна на чтение |
| Где работает | Windows, Docker (клиент платформы в образе) | **только Windows**: плагин исполняет виндовые бинарники; в Linux нужен wine — не используем |

### Клиент-серверные ИБ и сервер хранилища

- **Сервер хранилища**: в `[configuration] storage` / `[[extension]] storage`
  указывается строка `tcp://host:port/<имя_репозитория>` — gitsync/1cv8
  подключаются к сервису crs по TCP (локальная копия хранилища не делается,
  в отличие от файловых хранилищ). Свой crs можно поднять из этого же
  репозитория: сервис `crs` в compose (тонкий образ платформа+crserver,
  репозитории в `./storage-crs`, порт `CRS_PORT`, по умолчанию 1542):

  ```bash
  docker compose up -d crs
  # создать репозиторий из конфигурации ИБ (batch-команда конфигуратора):
  #   /ConfigurationRepositoryF tcp://<host>:1542/<имя> /ConfigurationRepositoryN <админ> \
  #   /ConfigurationRepositoryCreate -user <админ>
  ```

- **Клиент-серверная ИБ** (источник для выгрузки в XML): `ib_connection =
  "/S<server>\<ref>"` + при необходимости `ib_user`/`ib_pwd` — тогда вместо
  временной файловой ИБ конфигуратор работает с указанной ИБ. Для
  `xml_backend = "ibcmd"` дополнительно передаются параметры СУБД
  (`ibcmd_dbms` и т.д.).

### `xml_backend` — выгрузка конфигурации в XML

| | `configurator` | `ibcmd` |
|---|---|---|
| Как | `DESIGNER /DumpConfigToFiles` | плагин use-ibcmd → `ibcmd infobase config export` |
| Скорость (fixtures, 5 версий) | быстрее (инкрементальный `-update` для конфигураций) | ~1.7× медленнее без `--increment` |
| Лицензия | нужна | не нужна (но storage=configurator уже требует) |

Примеры комбинаций:

```toml
# максимум скорости, есть лицензия:
[gitsync]
storage_backend = "configurator"
xml_backend = "configurator"

# чтение без лицензии (только Windows, только конфигурации):
[gitsync]
storage_backend = "ctool1cd"
xml_backend = "ibcmd"
```

Автоматика движка gitsync (не настраивается): хранилище всегда копируется в
`cache/tmp` (источник может быть read-only); плагин `increment` включён для
конфигураций и **выключен для расширений** (инкрементальный `-update`-дамп
расширений платформой не поддерживается); `edtExport` всегда включён.

---

## [configuration] — хранилище основной конфигурации

| Ключ | Тип | По умолчанию | Описание |
|---|---|---|---|
| `enabled` | bool | `true` | `false` = пропустить шаг (в журнале «шаг отключён»); удобно держать секцию готовой в конфиге |
| `storage` | str | — (обязателен) | Каталог с `1cv8ddb.1CD` или путь к самому файлу |
| `project` | str | `"configuration"` | Имя EDT-проекта **и** подкаталога в worktree |
| `storage_user` | str | `"Администратор"` | Пользователь хранилища. Только gitsync (tool1cd читает файл напрямую) |
| `storage_pwd` | str | `""` | Пароль. Только gitsync |

---

## [[extension]] — хранилища расширений

Секций может быть сколько угодно; каждая синкается отдельным проектом.
Оба движка поддерживают расширения (tool1cd — depot v100 через ctool1cd;
gitsync — через `-Extension`, см. `[gitsync]`).

| Ключ | Тип | По умолчанию | Описание |
|---|---|---|---|
| `enabled` | bool | `true` | `false` = пропустить это расширение (каждая секция отключается независимо) |
| `name` | str | — (обязателен) | Имя расширения (именно имя в хранилище, не каталог) |
| `storage` | str | — (обязателен) | Каталог/файл хранилища расширения (depot v100) |
| `project` | str | `"extension"` | Имя проекта/подкаталога |
| `base_project` | str | — | Базовый EDT-проект (обычно `configuration`). **tool1cd**: расширение импортируется с `--base-project-name` в одной EDT-сессии с базой (EDT 2026.x базу «не видит» отдельным вызовом). gitsync: расширение импортируется как самостоятельный проект (ключ пока не используется). Базовый проект должен уже существовать — синкни конфигурацию первой секцией |
| `storage_user` / `storage_pwd` | str | см. выше | Только gitsync |

---

## [external] — внешние отчёты и обработки

Шаг опционален: отключается `enabled = false` или удалением секции.
Работает одинаково для обоих движков (шаг не зависит от хранилищ).

| Ключ | Тип | По умолчанию | Описание |
|---|---|---|---|
| `enabled` | bool | `false` | Включить шаг |
| `xml_dir` | str | — (нужен при enabled) | Каталог XML-выгрузки Конфигуратора (`/DumpExternalDataProcessorOrReportToFiles` или fixtures `dp-xml`) |
| `project` | str | `"external"` | Имя EDT-проекта в worktree (накапливает обработки: `src/ExternalReports/…`, `src/ExternalDataProcessors/…`) |
| `base_project` | str | — | Базовый EDT-проект (обычно проект конфигурации) |

Коммит шага: `1c-convert storage-sync` от имени служебного автора
(`1c-convert storage-sync`), сообщение «Внешние отчёты и обработки:
обновление (EDT)». Бинарники `.erf/.epf` headless-цепочка не читает —
нужен одноразовый Designer-dump в XML (см. README, раздел EPF/ERF).

---

## Полные примеры

### 1. Минимум, движок по умолчанию (без лицензии)

```toml
[worktree]
path = "/work/output/storage-git"

[configuration]
storage = "/storage"                # смонтированное хранилище
project = "configuration"
```

### 2. gitsync, всё штатно (нужна лицензия)

```toml
[worktree]
path = "/work/output/storage-git"
engine = "gitsync"

[configuration]
storage = "/storage"
project = "configuration"
storage_user = "Администратор"
```

### 3. Монорепозиторий: конфигурация + расширение + внешние обработки

```toml
[worktree]
path = "/work/output/storage-git"
engine = "tool1cd"
authors_file = "/work/authors.txt"
domain = "company.local"

[configuration]
storage = "/storage"
project = "configuration"

[[extension]]
name = "Расширение1"
storage = "/storage-ext"
project = "extension"
base_project = "configuration"

[external]
enabled = true
xml_dir = "/work/input/dp-xml"
project = "external"
base_project = "configuration"
```

### 4. gitsync с ibcmd-бэкендом XML

```toml
[worktree]
path = "/work/output/storage-git"
engine = "gitsync"

[gitsync]
storage_backend = "configurator"
xml_backend = "ibcmd"

[configuration]
storage = "/work/fixtures/crs/cf"
```

### 4а. Сервер хранилища (crs) + клиент-серверная ИБ

```toml
[worktree]
path = "/work/output/storage-git"
engine = "gitsync"

[gitsync]
storage_backend = "configurator"
xml_backend = "configurator"
ib_connection = "/Sdb-server\\billing"   # клиент-серверная ИБ для выгрузки
ib_user = "Администратор"
ib_pwd = "..."

[configuration]
storage = "tcp://crs:1542/billing-rep"   # сервер хранилища
project = "configuration"
```

### 5. Локально на Windows (без Docker)

```toml
[worktree]
path = "D:/git/convert2edt/output/local-git"
engine = "tool1cd"

[configuration]
storage = "D:/crs/cf"
project = "configuration"

[[extension]]
name = "Расширение1"
storage = "D:/crs/ext/Расширение1"
project = "extension"
base_project = "configuration"
```

## Правила валидации (ошибки конфига)

- `[worktree] path` обязателен; `engine` ∈ {tool1cd, gitsync}
- `[gitsync] storage_backend` ∈ {configurator, ctool1cd}; `xml_backend` ∈ {configurator, ibcmd}
- `storage_backend = "ctool1cd"`: запрещён для секций расширений и для удалённых хранилищ (`tcp://`); в Linux/Docker — ошибка «только Windows»
- удалённое хранилище (`tcp://`) требует `storage_backend = "configurator"`
- у каждой секции обязателен `storage`; у `[[extension]]` — ещё и `name`
- `base_project` должен существовать в worktree к моменту шага расширения
  (синкни конфигурацию раньше — `sync-all` выполняет секции по порядку)

## Служебные файлы в worktree

| Файл | Назначение | В git? |
|---|---|---|
| `.storage-sync.json` | state tool1cd-движка: последняя версия по каждому проекту | нет (gitignore) |
| `.storage-sync-stats.json` | статистика прогонов: движок/проект/длительность/фазы — см. [benchmarks.md](benchmarks.md) и веб-отчёт | нет (gitignore) |
| `AUTHORS`, `VERSION` (gitsync, внутри `<project>/src/`) | мапинг авторов и state gitsync | да (коммитятся gitsync) |
