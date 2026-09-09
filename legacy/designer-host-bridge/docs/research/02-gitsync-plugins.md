# Исследование: gitsync-plugins (актуальная версия)

**Источник:** https://github.com/oscript-library/gitsync-plugins, `master` (коммит `8f750ad`, 2026-06-01), пакет **2.0.3**.
**Дата исследования:** 2026-09-09. Факты — прямое чтение исходников master.

## 1. Список плагинов (15)

`check-authors`, `check-comments`, `disable-support`, `drop-config-dump`, `drop-support`, `edtExport` (2.0.2), `increment`, `limit` (1.6.1), `replace-authors`, `robo-copy`, `smart-tags`, `sync-remote` (2.0.0), `tool1CD`, `unpackForm`, `use-ibcmd` (2.0.1).

## 2. edtExport (`src/Классы/edtExport.os`)

Включение: `gitsync plugins enable edtExport`. Подписан только на команду `sync`.

### Параметры CLI (точные, стр. 106–124)

| Опция | Env | Назначение |
|---|---|---|
| `PN project-name` | `GITSYNC_PROJECT_NAME` | Имя EDT-проекта (**обязательно**) |
| `W workspace-location` | `GITSYNC_WORKSPACE_LOCATION` | Расположение рабочей области |
| `BP base-project-name` | `GITSYNC_BASE_PROJECT_NAME` | Базовый проект (для расширений) |
| `EDT edt-version` | `GITSYNC_EDT_VERSION` | Версия EDT (иначе автоопределение через `edtfind`) |

**Параметра `-edt-path` НЕТ** — путь к 1cedtcli ищется автоматически библиотекой `edtfind` (`ПоискEDT.НайтиИнформациюОEDT(ВерсияEDT)`). Отдельного параметра формата выгрузки нет.

### Выбор исполняемого файла (стр. 213–236)

Если `edtfind` нашёл `ПутьКcli` → **1cedtcli**; иначе ищется **ring** (`/opt/1C/1CE/components/ring` на Linux).

### Командные строки конвертации (стр. 268–301)

```
1cedtcli -data "<workspace>" -command import --project "<каталог_проекта>" \
  --configuration-files "<каталог_XML_выгрузки>" [--base-project-name "<имя>"]
```

(альтернатива через `ring edt@<версия>:x86_64 workspace import ...`).

### Сценарий (событие `ПередПеремещениемВКаталогРабочейКопии`, стр. 151–207)

1. Если в каталоге выгрузки есть `dumplist.txt` (его создаёт `use-ibcmd --increment` или `increment`) → догрузка изменённых объектов конфигуратором `/DumpConfigToFiles -listFile`.
2. Создаётся **временный** workspace EDT; если задан `-W`, его содержимое копируется во временный (реальный workspace не изменяется).
3. Каталог проекта `<tempWS>/<project-name>` **полностью очищается** и выполняется **полный** `import` XML→EDT. (Инкрементальна только XML-выгрузка; конвертация XML→EDT всегда полная — узкое место производительности.)
4. `ConfigDumpInfo.xml` копируется в корень проекта EDT (для инкремента).
5. **Исходный XML удаляется**, содержимое EDT-проекта копируется в каталог выгрузки → в git попадает только EDT-проект.

### Служебные файлы EDT

`.project`, `.settings/org.eclipse.core.resources.prefs`, `DT-INF/PROJECT.PMF`, `src/...` (`.mdo`, `.bsl`, `.form`, `.rights`). Рекомендаций по `.gitignore` в репозитории нет.

**Известная issue #53:** если в git-корне есть каталог `src`, gitsync может неверно определить каталог проекта EDT — не создавать `src` вне EDT-проекта.

## 3. use-ibcmd (`src/Классы/useIbcmd.os`)

Включение: `gitsync plugins enable use-ibcmd`. При активации **автоматически отключает `increment`** и сам выставляет флаг инкремента.

### Параметры CLI (стр. 139–171)

| Опция | Env | Умолчание |
|---|---|---|
| `ibcmd-data` | `GITSYNC_IBCMD_DATA` | рабочий каталог ibcmd |
| `t ibcmd-dbms` | `GITSYNC_IBCMD_DBMS` | `MSSQLServer` |
| `s ibcmd-db-server` | `GITSYNC_IBCMD_DB_SERVER` | `` |
| `n ibcmd-db-name` | `GITSYNC_IBCMD_DB_NAME` | `` |
| `U ibcmd-db-user` | `GITSYNC_IBCMD_DB_USER` | `` |
| `P ibcmd-db-pwd` | `GITSYNC_IBCMD_DB_PWD` | `` |
| `j ibcmd-threads` | `GITSYNC_IBCMD_THREADS` | 0 (не добавляется) |
| `i increment` | `GITSYNC_IBCMD_INCREMENT` | Ложь |

