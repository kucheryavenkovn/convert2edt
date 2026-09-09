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

## Дистрибутивы 1С

`vendor/` (не в git) содержит только официальные дистрибутивы
1С:Предприятие и 1C:EDT, скачиваемые вручную с releases.1c.ru. Они не
распространяются вместе с проектом и не включаются в release-артефакты.
