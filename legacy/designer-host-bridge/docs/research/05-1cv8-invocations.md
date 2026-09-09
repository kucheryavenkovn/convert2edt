# Исследование №5: точные вызовы 1cv8 в gitsync → v8storage → v8runner и требования к wrapper

**Дата:** 2026-09-09. Источники: клоны gitsync/v8runner/v8storage/gitsync-plugins (файлы и строки указаны).

## 0. Механизм запуска — формат argv

Вызовы идут через `УправлениеКонфигуратором.ВыполнитьКоманду(МассивСтрок)` → `ЗапуститьИПодждать`
(v8runner/src/v8runner.os:2388-2439), без shell, через 1commands → `СоздатьПроцесс` (execve, ArgumentList).
Парсер аргументов OneScript съедает кавычки, поэтому wrapper получает:

- **слитные ключи** (значение приклеено): `/F<path>`, `/N<user>`, `/P<pwd>`, `/UC<key>`, `/L<RU>`, `/VL<RU>`,
  `/AddInList<имя с пробелами>`, `/UseTemplate<path>`, `/WA+`;
- **раздельные пары** (ключ и значение — соседние argv): `/Out <path>` [`-NoTruncate`],
  `/ConfigurationRepositoryF <path>`, `/ConfigurationRepositoryN <user>`, `/ConfigurationRepositoryP <pwd>`,
  `/ConfigurationRepositoryReport <file>`, `/DumpConfigToFiles <dir>`, `/LoadCfg <file>`, `-v <N>`,
  `-NBegin <N>`, `-NEnd <N>`, `-format <Hierarchical>`, `-listFile <file>`, `-Extension <name>`,
  `-ReportFormat <fmt>`, `-configDumpInfoForChanges <file>`;
- первый argv — режим: `DESIGNER` или `CREATEINFOBASE` (у последнего строка соединения `File=<path>`, НЕ `/F`);
- stdout/stderr перехватываются (в лог oscript.lib.v8runner), cwd наследуется.

## 1. Таблица вызовов сценария `gitsync sync` (файловое хранилище)

| # | Вызов | argv | Источник |
|---|---|---|---|
| 1 | Создание временной ИБ | `CREATEINFOBASE` `File=<каталог>` `/Out <ф>` [`-NoTruncate`] [`/AddInList<имя>`] [`/UseTemplate<п>`] `/LRU` `/VLRU` | v8runner.os:1389-1429; каталог = `<temp>/v8r_TempDB` (1898-1900) |
| 2 | Префикс DESIGNER | `DESIGNER` `/F<путь ИБ>` [`/N<u>`] [`/P<p>`] [`/WA+`] [`/UC<k>`] `/LRU` `/VLRU` `/DisableStartupMessages` `/DisableStartupDialogs` | v8runner.os:2297-2335 |
| 3 | Ключи хранилища | `/ConfigurationRepositoryN <u>` [`/ConfigurationRepositoryP <p>`] `/ConfigurationRepositoryF <путь>` | v8storage.os:747-764 (N, P, затем F) |
| 4 | История версий | `… /ConfigurationRepositoryReport <ф.mxl> -NBegin <N> [-NEnd <N>] [-Extension <имя>] [-IncludeCommentLinesWithDoubleSlash -ReportFormat <mxl\|txt>]` (последние два — только если версия ≥ 8.3.17) | v8storage.os:574-602; парсинг MXL ripper-регулярками |
| 5 | Обновление до версии N | `… /ConfigurationRepositoryUpdateCfg [-v <N>] [-Extension <имя>] -force` (`-v` — строго сразу после команды) | v8storage.os:134-158; ретраи по лицензии в gitsync: МенеджерСинхронизации.os:482-512 |
| 6 | Выгрузка в исходники (стандартная) | `… /DumpConfigToFiles <кат> -format Hierarchical [-update -force [-configDumpInfoForChanges <ф>]] [-listFile <ф>]` (ключи `-update/-listFile` — только если версия ≥ 8.3.10) | v8runner.os:712-755 |
| 7 | (расширения) Загрузка cfe | `… /LoadCfg <ф.cfe> -Extension <имя>` | МенеджерСинхронизации.os:1308-1317 |
| 8 | (edtExport) Догрузка по dumplist | `… /DumpConfigToFiles <кат> -listFile <ф> [-Extension <имя>]` | edtExport.os:344-364 |
| 9 | (use-ibcmd) Выгрузка | `ibcmd infobase config export --data=… --db-path=<ИБ> [--base=…] [--threads=N] --force [--sync] <кат>` — **НЕ через v8-path**: путь к ibcmd ищет v8find `Платформа1С.ПутьКIBCMD` | useIbcmd.os:243-290, 413-457 |

