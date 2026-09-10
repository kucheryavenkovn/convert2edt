# Сравнение с upstream 1CFilesConverter

Обновляется по мере реальной проверки. «+» = проверено smoke-тестом/ручным
запуском; «-» = отсутствует; «частично» = реализовано, но не проверено.

| Возможность | 1CFilesConverter | convert2edt |
|---|---|---|
| CF → XML | + (`conf2xml`) | + (`cf-to-xml`) |
| XML → CF | + (`conf2cf`) | + (`xml-to-cf`) |
| CF → EDT | + (`conf2edt`) | + (`cf-to-edt`) |
| EDT → CF | + (`conf2cf`) | + (`edt-to-cf`) |
| XML → EDT | + (`conf2edt`) | + (`xml-to-edt`) |
| EDT → XML | + (`conf2xml`) | + (`edt-to-xml`) |
| file IB → XML | + (`conf2xml`) | + (`ib-to-xml`) |
| file IB → EDT | + (`conf2edt`) | + (`ib-to-edt`) |
| Хранилище → CF/XML/EDT версии | - (нужен gitsync + DESIGNER) | + (`storage-to-*`, `ctool1cd`, без лицензии) |
| Хранилище → git-история (1 версия = 1 коммит) | + (gitsync, DESIGNER+лицензия) | + (`storage-sync`, без DESIGNER) |
| Хранилище расширений → git (в тот же monorepo, с базовой конфигурацией) | - | + (`storage-sync --extension --base`; патч ctool1cd depot-ver100) |
| Расширения: cfe/xml/edt как разовые конвертации | + (`ext2edt`, `ext2cfe`, ...) | - (механизм реализован внутри storage-sync; отдельные команды — по запросу) |
| Внешние обработки (EPF/ERF) | + (dp2xml/dp2edt, только DESIGNER) | - (нужен v8unpack — в плане) |
| XML → IB (создание/загрузка) | + (`conf2ib`) | - (обёртки ibcmd `infobase create/import` уже есть внутри pipeline) |
| CF → IB | + (`conf2ib`) | - (см. выше) |
| client/server IB | + (`/S...`, `V8_DB_SRV_*`) | частично (параметры реализованы, не проверено) |
| `ibcmd` | + (`V8_CONVERT_TOOL=ibcmd`) | + (единственный инструмент) |
| `1cedtcli` / ring | + (ring или edtcli) | + (только 1cedtcli) |
| `--sync` incremental export | + | + (auto/force/off) |
| Повторный import в существующий EDT-проект | не требуется | + (полная очистка + полный реимпорт — механика gitsync `edtExport`; инкрементный import EDT CLI не поддерживает, проверено) |
| Расширения (CFE, ext2*) | + (`ext2edt`, `ext2cfe`, ...) | - |
| EPF/ERF (dp2*) | + (`dp2edt`, `dp2epf`, ...) | - |
| EDT validate | + (`edt-validate`) | - |
| Windows DESIGNER | optional (`V8_CONVERT_TOOL=designer`) | не нужен (нет по дизайну) |
| Linux/Docker | частично (Windows .cmd, WSL) | + (единственный способ запуска) |
| Проверка результата EDT по stdout/логам | - (только ERRORLEVEL) | + |
| Маскирование паролей в логах | - | + |

Примечания:

- Проверенные возможности подтверждены smoke-тестом
  `tests/smoke/run_smoke.sh` (CF → XML → EDT → XML → CF + читаемость
  итогового CF платформой) на платформе 8.3.27.2342 и EDT 2026.1.3;
  storage-команды проверены на реальном тестовом хранилище
  (4 версии, файловая, 8.3.27).
- Расширения/обработки переносятся после стабилизации основного pipeline
  (принцип спецификации: сначала CF ↔ XML ↔ EDT).
