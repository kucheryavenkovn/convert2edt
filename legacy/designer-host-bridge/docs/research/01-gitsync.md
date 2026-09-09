# Исследование: gitsync (актуальная версия)

**Источник:** https://github.com/oscript-library/gitsync, ветка `master` = тег `v3.8.0` (коммит `82d87f5`, последний релиз).
**Дата исследования:** 2026-09-09. Факты получены прямым чтением исходников master (shallow-клон в temp), не из устаревших статей.

## 1. CLI: команды

Команды регистрируются в `src/cmd/gitsync.os` (стр. 48–61):
`usage|u`, `init|i`, **`sync|s`**, `clone|c`, `all|a`, `set-version|sv`, `plugins|p`.

Команды `storage sync` НЕТ. Вызов: `gitsync sync [ОПЦИИ] PATH [WORKDIR]`.

### Собственные опции `sync` (`src/cmd/Классы/КомандаSync.os`, стр. 6–29)

| Параметр | Env | По умолчанию |
|---|---|---|
| `-u`, `--storage-user` | `GITSYNC_STORAGE_USER` | `Администратор` |
| `-p`, `--storage-pwd` | `GITSYNC_STORAGE_PASSWORD`, `GITSYNC_STORAGE_PWD` | — |
| `-e`, `--ext`, `--extension` | `GITSYNC_EXTENSION` | — (имя расширения) |
| `-d`, `--das`, `--disable-auto-src` | `GITSYNC_DISABLE_AUTO_SRC` | Ложь |
| аргумент `PATH` | `GITSYNC_STORAGE_PATH` | обязателен |
| аргумент `WORKDIR` | `GITSYNC_WORKDIR` | текущий каталог |

### Глобальные опции приложения (`src/cmd/gitsync.os`, стр. 18–46)

| Параметр | Env | Описание |
|---|---|---|
| `--v8version` | `GITSYNC_V8VERSION` | маска версии платформы, по умолчанию `8.3` |
| `--v8-path` | `GITSYNC_V8_PATH` | прямой путь к `1cv8` |
| `-v`, `--verbose` | `GITSYNC_VERBOSE` | отладка |
| `-U`, `--ib-user` | `GITSYNC_IB_USR`… | пользователь ИБ |
| `-P`, `--ib-pwd` | `GITSYNC_IB_PASSWORD`… | пароль ИБ |
| `-C`, `--ib-connection` | `GITSYNC_IB_CONNECTION` | строка подключения ИБ (`/F...`, `/S...`) |
| `-t`, `--tempdir` | `GITSYNC_TEMP`, `GITSYNC_TEMPDIR` | каталог временных файлов (ставится и в TEMP/TMP для 1С) |
| `--git-path` | `GITSYNC_GIT_PATH`, `GIT_PATH` | путь к git |
| `--domain-email` | `GITSYNC_EMAIL`, `GITSYNC_DOMAIN_EMAIL` | домен почты, по умолчанию `localhost` |

**В ядре НЕТ** параметров `-limit`, `-maxversion`, `-branch`, `-push` — они появляются только через плагины (см. `02-gitsync-plugins.md`).

## 2. `gitsync init` и monorepo

`src/cmd/Классы/КомандаInit.os`:
- создаёт WORKDIR, если не существует (стр. 46–49);
- проверка `git rev-parse --git-dir` в WORKDIR (стр. 51–56, 108–124): **успешен и для подкаталога существующего репозитория** → `git init` НЕ выполняется. Вложенный `.git` не создаётся — monorepo-сценарий поддерживается;
- пишет только `AUTHORS` и `VERSION` (стр. 81); AUTHORS наполняется пользователями хранилища (нужен доступ к хранилищу и платформа).

**Критично:** `МенеджерСинхронизации.os`, `ОчиститьКаталогРабочейКопии` (стр. 566–629): при каждой версии sync **полностью удаляет всё содержимое WORKDIR**, кроме белого списка: `.git`, `.gitignore`, `.gitattributes`, `.hooks`, `AUTHORS`, `VERSION` (стр. 570–576).
→ WORKDIR должен быть **выделенным подкаталогом** монорепо, в котором нет ничего постороннего.

Git-команды выполняются с рабочим каталогом = WORKDIR (`ПолучитьГитРепозиторий`, стр. 777–803), git сам находит `.git` вверх по дереву; `git add -A .` (стр. 840) индексирует только поддерево WORKDIR → коммит затрагивает только этот подкаталог. Дополнительно в репо выставляются локальные `core.quotepath=false`, `merge.ours.driver=true`.