Прочее (в базовом sync не встречается): `/ConfigurationRepositoryBindCfg`, `/ConfigurationRepositoryUnbindCfg -force`, `/ConfigurationRepositoryDumpCfg <ф> [-v N]`.

## 2. Определение версии платформы при явном пути

**1cv8 для этого НЕ запускается.** `ПутьКПлатформе1С(Путь)` (v8runner.os:1953-1974):
1. проверяет существование файла (wrapper обязан быть обычным файлом!);
2. версия = последнее совпадение регэкспа **`8(\.\d+){3}` в полном пути** (из имени каталога);
3. нет совпадения → версия `""` → НЕ добавляются `-ReportFormat`/`-IncludeCommentLinesWithDoubleSlash` (отчёт хранилища)
   и `-update`/`-configDumpInfoForChanges`/`-listFile` (выгрузка) — **потеря критичных функций**.

→ Решение: wrapper доступен по пути `/opt/1cv8/x86_64/8.3.27.2342/1cv8` (symlink на `/usr/local/bin/1cv8-host`),
а рядом — реальный Linux `ibcmd` (v8find находит оба по маске `8.3`). `GITSYNC_V8_PATH` указывает на этот путь.

## 3. Коды возврата, /Out, stdout

- `ВыполнитьКоманду` (v8runner.os:1645-1664): запуск → чтение файла `/Out` в `ВыводКоманды` (файл после чтения удаляется!);
  при коде ≠ 0 → исключение с текстом **из /Out** (не из stdout).
- `/Out` по умолчанию кладётся в `КаталогСборки` (рядом с v8r_TempDB, не в системный TEMP); `-NoTruncate` — дозапись,
  v8runner вычитывает только прирост (2527-2545). **Мост обязан обеспечить запись /Out по docker-пути** (общий staging) —
  пишет сам 1cv8, путь просто мапится.
- gitsync парсит /Out на `"Не обнаружено свободной лицензии!"` / `"Не найдена лицензия."` → пауза 10 с и ретрай.
- stdout/stderr — только в лог; пароли в логах маскируются (`/P…`, `/ConfigurationRepositoryP…`, v8runner.os:2396-2398).

## 4. TEMP/cwd/окружение

v8runner не меняет TEMP/TMP и cwd (cwd = cwd oscript-процесса). Окружение наследуется полностью.

## Требования к wrapper (реализация в docker/wrapper/1cv8-host)

1. Синхронный: argv → HTTP bridge → запуск 1cv8.exe → трансляция exit code; stdout/stderr пробросывать (уходят в лог).
2. Поддержка режимов `DESIGNER` и `CREATEINFOBASE`; слитные и раздельные ключи по п.0/1.
3. Любой неподдерживаемый ключ/режим → явный ERROR + nonzero exit (fail-fast, не молчать).
4. Маппинг путей делает BRIDGE (единая точка): `/bridge→E:\1c-bridge`, `/storage→E:\crs\gitsync`.
5. Wrapper-файл обязан существовать и лежать по пути с версией `8.3.27.2342` (регэксп v8runner).
6. Не логировать argv с паролями.
7. ibcmd/1cedtcli — реальные Linux-бинарё в контейнере, через wrapper НЕ ходят.