**Что заменяет:** только выгрузку в файлы (`/DumpConfigToFiles`), событие `ПриВыгрузкеКонфигурациюВИсходники`. Получение истории хранилища (`/ConfigurationRepositoryReport`) и загрузка версии (`/ConfigurationRepositoryUpdateCfg`) **остаются на конфигураторе** → толстый клиент `1cv8` всё равно нужен.

Путь к `ibcmd` берётся из API gitsync: `Платформа1С.ПутьКIBCMD(ВерсияПлатформы)`.

### Командная строка выгрузки (стр. 243–290)

```
ibcmd infobase config export --data="<ibcmd-data>" [--threads=N]
  --db-path="<путь к файловой ИБ>"
  [--user --password] [--base=<ConfigDumpInfo.xml>] [--extension=<имя>] --force [--sync]
  <КаталогВыгрузки>
```

Предварительная проверка инкремента: `ibcmd infobase config export status ... --out=tmp.dmp`; если первая строка `modified: all` → полная выгрузка, иначе список изменений сохраняется как `dumplist.txt` (подхватывает edtExport).

## 4. sync-remote (`src/Классы/syncRemote.os`)

| Опция | Env | Умолчание |
|---|---|---|
| `PS push` | `GITSYNC_REMOTE_PUSH` | Ложь |
| `G pull` | `GITSYNC_REMOTE_PULL` | Ложь |
| `b branch` | `GITSYNC_REMOTE_BRANCH` | `master` |
| `T push-tags` | `GITSYNC_REMOTE_PUSH_TAGS` | Ложь |
| `n push-n-commits` | `GITSYNC_REMOTE_PUSH_N_COMMITS` | 0 |
| `O push-options` | `GITSYNC_PUSH_OPTIONS` | через `;` |
| аргумент `URL` | `GITSYNC_REPO_URL` | — |

`--pull` → `git pull <URL> <branch>` перед началом; `--push` → `git gc --auto` + `git push -u <URL>` (имя ветки не передаётся); `--push-n-commits N` → промежуточный push каждые N коммитов.

**Решение:** в нашем конвейере push делаем внешним `git push` после проверки изоляции PROJECT_PATH (gitsync сам diff не контролирует). Плагин sync-remote оставляем опциональным.

## 5. limit (`src/Классы/limit.os`)

- `l limit` (env `GITSYNC_LIMIT`) — не более N версий от текущей выгруженной;
- `minversion`, `maxversion` (без env).

Лимит считается по строкам таблицы истории (индекс + N). При одновременном `maxversion` и `limit` берётся большее значение (особенность, стр. 134–135). Для миграции большой истории: повторные запуски с `GITSYNC_LIMIT=N` — gitsync продолжит с последней выгруженной версии (файл VERSION).

## 6. check-authors (`src/Классы/checkAuthors.os`)

Собственных параметров нет. Использует файл `AUTHORS` рабочей копии. При неизвестном авторе — `Лог.КритичнаяОшибка` на каждую версию + **исключение** («В таблице истории версий найдены авторы...»): синхронизация **блокируется** (не предупреждение). Это соответствует требованию «не подставлять случайные данные».

## 7. Подключение плагинов

- Установка: `opm install gitsync-plugins` или встроенный пакет через `gitsync plugins init` (**обязательно повторять после обновления gitsync**).
- Включение: `gitsync plugins enable <имя> [<имя2>...]` или `enable -a`.
- Состояние — `plugins.json` в каталоге плагинов (per-user!). В Docker: enable на этапе сборки, `GITSYNC_PLUGINS_PATH` зафиксировать.
- packagedef: `gitsync-plugins 2.0.3`, `ВерсияСреды("1.9.2")`, зависимость `edtfind 2.0.2` (поиск EDT).

## 8. Совместимость

gitsync v3.8.0 ↔ gitsync-plugins v2.0.3 (официальная таблица в readme gitsync).

## Выводы для конвейера

1. Связка `use-ibcmd --increment` + `edtExport` согласована (dumplist.txt / ConfigDumpInfo.xml).
2. Всё задаётся env: `GITSYNC_PROJECT_NAME`, `GITSYNC_EDT_VERSION`, `GITSYNC_IBCMD_*`, `GITSYNC_LIMIT`, `GITSYNC_REMOTE_*`.
3. XML→EDT всегда полная конвертация — основное время на больших конфигурациях.
4. Порядок в образе: `opm install gitsync` → `gitsync plugins init` → `gitsync plugins enable use-ibcmd edtExport limit check-authors` под тем же пользователем, что и runtime.