**Нюанс auto-src:** если в WORKDIR есть подкаталог `src`, он становится «каталогом исходников» (КомандаSync.os стр. 58–64); отключается флагом `--disable-auto-src`. ВНИМАНИЕ: формат EDT-проекта сам содержит `src/` — нужно проверить взаимодействие edtExport с auto-src (issue #53 gitsync-plugins). Для безопасности используем `--disable-auto-src`.

## 3. VERSION и AUTHORS

- Имена захардкожены: `ИмяФайлаАвторов() = "AUTHORS"`, `ИмяФайлаВерсииХранилища() = "VERSION"` (`МенеджерСинхронизации.os`, стр. 1213–1224). **Пути переназначить нельзя** — оба файла лежат в корне WORKDIR.
- Формат VERSION — XML: `<?xml version="1.0" encoding="UTF-8"?><VERSION>N</VERSION>`.
- «Последняя синхронизированная версия» = число из `WORKDIR/VERSION` (стр. 1412–1429). **Если VERSION нет — исключение**: перед первым sync обязателен `init` или `set-version`.
- После каждой выгруженной версии VERSION перезаписывается и коммитится вместе с исходниками; при ошибке версия откатывается (стр. 334) → recovery с прерванной версии работает штатно.
- AUTHORS: формат `ИмяВХранилище=Имя Гит <email>` (стр. 1398). Если автор не найден — генерируется `Имя <Имя@localhost>` (домен из `--domain-email`). **Команды `set-user` в 3.x нет.**
- Смена стартовой версии: `gitsync set-version|sv [-c|--commit] VERSION [WORKDIR]`.

**Вывод для monorepo:** `AUTHORS` и `VERSION` будут лежать внутри `PROJECT_PATH` (например `configuration/main/AUTHORS`, `configuration/main/VERSION`) и коммититься. Это допустимо (не нарушает структуру EDT-проекта, т.к. лежат в корне проекта рядом с `src/`), но нужно явно зафиксировать в README. Альтернативы штатно нет.

## 4. Получение версий из файлового хранилища

- Исполняемый файл: **толстый клиент `1cv8` (режим DESIGNER)** через библиотеки `v8runner` + `v8storage`. Ни ibcmd, ни ring ядром не используются.
- Выбор платформы: `--v8-path` (прямой путь) или `--v8version` (маска; поиск установленной платформы через v8runner, стр. 746–759).
- Команды конфигуратора (v8storage `МенеджерХранилищаКонфигурации.os`):
  - история: `/ConfigurationRepositoryReport "<файл>" -NBegin <N>` (+`-IncludeCommentLinesWithDoubleSlash -ReportFormat` для ≥8.3.17);
  - загрузка версии в базу: `/ConfigurationRepositoryUpdateCfg -v <N> -force`;
  - путь хранилища: `/ConfigurationRepositoryF "<путь>"`;
  - выгрузка в файлы: `/DumpConfigToFiles` (заменяется плагином use-ibcmd).
- Поддерживаются файловые, `tcp` и `http(s)` хранилища. Без `-ibconnection` v8runner создаёт временную файловую ИБ в temp-каталоге.

**Следствие для Docker:** в образе обязателен **толстый клиент платформы** (компонент `client`), а не только `server+ibcmd`.

## 5. Формирование коммитов

`ВыполнитьКоммитГит` (стр. 813–852):
- комментарий хранилища → временный файл UTF-8 (пустой → `.`) → `git commit -F`;
- автор: `git commit --author="..."`;
- дата версии хранилища → `GIT_AUTHOR_DATE` и `GIT_COMMITTER_DATE` (gitrunner, после коммита очищаются);
- коммиттер = автор (временный локальный `user.name/user.email` с восстановлением);
- перед коммитом `git add -A .`; `--allow-empty`.
- Номер версии в текст коммита не добавляется — фиксируется через файл VERSION. Теги — плагин `smart-tags`.

## 6. Плагины

Каталог плагинов по приоритету (`ПараметрыПриложения.os`, стр. 182–254):
1. env `GITSYNC_PLUGINS_PATH` (или `GITSYNC_PLUGINS_DIR`, `GITSYNC_PL_DIR`);
2. `./.gitsync/plugins`;
3. `$HOME/.local/share/gitsync/plugins` (Linux).

Состояние включённых — `plugins.json` в каталоге плагинов. Управление: `gitsync plugins init|list|enable|disable|install|clear`. Встроенный пакет `gitsync-plugins-2.0.3.ospx`.

**В Docker:** init/enable выполнять под тем же пользователем, что и sync; лучше зафиксировать `GITSYNC_PLUGINS_PATH=/opt/gitsync-plugins` и выполнять enable на этапе сборки образа.

## 7. Инкрементальная синхронизация

`Синхронизировать` (стр. 276–353): читает VERSION → таблица истории с `-NBegin = текущая+1` → цикл по версиям. Новых нет → **0 коммитов, корректный выход**. Если VERSION больше версии хранилища > чем на 10 — исключение «хранилище обрезали». Каждая версия = отдельный коммит с оригинальными автором/датой/комментарием; при ошибке — откат VERSION и выход с кодом 1.

## 8. Push/pull — НЕ в ядре

Ядро делает только локальные коммиты. Push/pull — плагин `sync-remote` или внешний `git push` (равноценно; для контроля изоляции PROJECT_PATH предпочтителен внешний push после проверки diff).

## 9. Версии и зависимости

- gitsync **3.8.0**, минимум **OneScript 1.9.2**.
- Зависимости: v8runner 1.12.0, gitrunner 1.8.0, v8storage 0.9.4, cli 0.11.0, opm 1.6.5 и др.
- Соответствие: gitsync v3.8.0 ↔ gitsync-plugins v2.0.3.
- Для платформы 1С > 8.3.11 readme требует утилиту `ring` (для определения установленных версий; при `--v8-path` не критично, но лучше иметь).

## 10. Установка и Docker

- `opm install gitsync`, затем `gitsync plugins init`, `gitsync plugins enable ...`.
- **Официального Docker-образа нет.**

## Выводы для конвейера

1. WORKDIR = выделенный подкаталог монорепо (`/repo/configuration/main`). `init` вложенный репо не создаст; sync не выйдет за пределы подкаталога; всё внутри подкаталога перезаписывается.
2. Минимальный конвейер: `gitsync init` → правка AUTHORS / `set-version` → `gitsync sync` → проверка diff → внешний `git push`.
3. Все параметры задаются env `GITSYNC_*` — удобно для контейнера; `--v8-path` указывает на `/opt/1cv8/current/1cv8`.
4. Повторные запуски безопасны; состояние — только VERSION в подкаталоге.
