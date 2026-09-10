# Third-party notices

Этот проект переиспользует подходы и код следующих upstream-проектов.

## arkuznetsov/1CFilesConverter — MPL-2.0

- URL: https://github.com/arkuznetsov/1CFilesConverter
- Лицензия: Mozilla Public License 2.0 (копия: см. репозиторий upstream)

Алгоритмы преобразования (последовательности вызовов ibcmd/1cedtcli,
определение типа источника, условия применения `--sync`, схема временной
информационной базы, `clean-up-source` после импорта EDT) воспроизведены по
скриптам `conf2edt.cmd`, `conf2cf.cmd`, `conf2xml.cmd`, `conf2ib.cmd`
в нашем Linux-оркестраторе `converter/onec_convert/` (перереализация на
Python, не построчное копирование).

Файл `tests/fixtures/1Cv8.cf` скопирован из
`1CFilesConverter/tests/fixtures/bin/1Cv8.cf` (тестовая конфигурация).

This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

## ShadobaAI/kafka-tools — Apache-2.0

- URL: https://github.com/ShadobaAI/kafka-tools
- Лицензия: Apache License 2.0 (копия: см. репозиторий upstream)

Файлы, адаптированные из `.github/ci-images/docker/` (оригинальные пути
указаны в заголовках файлов):

- `docker/scripts/install-platform.sh`
  (из `docker/scripts/install-platform.sh`);
- `docker/scripts/install-edt.sh`
  (из `docker/scripts/install-edt.sh`);
- схема multi-stage Dockerfile, наборы runtime-зависимостей платформы и EDT,
  каталоги `/opt/1cv8/current`, `/opt/1C/1CE/components/1cedtcli`, подача
  дистрибутивов через BuildKit named context, pruning каталогов
  (из `docker/Dockerfile`);
- приём валидации результата EDT-экспорта по наличию `Configuration.xml`
  (из `.github/scripts/edt2xml.py`).

Copyright ShadobaAI. Изменения перечислены в заголовках адаптированных
файлов. Licensed under the Apache License, Version 2.0 (the "License");
you may not use these files except in compliance with the License. You may
obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.

## e8tools/tool1cd — GPL-3.0

- URL: https://github.com/e8tools/tool1cd
- Лицензия: GNU GPL v3 (копия: см. репозиторий upstream, файл COPYING)
- Автор: Валерий Агеев (awa15), адаптация сообщества e8tools

`ctool1cd` собирается из исходников upstream в builder-стадии Dockerfile
(пин коммита — `ARG TOOL1CD_REF`) и используется как самостоятельный
исполняемый файл для чтения хранилища конфигурации 1С
(`1cv8ddb.1CD`): выгрузка `.cf` заданной версии (`-drc`) и экспорт таблиц
`VERSIONS`/`USERS` (`-ex`). Код tool1cd в код проекта не включается.
Изменения относительно upstream (обязательное указание по GPL-3):
удалена GUI-поддиректория `gtool1cd` из конфигурации сборки и применён
патч `docker/patches/tool1cd-depot-ver100.patch` (хранилища расширений,
depot version 100, трактуются как Ver7-layout). Образ с `ctool1cd`
предназначен для внутреннего использования; при распространении образа
действуют условия GPL-3 (исходники tool1cd доступны по URL выше, пин — в
label `onec.converter.tool1cd-ref`, изменения — в этом файле и в
`docker/patches/`).

## e8tools/v8unpack — MPL-2.0

- URL: https://github.com/e8tools/v8unpack
- Лицензия: Mozilla Public License 2.0 (копия: см. репозиторий upstream, файл LICENSE)
- Авторы: Denis Demidov, Sergey Batanov, Sergey Rudakov и сообщество e8tools

`v8unpack` собирается из исходников upstream в builder-стадии Dockerfile
(пин коммита — `ARG V8UNPACK_REF`) и используется как самостоятельная
утилита распаковки/сборки бинарных файлов внешних отчётов и обработок
(`.erf`/`.epf`) без платформы 1С. Код в код проекта не включается.
Изменение относительно upstream (только в конфигурации сборки builder-стадии):
динамический boost вместо захардкоженного статического
(`sed` удаляет `Boost_USE_STATIC_*` из CMakeLists.txt).

This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

## Дистрибутивы 1С

`vendor/` (не в git) содержит только официальные дистрибутивы
1С:Предприятие и 1C:EDT, скачиваемые вручную с releases.1c.ru. Они не
распространяются вместе с проектом и не включаются в release-артефакты.
